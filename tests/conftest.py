from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip tests marked ``live`` unless VERIFYPR_LIVE_TESTS=1 (CI never sets it for forks)."""
    if os.environ.get("VERIFYPR_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live test: set VERIFYPR_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
