"""Plain-language labels for user-facing output (CLAUDE.md §1.5.3).

Public interface: ``severity_label``, ``confidence_label``, ``classification_label``,
``headline``. Every user-facing surface must use these instead of internal names.
"""

from __future__ import annotations

from verifypr.models import Classification, Severity, Verdict

_SEVERITY = {
    Severity.HIGH: "Important",
    Severity.MEDIUM: "Worth a look",
    Severity.LOW: "Minor",
}

_CLASSIFICATION = {
    Classification.UNINTENDED: "Not asked for",
    Classification.UNCLEAR: "Not sure",
    Classification.SUPPORTING: "Needed for the change",
    Classification.INTENDED: "Asked for",
}


def severity_label(severity: Severity) -> str:
    return _SEVERITY[severity]


def confidence_label(confidence: int) -> str:
    if not 0 <= confidence <= 100:
        raise ValueError("confidence must be between 0 and 100")
    if confidence >= 80:
        return "Sure"
    if confidence >= 50:
        return "Likely"
    return "Not sure"


def classification_label(classification: Classification) -> str:
    return _CLASSIFICATION[classification]


def headline(verdict: Verdict, issue_count: int, *, ai_used: bool) -> str:
    """One honest headline sentence. Rules-only clean results never say 'Looks good'."""
    if verdict is not Verdict.PASS and issue_count < 1:
        raise ValueError(f"a {verdict.value} verdict needs at least one issue")
    if verdict is Verdict.FAIL:
        noun = "issue" if issue_count == 1 else "issues"
        return f"Don't merge yet — {issue_count} serious {noun}"
    if verdict is Verdict.WARN:
        noun = "change needs" if issue_count == 1 else "changes need"
        return f"{issue_count} {noun} your attention"
    if ai_used:
        return "Looks good — every change matches what was asked"
    return "No problems found by basic checks"
