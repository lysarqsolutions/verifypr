"""Anthropic adapter (default provider) using the official ``anthropic`` SDK.

Public interface: ``AnthropicLLM``, ``DEFAULT_ANTHROPIC_MODEL``.

- Structured output via ``output_config.format`` (JSON schema); effort set explicitly.
- Thinking is left to the model's default (adaptive).
- Server-side refusal fallbacks are enabled for models that support them.
- ``stop_reason`` is checked before reading content (refusal / truncated output).
"""

from __future__ import annotations

from typing import Any

import anthropic

from verifypr.llm.base import LLMError, ProviderConfig, Usage

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_SERVER_FALLBACK = {
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, config: ProviderConfig, sdk: anthropic.Anthropic | None = None) -> None:
        self.model = config.model
        self.effort = config.effort
        self.usage = Usage()
        self._sdk = sdk or anthropic.Anthropic(
            api_key=config.api_key, base_url=config.base_url, timeout=config.timeout_s
        )

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int
    ) -> str:
        use_fallback = self.model in MODELS_WITH_SERVER_FALLBACK
        output_config: Any = {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        try:
            response = self._sdk.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                betas=[FALLBACK_BETA] if use_fallback else anthropic.omit,
                fallbacks="default" if use_fallback else anthropic.omit,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("auth", "That key was rejected — check it was copied fully.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("auth", "This key isn't allowed to use that model.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("config", f"The model `{self.model}` wasn't found.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("rate_limit", "The AI provider is busy (rate limit).") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("timeout", "The AI provider took too long to answer.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("connection", "Couldn't reach the AI provider.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(
                "other", f"The AI provider returned an error ({exc.status_code})."
            ) from exc

        usage = getattr(response, "usage", None)
        self.usage.calls += 1
        self.usage.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.usage.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

        if response.stop_reason == "refusal":
            raise LLMError("refused", "The AI declined to check this part.")
        if response.stop_reason == "max_tokens":
            raise LLMError("invalid_output", "The AI's answer was cut off.")
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return str(getattr(block, "text", ""))
        raise LLMError("invalid_output", "The AI returned no answer.")
