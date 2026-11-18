"""Turn findings into a verdict, and apply allow rules.

Public interface: ``apply_allow_rules(findings, rules)``, ``decide(findings, tolerances,
input_level)``.

Rules (CLAUDE.md §4 Phase 1):
- ``critical`` findings (committed secrets, explicit "should not change" areas) → FAIL.
- A category whose tolerance is ``block`` → FAIL; ``allow`` → ignored for the verdict.
- Other Important/Worth-a-look findings, or a ``warn`` tolerance → WARN.
- Findings based on *inferred* intent never go above WARN in Auto mode.
"""

from __future__ import annotations

from verifypr.analysis.globs import any_match
from verifypr.config import AllowRule
from verifypr.intent.contract import Tolerance, Tolerances
from verifypr.models import Finding, InputLevel, Severity, Verdict

_TOLERANCE_BY_CATEGORY = {
    "formatting": "formatting_only_changes",
    "dependencies": "dependency_changes",
    "scope_new_file": "new_files_outside_allowed",
}


def apply_allow_rules(
    findings: list[Finding], rules: tuple[AllowRule, ...]
) -> tuple[list[Finding], int]:
    kept: list[Finding] = []
    allowed = 0
    for finding in findings:
        paths = [e.file_path for e in finding.evidence]
        if any(
            rule.kind == finding.category and all(any_match(rule.paths, p) for p in paths)
            for rule in rules
        ):
            allowed += 1
        else:
            kept.append(finding)
    return kept, allowed


def _tolerance(finding: Finding, tolerances: Tolerances) -> Tolerance | None:
    key = _TOLERANCE_BY_CATEGORY.get(finding.category)
    value = getattr(tolerances, key) if key else None
    return value if isinstance(value, Tolerance) else None


def decide(
    findings: list[Finding], tolerances: Tolerances, input_level: InputLevel
) -> tuple[Verdict, int]:
    """Return the verdict and how many findings caused it (for the headline)."""
    fail: list[Finding] = []
    warn: list[Finding] = []
    for finding in findings:
        tolerance = _tolerance(finding, tolerances)
        if tolerance is Tolerance.ALLOW:
            continue
        capped = finding.inferred and input_level is InputLevel.AUTO
        if (finding.critical or tolerance is Tolerance.BLOCK) and not capped:
            fail.append(finding)
        elif (
            finding.critical
            or tolerance in (Tolerance.BLOCK, Tolerance.WARN)
            or finding.severity in (Severity.HIGH, Severity.MEDIUM)
        ):
            warn.append(finding)
    if fail:
        return Verdict.FAIL, len(fail)
    if warn:
        return Verdict.WARN, len(warn)
    return Verdict.PASS, 0
