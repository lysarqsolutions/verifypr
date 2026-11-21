"""Phase 4 CLI: View only, offline, HTML report, agent prompt, export-patch, Check again."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.gitrepo import Repo
from tests.readonly import assert_unchanged, snapshot
from verifypr.cli import app
from verifypr.models import Evidence, Finding, Report, Severity, Verdict
from verifypr.render.html import render_html

runner = CliRunner()
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


def _repo(path: Path) -> Repo:
    repo = Repo(path)
    repo.write("src/app.py", "x = 1\n")
    repo.commit()
    repo.branch("feature")
    repo.write("src/app.py", "x = 2\n")
    repo.write(".env", f"AWS_ACCESS_KEY_ID={FAKE_AWS}\n")
    repo.commit("work")
    return repo


def _state_dir() -> Path:
    path = Path(os.environ["VERIFYPR_STATE_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_view_only_badge_and_nothing_saved(repo_dir: Path) -> None:
    _repo(repo_dir)
    before_repo, before_state = snapshot(repo_dir), snapshot(_state_dir())
    out = runner.invoke(app, ["--repo", str(repo_dir), "--view-only"]).output
    assert out.splitlines()[0] == "👁 View only — nothing will be changed or saved"
    assert_unchanged(before_repo, snapshot(repo_dir))
    assert_unchanged(before_state, snapshot(_state_dir()))


def test_view_only_from_environment_and_offline_badge(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _repo(repo_dir)
    monkeypatch.setenv("VERIFYPR_VIEW_ONLY", "1")
    out = runner.invoke(app, ["check", "--repo", str(repo_dir), "--offline"]).output
    assert out.splitlines()[0] == "👁 View only · Offline — nothing leaves this computer"
    assert "Offline: nothing was sent anywhere" in out


def test_view_only_refuses_saving_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERIFYPR_VIEW_ONLY", "1")
    result = runner.invoke(app, ["key", "set"], input="sk-ant-" + "x" * 30 + "\n")
    assert result.exit_code == 3
    assert "View only is on — nothing can be changed or saved" in result.output


def test_check_again_progress_line(repo_dir: Path) -> None:
    repo = _repo(repo_dir)
    runner.invoke(app, ["--repo", str(repo_dir)])
    repo.git("rm", "-q", ".env")
    repo.commit("remove env file")
    out = runner.invoke(app, ["--repo", str(repo_dir)]).output
    assert "Since your last check: Fixed 2 of 2 · 0 still open · 0 new issues" in out


def test_html_report_and_agent_prompt(repo_dir: Path, tmp_path: Path) -> None:
    _repo(repo_dir)
    report = tmp_path / "report.html"
    runner.invoke(app, ["check", "--repo", str(repo_dir), "--report", str(report)])
    html = report.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "Don&#x27;t merge yet" in html or "Don't merge yet" in html
    assert FAKE_AWS not in html
    prompt = runner.invoke(app, ["check", "--repo", str(repo_dir), "--agent-prompt"]).stdout
    assert prompt.startswith("Please also fix these problems:")
    assert "An AWS access key was added in .env" in prompt


def test_html_escapes_repository_text() -> None:
    finding = Finding(
        id="x", problem_id="U6", category="secrets", severity=Severity.HIGH, confidence=90,
        evidence=(Evidence(file_path="<img src=x onerror=alert(1)>.py", start_line=1, end_line=1),),
        title="<script>alert(1)</script>", why="why",
    )  # fmt: skip
    html = render_html(
        Report(
            verdict=Verdict.WARN, compared="c", findings=(finding,), file_count=1, attention_count=1
        )
    )
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html


def test_export_patch_writes_exact_bytes_that_git_can_reverse(
    repo_dir: Path, tmp_path: Path
) -> None:
    repo = _repo(repo_dir)
    patch_file = tmp_path / "undo.patch"
    result = runner.invoke(
        app,
        [
            "export-patch",
            "--repo",
            str(repo_dir),
            "--finding",
            "env_file:.env",
            "-o",
            str(patch_file),
        ],
    )
    assert result.exit_code == 0, result.output
    data = patch_file.read_bytes()
    assert b"\r\n" not in data
    subprocess.run(["git", "apply", "-R", str(patch_file)], cwd=repo.path, check=True)
    assert not (repo_dir / ".env").exists()


def test_export_patch_with_nothing_to_undo(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.branch("f")
    repo.write("a.py", "x = 2\n")
    result = runner.invoke(app, ["export-patch", "--repo", str(repo_dir)])
    assert result.exit_code == 0
    assert "Nothing to undo." in result.output


def test_markdown_has_the_agent_prompt_and_next_step(repo_dir: Path) -> None:
    _repo(repo_dir)
    out = runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "markdown"]).stdout
    assert "**Next step:** paste the prompt below into your coding agent" in out
    assert "### Prompt for your coding agent" in out


def test_agent_prompt_asks_to_confirm_medium_findings() -> None:
    from verifypr.render.agent_prompt import agent_prompt

    finding = Finding(
        id="m", problem_id="U18", category="access_rules", severity=Severity.MEDIUM,
        confidence=70, evidence=(Evidence(file_path="menu.ts", start_line=14, end_line=14),),
        title="Access rules changed in menu.ts", why="why",
    )  # fmt: skip
    report = Report(
        verdict=Verdict.WARN, compared="c", findings=(finding,), file_count=1, attention_count=1
    )
    prompt = agent_prompt(report)
    assert "Please confirm these changes were intended" in prompt
    assert "Access rules changed in menu.ts (menu.ts:14)" in prompt


def test_marked_fine_is_not_counted_as_fixed() -> None:
    from verifypr import userstate

    report = Report(verdict=Verdict.PASS, compared="c", findings=(), file_count=1)
    assert userstate.progress({"a"}, report, {"a"}) is None
    progress = userstate.progress({"a", "b"}, report, {"a"})
    assert progress is not None
    assert (progress.fixed, progress.previous) == (1, 1)


def test_old_kept_list_format_still_reads(tmp_path: Path) -> None:
    from verifypr import state, userstate

    state.write_json(userstate.KEPT_FILE, {state.repo_key(tmp_path): ["x"]})
    assert userstate.kept_titles(tmp_path) == {"x": ""}


def test_export_patch_names_the_saved_file(repo_dir: Path, tmp_path: Path) -> None:
    _repo(repo_dir)
    out = tmp_path / "undo.patch"
    args = ["export-patch", "--repo", str(repo_dir), "--finding", "env_file:.env", "-o", str(out)]
    result = runner.invoke(app, args)
    assert f'git apply -R "{out}"' in result.output


def test_binary_changes_are_listed_to_undo_by_hand(repo_dir: Path) -> None:
    from verifypr.analysis.undo import undo_for_findings
    from verifypr.pipeline import CheckRequest, run_check
    from verifypr.sources.local_git import CompareOptions

    repo = Repo(repo_dir)
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\x00\x01")
    repo.commit()
    repo.branch("f")
    (repo_dir / "logo.png").write_bytes(b"\x89PNG\x00\x02\x03")
    _, changes = run_check(CheckRequest(repo=repo_dir, compare=CompareOptions(), use_ai=False))
    finding = Finding(
        id="b", problem_id="U1", category="scope", severity=Severity.MEDIUM, confidence=90,
        evidence=(Evidence(file_path="logo.png", start_line=1, end_line=1, file_level=True),),
        title="t", why="w",
    )  # fmt: skip
    result = undo_for_findings(changes, [finding])
    assert result.patch == ""
    assert result.by_hand == ("logo.png",)


# ---- API key format check ---------------------------------------------------------------
GOOD_KEY = "sk-ant-api03-" + "Ab9_" * 20


@pytest.mark.parametrize(
    ("key", "problem"),
    [
        ("", "No key was entered"),
        (GOOD_KEY + chr(0xA0) + GOOD_KEY, "pasted twice"),
        (GOOD_KEY + GOOD_KEY + GOOD_KEY + GOOD_KEY, "far longer"),
        ("sk-ant-api03", "too short"),
    ],
)
def test_broken_keys_are_refused(key: str, problem: str) -> None:
    from verifypr.llm.keys import check_key

    result = check_key("anthropic", key)
    assert result.error is not None
    assert problem in result.error
    assert GOOD_KEY not in result.error


def test_every_kind_of_anthropic_key_is_accepted_and_others_get_a_warning() -> None:
    from verifypr.llm.keys import KeyCheck, check_key

    # Console keys come in several kinds, e.g. user-linked sk-ant-usr- keys.
    assert check_key("anthropic", GOOD_KEY) == KeyCheck()
    assert check_key("anthropic", "sk-ant-usr-" + "x" * 90) == KeyCheck()
    odd = check_key("anthropic", "sk-proj-" + "x" * 60)
    assert odd.error is None
    assert odd.warning is not None
    assert "start with sk-ant-" in odd.warning
    assert check_key("azure", "0123456789abcdef" * 2).warning is None


def test_key_set_refuses_a_mangled_paste_and_saves_nothing() -> None:
    from verifypr.llm.keys import resolve_key

    result = runner.invoke(app, ["key", "set"], input=GOOD_KEY + chr(0xA0) + GOOD_KEY + "\n")
    assert result.exit_code == 3
    assert "Nothing was saved." in result.output
    assert resolve_key("anthropic")[0] is None


def test_key_set_asks_before_saving_an_odd_looking_key() -> None:
    from verifypr.llm.keys import resolve_key

    odd = "sk-proj-" + "x" * 90
    declined = runner.invoke(app, ["key", "set"], input=odd + "\nn\n")
    assert declined.exit_code == 3
    assert resolve_key("anthropic")[0] is None
    accepted = runner.invoke(app, ["key", "set"], input=odd + "\ny\n")
    assert accepted.exit_code == 0
    assert resolve_key("anthropic")[0] == odd


def test_long_tokens_are_fine_for_other_compatible_servers() -> None:
    from verifypr.llm.keys import check_key

    assert check_key("openai_compatible", "eyJ" + "a" * 900).error is None
