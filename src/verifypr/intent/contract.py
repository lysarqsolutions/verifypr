"""Review Contract: what a change is allowed to do (engineer-facing name).

Users see this only as "What this change should do". Internal model: ``IntentContract``
(alias ``ReviewContract``). Public interface: ``Tolerance``, ``Tolerances``, ``PathRules``,
``IntentContract``, ``load_review_contract(path)``. Loading never writes anything.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from verifypr.errors import ConfigError


class Tolerance(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PathRules(_M):
    paths: tuple[str, ...] = ()
    behaviors: tuple[str, ...] = ()


class Tolerances(_M):
    formatting_only_changes: Tolerance = Tolerance.WARN
    dependency_changes: Tolerance = Tolerance.WARN
    new_files_outside_allowed: Tolerance = Tolerance.WARN
    tests_required: bool = False


class IntentContract(_M):
    goal: str | None = None
    allowed: PathRules = PathRules()
    forbidden: PathRules = PathRules()
    assumptions: tuple[str, ...] = ()
    tolerances: Tolerances = Tolerances()


ReviewContract = IntentContract


def _friendly_validation(path: Path, err: ValidationError) -> ConfigError:
    first = err.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ())) or "(top level)"
    return ConfigError(
        f"The file {path.name} has a problem at '{where}': {first.get('msg', 'invalid value')}.",
        hint="Check the spelling of the setting and its value.",
    )


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Couldn't find {path}.", hint="Check the file path.") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{path.name} isn't valid YAML.", hint="Check indentation and quotes."
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} should contain settings (key: value), not a list or text.")
    return data


def load_review_contract(path: Path) -> IntentContract:
    data = read_yaml_mapping(path)
    try:
        return IntentContract.model_validate(data)
    except ValidationError as exc:
        raise _friendly_validation(path, exc) from exc
