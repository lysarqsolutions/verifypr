"""Phase 4: the local server — token, host check, View only, consent, keys, undo patches."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.ai_helpers import classify_by_file, fake_ai, intent_reply
from tests.gitrepo import Repo
from tests.readonly import assert_unchanged, snapshot
from verifypr.llm.fake import FakeLLM
from verifypr.llm.setup import LLMChoice, LLMSettings
from verifypr.server.app import _NO_TELEMETRY, TOKEN_HEADER, Session, create_app

FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
UI_DIR = Path(__file__).resolve().parents[1] / "src" / "verifypr" / "ui"
BANNED = re.compile(
    r"\bhunks?\b|\bcontract\b|\bunintended\b|blast radius|behavioral delta|\bseverity\b|"
    r"\bconfidence\b|please verify|\bU\d+\b",
    re.IGNORECASE,
)
RULES = {
    "segments": ("intended", "segment filtering", "Adds the segment filter."),
    "billing": ("unintended", "billing rename", "Renames a billing setting nobody asked about."),
}


def _repo(path: Path, *, secret: bool = False) -> Repo:
    repo = Repo(path)
    repo.write("src/segments/filter.py", "def segment(users):\n    return users\n")
    repo.write("src/billing/invoice.py", "TAX = 0.2\n")
    repo.commit("initial")
    repo.branch("feature")
    repo.write(
        "src/segments/filter.py",
        "def segment(users, plan):\n    return [u for u in users if u.plan == plan]\n",
    )
    repo.write("src/billing/invoice.py", "TAX_RATE = 0.2\n")
    if secret:
        repo.write("src/settings.py", f"KEY = '{FAKE_AWS}'\n")
    repo.commit("work")
    return repo


def _client(root: Path, *, llm: FakeLLM | None = None, **kw: Any) -> tuple[TestClient, Session]:
    def choose(settings: LLMSettings) -> LLMChoice:
        return LLMChoice(llm, True) if llm else LLMChoice(None, False, "No AI key found.")

    session = Session(root=root, choose=choose, **kw)
    client = TestClient(create_app(session))
    client.headers[TOKEN_HEADER] = session.token
    return client, session


# ---- security ---------------------------------------------------------------------------
def test_api_needs_the_session_token(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    assert client.get("/api/state").status_code == 200
    del client.headers[TOKEN_HEADER]
    assert client.get("/api/state").status_code == 401
    client.headers[TOKEN_HEADER] = "wrong"
    assert client.get("/api/state").status_code == 401


def test_page_is_served_with_strict_headers(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    page = client.get("/")
    assert page.status_code == 200
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    for asset in ("/app.js", "/strings.js", "/style.css"):
        assert client.get(asset).status_code == 200


def test_unknown_host_is_rejected(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir, allowed_hosts={"127.0.0.1:5555"})
    assert client.get("/", headers={"host": "evil.example:5555"}).status_code == 403
    assert client.get("/", headers={"host": "127.0.0.1:5555"}).status_code == 200


def test_paths_outside_the_project_are_refused(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    # Allow rules only take a finding id; the path comes from the parsed changes.
    assert client.post("/api/allow", json={"finding_id": "../../etc/passwd"}).status_code == 409
    client.post("/api/check", json={})
    assert client.post("/api/allow", json={"finding_id": "nope"}).status_code == 409


# ---- checking, marking fine, allow rules ---------------------------------------------------
def test_check_returns_plain_results(repo_dir: Path) -> None:
    _repo(repo_dir, secret=True)
    client, _ = _client(repo_dir)
    data = client.post("/api/check", json={}).json()
    assert data["report"]["verdict"] == "fail"
    titles = [f["title"] for f in data["findings"]]
    assert "An AWS access key was added in src/settings.py" in titles
    assert all("problem_id" not in f for f in data["findings"])
    assert data["check_items"]
    assert "Please also fix these problems:" in data["agent_prompt"]
    assert FAKE_AWS not in json.dumps(data)


def test_keep_and_allow_rules(repo_dir: Path) -> None:
    _repo(repo_dir, secret=True)
    client, _ = _client(repo_dir)
    first = client.post("/api/check", json={}).json()
    secret = next(f for f in first["findings"] if f["category"] == "secrets")
    body = {"finding_id": secret["id"], "title": secret["title"]}
    assert client.post("/api/keep", json=body).status_code == 200
    second = client.post("/api/check", json={}).json()
    assert secret["id"] not in [f["id"] for f in second["findings"]]
    assert second["report"]["kept_count"] == 1
    # Marked as fine is not "fixed".
    progress = second["report"]["progress"]
    assert progress is None or progress["fixed"] == 0
    kept = client.get("/api/state").json()["kept"]
    assert kept == [{"id": secret["id"], "title": secret["title"]}]
    client.post("/api/unkeep", json={"finding_id": secret["id"]})
    assert client.get("/api/state").json()["kept"] == []
    third = client.post("/api/check", json={}).json()
    assert secret["id"] in [f["id"] for f in third["findings"]]

    # A serious finding is only ever allowed for that one file, never its folder.
    res = client.post("/api/allow", json={"finding_id": secret["id"]}).json()
    assert res["pattern"] == "src/settings.py"
    rules = client.get("/api/state").json()["allow_rules"]
    assert rules == [{"index": 0, "kind": "secrets", "paths": ["src/settings.py"], "reason": None}]
    assert "kind: secrets" in client.get("/api/allow-rules/export").text
    assert client.delete("/api/allow-rules/0").json() == {"ok": True}


# ---- consent ------------------------------------------------------------------------------
def test_consent_is_asked_before_anything_is_sent(repo_dir: Path) -> None:
    _repo(repo_dir)
    llm = fake_ai(intent_reply("Add segment filtering"), classify_by_file(RULES))
    client, _ = _client(repo_dir, llm=llm)
    first = client.post("/api/check", json={}).json()
    assert first["needs_consent"].endswith("Estimated cost: under $0.01.")
    assert llm.prompts == []
    assert not any("wasn't agreed to" in n for n in first["notes"])
    client.post("/api/consent", json={"allow": True})
    second = client.post("/api/check", json={}).json()
    assert second["report"]["ai_used"]
    assert any(c["classification"] == "unintended" for c in second["changes"])


def test_saying_no_sends_nothing(repo_dir: Path) -> None:
    _repo(repo_dir)
    llm = fake_ai(intent_reply("g"), classify_by_file(RULES))
    client, _ = _client(repo_dir, llm=llm)
    client.post("/api/check", json={})
    client.post("/api/consent", json={"allow": False})
    client.post("/api/check", json={})
    assert llm.prompts == []


# ---- View only ----------------------------------------------------------------------------
WRITES = [
    ("post", "/api/keep", {"finding_id": "x"}),
    ("post", "/api/unkeep", {"finding_id": "x"}),
    ("post", "/api/allow", {"finding_id": "x"}),
    ("post", "/api/scope/add", {"finding_id": "x"}),
    ("delete", "/api/allow-rules/0", None),
    ("post", "/api/scope", {"goal": "g"}),
    ("delete", "/api/scope", None),
    ("delete", "/api/key/anthropic", None),
    ("get", "/api/patch", None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_view_only_refuses_every_write(repo_dir: Path, method: str, path: str, body: Any) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir, view_only_locked=True)
    client.post("/api/check", json={})
    kwargs = {"json": body} if body is not None else {}
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 403
    assert res.json()["error"] == "View only is on — nothing can be changed or saved."


def test_view_only_saves_nothing_anywhere(repo_dir: Path, tmp_path: Path) -> None:
    _repo(repo_dir)
    llm = fake_ai(intent_reply("g"), classify_by_file(RULES))
    client, _ = _client(repo_dir, llm=llm, view_only_locked=True)
    state_dir = Path(__import__("os").environ["VERIFYPR_STATE_DIR"])
    state_dir.mkdir(parents=True, exist_ok=True)
    before_repo, before_state = snapshot(repo_dir), snapshot(state_dir)
    client.post("/api/check", json={})
    client.post("/api/consent", json={"allow": True})
    client.post("/api/check", json={})
    saved = client.post(
        "/api/key", json={"provider": "anthropic", "key": "sk-ant-api03-" + "q" * 30}
    ).json()
    assert saved["saved"] == "session"
    assert client.get("/api/report.html").status_code == 200  # sharing is still allowed
    assert client.post("/api/wizard-done").status_code == 200
    assert_unchanged(before_repo, snapshot(repo_dir))
    assert_unchanged(before_state, snapshot(state_dir))
    assert client.get("/api/state").json()["view_only"]


def test_turning_view_only_on_from_the_page(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    client.post("/api/view-only")
    assert client.get("/api/state").json()["view_only"]
    assert client.post("/api/keep", json={"finding_id": "x"}).status_code == 403


# ---- keys -----------------------------------------------------------------------------------
def test_keys_are_never_sent_back(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    secret = "sk-ant-api03-" + "k3y" * 12
    saved = client.post("/api/key", json={"provider": "anthropic", "key": secret}).json()
    assert saved["saved"] == "keychain"
    assert saved["masked"] == "…3yk3y"[-5:] or saved["masked"].startswith("…")
    everything = client.get("/api/state").text + json.dumps(saved)
    assert secret not in everything
    assert client.post("/api/key", json={"provider": "nope", "key": "x" * 20}).status_code == 400


def test_offline_refuses_keys_and_ai(repo_dir: Path) -> None:
    _repo(repo_dir)
    llm = fake_ai()
    client, _ = _client(repo_dir, llm=llm, offline=True)
    assert (
        client.post("/api/key", json={"provider": "anthropic", "key": "x" * 20}).status_code == 403
    )
    data = client.post("/api/check", json={}).json()
    assert data["report"]["offline"]
    assert "Offline: nothing was sent anywhere" in " ".join(data["notes"])
    assert llm.prompts == []


def test_key_test_endpoint(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir, llm=fake_ai({"ok": True}))
    assert client.post("/api/key/test", json={"provider": "anthropic"}).json()["ok"]


# ---- scope ----------------------------------------------------------------------------------
def test_suggest_and_save_scope(repo_dir: Path) -> None:
    _repo(repo_dir)
    proposal = {
        "goal": "Add segment filtering",
        "allowed_paths": ["src/segments/**"],
        "forbidden_paths": ["src/billing/**"],
        "allowed_behaviors": [],
        "forbidden_behaviors": [],
    }
    client, _ = _client(repo_dir, llm=fake_ai(proposal))
    first = client.post("/api/scope/suggest", json={"description": "Add segment filtering"}).json()
    assert "no code" in first["needs_consent"]
    client.post("/api/consent", json={"allow": True})
    scope = client.post("/api/scope/suggest", json={"description": "Add segment filtering"}).json()[
        "scope"
    ]
    assert scope["forbidden"]["paths"] == ["src/billing/**"]
    client.post("/api/scope", json={"goal": scope["goal"], "forbidden_paths": ["src/billing/**"]})
    assert client.get("/api/state").json()["scope"]["goal"] == "Add segment filtering"
    data = client.post("/api/check", json={}).json()
    assert data["report"]["verdict"] == "fail"  # billing is in a "should not change" area


# ---- undo patch (VerifyPR never applies it; the test does, to prove it's correct) ----------
def test_undo_patch_reverts_only_the_selected_changes(repo_dir: Path) -> None:
    repo = _repo(repo_dir)
    llm = fake_ai(intent_reply("g"), classify_by_file(RULES))
    client, _ = _client(repo_dir, llm=llm)
    client.post("/api/check", json={})
    client.post("/api/consent", json={"allow": True})
    client.post("/api/check", json={})
    patch = client.get("/api/patch").text
    assert "src/billing/invoice.py" in patch
    assert "src/segments/filter.py" not in patch
    (repo_dir.parent / "undo.patch").write_text(patch, encoding="utf-8", newline="")
    subprocess.run(
        ["git", "apply", "-R", str(repo_dir.parent / "undo.patch")], cwd=repo.path, check=True
    )
    assert (repo_dir / "src/billing/invoice.py").read_text(encoding="utf-8") == "TAX = 0.2\n"
    assert "plan" in (repo_dir / "src/segments/filter.py").read_text(encoding="utf-8")


def test_undo_patch_for_a_new_untracked_file(repo_dir: Path) -> None:
    repo = _repo(repo_dir)
    repo.write("dist/bundle.js", "built();\n")
    client, _ = _client(repo_dir)
    data = client.post("/api/check", json={}).json()
    build = next(f for f in data["findings"] if f["id"] == "artifacts:build")
    patch = client.get(f"/api/patch?findings={build['id']}").text
    assert "new file mode 100644" in patch
    (repo_dir.parent / "undo.patch").write_text(patch, encoding="utf-8", newline="")
    subprocess.run(
        ["git", "apply", "-R", str(repo_dir.parent / "undo.patch")], cwd=repo.path, check=True
    )
    assert not (repo_dir / "dist/bundle.js").exists()


# ---- UX: plain words in the page --------------------------------------------------------------
def _js_strings(text: str) -> list[tuple[str, str]]:
    return re.findall(r'"((?:[^"\\]|\\.)*)"|`([^`]*)`', text)


def test_page_text_uses_plain_words() -> None:
    source = (UI_DIR / "strings.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    texts = [a or b for a, b in _js_strings(code)]
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    visible_html = re.sub(r"<[^>]+>", " ", html)
    for text in [*texts, visible_html]:
        assert not BANNED.search(text), (text, BANNED.search(text))


def test_page_has_no_inline_scripts_or_styles_and_labels_every_field() -> None:
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"<script(?![^>]*\bsrc=)", html) == []
    assert ' style="' not in html
    assert '<html lang="en">' in html
    for field_id in re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html):
        if field_id == "remember":
            continue  # wrapped in its <label>
        assert f'for="{field_id}"' in html, field_id
    app_js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in app_js
    assert "localStorage" not in app_js
    assert "sessionStorage" not in app_js


# ---- walkthrough regressions -------------------------------------------------------------
def test_page_text_points_to_settings_and_drops_backticks() -> None:
    from verifypr.server.app import page_text

    note = "Smarter checks were skipped: no AI key. Add one with `verifypr key set`."
    assert page_text(note) == "Smarter checks were skipped: no AI key. Add one in Settings."
    assert page_text("compared with `main`") == "compared with main"


def test_check_results_have_no_terminal_markup(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    data = client.post("/api/check", json={}).json()
    assert "`" not in data["report"]["compared"]
    assert all("`" not in n and "verifypr key" not in n for n in data["notes"])


def test_local_model_needs_no_key(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    providers = client.get("/api/state").json()["providers"]
    ollama = next(p for p in providers if p["provider"] == "ollama")
    assert ollama["source"] == "no_key_needed"


def test_results_come_before_the_ai_setup_card() -> None:
    page = (UI_DIR / "index.html").read_text(encoding="utf-8")
    assert page.index('id="summary"') < page.index('id="wizard"')


def test_web_framework_telemetry_is_switched_off(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect

    from fastapi import FastAPI

    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    if "telemetry" in inspect.signature(FastAPI).parameters:
        config = _NO_TELEMETRY["telemetry"]
        assert config["auto_configure"] is False
        assert [config[k] for k in ("tracing", "metrics", "logs")] == [False, False, False]
    assert client.get("/api/state").status_code == 200


def test_allow_pattern_is_folder_only_for_minor_kinds() -> None:
    from verifypr.server.app import allow_pattern

    assert allow_pattern("docs/guide/a.md", serious=False) == "docs/guide/**"
    assert allow_pattern("src/settings.py", serious=True) == "src/settings.py"
    assert allow_pattern("README.md", serious=False) == "README.md"


def test_page_gets_the_same_headline_and_status_as_the_terminal(repo_dir: Path) -> None:
    from verifypr.models import Report, Verdict
    from verifypr.render.text import status_label

    _repo(repo_dir)
    client, _ = _client(repo_dir)
    report = client.post("/api/check", json={}).json()["report"]
    assert report["headline"]
    assert report["status_label"] in {"Needs attention", "No problems found", "Don't merge yet"}
    clean = Report(verdict=Verdict.PASS, compared="c", file_count=1)
    assert status_label(clean) == "No problems found"
    assert status_label(clean.model_copy(update={"ai_used": True})) == "Looks good"
    js = (UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "function headline" not in js


def test_add_a_finding_to_what_this_change_should_do(repo_dir: Path) -> None:
    _repo(repo_dir, secret=True)
    client, _ = _client(repo_dir)
    finding = client.post("/api/check", json={}).json()["findings"][0]
    res = client.post("/api/scope/add", json={"finding_id": finding["id"]}).json()
    folder = res["pattern"]
    assert folder.endswith("/**")
    assert folder in client.get("/api/state").json()["scope"]["allowed"]["paths"]
    client.post("/api/scope/add", json={"finding_id": finding["id"]})
    assert client.get("/api/state").json()["scope"]["allowed"]["paths"].count(folder) == 1


def test_key_test_refuses_unknown_providers(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    assert client.post("/api/key/test", json={"provider": "evil"}).status_code == 400


def test_patch_with_nothing_to_undo_says_so(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.branch("f")
    repo.write("a.py", "x = 2\n")
    client, _ = _client(repo_dir)
    client.post("/api/check", json={})
    res = client.get("/api/patch")
    assert res.status_code == 409
    assert res.json()["error"] == "Nothing to undo."


def test_page_refuses_mangled_keys_and_warns_on_odd_ones(repo_dir: Path) -> None:
    _repo(repo_dir)
    client, _ = _client(repo_dir)
    good = "sk-ant-api03-" + "Ab9_" * 20
    res = client.post("/api/key", json={"provider": "anthropic", "key": good + "\n" + good})
    assert res.status_code == 400
    assert "pasted twice" in res.json()["error"]
    assert good not in res.text
    odd = client.post("/api/key", json={"provider": "anthropic", "key": "sk-ant-usr-" + "x" * 90})
    assert odd.status_code == 200
    assert "Test connection" in odd.json()["note"]
