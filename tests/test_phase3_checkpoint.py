"""Phase 3 checkpoint, end to end through the CLI with a scripted AI (no network):
(a) zero-input check labels its guess, flags the unrelated change, and AI-based findings
never block on their own — while a committed secret still does;
(b) with a one-sentence description, the unrelated change is "Not asked for" and the test
is linked as "Needed for the change"."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.ai_helpers import classify_by_file, fake_ai, intent_reply
from tests.gitrepo import Repo
from tests.readonly import assert_unchanged, snapshot
from tests.test_cli import BANNED
from verifypr.cli import app
from verifypr.llm.fake import FakeLLM
from verifypr.llm.setup import LLMChoice, LLMSettings, store_consent

runner = CliRunner()
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
RULES = {
    "segments": ("intended", "segment filtering", "Adds the segment filter."),
    "billing": (
        "unintended",
        "billing rename",
        "Renames a billing setting the task doesn't mention.",
    ),
    "test_filter": ("supporting", "segment filtering", "Tests the new filter."),
}


def _repo(path: Path, *, secret: bool = False) -> Repo:
    repo = Repo(path)
    repo.write("src/segments/filter.py", "def segment(users):\n    return users\n")
    repo.write("src/billing/invoice.py", "TAX = 0.2\n")
    repo.commit("initial")
    repo.branch("add-segment-filter")
    repo.write(
        "src/segments/filter.py",
        "def segment(users, plan):\n    return [u for u in users if u.plan == plan]\n",
    )
    repo.write("src/billing/invoice.py", "TAX_RATE = 0.2\n")
    repo.write("tests/test_filter.py", "def test_segment():\n    assert segment([], 'pro') == []\n")
    if secret:
        repo.write("src/settings.py", f"AWS_KEY = '{FAKE_AWS}'\n")
    repo.commit("Add segment filter")
    return repo


def _use(monkeypatch: pytest.MonkeyPatch, llm: FakeLLM, *, explicit: bool = True) -> None:
    def choose(
        settings: LLMSettings, provider: str | None = None, model: str | None = None
    ) -> LLMChoice:
        return LLMChoice(llm, explicit)

    monkeypatch.setattr("verifypr.cli.choose_llm", choose)


def test_checkpoint_a_zero_input(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(repo_dir)
    llm = fake_ai(
        intent_reply("Add segment filtering", "segment filtering"), classify_by_file(RULES)
    )
    _use(monkeypatch, llm)
    before = snapshot(repo_dir)
    result = runner.invoke(app, ["--repo", str(repo_dir)])
    assert_unchanged(before, snapshot(repo_dir))
    out = result.output
    assert result.exit_code == 1, out
    assert "Checked against (my best guess): Add segment filtering" in out
    assert "Looks unrelated to the main change: src/billing/invoice.py (billing rename)" in out
    assert "Checked with AI (claude-opus-5-5 · " in out
    assert "tokens · under $0.01) plus rule-based checks." in out
    assert "would be sent to anthropic (claude-opus-5-5)" in out  # CI-style consent line
    assert not BANNED.search(out.split("Note: ")[0]), BANNED.search(out)


def test_checkpoint_a_secret_still_blocks(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(repo_dir, secret=True)
    everything_fine = classify_by_file({}, default=("intended", "all good", "Looks fine."))
    _use(monkeypatch, fake_ai(intent_reply("Add segment filtering"), everything_fine))
    result = runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "json"])
    data = json.loads(result.stdout)
    assert data["verdict"] == "fail"
    assert data["ai_used"]
    assert any(f["problem_id"] == "U6" for f in data["findings"])


def test_checkpoint_b_describe(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(repo_dir)
    llm = fake_ai(classify_by_file(RULES))
    _use(monkeypatch, llm)
    args = [
        "check",
        "--repo",
        str(repo_dir),
        "--describe",
        "Add segment filtering",
        "--format",
        "json",
    ]
    data = json.loads(runner.invoke(app, args).stdout)
    assert data["input_level"] == "describe"
    assert data["intent"] == "Add segment filtering"
    titles = [f["title"] for f in data["findings"]]
    assert "Not asked for: src/billing/invoice.py (billing rename)" in titles
    by_file = {c["file_path"]: c for c in data["changes"]}
    assert by_file["tests/test_filter.py"]["classification"] == "supporting"
    assert by_file["src/billing/invoice.py"]["classification"] == "unintended"
    assert len(llm.prompts) == 1


def test_markdown_lists_changes_not_asked_for(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(repo_dir)
    _use(monkeypatch, fake_ai(classify_by_file(RULES)))
    out = runner.invoke(
        app, ["explain", "--repo", str(repo_dir), "-d", "Add segment filtering"]
    ).stdout
    assert "Checked against: Add segment filtering" in out
    assert "### Changes not asked for" in out
    assert "| src/billing/invoice.py | 1-1 | Renames a billing setting" in out
    assert "1 not asked for · 0 not sure · 1 asked for · 1 needed for the change" in out
    assert not BANNED.search(out)


def test_without_a_key_basic_checks_run_and_say_so(repo_dir: Path) -> None:
    _repo(repo_dir)
    out = runner.invoke(app, ["--repo", str(repo_dir)]).output
    assert "Smarter AI checks were skipped: no AI key found" in out
    assert "Only basic rule-based checks ran." in out


def test_ci_without_explicit_provider_sends_nothing(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(repo_dir)
    llm = fake_ai(intent_reply("g"), classify_by_file(RULES))
    _use(monkeypatch, llm, explicit=False)
    out = runner.invoke(app, ["--repo", str(repo_dir)]).output
    assert llm.prompts == []
    assert "sending code wasn't agreed to" in out


def test_a_stored_no_is_respected(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(repo_dir)
    store_consent(repo.path, "anthropic", "claude-opus-5-5", False)
    llm = fake_ai(intent_reply("g"), classify_by_file(RULES))
    _use(monkeypatch, llm)
    runner.invoke(app, ["--repo", str(repo_dir)])
    assert llm.prompts == []


def test_no_llm_flag(repo_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _repo(repo_dir)
    llm = fake_ai()
    _use(monkeypatch, llm)
    out = runner.invoke(app, ["check", "--repo", str(repo_dir), "--no-llm"]).output
    assert llm.prompts == []
    assert "AI key" not in out


# ---- keys -------------------------------------------------------------------------------
def test_key_set_status_remove_never_show_the_key() -> None:
    secret = "sk-ant-api03-" + "z9" * 20
    set_out = runner.invoke(app, ["key", "set"], input=secret + "\n").output
    assert "Saved anthropic key …z9z9" in set_out
    status = runner.invoke(app, ["key", "status"]).output
    assert "anthropic: …z9z9 (from keychain)" in status
    removed = runner.invoke(app, ["key", "remove"]).output
    assert "Removed the saved anthropic key." in removed
    for output in (set_out, status, removed):
        assert secret not in output


def test_key_test_reports_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, fake_ai({"ok": True}))
    out = runner.invoke(app, ["key", "test"]).output
    assert "Connected to anthropic (claude-opus-5-5)." in out


# ---- intent init / show / clear ---------------------------------------------------------
def test_intent_init_save_then_check_uses_it(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(repo_dir)
    proposal = {
        "goal": "Add segment filtering",
        "allowed_paths": ["src/segments/**", "tests/**"],
        "forbidden_paths": ["src/billing/**"],
        "allowed_behaviors": ["Filter users by plan"],
        "forbidden_behaviors": ["Invoice totals"],
    }
    _use(monkeypatch, fake_ai(proposal))
    before = snapshot(repo_dir)
    out = runner.invoke(
        app, ["intent", "init", "Add segment filtering", "--repo", str(repo_dir), "--save"]
    ).output
    assert_unchanged(before, snapshot(repo_dir))
    assert "forbidden:" in out
    assert "src/billing/**" in out
    assert "Saved (outside your repository)" in out

    _use(monkeypatch, fake_ai(classify_by_file(RULES)))
    data = json.loads(
        runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "json"]).stdout
    )
    assert data["input_level"] == "describe"
    assert data["verdict"] == "fail"  # billing is in a "should not change" area
    assert (
        "Add segment filtering"
        in runner.invoke(app, ["intent", "show", "--repo", str(repo_dir)]).output
    )
    assert "Removed." in runner.invoke(app, ["intent", "clear", "--repo", str(repo_dir)]).output
    assert (
        "No saved scope" in runner.invoke(app, ["intent", "show", "--repo", str(repo_dir)]).output
    )
