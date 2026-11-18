"""Project configuration read from ``.verifypr.yml`` at the repo root (optional).

Public interface: ``AllowRule``, ``Config``, ``load_config(repo_root)``, ``DEFAULT_IGNORE_GLOBS``.
Reading config never writes anything.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from verifypr.intent.contract import Tolerances, _friendly_validation, read_yaml_mapping

CONFIG_FILENAME = ".verifypr.yml"

DEFAULT_IGNORE_GLOBS: tuple[str, ...] = (
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/poetry.lock",
    "**/Pipfile.lock",
    "**/uv.lock",
    "**/go.sum",
    "**/Cargo.lock",
    "**/packages.lock.json",
    "**/gradle.lockfile",
    "**/vendor/**",
    "**/node_modules/**",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.generated.*",
)
"""Files skipped from detailed (AI) analysis. Rule-based detectors still see them."""


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AllowRule(_M):
    """Suppress one kind of finding in matching paths. Suppressed findings are counted."""

    kind: str = Field(min_length=1, description="Finding category, e.g. 'formatting'.")
    paths: tuple[str, ...] = ("**",)
    reason: str | None = None


class Config(_M):
    base: str | None = Field(default=None, description="Branch to compare with.")
    ignore_globs: tuple[str, ...] = DEFAULT_IGNORE_GLOBS
    allow: tuple[AllowRule, ...] = ()
    disabled_detectors: tuple[str, ...] = ()
    tolerances: Tolerances = Tolerances()


def load_config(repo_root: Path) -> Config:
    path = repo_root / CONFIG_FILENAME
    if not path.is_file():
        return Config()
    data = read_yaml_mapping(path)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise _friendly_validation(path, exc) from exc
