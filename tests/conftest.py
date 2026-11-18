from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked ``live`` unless VERIFYPR_LIVE_TESTS=1 (CI never sets it for forks)."""
    if os.environ.get("VERIFYPR_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test: set VERIFYPR_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Make every git call (ours and VerifyPR's) ignore the developer's own git config,
    e.g. Windows ``core.autocrlf=true``, so tests behave the same on every machine."""
    home = tmp_path_factory.mktemp("githome")
    empty = home / ".gitconfig"
    empty.write_text(
        '[protocol "file"]\n\tallow = always\n[init]\n\tdefaultBranch = main\n',
        encoding="utf-8",
    )
    saved = dict(os.environ)
    os.environ.update(
        {
            "GIT_CONFIG_GLOBAL": str(empty),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Fixture Author",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture Author",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        }
    )
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        os.environ.pop(var, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path
