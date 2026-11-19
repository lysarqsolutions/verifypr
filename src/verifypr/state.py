"""The tool's own state folder — outside every repository, never inside it.

Public interface: ``state_dir()``, ``repo_key(root)``, ``read_json(name)``,
``write_json(name, data)``.

Location: ``VERIFYPR_STATE_DIR`` if set; otherwise the OS user-data folder
(Windows ``%LOCALAPPDATA%\\verifypr``, macOS ``~/Library/Application Support/verifypr``,
Linux ``$XDG_STATE_HOME/verifypr`` or ``~/.local/state/verifypr``).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    override = os.environ.get("VERIFYPR_STATE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "verifypr"


def repo_key(root: Path) -> str:
    """A stable, non-reversible key for a project folder (no path stored in file names)."""
    return hashlib.sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest()[:16]


def read_json(name: str) -> dict[str, Any]:
    path = state_dir() / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(name: str, data: dict[str, Any]) -> None:
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.tmp"
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(folder / name)
