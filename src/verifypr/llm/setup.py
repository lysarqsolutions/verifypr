"""Pick the AI provider, find its key, and decide whether code may be sent (consent).

Public interface: ``LLMSettings``, ``LLMChoice``, ``choose_llm(settings, overrides)``,
``SendSummary``, ``estimate_cost(model, input_tokens, output_tokens)``,
``stored_consent(...)``, ``store_consent(...)``.

Rules (CLAUDE.md §1.5.13): nothing is sent before consent. Interactive runs ask once per
project + provider + model and remember the answer in the state folder. Non-interactive
runs (CI) count an *explicitly configured* provider as consent and print one line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from verifypr.llm.anthropic_client import DEFAULT_ANTHROPIC_MODEL, AnthropicLLM
from verifypr.llm.base import LLMClient, LLMError, ProviderConfig
from verifypr.llm.keys import NO_KEY_PROVIDERS, resolve_key
from verifypr.llm.openai_compat import PROVIDER_DEFAULTS, OpenAICompatLLM
from verifypr.state import read_json, repo_key, write_json

PROVIDERS = ("anthropic", *PROVIDER_DEFAULTS)
CONSENT_FILE = "consent.json"
# $ per 1M tokens (input, output). Unknown models -> "depends on your provider".
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.0, 40.0),
}


class LLMSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str | None = Field(default=None, description="anthropic, openai, ollama, …")
    model: str | None = None
    base_url: str | None = None
    effort: str = "medium"
    max_chunk_tokens: int = Field(default=12_000, ge=1_000)
    max_total_tokens: int = Field(default=150_000, ge=1_000)


@dataclass(frozen=True)
class LLMChoice:
    client: LLMClient | None
    explicit: bool
    reason: str | None = None


def _setting(env: str, override: str | None, configured: str | None) -> str | None:
    return os.environ.get(env) or override or configured


def choose_llm(
    settings: LLMSettings, *, provider: str | None = None, model: str | None = None
) -> LLMChoice:
    """Build the client, or explain in plain words why AI checks can't run."""
    chosen = _setting("VERIFYPR_LLM_PROVIDER", provider, settings.provider)
    explicit = chosen is not None
    if chosen is None:
        key, _source = resolve_key("anthropic")
        if not key:
            return LLMChoice(
                None,
                False,
                "Smarter AI checks were skipped: no AI key found. Add one with "
                "`verifypr key set` (nothing is sent until you agree).",
            )
        chosen = "anthropic"
    if chosen not in PROVIDERS:
        return LLMChoice(None, explicit, f"Unknown AI provider `{chosen}`.")
    key, _source = resolve_key(chosen)
    if not key and chosen not in NO_KEY_PROVIDERS:
        return LLMChoice(
            None,
            explicit,
            f"Smarter AI checks were skipped: no key for `{chosen}`. Add one with "
            f"`verifypr key set {chosen}`.",
        )
    name = _setting("VERIFYPR_LLM_MODEL", model, settings.model)
    base = _setting("VERIFYPR_LLM_BASE_URL", None, settings.base_url)
    try:
        if chosen == "anthropic":
            cfg = ProviderConfig(
                "anthropic", name or DEFAULT_ANTHROPIC_MODEL, key, base, settings.effort
            )
            return LLMChoice(AnthropicLLM(cfg), explicit)
        cfg = ProviderConfig(chosen, name or "", key, base, settings.effort)
        return LLMChoice(OpenAICompatLLM(cfg), explicit)
    except LLMError as err:
        return LLMChoice(None, explicit, f"Smarter AI checks were skipped: {err.message}")


@dataclass(frozen=True)
class SendSummary:
    provider: str
    model: str
    files: int
    characters: int
    input_tokens: int
    output_tokens: int

    @property
    def cost(self) -> str:
        return estimate_cost(self.model, self.input_tokens, self.output_tokens)

    def describe(self) -> str:
        size = f"{self.characters / 1000:.0f} KB" if self.characters >= 1000 else "under 1 KB"
        return (
            f"{self.files} changed {'file' if self.files == 1 else 'files'} ({size}, secrets "
            f"already removed) would be sent to {self.provider} ({self.model}). "
            f"Estimated cost: {self.cost}."
        )


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> str:
    price = PRICES.get(model)
    if price is None:
        return "depends on your provider"
    dollars = input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]
    return "under $0.01" if dollars < 0.01 else f"about ${dollars:.2f}"


def _consent_key(root: Path, provider: str, model: str) -> str:
    return f"{repo_key(root)}|{provider}|{model}"


def stored_consent(root: Path, provider: str, model: str) -> bool | None:
    value = read_json(CONSENT_FILE).get(_consent_key(root, provider, model))
    return value if isinstance(value, bool) else None


def store_consent(root: Path, provider: str, model: str, allowed: bool) -> None:
    data = read_json(CONSENT_FILE)
    data[_consent_key(root, provider, model)] = allowed
    write_json(CONSENT_FILE, data)
