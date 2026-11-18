"""U1: files changed outside what the Review Contract allows (path rules only).

Public interface: ``detect(ctx)``. Does nothing without a contract; AI-based scope
checks arrive in Phase 3.
"""

from __future__ import annotations

from verifypr.analysis.globs import glob_match
from verifypr.detectors.base import DetectorContext, file_evidence, hunk_evidence
from verifypr.intent.contract import Tolerance
from verifypr.models import ChangeKind, Classification, Evidence, Finding, Severity

_NEW_FILE_SEVERITY = {
    Tolerance.BLOCK: Severity.HIGH,
    Tolerance.WARN: Severity.MEDIUM,
    Tolerance.ALLOW: Severity.LOW,
}


def _evidence(ctx: DetectorContext, path: str) -> tuple[Evidence, ...]:
    hunks = ctx.changes.hunks_for(path)
    return (hunk_evidence(hunks[0]),) if hunks else (file_evidence(path),)


def detect(ctx: DetectorContext) -> list[Finding]:
    contract = ctx.contract
    if contract is None:
        return []
    findings: list[Finding] = []
    for change in ctx.changes.files:
        paths = [p for p in (change.path, change.old_path) if p]
        forbidden = next(
            (pat for pat in contract.forbidden.paths for p in paths if glob_match(pat, p)), None
        )
        if forbidden:
            findings.append(
                Finding(
                    id=f"scope:forbidden:{change.path}",
                    problem_id="U1",
                    category="scope",
                    severity=Severity.HIGH,
                    confidence=95,
                    critical=True,
                    classification=Classification.UNINTENDED,
                    evidence=_evidence(ctx, change.path),
                    title=f"Changed something that shouldn't change: {change.path}",
                    why=f"{change.path} is in the area '{forbidden}' that this change "
                    "was not supposed to touch.",
                    check_item=f"The changes to {change.path} were really needed",
                )
            )
            continue
        allowed = contract.allowed.paths
        if not allowed or any(glob_match(pat, p) for pat in allowed for p in paths):
            continue
        is_new = change.change_kind is ChangeKind.ADD or change.untracked
        if is_new:
            tolerance = contract.tolerances.new_files_outside_allowed
            findings.append(
                Finding(
                    id=f"scope:new:{change.path}",
                    problem_id="U1",
                    category="scope_new_file",
                    severity=_NEW_FILE_SEVERITY[tolerance],
                    confidence=90,
                    classification=Classification.UNINTENDED,
                    evidence=_evidence(ctx, change.path),
                    title=f"New file outside the expected area: {change.path}",
                    why="This file was added outside the folders this change was expected "
                    "to work in.",
                    check_item=f"The new file {change.path} belongs in this change",
                )
            )
        else:
            findings.append(
                Finding(
                    id=f"scope:outside:{change.path}",
                    problem_id="U1",
                    category="scope",
                    severity=Severity.MEDIUM,
                    confidence=85,
                    classification=Classification.UNINTENDED,
                    evidence=_evidence(ctx, change.path),
                    title=f"Changed a file outside the expected area: {change.path}",
                    why="This file is outside the folders this change was expected to work in.",
                    check_item=f"The changes to {change.path} were really needed",
                )
            )
    return findings
