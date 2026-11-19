"""A scripted LLM for tests (and offline demos). Never makes a network call.

Public interface: ``FakeLLM``. Give it a list of replies (strings, dicts, ``LLMError``s,
or a callable ``(system, user) -> str | dict``); each call consumes the next one. Every
prompt it receives is recorded in ``prompts``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from verifypr.llm.base import LLMError, Usage

Reply = str | dict[str, Any] | LLMError | Callable[[str, str], "str | dict[str, Any]"]


class FakeLLM:
    def __init__(
        self, replies: list[Reply] | None = None, *, provider: str = "fake", model: str = "fake-1"
    ) -> None:
        self.provider = provider
        self.model = model
        self.usage = Usage()
        self.replies: list[Reply] = list(replies or [])
        self.prompts: list[tuple[str, str]] = []
        self.default: Reply | None = None

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> str:
        self.prompts.append((system, user))
        reply = self.replies.pop(0) if self.replies else self.default
        if reply is None:
            raise LLMError("other", "FakeLLM has no reply scripted.")
        if isinstance(reply, LLMError):
            raise reply
        if callable(reply):
            reply = reply(system, user)
        self.usage.calls += 1
        self.usage.input_tokens += len(system + user) // 4
        text = reply if isinstance(reply, str) else json.dumps(reply)
        self.usage.output_tokens += len(text) // 4
        return text
