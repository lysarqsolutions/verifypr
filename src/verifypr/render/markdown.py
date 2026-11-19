"""Markdown report (CLAUDE.md §5.1). Public interface: ``render_markdown(report)``.

Same headline and wording as the terminal: answer first, details in a collapsed block.
"""

from __future__ import annotations

from verifypr import __version__
from verifypr.models import Classification, Report, Verdict
from verifypr.render.text import checked_against, importance, numbers, report_headline, where

_ICON = {Verdict.PASS: "✅", Verdict.WARN: "⚠️", Verdict.FAIL: "⛔"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Report) -> str:
    icon = "🔎" if report.file_count == 0 else _ICON[report.verdict]
    out = [f"## {icon} {report_headline(report)}"]
    if report.file_count:
        out += ["", f"Compared: {report.compared}"]
    if report.file_count and report.intent:
        out += ["", checked_against(report)]
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
        not_asked = [c for c in report.changes if c.classification is Classification.UNINTENDED]
        if not_asked:
            out += [
                "",
                "### Changes not asked for",
                "| File | Lines | Why it was flagged |",
                "|------|-------|--------------------|",
            ]
            out += [
                f"| {_cell(c.file_path)} | {c.start_line}-{c.end_line} | {_cell(c.reason)} |"
                for c in not_asked
            ]
        out += [
            "",
            "### Numbers",
            f"{report.file_count} files changed · "
            f"{len(ranked)} findings · {report.allowed_count} allowed by your rules"
            + (f"  \n{numbers(report)}" if numbers(report) else ""),
            "",
            "</details>",
        ]

    depth = (
        f"model: {report.ai_model} · tokens: {report.ai_tokens}"
        if report.ai_used
        else "basic checks only"
    )
    level = f" · input: {report.input_level.value}"
    out += ["", f"<sub>VerifyPR {__version__} · {depth}{level}</sub>"]
    return "\n".join(out) + "\n"
