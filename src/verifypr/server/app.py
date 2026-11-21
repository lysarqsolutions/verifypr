"""The local web page's server (``verifypr ui``). Runs only on this computer.

Public interface: ``Session``, ``create_app(session)``, ``serve(root, ...)``.

Security (CLAUDE.md §7): binds 127.0.0.1 only; every ``/api`` call needs the random
per-session token (sent in a header; the page gets it from the URL fragment, which browsers
never send to servers); the Host header must be this machine (blocks DNS-rebinding); strict
Content-Security-Policy; file paths are only ever ones from the parsed diff, checked to be
inside the project. In View only mode every route that changes or saves anything returns
403. API keys are accepted but never returned, logged, or stored in the browser.
"""

from __future__ import annotations

import hmac
import inspect
import re
import secrets
import socket
import threading
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from verifypr import userstate
from verifypr.analysis.changes import ChangeSet
from verifypr.analysis.redaction import redact
from verifypr.analysis.undo import by_hand_message, undo_for_findings
from verifypr.config import AllowRule, load_config
from verifypr.errors import VerifyPRError
from verifypr.intent.contract import IntentContract, PathRules
from verifypr.intent.propose import clear_contract, propose_contract, save_contract, saved_contract
from verifypr.llm.base import LLMError
from verifypr.llm.keys import (
    ENV_VARS,
    NO_KEY_PROVIDERS,
    KeychainUnavailableError,
    anthropic_login,
    check_key,
    masked,
    remember_for_session,
    remove_key,
    resolve_key,
    save_key,
)
from verifypr.llm.setup import (
    PROVIDERS,
    LLMChoice,
    LLMSettings,
    SendSummary,
    choose_llm,
    store_consent,
    stored_consent,
)
from verifypr.models import Report, Severity
from verifypr.pipeline import CheckRequest, run_check
from verifypr.render.agent_prompt import agent_prompt, fixable
from verifypr.render.html import render_html
from verifypr.render.markdown import render_markdown
from verifypr.render.text import importance, report_headline, status_label
from verifypr.sources.local_git import CompareOptions, LocalGit
from verifypr.state import freeze, is_frozen, read_json, repo_key, write_json

TOKEN_HEADER = "X-VerifyPR-Token"
VIEW_ONLY_MESSAGE = "View only is on — nothing can be changed or saved."
SETTINGS_FILE = "ui.json"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


@dataclass
class Session:
    root: Path
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    base: str | None = None
    view_only_locked: bool = False
    offline: bool = False
    allowed_hosts: set[str] = field(default_factory=set)
    choose: Callable[[LLMSettings], LLMChoice] = choose_llm
    consent_answers: dict[str, bool] = field(default_factory=dict)
    pending_consent: SendSummary | None = None
    last_changes: ChangeSet | None = None
    last_report: Report | None = None
    describe: str | None = None

    @property
    def view_only(self) -> bool:
        return self.view_only_locked or is_frozen()

    def consent(self, root: Path, summary: SendSummary, explicit: bool) -> bool:
        key = f"{summary.provider}|{summary.model}"
        remembered = stored_consent(root, summary.provider, summary.model)
        if remembered is not None:
            return remembered
        if key in self.consent_answers:
            return self.consent_answers[key]
        self.pending_consent = summary
        return False


# ---- request bodies ---------------------------------------------------------------------
class CheckBody(BaseModel):
    describe: str | None = Field(default=None, max_length=4000)
    base: str | None = Field(default=None, max_length=200)


class FindingBody(BaseModel):
    finding_id: str = Field(min_length=1, max_length=500)
    title: str | None = Field(default=None, max_length=500)


class AllowBody(BaseModel):
    finding_id: str = Field(min_length=1, max_length=500)


class ConsentBody(BaseModel):
    allow: bool


class ScopeBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    allowed_paths: list[str] = Field(default_factory=list, max_length=50)
    forbidden_paths: list[str] = Field(default_factory=list, max_length=50)
    allowed_behaviors: list[str] = Field(default_factory=list, max_length=20)
    forbidden_behaviors: list[str] = Field(default_factory=list, max_length=20)


class SuggestBody(BaseModel):
    description: str = Field(min_length=1, max_length=4000)


class KeyBody(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    key: str = Field(min_length=1, max_length=2000, repr=False)
    remember: bool = True


class ProviderBody(BaseModel):
    provider: str = Field(min_length=1, max_length=50)


# ---- helpers ----------------------------------------------------------------------------
def _ui_settings(root: Path) -> dict[str, Any]:
    value = read_json(SETTINGS_FILE).get(repo_key(root))
    return value if isinstance(value, dict) else {}


def _set_ui_setting(root: Path, key: str, value: Any) -> None:
    data = read_json(SETTINGS_FILE)
    current = data.get(repo_key(root)) or {}
    current[key] = value
    data[repo_key(root)] = current
    write_json(SETTINGS_FILE, data)


# No telemetry, ever: newer FastAPI versions have OpenTelemetry hooks that can export
# request data when the environment asks for it. Turn all of it off where supported.
_NO_TELEMETRY: dict[str, Any] = (
    {
        "telemetry": {
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
            "exclude": lambda scope: True,
        }
    }
    if "telemetry" in inspect.signature(FastAPI).parameters
    else {}
)


def page_text(text: str) -> str:
    """Terminal wording -> page wording: point to Settings, drop Markdown backticks."""
    text = re.sub(
        r"Add one with `verifypr key set[^`]*`",
        "Add one in Settings",
        text,
    )
    return text.replace("`", "")


def allow_pattern(path: str, *, serious: bool) -> str:
    """Where "Always allow this kind of change here" applies: the folder for minor kinds,
    only that one file for serious ones (a committed secret must never silence a folder)."""
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    return f"{folder}/**" if folder and not serious else path


def _inside(root: Path, rel: str) -> Path | None:
    full = (root / rel).resolve()
    return full if full.is_relative_to(root.resolve()) else None


def _editor_link(root: Path, rel: str, line: int) -> str | None:
    full = _inside(root, rel)
    if full is None:
        return None
    return f"vscode://file/{full.as_posix()}:{line}"


def _changes_view(session: Session, report: Report, changes: ChangeSet) -> list[dict[str, Any]]:
    hunks = {h.id: h for h in changes.hunks}
    out = []
    for c in report.changes:
        hunk = hunks.get(c.hunk_id)
        code = [redact(line) for line in (hunk.raw[1:] if hunk else ())][:80]
        out.append(
            {
                **c.model_dump(mode="json"),
                "code": code,
                "editor": _editor_link(session.root, c.file_path, c.start_line),
            }
        )
    return out


def _findings_view(session: Session, report: Report) -> list[dict[str, Any]]:
    fix = {f.id for f in fixable(report)}
    out = []
    for f in report.ranked():
        first = f.evidence[0]
        out.append(
            {
                **f.model_dump(mode="json", exclude={"problem_id"}),
                "importance": importance(f),
                "where": [
                    e.file_path if e.file_level else f"{e.file_path}:{e.start_line}"
                    for e in f.evidence[:10]
                ],
                "editor": _editor_link(session.root, first.file_path, first.start_line),
                "fixable": f.id in fix,
                "worth_a_look": f in report.worth_a_look(),
            }
        )
    return out


def _providers(session: Session) -> list[dict[str, Any]]:
    out = []
    for provider in PROVIDERS:
        secret, source = resolve_key(provider)
        entry: dict[str, Any] = {"provider": provider, "source": source}
        if secret:
            entry["masked"] = masked(secret)
            if source == "environment":
                entry["env_var"] = ENV_VARS.get(provider)
        elif provider == "anthropic" and anthropic_login():
            entry["source"], entry["signed_in"] = "login", anthropic_login()
        elif provider in NO_KEY_PROVIDERS:
            entry["source"] = "no_key_needed"
        out.append(entry)
    return out


def _branches(root: Path) -> list[str]:
    import subprocess

    proc = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes",
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    names = proc.stdout.decode("utf-8", errors="replace").split()
    return [n for n in names if not n.endswith("/HEAD")][:200]


# ---- app --------------------------------------------------------------------------------
def create_app(session: Session) -> FastAPI:
    if session.view_only_locked:
        freeze()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, **_NO_TELEMETRY)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = (request.headers.get("host") or "").lower()
        if session.allowed_hosts and host not in session.allowed_hosts:
            return PlainTextResponse("Forbidden host", status_code=403)
        if request.url.path.startswith("/api/"):
            token = request.headers.get(TOKEN_HEADER, "")
            if not hmac.compare_digest(token, session.token):
                return JSONResponse({"error": "Missing or wrong session token."}, status_code=401)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def write_allowed() -> None:
        if session.view_only:
            raise HTTPException(status_code=403, detail=VIEW_ONLY_MESSAGE)

    def static(name: str, media: str) -> Response:
        data = (resources.files("verifypr") / "ui" / name).read_bytes()
        return Response(data, media_type=media)

    @app.get("/", response_class=HTMLResponse)
    def index() -> Response:
        return static("index.html", "text/html; charset=utf-8")

    @app.get("/app.js")
    def script() -> Response:
        return static("app.js", "text/javascript; charset=utf-8")

    @app.get("/strings.js")
    def strings() -> Response:
        return static("strings.js", "text/javascript; charset=utf-8")

    @app.get("/style.css")
    def style() -> Response:
        return static("style.css", "text/css; charset=utf-8")

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        contract = saved_contract(session.root)
        return {
            "project": session.root.name,
            "base": session.base,
            "branches": _branches(session.root),
            "view_only": session.view_only,
            "view_only_locked": session.view_only_locked,
            "offline": session.offline,
            "providers": _providers(session),
            "wizard_done": bool(_ui_settings(session.root).get("wizard_done")),
            "kept": [
                {"id": k, "title": page_text(v) or "A change you marked as fine earlier"}
                for k, v in userstate.kept_titles(session.root).items()
            ],
            "allow_rules": [
                {"index": i, **r.model_dump(mode="json")}
                for i, r in enumerate(userstate.allow_rules(session.root))
            ],
            "scope": contract.model_dump(mode="json") if contract else None,
        }

    @app.post("/api/check")
    def check(body: CheckBody) -> dict[str, Any]:
        if body.base is not None:
            session.base = body.base or None
        session.describe = body.describe or None
        session.pending_consent = None
        request = CheckRequest(
            repo=session.root,
            compare=CompareOptions(base=session.base),
            describe=session.describe,
            offline=session.offline,
            choose=session.choose,
            consent=session.consent,
        )
        try:
            report, changes = run_check(request)
        except VerifyPRError as err:
            return {"error": err.message, "hint": err.hint}
        userstate.save_result(session.root, report)
        session.last_report, session.last_changes = report, changes
        pending = session.pending_consent
        notes = [page_text(n) for n in report.notes if not (pending and "wasn't agreed to" in n)]
        dumped = report.model_dump(mode="json", exclude={"findings", "changes", "notes"})
        dumped["compared"] = page_text(report.compared)
        dumped["headline"] = page_text(report_headline(report))
        dumped["status_label"] = status_label(report)
        return {
            "report": dumped,
            "notes": notes,
            "findings": _findings_view(session, report),
            "changes": _changes_view(session, report, changes),
            "check_items": report.check_items(),
            "top_ids": [f.id for f in report.top_issues()],
            "agent_prompt": agent_prompt(report),
            "needs_consent": pending.describe() if pending else None,
        }

    @app.post("/api/consent")
    def consent(body: ConsentBody) -> dict[str, Any]:
        summary = session.pending_consent
        if summary is None:
            return {"ok": True}
        session.consent_answers[f"{summary.provider}|{summary.model}"] = body.allow
        if not session.view_only:
            store_consent(session.root, summary.provider, summary.model, body.allow)
        session.pending_consent = None
        return {"ok": True}

    @app.post("/api/keep")
    def keep(body: FindingBody) -> dict[str, Any]:
        write_allowed()
        userstate.keep_finding(session.root, body.finding_id, body.title)
        return {"ok": True}

    @app.post("/api/unkeep")
    def unkeep(body: FindingBody) -> dict[str, Any]:
        write_allowed()
        userstate.unkeep_finding(session.root, body.finding_id)
        return {"ok": True}

    @app.post("/api/allow")
    def allow(body: AllowBody) -> dict[str, Any]:
        write_allowed()
        report = session.last_report
        finding = (
            next((f for f in report.findings if f.id == body.finding_id), None) if report else None
        )
        if finding is None:
            raise HTTPException(status_code=409, detail="Run a check first.")
        path = finding.evidence[0].file_path
        if _inside(session.root, path) is None:
            raise HTTPException(status_code=400, detail="That path is outside the project.")
        pattern = allow_pattern(path, serious=finding.critical or finding.severity is Severity.HIGH)
        userstate.add_allow_rule(session.root, AllowRule(kind=finding.category, paths=(pattern,)))
        return {"ok": True, "pattern": pattern}

    @app.delete("/api/allow-rules/{index}")
    def remove_rule(index: int) -> dict[str, Any]:
        write_allowed()
        return {"ok": userstate.remove_allow_rule(session.root, index)}

    @app.get("/api/allow-rules/export", response_class=PlainTextResponse)
    def export_rules() -> str:
        rules = userstate.allow_rules(session.root)
        if not rules:
            return "# No allow rules yet.\n"
        lines = ["allow:"]
        for r in rules:
            lines.append(f"  - kind: {r.kind}")
            lines.append("    paths: [" + ", ".join(f"'{p}'" for p in r.paths) + "]")
        return "\n".join(lines) + "\n"

    @app.post("/api/scope/suggest")
    def suggest(body: SuggestBody) -> dict[str, Any]:
        if session.offline:
            return {"error": "Offline: suggesting a scope needs the AI helper."}
        config = load_config(session.root)
        choice = session.choose(config.llm)
        if choice.client is None:
            return {"error": page_text(choice.reason or "No AI helper is set up.")}
        summary = SendSummary(
            choice.client.provider,
            choice.client.model,
            0,
            len(body.description),
            800,
            400,
            what="Your description and the names of your project's top folders (no code)",
        )
        if not session.consent(session.root, summary, choice.explicit):
            return {"needs_consent": summary.describe()}
        try:
            files = LocalGit.open(session.root).project_files()
            contract = propose_contract(choice.client, body.description, files)
        except (LLMError, VerifyPRError) as err:
            return {"error": err.message}
        return {"scope": contract.model_dump(mode="json")}

    @app.post("/api/scope")
    def scope_save(body: ScopeBody) -> dict[str, Any]:
        write_allowed()
        contract = IntentContract(
            goal=body.goal,
            allowed=PathRules(
                paths=tuple(body.allowed_paths), behaviors=tuple(body.allowed_behaviors)
            ),
            forbidden=PathRules(
                paths=tuple(body.forbidden_paths), behaviors=tuple(body.forbidden_behaviors)
            ),
        )
        save_contract(session.root, contract)
        return {"ok": True}

    @app.post("/api/scope/add")
    def scope_add(body: FindingBody) -> dict[str, Any]:
        write_allowed()
        report = session.last_report
        finding = (
            next((f for f in report.findings if f.id == body.finding_id), None) if report else None
        )
        if finding is None:
            raise HTTPException(status_code=409, detail="Run a check first.")
        path = finding.evidence[0].file_path
        if _inside(session.root, path) is None:
            raise HTTPException(status_code=400, detail="That path is outside the project.")
        pattern = allow_pattern(path, serious=False)
        current = saved_contract(session.root) or IntentContract(goal=session.describe)
        allowed = tuple(dict.fromkeys((*current.allowed.paths, pattern)))
        forbidden = tuple(p for p in current.forbidden.paths if p != pattern)
        save_contract(
            session.root,
            current.model_copy(
                update={
                    "allowed": current.allowed.model_copy(update={"paths": allowed}),
                    "forbidden": current.forbidden.model_copy(update={"paths": forbidden}),
                }
            ),
        )
        return {"ok": True, "pattern": pattern}

    @app.delete("/api/scope")
    def scope_clear() -> dict[str, Any]:
        write_allowed()
        return {"ok": clear_contract(session.root)}

    @app.get("/api/patch", response_class=PlainTextResponse)
    def patch(findings: str = "") -> Response:
        write_allowed()
        report, changes = session.last_report, session.last_changes
        if report is None or changes is None:
            raise HTTPException(status_code=409, detail="Run a check first.")
        wanted = set(filter(None, findings.split(",")))
        chosen = [f for f in report.findings if f.id in wanted] if wanted else fixable(report)
        result = undo_for_findings(changes, chosen)
        if not result.patch:
            detail = by_hand_message(result.by_hand) if result.by_hand else "Nothing to undo."
            raise HTTPException(status_code=409, detail=detail)
        return PlainTextResponse(
            result.patch,
            headers={"Content-Disposition": 'attachment; filename="verifypr-undo.patch"'},
        )

    @app.get("/api/report.{kind}")
    def report_file(kind: str) -> Response:
        report = session.last_report
        if report is None:
            raise HTTPException(status_code=409, detail="Run a check first.")
        renders = {
            "html": (render_html, "text/html; charset=utf-8"),
            "md": (render_markdown, "text/markdown; charset=utf-8"),
            "json": (lambda r: r.model_dump_json(indent=2), "application/json"),
        }
        if kind not in renders:
            raise HTTPException(status_code=404)
        render, media = renders[kind]
        return Response(
            render(report),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="verifypr-report.{kind}"'},
        )

    @app.post("/api/key")
    def key_save(body: KeyBody) -> dict[str, Any]:
        if session.offline:
            raise HTTPException(status_code=403, detail="Offline: AI keys can't be used.")
        if body.provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail="Unknown provider.")
        secret = body.key.strip()
        checked = check_key(body.provider, secret)
        if checked.error:
            raise HTTPException(status_code=400, detail=checked.error)
        warning = f" {checked.warning} Use Test connection to check it." if checked.warning else ""
        if body.remember and not session.view_only:
            try:
                save_key(body.provider, secret)
                return {
                    "ok": True,
                    "masked": masked(secret),
                    "saved": "keychain",
                    "note": warning.strip(),
                }
            except KeychainUnavailableError as err:
                remember_for_session(body.provider, secret)
                note = f"{err}{warning}"
                return {"ok": True, "masked": masked(secret), "saved": "session", "note": note}
        remember_for_session(body.provider, secret)
        return {"ok": True, "masked": masked(secret), "saved": "session", "note": warning.strip()}

    @app.post("/api/key/test")
    def key_test(body: ProviderBody) -> dict[str, Any]:
        if session.offline:
            return {"ok": False, "message": "Offline: nothing is sent."}
        if body.provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail="Unknown provider.")
        config = load_config(session.root)
        choice = session.choose(config.llm.model_copy(update={"provider": body.provider}))
        if choice.client is None:
            return {"ok": False, "message": choice.reason or "Not set up."}
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        try:
            choice.client.complete_json(
                system="Reply with JSON only.",
                user='Reply with {"ok": true}.',
                schema=schema,
                max_tokens=4000,
            )
        except LLMError as err:
            return {"ok": False, "message": err.message}
        return {"ok": True, "message": f"Connected ({choice.client.model})"}

    @app.delete("/api/key/{provider}")
    def key_remove(provider: str) -> dict[str, Any]:
        write_allowed()
        return {"ok": remove_key(provider)}

    @app.post("/api/view-only")
    def view_only_on() -> dict[str, Any]:
        freeze()
        return {"ok": True, "view_only": True}

    @app.post("/api/wizard-done")
    def wizard_done() -> dict[str, Any]:
        if not session.view_only:
            _set_ui_setting(session.root, "wizard_done", True)
        return {"ok": True}

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    return app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def serve(
    root: Path,
    *,
    base: str | None = None,
    port: int = 0,
    open_browser: bool = True,
    view_only_locked: bool = False,
    offline: bool = False,
) -> None:
    import uvicorn

    port = port or _free_port()
    session = Session(
        root=root,
        base=base,
        view_only_locked=view_only_locked,
        offline=offline,
        allowed_hosts={f"127.0.0.1:{port}", f"localhost:{port}"},
    )
    url = f"http://127.0.0.1:{port}/#token={session.token}"
    print(f"VerifyPR is running on this computer only: {url}")
    print("Keep this window open while you use the page. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(session), host="127.0.0.1", port=port, log_level="warning", access_log=False
    )
