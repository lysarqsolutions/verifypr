"""Terminal output (CLAUDE.md §1.5). Public interface: ``render_text(report, verbose)``.

Default: headline, what was compared, up to 3 top issues, and the Please-check list.
``verbose`` adds every finding with its locations. Plain words only — no internal names.
"""

from __future__ import annotations

from verifypr.models import Classification, Finding, Report, Verdict
from verifypr.render.labels import confidence_label, headline, severity_label

STATUS_ICON = {Verdict.PASS: "✔", Verdict.WARN: "⚠", Verdict.FAIL: "✖"}


def report_headline(report: Report) -> str:
    if report.file_count == 0:
        base = f" compared with `{report.base}`" if report.base else ""
        return f"No changes found{base}"
    return headline(report.verdict, report.attention_count, ai_used=report.ai_used)


def importance(finding: Finding) -> str:
    return f"{severity_label(finding.severity)} · {confidence_label(finding.confidence)}"


def where(finding: Finding, limit: int = 3) -> str:
    spots = []
    for ev in finding.evidence[:limit]:
        if ev.file_level:
            spots.append(ev.file_path)
            continue
        lines = (
            f"{ev.start_line}" if ev.start_line == ev.end_line else f"{ev.start_line}-{ev.end_line}"
        )
        spots.append(f"{ev.file_path}:{lines}")
    more = len(finding.evidence) - limit
    return ", ".join(spots) + (f" and {more} more" if more > 0 else "")


def checked_against(report: Report) -> str:
    if report.intent_inferred:
        return (
            f"Checked against (my best guess): {report.intent} — say what it was for with "
            '`verifypr check --describe "..."` for a stricter check'
        )
    return f"Checked against: {report.intent}"


def numbers(report: Report) -> str | None:
    if not report.changes:
        return None
    parts = [
        (Classification.UNINTENDED, "not asked for"),
        (Classification.UNCLEAR, "not sure"),
        (Classification.INTENDED, "asked for"),
        (Classification.SUPPORTING, "needed for the change"),
    ]
    return " · ".join(f"{report.count(c)} {label}" for c, label in parts)


def depth_line(report: Report) -> str:
    if report.ai_used:
        return f"Checked with AI ({report.ai_model}) plus rule-based checks."
    return "Only basic rule-based checks ran."


def render_text(report: Report, *, verbose: bool = False) -> str:
    out: list[str] = []
    icon = "•" if report.file_count == 0 else STATUS_ICON[report.verdict]
    out.append(f"{icon} {report_headline(report)}")
    if report.file_count:
        out.append(f"  {report.compared}")
    if report.file_count and report.intent:
        out.append(f"  {checked_against(report)}")
    for note in report.notes:
        out.append(f"  Note: {note}")
    if report.file_count == 0:
        out.append("  Pick another branch to compare with: verifypr --base <branch>")
        return "\n".join(out) + "\n"

    ranked = report.ranked()
    shown = ranked if verbose else report.top_issues()
    maybe = [] if verbose else report.worth_a_look()[:3]
    if shown:
        out.append("")
        out.append("All findings" if verbose else "Top issues")
        for n, finding in enumerate(shown, 1):
            out.append(f"  {n}. {finding.title} — {importance(finding)}")
            out.append(f"     Why: {finding.why}")
            if verbose:
                out.append(f"     Where: {where(finding, limit=10)}")
                for ev in finding.evidence[:3]:
                    if ev.snippet:
                        first = ev.snippet.splitlines()[0].rstrip("\r")[:120]
                        out.append(f"       {ev.file_path}:{ev.start_line}  {first}")
            else:
                out.append(f"     Where: {where(finding)}")

    if maybe:
        out.append("")
        out.append("Worth a look (possibly important, not sure)")
        out.extend(f"  - {f.title} — {importance(f)}" for f in maybe)

    checks = report.check_items()
    if checks:
        out.append("")
        out.append("Please check before approving")
        out.extend(f"  [ ] {item}" for item in checks)

    out.append("")
    hidden = len(ranked) - len(shown) - len(maybe)
    if hidden > 0:
        out.append(
            f"{hidden} more {'finding' if hidden == 1 else 'findings'} — "
            "run `verifypr --verbose` to see everything."
        )
    if report.allowed_count:
        n = report.allowed_count
        out.append(f"{n} {'item was' if n == 1 else 'items were'} hidden by your allow rules.")
    if verbose and numbers(report):
        out.append(f"Numbers: {numbers(report)}")
    out.append(depth_line(report))
    return "\n".join(out) + "\n"
