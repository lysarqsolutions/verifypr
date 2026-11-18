"""Terminal output (CLAUDE.md §1.5). Public interface: ``render_text(report, verbose)``.

Default: headline, what was compared, up to 3 top issues, and the Please-check list.
``verbose`` adds every finding with its locations. Plain words only — no internal names.
"""

from __future__ import annotations

from verifypr.models import Finding, Report, Verdict
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
        lines = (
            f"{ev.start_line}" if ev.start_line == ev.end_line else f"{ev.start_line}-{ev.end_line}"
        )
        spots.append(f"{ev.file_path}:{lines}")
    more = len(finding.evidence) - limit
    return ", ".join(spots) + (f" and {more} more" if more > 0 else "")


def render_text(report: Report, *, verbose: bool = False) -> str:
    out: list[str] = []
    icon = "•" if report.file_count == 0 else STATUS_ICON[report.verdict]
    out.append(f"{icon} {report_headline(report)}")
    out.append(f"  {report.compared}")
    for note in report.notes:
        out.append(f"  Note: {note}")
    if report.file_count == 0:
        out.append("  Pick another branch to compare with: verifypr --base <branch>")
        return "\n".join(out) + "\n"

    ranked = report.ranked()
    shown = ranked if verbose else ranked[:3]
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

    checks = report.check_items()
    if checks:
        out.append("")
        out.append("Please check before approving")
        out.extend(f"  [ ] {item}" for item in checks)

    out.append("")
    hidden = len(ranked) - len(shown)
    if hidden > 0:
        out.append(
            f"{hidden} more {'finding' if hidden == 1 else 'findings'} — "
            "run `verifypr --verbose` to see everything."
        )
    if report.allowed_count:
        n = report.allowed_count
        out.append(
            f"{n} {'finding was' if n == 1 else 'findings were'} hidden by your allow rules."
        )
    if not report.ai_used:
        out.append("Only basic rule-based checks ran.")
    return "\n".join(out) + "\n"
