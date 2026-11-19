"""AI intent checks: work out what the change was for, then say for every change whether it
was asked for. Covers U1 (out of scope), U2 (unrelated themes) and feeds U27 ranking.

Public interface: ``IntentRequest``, ``AIResult``, ``ConsentFn``, ``run_ai_checks(...)``.

Safety and honesty rules:
- Code is redacted before it's sent; nothing is sent before ``consent`` says yes.
- Repository text is wrapped in ``<untrusted_*>`` blocks (see ``intent.prompts``).
- The AI only refers to short change ids it was given; unknown ids are ignored and missing
  answers become "Not sure". File and line numbers always come from the parsed diff.
- Low-confidence "asked for" answers are downgraded to "Not sure" (unsure is never ✅).
- One failing part never stops the run: it becomes "Not sure — AI check failed".
- AI findings can only add warnings; they never remove rule-based findings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from verifypr.analysis.changes import ChangeSet
from verifypr.analysis.chunker import Chunk, chunk_hunks, estimate_tokens, split_for_analysis
from verifypr.analysis.redaction import redact
from verifypr.detectors.base import hunk_evidence
from verifypr.intent.contract import IntentContract
from verifypr.intent.prompts import load_prompt, render, untrusted
from verifypr.llm.base import LLMClient, LLMError, ask_json
from verifypr.llm.setup import LLMSettings, SendSummary
from verifypr.models import (
    Classification,
    ClassifiedChange,
    Finding,
    Hunk,
    InputLevel,
    Severity,
)

ConsentFn = Callable[[SendSummary], bool]
MIN_INTENDED_CONFIDENCE = 50
OUTPUT_TOKENS_PER_CHANGE = 80

# ---- schemas the model must answer with --------------------------------------------------
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "themes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["goal", "themes"],
    "additionalProperties": False,
}
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": ["intended", "supporting", "unintended", "unclear"],
                    },
                    "reason": {"type": "string"},
                    "theme": {"type": "string"},
                    "supports": {"type": "string"},
                    "confidence": {"type": "integer"},
                },
                "required": ["id", "classification", "reason", "theme", "supports", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["changes"],
    "additionalProperties": False,
}


class _Intent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    goal: str
    themes: list[str] = Field(default_factory=list)


class _Verdict(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    classification: Literal["intended", "supporting", "unintended", "unclear"]
    reason: str = ""
    theme: str = ""
    supports: str = ""
    confidence: int = 50


class _Verdicts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    changes: list[_Verdict]


# ---- inputs / outputs -------------------------------------------------------------------
@dataclass(frozen=True)
class IntentRequest:
    level: InputLevel
    description: str | None = None
    contract: IntentContract | None = None


@dataclass
class AIResult:
    changes: list[ClassifiedChange] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    intent: str | None = None
    inferred: bool = False
    ai_used: bool = False


def _lines(hunk: Hunk) -> tuple[int, int]:
    if hunk.added_at:
        return min(hunk.added_at), max(hunk.added_at)
    line = max(hunk.new_start, 1)
    return line, line


def _render_change(short_id: str, hunk: Hunk) -> str:
    start, end = _lines(hunk)
    body = "\n".join(
        [*(f"-{redact(r)}" for r in hunk.removed), *(f"+{redact(a)}" for a in hunk.added)]
    )
    return untrusted(
        "change",
        body,
        id=short_id,
        file=hunk.file_path,
        lines=f"{start}-{end}",
        kind=hunk.change_kind.value,
    )


def _context_block(changes: ChangeSet) -> str:
    parts: list[str] = []
    if changes.branch:
        parts.append(f"Branch name: {changes.branch}")
    if changes.commit_messages:
        parts.append("Commit messages:\n" + "\n".join(f"- {m}" for m in changes.commit_messages))
    if not parts:
        return "There is no branch name or commit message to go on."
    return untrusted("context", "\n".join(parts))


def _task_block(request: IntentRequest, goal: str | None, themes: list[str]) -> str:
    if request.level is InputLevel.AUTO:
        if goal:
            lines = [
                "Nobody said what this change was for. Its most likely purpose (inferred):",
                untrusted("description", goal),
            ]
            if themes:
                lines.append(f"Main theme: {themes[0]}.")
            lines.append(
                "Changes that don't serve this purpose count as `unintended`; changes that "
                "might, but you can't tell, are `unclear`."
            )
            return "\n".join(lines)
        return (
            "Nobody said what this change was for. Work out its main purpose from the changes "
            "themselves; changes that don't serve that main purpose are `unintended`."
        )
    contract = request.contract
    lines = ["What this change should do:", untrusted("description", goal or "")]
    if contract is not None:
        for label, items in (
            ("It may change", contract.allowed.behaviors),
            ("It must NOT change", contract.forbidden.behaviors),
            ("Folders it is expected to touch", contract.allowed.paths),
            ("Folders it must not touch", contract.forbidden.paths),
        ):
            if items:
                lines.append(f"{label}: " + "; ".join(items))
        if contract.assumptions:
            lines.append("Assumptions: " + "; ".join(contract.assumptions))
    return "\n".join(lines)


def _file_summary(changes: ChangeSet) -> str:
    rows = [
        f"- {f.path} ({f.change_kind.value}, +{f.added_lines} -{f.removed_lines})"
        for f in changes.files[:200]
    ]
    more = len(changes.files) - 200
    if more > 0:
        rows.append(f"- … and {more} more files")
    return untrusted("context", "\n".join(rows) or "(none)")


def _classified(
    hunk: Hunk,
    cls: Classification,
    reason: str,
    *,
    theme: str | None = None,
    supports: str | None = None,
    confidence: int = 0,
    ai: bool = True,
) -> ClassifiedChange:
    start, end = _lines(hunk)
    return ClassifiedChange(
        hunk_id=hunk.id,
        file_path=hunk.file_path,
        start_line=start,
        end_line=end,
        classification=cls,
        reason=reason,
        theme=theme or None,
        supports=supports,
        confidence=max(0, min(100, confidence)),
        ai=ai,
    )


def _from_verdict(hunk: Hunk, v: _Verdict, ids: dict[str, Hunk]) -> ClassifiedChange:
    cls = Classification(v.classification)
    confidence = max(0, min(100, v.confidence))
    if cls is Classification.INTENDED and confidence < MIN_INTENDED_CONFIDENCE:
        cls = Classification.UNCLEAR
    supported = ids.get(v.supports.strip())
    return _classified(
        hunk,
        cls,
        redact(v.reason.strip())[:300] or "No reason given.",
        theme=v.theme.strip()[:60],
        supports=supported.id if supported else None,
        confidence=confidence,
    )


def run_ai_checks(
    llm: LLMClient,
    changes: ChangeSet,
    request: IntentRequest,
    settings: LLMSettings,
    ignore_globs: tuple[str, ...],
    consent: ConsentFn,
    already_flagged: set[str],
) -> AIResult:
    result = AIResult()
    candidates = [h for h in changes.hunks if h.added or h.removed]
    kept, ignored = split_for_analysis(candidates, ignore_globs)
    if ignored:
        n = len(ignored)
        result.skipped.append(
            f"{n} generated or lock {'file was' if n == 1 else 'files were'} not sent to the AI"
        )
    if not kept:
        return result

    chunks = chunk_hunks(kept, settings.max_chunk_tokens)
    planned, overflow, used = [], [], 0
    for chunk in chunks:
        if chunk.oversize or used + chunk.tokens > settings.max_total_tokens:
            overflow.append(chunk)
        else:
            planned.append(chunk)
            used += chunk.tokens
    overhead = estimate_tokens(load_prompt("system") + load_prompt("classify"))
    summary = SendSummary(
        provider=llm.provider,
        model=llm.model,
        files=len({h.file_path for c in planned for h in c.hunks}),
        characters=used * 4,
        input_tokens=used + overhead * (len(planned) + 1),
        output_tokens=OUTPUT_TOKENS_PER_CHANGE * sum(len(c.hunks) for c in planned),
    )
    if not planned:
        _mark_overflow(result, overflow)
        return result
    if not consent(summary):
        result.notes.append(
            "AI checks were skipped because sending code wasn't agreed to. Run `verifypr` "
            "in a terminal once to agree, or set `llm.provider` in .verifypr.yml for CI."
        )
        return result

    system = load_prompt("system")
    goal, themes = request.description, []
    if request.level is InputLevel.AUTO:
        result.inferred = True
        user = render("infer_intent", context=_context_block(changes), files=_file_summary(changes))
        try:
            intent = ask_json(
                llm, system=system, user=user, schema=INTENT_SCHEMA, model=_Intent, max_tokens=1000
            )
            goal, themes = redact(intent.goal.strip())[:300] or None, intent.themes[:5]
            result.ai_used = True
        except LLMError as err:
            if err.kind in ("auth", "config"):
                result.notes.append(f"AI checks were skipped: {err.message}")
                return result
    result.intent = goal

    failed = 0
    stop: str | None = None
    for chunk in planned:
        if stop:
            reason = "Not checked by AI."
            result.changes += [
                _classified(h, Classification.UNCLEAR, reason, ai=False) for h in chunk.hunks
            ]
            continue
        ids = {f"C{i + 1}": h for i, h in enumerate(chunk.hunks)}
        user = render(
            "classify",
            task=_task_block(request, goal, themes),
            context=_context_block(changes),
            changes="\n\n".join(_render_change(sid, h) for sid, h in ids.items()),
        )
        try:
            verdicts = ask_json(
                llm,
                system=system,
                user=user,
                schema=CLASSIFY_SCHEMA,
                model=_Verdicts,
                max_tokens=OUTPUT_TOKENS_PER_CHANGE * len(ids) + 2000,
            )
        except LLMError as err:
            failed += 1
            if err.kind in ("auth", "config"):
                stop = err.message
            reason = "Not sure — AI check failed for this part."
            result.changes += [
                _classified(h, Classification.UNCLEAR, reason, ai=False) for h in ids.values()
            ]
            continue
        result.ai_used = True
        answered = {v.id.strip(): v for v in verdicts.changes if v.id.strip() in ids}
        for sid, hunk in ids.items():
            verdict = answered.get(sid)
            if verdict is None:
                result.changes.append(
                    _classified(
                        hunk, Classification.UNCLEAR, "The AI gave no answer for this change."
                    )
                )
            else:
                result.changes.append(_from_verdict(hunk, verdict, ids))
    _mark_overflow(result, overflow)
    if stop:
        result.notes.append(f"AI checks stopped: {stop}")
    elif failed:
        result.notes.append(
            f"The AI check skipped {failed} of {len(planned)} parts — run again to retry them."
        )
    result.findings = _scope_findings(result.changes, changes, request, already_flagged)
    return result


def _mark_overflow(result: AIResult, overflow: list[Chunk]) -> None:
    for chunk in overflow:
        reason = "Not checked by AI: this part is too large."
        result.changes += [
            _classified(h, Classification.UNCLEAR, reason, ai=False) for h in chunk.hunks
        ]
    if overflow:
        n = sum(len(c.hunks) for c in overflow)
        result.notes.append(
            f"{n} very large {'change was' if n == 1 else 'changes were'} not "
            "checked by the AI (size limit)."
        )


def _scope_findings(
    classified: list[ClassifiedChange],
    changes: ChangeSet,
    request: IntentRequest,
    already_flagged: set[str],
) -> list[Finding]:
    auto = request.level is InputLevel.AUTO
    hunks = {h.id: h for h in changes.hunks}
    by_file: dict[str, list[ClassifiedChange]] = defaultdict(list)
    unclear: dict[str, list[ClassifiedChange]] = defaultdict(list)
    for c in classified:
        if c.file_path in already_flagged:
            continue
        if c.classification is Classification.UNINTENDED:
            by_file[c.file_path].append(c)
        elif c.classification is Classification.UNCLEAR and c.ai:
            unclear[c.file_path].append(c)
    out: list[Finding] = []
    for path, items in by_file.items():
        best = max(items, key=lambda c: c.confidence)
        theme = f" ({best.theme})" if best.theme else ""
        title = (
            f"Looks unrelated to the main change: {path}{theme}"
            if auto
            else f"Not asked for: {path}{theme}"
        )
        out.append(
            Finding(
                id=f"scope_ai:{path}",
                problem_id="U2" if auto else "U1",
                category="scope_ai",
                severity=Severity.MEDIUM,
                confidence=best.confidence,
                inferred=auto,
                classification=Classification.UNINTENDED,
                evidence=tuple(hunk_evidence(hunks[c.hunk_id]) for c in items[:5]),
                title=title,
                why=best.reason,
                check_item=f"The changes to {path} really belong in this change",
            )
        )
    for path, items in unclear.items():
        best = max(items, key=lambda c: c.confidence)
        out.append(
            Finding(
                id=f"scope_ai_unclear:{path}",
                problem_id="U1",
                category="scope_ai_unclear",
                severity=Severity.LOW,
                confidence=max(best.confidence, 30),
                inferred=auto,
                classification=Classification.UNCLEAR,
                evidence=tuple(hunk_evidence(hunks[c.hunk_id]) for c in items[:5]),
                title=f"Not sure if the changes to {path} were asked for",
                why=best.reason,
            )
        )
    return out
