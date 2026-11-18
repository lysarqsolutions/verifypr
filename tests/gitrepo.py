"""Tiny helper for building synthetic git repos in tests. All content is made up."""

from __future__ import annotations

import subprocess
from pathlib import Path


class Repo:
    def __init__(self, path: Path, *, init: bool = True, branch: str = "main") -> None:
        self.path = path
        if init:
            path.mkdir(parents=True, exist_ok=True)
            self.git("init", "-q", "-b", branch)
            self.git("config", "core.autocrlf", "false")

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=self.path, capture_output=True, check=True)
        return proc.stdout.decode("utf-8", errors="replace").strip()

    def write(self, rel: str, content: str | bytes) -> Path:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_bytes(content.encode("utf-8"))
        else:
            target.write_bytes(content)
        return target

    def commit(self, message: str = "change", *paths: str) -> str:
        self.git("add", *(paths or ("-A",)))
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def branch(self, name: str) -> None:
        self.git("checkout", "-q", "-b", name)
