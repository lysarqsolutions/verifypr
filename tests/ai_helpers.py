"""Scripted AI replies for intent tests: answer by file name, like a careful reviewer would."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from verifypr.llm.fake import FakeLLM

_CHANGE = re.compile(r'<untrusted_change id="(C\d+)" file="([^"]+)"')

Rule = tuple[str, str, str]  # (classification, theme, reason)


def classify_by_file(
    rules: dict[str, Rule], default: Rule | None = None
) -> Callable[[str, str], dict[str, Any]]:
    """Reply for a classify prompt: the first rule whose key is in the file path wins."""

    def reply(_system: str, user: str) -> dict[str, Any]:
        changes = []
        for short_id, path in _CHANGE.findall(user):
            rule = next((r for key, r in rules.items() if key in path), default)
            if rule is None:
                continue
            cls, theme, reason = rule
            changes.append(
                {
                    "id": short_id,
                    "classification": cls,
                    "reason": reason,
                    "theme": theme,
                    "supports": "",
                    "confidence": 90,
                }
            )
        return {"changes": changes}

    return reply


def intent_reply(goal: str, *themes: str) -> dict[str, Any]:
    return {"goal": goal, "themes": list(themes)}


def fake_ai(*replies: Any) -> FakeLLM:
    return FakeLLM(list(replies), provider="anthropic", model="claude-opus-5-5")
