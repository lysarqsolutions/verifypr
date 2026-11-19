"""OpenAI-compatible adapter (OpenAI, Azure OpenAI, OpenRouter, Ollama, vLLM, others).

Public interface: ``OpenAICompatLLM``, ``PROVIDER_DEFAULTS``.

Uses the widely implemented ``POST {base_url}/chat/completions`` with a JSON-schema
``response_format``. A model name is required (VerifyPR doesn't guess one for you).
"""

from __future__ import annotations

from typing import Any

import httpx

from verifypr.llm.base import LLMError, ProviderConfig, Usage

PROVIDER_DEFAULTS: dict[str, str | None] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "azure": None,
    "openai_compatible": None,
}


class OpenAICompatLLM:
    def __init__(self, config: ProviderConfig, http: httpx.Client | None = None) -> None:
        base = config.base_url or PROVIDER_DEFAULTS.get(config.provider)
        if not base:
            raise LLMError("config", f"Set a base URL for the `{config.provider}` provider.")
        if not config.model:
            raise LLMError("config", f"Set a model name for the `{config.provider}` provider.")
        self.provider = config.provider
        self.model = config.model
        self.usage = Usage()
        self._url = base.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            if config.provider == "azure":
                headers["api-key"] = config.api_key
            else:
                headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = http or httpx.Client(timeout=config.timeout_s)
        self._headers = headers
        # OpenAI's own API (and Azure) want max_completion_tokens; most others max_tokens.
        self._token_param = (
            "max_completion_tokens" if config.provider in ("openai", "azure") else "max_tokens"
        )

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int,
        prefix: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            self._token_param: max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": (prefix or "") + user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            },
        }
        try:
            response = self._http.post(self._url, json=body, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise LLMError("timeout", "The AI provider took too long to answer.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("connection", "Couldn't reach the AI provider.") from exc
        if response.status_code in (401, 403):
            raise LLMError("auth", "That key was rejected — check it was copied fully.")
        if response.status_code == 404:
            raise LLMError("config", f"The model `{self.model}` or address wasn't found.")
        if response.status_code == 429:
            raise LLMError("rate_limit", "The AI provider is busy (rate limit).")
        if response.status_code >= 400:
            raise LLMError("other", f"The AI provider returned an error ({response.status_code}).")
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("invalid_output", "The AI provider's reply couldn't be read.") from exc
        usage = data.get("usage") or {}
        self.usage.calls += 1
        self.usage.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.usage.output_tokens += int(usage.get("completion_tokens", 0) or 0)
        if choice.get("finish_reason") == "length":
            raise LLMError("invalid_output", "The AI's answer was cut off.")
        return str(content)
