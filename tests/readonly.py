"""Read-only guarantee harness (CLAUDE.md §1.4.1, Phase 0).

Public interface:
- ``make_fixture_repo(root)``: build a small synthetic git repo with committed branch
  changes, an uncommitted edit and an untracked file (what an agent typically leaves).
- ``snapshot(*paths)``: SHA-256 of every file (including ``.git``) plus the directory set.
- ``assert_unchanged(before, after)``: fail with a readable list of what changed.

Note for later phases: some "read-only" git commands still write to ``.git`` (for
example ``git status`` may refresh the index). Run git with ``--no-optional-locks``
and avoid commands that update refs or the index; this harness will catch it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Snapshot:
    files: dict[str, str]
    dirs: frozenset[str]


def _git_env(root: Path) -> dict[str, str]:
    empty_config = root / ".gitconfig-empty"
    empty_config.touch()
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Fixture Author",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture Author",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        }
    )
    return env


def _git(repo: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def make_fixture_repo(root: Path) -> Path:
    """Create ``root/repo`` and return its path. All content is synthetic."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    env = _git_env(root)
    _git(repo, env, "init", "-q", "-b", "main")
    _git(repo, env, "config", "core.autocrlf", "false")
    (repo / "app.py").write_text("def total(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "README.md").write_text("# Acme demo\n", encoding="utf-8")
    _git(repo, env, "add", ".")
    _git(repo, env, "commit", "-q", "-m", "initial")
    _git(repo, env, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text(
        "def total(a, b):\n    return a + b\n\n\ndef avg(a, b):\n    return (a + b) / 2\n",
        encoding="utf-8",
    )
    _git(repo, env, "commit", "-q", "-am", "add avg")
    # What an agent often leaves behind: an uncommitted edit and a new untracked file.
    (repo / "README.md").write_text("# Acme demo\n\nNow with averages.\n", encoding="utf-8")
    (repo / "notes.txt").write_text("scratch\n", encoding="utf-8")
    return repo


def snapshot(*paths: Path) -> Snapshot:
    files: dict[str, str] = {}
    dirs: set[str] = set()
    for base in paths:
        for current, dirnames, filenames in os.walk(base):
            current_path = Path(current)
            for name in dirnames:
                dirs.add(str(current_path / name))
            for name in filenames:
                file_path = current_path / name
                files[str(file_path)] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return Snapshot(files=files, dirs=frozenset(dirs))


def assert_unchanged(before: Snapshot, after: Snapshot) -> None:
    added = sorted(set(after.files) - set(before.files))
    removed = sorted(set(before.files) - set(after.files))
    modified = sorted(
        p for p in set(before.files) & set(after.files) if before.files[p] != after.files[p]
    )
    new_dirs = sorted(after.dirs - before.dirs)
    gone_dirs = sorted(before.dirs - after.dirs)
    problems = {
        "added files": added,
        "removed files": removed,
        "modified files": modified,
        "added dirs": new_dirs,
        "removed dirs": gone_dirs,
    }
    report = {k: v for k, v in problems.items() if v}
    if report:
        lines = [f"{kind}: {', '.join(items)}" for kind, items in report.items()]
        raise AssertionError("Command changed the repository:\n" + "\n".join(lines))
