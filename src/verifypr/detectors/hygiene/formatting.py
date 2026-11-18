"""U3: changes that are only formatting, line endings, encoding markers, import order,
or file permissions — noise that hides the real change.

Public interface: ``detect(ctx)``, ``classify_hunk(hunk)``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from enum import Enum

from verifypr.detectors.base import DetectorContext, hunk_evidence
from verifypr.models import Evidence, Finding, Hunk, Severity

_IMPORT_RE = re.compile(
    r"^\s*(?:import\s|from\s+\S+\s+import\s|using\s+[\w.]+\s*;|#include\s|"
    r"(?:const|let|var)\s+\w+\s*=\s*require\(|package\s)"
)
_BOM = "﻿"


class HunkKind(str, Enum):
    LINE_ENDINGS = "line_endings"
    BOM = "bom"
    WHITESPACE = "whitespace"
    IMPORT_ORDER = "import_order"
    REAL = "real"


def _squash(lines: tuple[str, ...]) -> str:
    return "".join("".join(lines).split())


def classify_hunk(hunk: Hunk) -> HunkKind:
    removed, added = hunk.removed, hunk.added
    if not removed or not added:
        return HunkKind.REAL
    if removed == added:
        return HunkKind.REAL
    if len(removed) == len(added) and [r.rstrip("\r") for r in removed] == [
        a.rstrip("\r") for a in added
    ]:
        return HunkKind.LINE_ENDINGS
    if (
        removed[0].lstrip(_BOM) == added[0].lstrip(_BOM)
        and removed[0] != added[0]
        and removed[1:] == added[1:]
    ):
        return HunkKind.BOM
    if _squash(removed) == _squash(added):
        return HunkKind.WHITESPACE
    strip_r = [r.strip() for r in removed if r.strip()]
    strip_a = [a.strip() for a in added if a.strip()]
    if (
        strip_r
        and sorted(strip_r) == sorted(strip_a)
        and all(_IMPORT_RE.match(line) for line in strip_r)
    ):
        return HunkKind.IMPORT_ORDER
    return HunkKind.REAL


_TEXT = {
    HunkKind.LINE_ENDINGS: (
        "Line endings changed in {n} {files}",
        "Only the invisible line-ending characters (Windows vs. Mac/Linux) changed, which "
        "makes the change look bigger than it is and can hide real edits.",
        95,
    ),
    HunkKind.BOM: (
        "An invisible encoding marker was added or removed in {n} {files}",
        "A byte-order mark (an invisible character at the start of the file) changed; "
        "some tools treat the file differently because of it.",
        90,
    ),
    HunkKind.WHITESPACE: (
        "{n} {files} changed only in formatting",
        "Only spaces, indentation, or line wrapping changed — nothing that affects behavior, "
        "but it adds noise to the review.",
        90,
    ),
    HunkKind.IMPORT_ORDER: (
        "Imports were only reordered in {n} {files}",
        "The same imports were moved around; this doesn't change behavior but adds noise.",
        90,
    ),
}


def _plural_files(n: int) -> str:
    return "file" if n == 1 else "files"


def _formatting_findings(ctx: DetectorContext) -> list[Finding]:
    only: dict[HunkKind, list[Evidence]] = defaultdict(list)
    mixed: list[Evidence] = []
    for change in ctx.changes.files:
        if change.binary:
            continue
        hunks = ctx.changes.hunks_for(change.path)
        if not hunks:
            continue
        kinds = [classify_hunk(h) for h in hunks]
        noise = [(h, k) for h, k in zip(hunks, kinds, strict=True) if k is not HunkKind.REAL]
        if not noise:
            continue
        if len(noise) == len(hunks):
            dominant = max(set(kinds), key=kinds.count)
            only[dominant].append(hunk_evidence(hunks[0]))
        else:
            mixed.append(hunk_evidence(noise[0][0]))
    findings: list[Finding] = []
    for kind, evidence in only.items():
        title, why, confidence = _TEXT[kind]
        n = len(evidence)
        findings.append(
            Finding(
                id=f"formatting:{kind.value}",
                problem_id="U3",
                category="formatting",
                severity=Severity.LOW,
                confidence=confidence,
                evidence=tuple(evidence),
                title=title.format(n=n, files=_plural_files(n)),
                why=why,
            )
        )
    if mixed:
        n = len(mixed)
        findings.append(
            Finding(
                id="formatting:mixed",
                problem_id="U3",
                category="formatting",
                severity=Severity.LOW,
                confidence=70,
                evidence=tuple(mixed),
                title=f"Formatting changes are mixed in with real changes in {n} "
                f"{_plural_files(n)}",
                why="Some parts of these files changed only in formatting, which makes the "
                "real changes harder to spot.",
            )
        )
    return findings


def _mode_findings(ctx: DetectorContext) -> list[Finding]:
    findings: list[Finding] = []
    for change in ctx.changes.files:
        if not (change.old_mode and change.new_mode) or change.old_mode == change.new_mode:
            continue
        executable = change.new_mode.endswith("755")
        title = (
            f"{change.path} was made executable"
            if executable
            else f"File permissions changed for {change.path}"
        )
        findings.append(
            Finding(
                id=f"file_mode:{change.path}",
                problem_id="U3",
                category="file_mode",
                severity=Severity.MEDIUM if executable else Severity.LOW,
                confidence=95,
                evidence=(Evidence(file_path=change.path, start_line=1, end_line=1),),
                title=title,
                why=f"The file's permissions changed from {change.old_mode} to "
                f"{change.new_mode}, which is easy to miss in a review.",
                check_item=f"{change.path} is meant to be executable" if executable else None,
            )
        )
    return findings


def detect(ctx: DetectorContext) -> list[Finding]:
    return _formatting_findings(ctx) + _mode_findings(ctx)
