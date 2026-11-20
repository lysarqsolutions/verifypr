"""Per-project choices kept in the tool's state folder (never in the repository).

Public interface: ``allow_rules``, ``add_allow_rule``, ``remove_allow_rule``,
``kept_findings``, ``keep_finding``, ``unkeep_finding``, ``last_result``, ``save_result``,
``progress``.

All writes go through ``verifypr.state`` and therefore stay in memory in View only mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from verifypr.config import AllowRule
from verifypr.models import Progress, Report
from verifypr.state import read_json, repo_key, write_json

ALLOW_FILE = "allow.json"
KEPT_FILE = "kept.json"
HISTORY_FILE = "history.json"


def _get(name: str, root: Path) -> Any:
    return read_json(name).get(repo_key(root))


def _put(name: str, root: Path, value: Any) -> None:
    data = read_json(name)
    data[repo_key(root)] = value
    write_json(name, data)


def allow_rules(root: Path) -> list[AllowRule]:
    rules: list[AllowRule] = []
    for raw in _get(ALLOW_FILE, root) or []:
        try:
            rules.append(AllowRule.model_validate(raw))
        except ValidationError:
            continue
    return rules


def add_allow_rule(root: Path, rule: AllowRule) -> None:
    rules = [r for r in allow_rules(root) if r != rule] + [rule]
    _put(ALLOW_FILE, root, [r.model_dump(mode="json") for r in rules])


def remove_allow_rule(root: Path, index: int) -> bool:
    rules = allow_rules(root)
    if not 0 <= index < len(rules):
        return False
    del rules[index]
    _put(ALLOW_FILE, root, [r.model_dump(mode="json") for r in rules])
    return True


def kept_titles(root: Path) -> dict[str, str]:
    raw = _get(KEPT_FILE, root) or {}
    if isinstance(raw, list):  # older format: ids only
        return {str(x): "" for x in raw}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def kept_findings(root: Path) -> set[str]:
    return set(kept_titles(root))


def keep_finding(root: Path, finding_id: str, title: str | None = None) -> None:
    titles = kept_titles(root)
    titles[finding_id] = title or ""
    _put(KEPT_FILE, root, titles)


def unkeep_finding(root: Path, finding_id: str) -> None:
    titles = kept_titles(root)
    titles.pop(finding_id, None)
    _put(KEPT_FILE, root, titles)


def last_result(root: Path) -> set[str] | None:
    value = _get(HISTORY_FILE, root)
    return {str(x) for x in value} if isinstance(value, list) else None


def save_result(root: Path, report: Report) -> None:
    if report.file_count:
        _put(HISTORY_FILE, root, sorted(f.id for f in report.findings))


def progress(
    previous: set[str] | None, report: Report, marked_fine: set[str] | None = None
) -> Progress | None:
    """Items marked "It's fine" since the last check are neither fixed nor open."""
    if previous is None:
        return None
    previous = previous - (marked_fine or set())
    if not previous:
        return None
    current = {f.id for f in report.findings}
    return Progress(
        fixed=len(previous - current),
        still_open=len(previous & current),
        new=len(current - previous),
        previous=len(previous),
    )
