"""Provider-neutral LLM interface.

Public interface: ``LLMError``, ``Usage``, ``ProviderConfig``, ``LLMClient`` (protocol),
``ask_json(client, system=..., user=..., schema=..., model=...)``.

Every call asks for JSON matching a schema and validates it with Pydantic, retrying once
on invalid output. Failures raise ``LLMError`` with a plain-language message; callers turn
those into "Not sure — AI check failed for this part", never a crash.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

ErrorKind = Literal[
    "auth", "rate_limit", "timeout", "connection", "refused", "invalid_output", "config", "other"
]

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    effort: str = "medium"
    timeout_s: float = 120.0


class LLMClient(Protocol):
    provider: str
    model: str
    usage: Usage

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> str:
        """Return the model's raw JSON text for ``schema``. Raise ``LLMError`` on failure."""
        ...


_RETRY_NOTE = (
    "\n\nYour previous answer was not valid JSON for the required schema. "
    "Reply again with only JSON that matches the schema exactly."
)


def ask_json(
    client: LLMClient,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    model: type[T],
    max_tokens: int = 8000,
) -> T:
    """Ask for JSON and validate it; one retry on invalid output, then ``LLMError``."""
    prompt = user
    for attempt in range(2):
        text = client.complete_json(
            system=system, user=prompt, schema=schema, max_tokens=max_tokens
        )
        try:
            return model.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError, TypeError):
            if attempt == 0:
                prompt = user + _RETRY_NOTE
    raise LLMError("invalid_output", "The AI's answer couldn't be read, even after one retry.")
