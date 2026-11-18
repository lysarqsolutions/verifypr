from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.gitrepo import Repo
from tests.readonly import assert_unchanged, snapshot
from verifypr.cli import app

FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
runner = CliRunner()

# Internal names that must never reach user-facing text/Markdown output (CLAUDE.md §1.5).
BANNED = re.compile(
    r"\bhunks?\b|\bcontract\b|\bunintended\b|blast radius|behavioral delta|\bseverity\b|"
    r"\bconfidence\b|please verify|\bU\d+\b",
    re.IGNORECASE,
)


def _checkpoint_repo(path: Path) -> Repo:
    """Phase 1 checkpoint: a real change + CRLF flip + lockfile bump + committed .env key."""
    repo = Repo(path)
    repo.write("src/app.py", "def total(a, b):\n    return a + b\n")
    repo.write("src/util.py", "def one():\n    return 1\n")
    repo.write("package.json", json.dumps({"dependencies": {"left-pad": "1.3.0"}}) + "\n")
    repo.write("package-lock.json", '{"lockfileVersion": 3, "x": 1}\n')
    repo.commit("initial")
    repo.branch("feature")
    repo.write(
        "src/app.py",
        "def total(a, b):\n    return a + b\n\n\ndef avg(a, b):\n    return (a + b) / 2\n",
    )
    repo.write("src/util.py", "def one():\r\n    return 1\r\n")
    repo.write("package-lock.json", '{"lockfileVersion": 3, "x": 2}\n')
    repo.write(".env", f"DEBUG=1\nAWS_ACCESS_KEY_ID={FAKE_AWS}\n")
    repo.commit("agent work")
    return repo


def test_checkpoint_scenario(repo_dir: Path) -> None:
    _checkpoint_repo(repo_dir)
    before = snapshot(repo_dir)
    result = runner.invoke(app, ["--repo", str(repo_dir), "--verbose"])
    assert_unchanged(before, snapshot(repo_dir))
    out = result.output
    assert result.exit_code == 2, out
    assert out.startswith("✖ Don't merge yet — 1 serious issue")
    assert "Your branch (1 commit), compared with `main`" in out
    assert "An AWS access key was added in .env — Important · Sure" in out
    assert "Line endings changed in 1 file" in out
    assert "Lock file changed without a dependency change: package-lock.json" in out
    assert "An environment settings file was added: .env" in out
    assert "Please check before approving" in out
    assert FAKE_AWS not in out
    assert not BANNED.search(out), BANNED.search(out)


def test_json_output_has_evidence(repo_dir: Path) -> None:
    _checkpoint_repo(repo_dir)
    result = runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "json"])
    data = json.loads(result.output)
    assert data["verdict"] == "fail"
    assert data["schema_version"] == "1"
    by_problem = {f["problem_id"] for f in data["findings"]}
    assert {"U3", "U4", "U6"} <= by_problem
    for finding in data["findings"]:
        assert finding["evidence"], finding
        assert 0 <= finding["confidence"] <= 100
    assert FAKE_AWS not in result.output


def test_markdown_output(repo_dir: Path) -> None:
    _checkpoint_repo(repo_dir)
    result = runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "markdown"])
    out = result.output
    assert out.startswith("## ⛔ Don't merge yet")
    assert "### ✅ Please check before approving" in out
    assert "<details><summary>See details</summary>" in out
    assert not BANNED.search(out)


def test_top_three_by_default_and_more_hint(repo_dir: Path) -> None:
    _checkpoint_repo(repo_dir)
    out = runner.invoke(app, ["--repo", str(repo_dir)]).output
    assert "Top issues" in out
    assert "  4. " not in out
    assert "run `verifypr --verbose` to see everything" in out


def test_clean_change_is_honest(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.branch("feature")
    repo.write("a.py", "x = 2\n")
    result = runner.invoke(app, ["--repo", str(repo_dir)])
    assert result.exit_code == 0
    assert result.output.startswith("✔ No problems found by basic checks")
    assert "Looks good" not in result.output


def test_no_changes_state(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.py", "x = 1\n")
    repo.commit()
    result = runner.invoke(app, ["--repo", str(repo_dir)])
    assert result.exit_code == 0
    assert "No changes found compared with `main`" in result.output
    assert "verifypr --base <branch>" in result.output


def test_errors_are_friendly_with_exit_3(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--repo", str(tmp_path)])
    assert result.exit_code == 3
    assert "This folder isn't a git project." in result.output
    assert "Traceback" not in result.output


def test_staged_conflicts_with_head(repo_dir: Path) -> None:
    result = runner.invoke(app, ["check", "--repo", str(repo_dir), "--staged", "--head", "x"])
    assert result.exit_code == 3


def test_allow_rules_from_config(repo_dir: Path) -> None:
    repo = _checkpoint_repo(repo_dir)
    repo.git("checkout", "-q", "main")
    repo.write(".verifypr.yml", "allow:\n  - kind: formatting\n    paths: ['src/**']\n")
    repo.commit("config")
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "main", "-m", "merge")
    out = runner.invoke(app, ["--repo", str(repo_dir), "--verbose"]).output
    assert "Line endings changed" not in out
    assert "1 finding was hidden by your allow rules." in out


def test_review_contract_forbidden_area(repo_dir: Path, tmp_path: Path) -> None:
    _checkpoint_repo(repo_dir)
    contract = tmp_path / "contract.yml"
    contract.write_text("forbidden:\n  paths: ['src/util.py']\n", encoding="utf-8")
    out = runner.invoke(
        app, ["check", "--repo", str(repo_dir), "--review-contract", str(contract), "--verbose"]
    ).output
    assert "Changed something that shouldn't change: src/util.py" in out
    assert "2 serious issues" in out


def test_diff_command(repo_dir: Path) -> None:
    _checkpoint_repo(repo_dir)
    result = runner.invoke(app, ["diff", "--repo", str(repo_dir)])
    assert result.exit_code == 0
    assert "4 files changed" in result.output
    data = json.loads(runner.invoke(app, ["diff", "--repo", str(repo_dir), "--json"]).output)
    assert {f["path"] for f in data["files"]} == {
        "src/app.py",
        "src/util.py",
        "package-lock.json",
        ".env",
    }


@pytest.mark.parametrize("args", [["--version"], ["--help"], ["check", "--help"]])
def test_help_and_version(args: list[str]) -> None:
    assert runner.invoke(app, args).exit_code == 0
