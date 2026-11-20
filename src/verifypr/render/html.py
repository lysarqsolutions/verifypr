"""A self-contained, read-only HTML report (``check --report report.html``, "Share report").

Public interface: ``render_html(report)``.

Same headline and wording as the terminal and Markdown output. One file, no scripts, no
external resources, readable offline; light/dark via ``prefers-color-scheme``. Every value
from the repository is HTML-escaped.
"""

from __future__ import annotations

from html import escape

from verifypr import __version__
from verifypr.models import Classification, Report, Verdict
from verifypr.render.agent_prompt import agent_prompt
from verifypr.render.text import (
    checked_against,
    depth_line,
    importance,
    numbers,
    report_headline,
    status_label,
    view_only_badge,
    where,
)

_STATUS_CLASS = {Verdict.PASS: "ok", Verdict.WARN: "warn", Verdict.FAIL: "fail"}

CSS = """
:root{--bg:#fff;--fg:#1b1b1f;--muted:#5b5b66;--card:#f5f5f8;--line:#d9d9e0;
--ok:#1f7a3a;--warn:#8a5a00;--fail:#b3261e;--accent:#2457c5}
@media (prefers-color-scheme:dark){:root{--bg:#121216;--fg:#ececf1;--muted:#a9a9b6;
--card:#1d1d23;--line:#34343d;--ok:#5fd18a;--warn:#f1bb4a;--fail:#ff8a80;--accent:#8fb0ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.15rem;margin:1.6em 0 .4em}
.status{display:inline-block;font-weight:600;padding:2px 10px;border-radius:999px;
border:2px solid currentColor}.ok{color:var(--ok)}.warn{color:var(--warn)}.fail{color:var(--fail)}
.muted{color:var(--muted)}.badge{background:var(--card);border:1px solid var(--line);
padding:6px 10px;border-radius:8px;display:inline-block;margin-bottom:12px}
ol,ul{padding-left:1.4em}li{margin:.35em 0}.why{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--card)}pre{background:var(--card);border:1px solid var(--line);
padding:12px;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}
details{margin-top:1.4em}summary{cursor:pointer;font-weight:600}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def render_html(report: Report) -> str:
    cls, label = _STATUS_CLASS[report.verdict], status_label(report)
    out: list[str] = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>VerifyPR report — {_e(report_headline(report))}</title>",
        f"<style>{CSS}</style></head><body><main>",
    ]
    if report.view_only:
        out.append(f'<p class="badge">{_e(view_only_badge(report))}</p>')
    out.append(f'<p><span class="status {cls}">{_e(label)}</span></p>')
    out.append(f"<h1>{_e(report_headline(report))}</h1>")
    out.append(f'<p class="muted">{_e(report.compared)}</p>')
    if report.intent:
        out.append(f"<p>{_e(checked_against(report))}</p>")
    if report.progress:
        out.append(f"<p>Since the last check: {_e(report.progress.text())}</p>")
    for note in report.notes:
        out.append(f'<p class="muted">Note: {_e(note)}</p>')

    top = report.top_issues()
    if top:
        out.append("<h2>Top issues</h2><ol>")
        for f in top:
            out.append(
                f"<li><strong>{_e(f.title)}</strong> — <em>{_e(importance(f))}</em>"
                f'<br><span class="why">Why: {_e(f.why)}</span>'
                f'<br><span class="muted">Where: {_e(where(f))}</span></li>'
            )
        out.append("</ol>")
    maybe = report.worth_a_look()
    if maybe:
        out.append("<h2>Worth a look (possibly important, not sure)</h2><ul>")
        out += [f"<li>{_e(f.title)} — <em>{_e(importance(f))}</em></li>" for f in maybe[:5]]
        out.append("</ul>")
    checks = report.check_items()
    if checks:
        out.append("<h2>Please check before approving</h2><ul>")
        out += [f"<li>☐ {_e(item)}</li>" for item in checks]
        out.append("</ul>")
    prompt = agent_prompt(report)
    if prompt:
        out.append("<h2>Prompt for your coding agent</h2>")
        out.append(f"<pre>{_e(prompt)}</pre>")

    ranked = report.ranked()
    if ranked or report.changes:
        out.append("<details><summary>See details</summary>")
    if ranked:
        out.append(
            '<h2>All findings</h2><table><thead><tr><th scope="col">What</th>'
            '<th scope="col">Where</th><th scope="col">How important · How sure</th>'
            "</tr></thead><tbody>"
        )
        out += [
            f"<tr><td>{_e(f.title)}<br><span class='why'>{_e(f.why)}</span></td>"
            f"<td>{_e(where(f, limit=10))}</td><td>{_e(importance(f))}</td></tr>"
            for f in ranked
        ]
        out.append("</tbody></table>")
    not_asked = [c for c in report.changes if c.classification is Classification.UNINTENDED]
    if not_asked:
        out.append(
            '<h2>Changes not asked for</h2><table><thead><tr><th scope="col">File</th>'
            '<th scope="col">Lines</th><th scope="col">Why it was flagged</th></tr></thead><tbody>'
        )
        out += [
            f"<tr><td>{_e(c.file_path)}</td><td>{c.start_line}-{c.end_line}</td>"
            f"<td>{_e(c.reason)}</td></tr>"
            for c in not_asked
        ]
        out.append("</tbody></table>")
    if numbers(report):
        out.append(f"<h2>Numbers</h2><p>{_e(numbers(report))}</p>")
    if ranked or report.changes:
        out.append("</details>")
    out.append(
        f'<p class="muted"><small>VerifyPR {_e(__version__)} · {_e(depth_line(report))}'
        "</small></p></main></body></html>"
    )
    return "\n".join(out) + "\n"
