"""Markdown report (CLAUDE.md §5.1). Public interface: ``render_markdown(report)``.

Same headline and wording as the terminal: answer first, details in a collapsed block.
"""

from __future__ import annotations

from verifypr import __version__
from verifypr.models import Report, Verdict
from verifypr.render.text import importance, report_headline, where

_ICON = {Verdict.PASS: "✅", Verdict.WARN: "⚠️", Verdict.FAIL: "⛔"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Report) -> str:
    icon = "🔎" if report.file_count == 0 else _ICON[report.verdict]
    out = [f"## {icon} {report_headline(report)}"]
    if report.file_count:
        out += ["", f"Compared: {report.compared}"]
    for note in report.notes:
        out.append(f"> Note: {note}")
    if report.file_count == 0:
        out += ["", "Pick another branch to compare with: `verifypr --base <branch>`"]
        return "\n".join(out) + "\n"

    ranked = report.ranked()
    if ranked:
        out += ["", "**Top issues**"]
        for n, finding in enumerate(ranked[:3], 1):
            out.append(f"{n}. {finding.title} — *{importance(finding)}*  ")
            out.append(f"   {finding.why}")

    checks = report.check_items()
    if checks:
        out += ["", "### ✅ Please check before approving"]
        out += [f"- [ ] {item}" for item in checks]

    if ranked:
        out += [
            "",
            "<details><summary>See details</summary>",
            "",
            "| What | Where | How important · How sure |",
            "|------|-------|--------------------------|",
        ]
        for finding in ranked:
            out.append(
                f"| {_cell(finding.title)} | {_cell(where(finding, limit=5))} | "
                f"{importance(finding)} |"
            )
        out += [
            "",
            "### Numbers",
            f"{report.file_count} files changed · "
            f"{len(ranked)} findings · {report.allowed_count} allowed by your rules",
            "",
            "</details>",
        ]

    depth = "AI-assisted checks" if report.ai_used else "basic checks only"
    out += ["", f"<sub>VerifyPR {__version__} · {depth}</sub>"]
    return "\n".join(out) + "\n"
