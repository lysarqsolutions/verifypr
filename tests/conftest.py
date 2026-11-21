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
    # Never use the developer's real AI keys, keychain, or VerifyPR state in tests.
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "VERIFYPR_LLM_API_KEY",
        "VERIFYPR_LLM_PROVIDER",
        "VERIFYPR_LLM_MODEL",
        "ANTHROPIC_PROFILE",
        "VERIFYPR_LLM_BASE_URL",
    ):
        os.environ.pop(var, None)
    os.environ["VERIFYPR_STATE_DIR"] = str(home / "state")
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")  # no real `ant auth login` profile
    import keyring

    from tests.memory_keyring import MemoryKeyring

    previous_keyring = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    from verifypr import state, userstate  # noqa: F401  (import before unfreezing)
    from verifypr.llm import keys

    state.unfreeze()
    keys._session.clear()
    try:
        yield
    finally:
        state.unfreeze()
        keys._session.clear()
        keyring.set_keyring(previous_keyring)
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """On GitHub Actions, turn each failing test into an annotation, so failures can be read
    without opening the job log (logs need a signed-in account; annotations don't)."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    path, line, _ = report.location
    text = str(report.longrepr).strip().splitlines()
    tail = " | ".join(text[-6:])[:900]
    tail = tail.replace("%", "%25").replace("\r", "").replace("\n", " ")
    print(f"\n::error file={path},line={(line or 0) + 1},title={report.nodeid}::{tail}")
