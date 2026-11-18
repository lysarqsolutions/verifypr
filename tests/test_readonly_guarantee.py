"""Every default command must leave the working tree and .git byte-identical.

Add each new default command to DEFAULT_COMMANDS as it is built.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.readonly import assert_unchanged, make_fixture_repo, snapshot
from verifypr.cli import app

DEFAULT_COMMANDS: list[list[str]] = [
    [],
    ["--version"],
    ["--help"],
]


@pytest.mark.parametrize("args", DEFAULT_COMMANDS, ids=lambda a: " ".join(a) or "<no args>")
def test_default_command_is_read_only(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_fixture_repo(tmp_path)
    monkeypatch.chdir(repo)
    before = snapshot(repo)

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert_unchanged(before, snapshot(repo))


def test_harness_detects_a_modified_file(tmp_path: Path) -> None:
    repo = make_fixture_repo(tmp_path)
    before = snapshot(repo)
    (repo / "app.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="modified files"):
        assert_unchanged(before, snapshot(repo))


def test_harness_detects_new_files_and_git_writes(tmp_path: Path) -> None:
    repo = make_fixture_repo(tmp_path)
    before = snapshot(repo)
    (repo / ".git" / "verifypr-was-here").write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="added files"):
        assert_unchanged(before, snapshot(repo))


def test_fixture_repo_has_agent_style_leftovers(tmp_path: Path) -> None:
    repo = make_fixture_repo(tmp_path)
    assert (repo / "notes.txt").exists()
    assert "averages" in (repo / "README.md").read_text(encoding="utf-8")
