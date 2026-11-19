"""AI layer: adapters (no network), JSON retry, keys, provider choice, consent, cost."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import keyring
import pytest
from pydantic import BaseModel

from verifypr.llm.anthropic_client import FALLBACK_BETA, AnthropicLLM
from verifypr.llm.base import LLMError, ProviderConfig, ask_json
from verifypr.llm.fake import FakeLLM
from verifypr.llm.keys import (
    KeychainUnavailableError,
    masked,
    remember_for_session,
    remove_key,
    resolve_key,
    save_key,
)
from verifypr.llm.openai_compat import OpenAICompatLLM
from verifypr.llm.setup import (
    LLMSettings,
    SendSummary,
    choose_llm,
    estimate_cost,
    store_consent,
    stored_consent,
)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
FAKE_KEY = "sk-ant-" + "test" * 8


class Ok(BaseModel):
    ok: bool


# ---- ask_json -------------------------------------------------------------------------
def test_ask_json_retries_once_on_invalid_output() -> None:
    llm = FakeLLM(["not json", {"ok": True}])
    assert ask_json(llm, system="s", user="u", schema=SCHEMA, model=Ok).ok
    assert "previous answer was not valid JSON" in llm.prompts[1][1]


def test_ask_json_gives_up_after_one_retry() -> None:
    llm = FakeLLM(["{", {"wrong": 1}])
    with pytest.raises(LLMError) as info:
        ask_json(llm, system="s", user="u", schema=SCHEMA, model=Ok)
    assert info.value.kind == "invalid_output"


# ---- Anthropic adapter (fake SDK object, no network) ------------------------------------
class _FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response, self.error = response, error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _sdk(response: Any = None, error: Exception | None = None) -> Any:
    messages = _FakeMessages(response, error)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def _response(text: str = '{"ok": true}', stop: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


def test_anthropic_adapter_sends_schema_effort_and_fallback() -> None:
    sdk, messages = _sdk(_response())
    llm = AnthropicLLM(ProviderConfig("anthropic", "claude-opus-5-5", "k"), sdk=sdk)
    assert llm.complete_json(system="s", user="u", schema=SCHEMA, max_tokens=500) == '{"ok": true}'
    call = messages.calls[0]
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert call["output_config"]["effort"] == "medium"
    assert call["betas"] == [FALLBACK_BETA]
    assert call["fallbacks"] == "default"
    assert "thinking" not in call
    assert llm.usage.total == 120


def test_anthropic_adapter_no_fallback_for_models_without_it() -> None:
    sdk, messages = _sdk(_response())
    AnthropicLLM(ProviderConfig("anthropic", "claude-haiku-5-5", "k"), sdk=sdk).complete_json(
        system="s", user="u", schema=SCHEMA, max_tokens=500
    )
    assert messages.calls[0]["betas"] is anthropic.omit
    assert messages.calls[0]["fallbacks"] is anthropic.omit


@pytest.mark.parametrize(
    ("stop", "kind"), [("refusal", "refused"), ("max_tokens", "invalid_output")]
)
def test_anthropic_adapter_checks_stop_reason(stop: str, kind: str) -> None:
    sdk, _ = _sdk(_response(stop=stop))
    llm = AnthropicLLM(ProviderConfig("anthropic", "claude-opus-5-5", "k"), sdk=sdk)
    with pytest.raises(LLMError) as info:
        llm.complete_json(system="s", user="u", schema=SCHEMA, max_tokens=500)
    assert info.value.kind == kind


def _status_error(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (_status_error(anthropic.AuthenticationError, 401), "auth"),
        (_status_error(anthropic.RateLimitError, 429), "rate_limit"),
        (_status_error(anthropic.InternalServerError, 500), "other"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")), "connection"),
    ],
)
def test_anthropic_adapter_maps_errors(error: Exception, kind: str) -> None:
    sdk, _ = _sdk(error=error)
    llm = AnthropicLLM(ProviderConfig("anthropic", "claude-opus-5-5", "k"), sdk=sdk)
    with pytest.raises(LLMError) as info:
        llm.complete_json(system="s", user="u", schema=SCHEMA, max_tokens=500)
    assert info.value.kind == kind


# ---- OpenAI-compatible adapter (httpx mock transport) -----------------------------------
def _openai(handler: Any, provider: str = "openai", model: str = "some-model") -> OpenAICompatLLM:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatLLM(ProviderConfig(provider, model, "key-123"), http=http)


def test_openai_compat_success() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return httpx.Response(200, json=body)

    llm = _openai(handler)
    assert llm.complete_json(system="s", user="u", schema=SCHEMA, max_tokens=50) == '{"ok": true}'
    sent = json.loads(seen[0].content)
    assert seen[0].url == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer key-123"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert llm.usage.total == 15


@pytest.mark.parametrize(("status", "kind"), [(401, "auth"), (429, "rate_limit"), (500, "other")])
def test_openai_compat_errors(status: int, kind: str) -> None:
    llm = _openai(lambda r: httpx.Response(status, json={}))
    with pytest.raises(LLMError) as info:
        llm.complete_json(system="s", user="u", schema=SCHEMA, max_tokens=50)
    assert info.value.kind == kind


def test_openai_compat_timeout_and_cut_off() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMError, match="too long"):
        _openai(slow).complete_json(system="s", user="u", schema=SCHEMA, max_tokens=50)
    cut = {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}
    with pytest.raises(LLMError, match="cut off"):
        _openai(lambda r: httpx.Response(200, json=cut)).complete_json(
            system="s", user="u", schema=SCHEMA, max_tokens=50
        )


def test_openai_compat_needs_model_and_base_url() -> None:
    with pytest.raises(LLMError, match="model name"):
        OpenAICompatLLM(ProviderConfig("openai", "", "k"))
    with pytest.raises(LLMError, match="base URL"):
        OpenAICompatLLM(ProviderConfig("azure", "m", "k"))


# ---- keys -------------------------------------------------------------------------------
def test_key_precedence_env_then_keychain_then_session(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_key("anthropic") == (None, "none")
    remember_for_session("anthropic", "session-key-1234")
    assert resolve_key("anthropic") == ("session-key-1234", "session")
    save_key("anthropic", "keychain-key-5678")
    assert resolve_key("anthropic") == ("keychain-key-5678", "keychain")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-9999")
    assert resolve_key("anthropic") == ("env-key-9999", "environment")
    assert remove_key("anthropic")
    assert masked("abcdefghijkl") == "…ijkl"


def test_no_keychain_never_falls_back_to_a_file(tmp_path: Path) -> None:
    class Broken(keyring.backend.KeyringBackend):
        priority = 1

        def __init__(self) -> None:
            pass

        def get_password(self, service: str, username: str) -> str | None:
            raise keyring.errors.NoKeyringError("none")

        def set_password(self, service: str, username: str, password: str) -> None:
            raise keyring.errors.NoKeyringError("none")

        def delete_password(self, service: str, username: str) -> None:
            raise keyring.errors.NoKeyringError("none")

    keyring.set_keyring(Broken())
    with pytest.raises(KeychainUnavailableError, match="ANTHROPIC_API_KEY"):
        save_key("anthropic", "secret-value-1234")
    assert resolve_key("anthropic") == (None, "none")


# ---- choosing a provider ----------------------------------------------------------------
def test_choose_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    none = choose_llm(LLMSettings())
    assert none.client is None
    assert "no AI key found" in (none.reason or "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    implicit = choose_llm(LLMSettings())
    assert implicit.client is not None
    assert implicit.client.model == "claude-opus-5-5"
    assert not implicit.explicit
    assert choose_llm(LLMSettings(provider="anthropic")).explicit
    missing = choose_llm(LLMSettings(provider="openai"))
    assert missing.client is None
    assert "no key for `openai`" in (missing.reason or "")
    local = choose_llm(LLMSettings(provider="ollama"))
    assert local.client is None
    assert "model name" in (local.reason or "")
    assert choose_llm(LLMSettings(provider="ollama", model="llama3")).client is not None
    assert "Unknown AI provider" in (choose_llm(LLMSettings(provider="nope")).reason or "")


def test_consent_is_remembered_per_project_provider_and_model(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert stored_consent(root, "anthropic", "claude-opus-5-5") is None
    store_consent(root, "anthropic", "claude-opus-5-5", True)
    assert stored_consent(root, "anthropic", "claude-opus-5-5") is True
    assert stored_consent(root, "anthropic", "claude-sonnet-5-5") is None
    assert not list(root.iterdir())  # nothing is written into the project


def test_cost_estimate_and_summary() -> None:
    assert estimate_cost("claude-opus-5-5", 1_000_000, 0) == "about $4.00"
    assert estimate_cost("claude-opus-5-5", 100, 10) == "under $0.01"
    assert estimate_cost("my-local-model", 10, 10) == "depends on your provider"
    text = SendSummary("anthropic", "claude-opus-5-5", 3, 12_000, 3_000, 500).describe()
    assert "3 changed files (12 KB, secrets already removed)" in text
    assert "anthropic (claude-opus-5-5)" in text
