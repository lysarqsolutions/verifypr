"""Run a check end to end. Public interface: ``CheckRequest``, ``run_check(request)``,
``collect_changes(request)``.

Read-only towards the repository: loads config and the Review Contract, collects changes
via read-only git, runs rule-based detectors, then (if an AI provider is set up and sending
is agreed to) the AI intent checks, applies allow rules, and builds the ``Report``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from verifypr import userstate
from verifypr.analysis.changes import ChangeSet
from verifypr.config import Config, load_config
from verifypr.detectors.base import DetectorContext
from verifypr.detectors.registry import run_detectors
from verifypr.intent.classifier import AIResult, IntentRequest, run_ai_checks
from verifypr.intent.contract import IntentContract, load_review_contract
from verifypr.intent.propose import saved_contract
from verifypr.llm.setup import LLMChoice, LLMSettings, SendSummary, choose_llm, estimate_cost
from verifypr.models import InputLevel, Report
from verifypr.sources.local_git import CompareOptions, LocalGit
from verifypr.state import is_frozen
from verifypr.verdict import apply_allow_rules, decide

ConsentHook = Callable[[Path, SendSummary, bool], bool]


def _deny(_root: Path, _summary: SendSummary, _explicit: bool) -> bool:
    return False


@dataclass(frozen=True)
class CheckRequest:
    repo: Path = field(default_factory=Path.cwd)
    compare: CompareOptions = field(default_factory=CompareOptions)
    contract_path: Path | None = None
    describe: str | None = None
    use_ai: bool = True
    use_saved_contract: bool = True
    use_user_state: bool = True
    offline: bool = False
    choose: Callable[[LLMSettings], LLMChoice] = choose_llm
    consent: ConsentHook = _deny


def _prepare(request: CheckRequest) -> tuple[LocalGit, Config, CompareOptions]:
    git = LocalGit.open(request.repo)
    config = load_config(git.root)
    compare = request.compare
    if compare.base is None and config.base:
        compare = replace(compare, base=config.base)
    return git, config, compare


def collect_changes(request: CheckRequest) -> ChangeSet:
    git, _config, compare = _prepare(request)
    return git.collect(compare)


def _contract(request: CheckRequest, root: Path) -> IntentContract | None:
    if request.contract_path:
        return load_review_contract(request.contract_path)
    return saved_contract(root) if request.use_saved_contract else None


def run_check(request: CheckRequest) -> tuple[Report, ChangeSet]:
    git, config, compare = _prepare(request)
    if request.use_user_state:
        extra = tuple(userstate.allow_rules(git.root))
        config = config.model_copy(update={"allow": config.allow + extra})
    contract = _contract(request, git.root)
    changes = git.collect(compare)
    description = request.describe or (contract.goal if contract else None)
    level = InputLevel.DESCRIBE if (description or contract) else InputLevel.AUTO

    context = DetectorContext(changes=changes, config=config, contract=contract)
    findings = run_detectors(context)
    notes = list(changes.notes)

    ai = AIResult()
    model_name: str | None = None
    tokens = 0
    cost: str | None = None
    if request.offline:
        notes.append("Offline: nothing was sent anywhere; only rule-based checks ran.")
    if request.use_ai and not request.offline and not changes.is_empty:
        choice = request.choose(config.llm)
        if choice.client is None:
            if choice.reason:
                notes.append(choice.reason)
        else:
            flagged = {e.file_path for f in findings if f.category == "scope" for e in f.evidence}
            ai = run_ai_checks(
                choice.client,
                changes,
                IntentRequest(level=level, description=description, contract=contract),
                config.llm,
                config.ignore_globs,
                lambda summary: request.consent(git.root, summary, choice.explicit),
                flagged,
            )
            notes.extend(ai.notes)
            if ai.ai_used:
                model_name = choice.client.model
                usage = choice.client.usage
                tokens = usage.total
                cost = estimate_cost(model_name, usage.input_tokens, usage.output_tokens)

    kept, allowed = apply_allow_rules(findings + ai.findings, config.allow)
    allowed += len(context.suppressed)
    marked_fine = userstate.kept_findings(git.root) if request.use_user_state else set()
    kept_count = sum(1 for f in kept if f.id in marked_fine)
    kept = [f for f in kept if f.id not in marked_fine]
    tolerances = contract.tolerances if contract else config.tolerances
    verdict, attention = decide(kept, tolerances, level)
    report = Report(
        verdict=verdict,
        input_level=level,
        compared=changes.compared,
        base=changes.base_label,
        findings=tuple(kept),
        skipped=tuple(ai.skipped),
        notes=tuple(notes),
        ai_used=ai.ai_used,
        file_count=len(changes.files),
        allowed_count=allowed,
        attention_count=attention,
        changes=tuple(ai.changes),
        intent=ai.intent if level is InputLevel.AUTO else description,
        intent_inferred=level is InputLevel.AUTO and ai.intent is not None,
        ai_model=model_name,
        ai_tokens=tokens,
        ai_cost=cost,
        kept_count=kept_count,
        offline=request.offline,
        view_only=is_frozen(),
    )
    if request.use_user_state:
        report = report.model_copy(
            update={
                "progress": userstate.progress(
                    userstate.last_result(git.root), report, userstate.kept_findings(git.root)
                )
            }
        )
    return report, changes
