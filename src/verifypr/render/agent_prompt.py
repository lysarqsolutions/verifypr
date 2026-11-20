"""The "Tell the agent to fix this" text (CLAUDE.md §4 Phase 4).

Public interface: ``agent_prompt(report)``, ``fixable(report)``.

Lists each change that wasn't asked for (with file and lines) and each serious problem,
and asks the coding agent to fix only those and confirm nothing else changed. Findings the
user marked "It's fine" are already gone from the report, so they're never included.
It's text to copy; VerifyPR never sends it anywhere.
"""

from __future__ import annotations

from verifypr.models import Classification, Finding, Report, Severity
from verifypr.render.text import where


def fixable(report: Report) -> list[Finding]:
    """Findings worth asking the agent to fix: changes not asked for, and Important issues."""
    return [
        f
        for f in report.ranked()
        if f.classification is Classification.UNINTENDED
        or f.category in {"scope", "scope_new_file"}
        or f.severity is Severity.HIGH
    ]


def agent_prompt(report: Report) -> str:
    items = fixable(report)
    if not items and not any(f.severity is Severity.MEDIUM for f in report.top_issues(limit=50)):
        return ""
    not_asked = [f for f in items if f.classification is Classification.UNINTENDED]
    problems = [f for f in items if f not in not_asked]
    confirm = [
        f for f in report.top_issues(limit=50) if f not in items and f.severity is Severity.MEDIUM
    ]
    lines: list[str] = []
    if report.intent:
        lines.append(f"The task was: {report.intent}")
        lines.append("")
    if not_asked:
        lines.append(
            "Please undo these changes, which weren't part of the task, and leave everything "
            "else as it is:"
        )
        lines += [f"{n}. {where(f, limit=10)} — {f.why}" for n, f in enumerate(not_asked, 1)]
        lines.append("")
    if problems:
        lines.append("Please also fix these problems:")
        lines += [
            f"{n}. {f.title} ({where(f, limit=10)}). {f.why}" for n, f in enumerate(problems, 1)
        ]
        lines.append("")
    if confirm:
        lines.append("Please confirm these changes were intended, and undo them if they weren't:")
        lines += [f"{n}. {f.title} ({where(f, limit=10)})" for n, f in enumerate(confirm, 1)]
        lines.append("")
    lines.append(
        "Don't change anything else. When you're done, list exactly which files you changed."
    )
    return "\n".join(lines) + "\n"
