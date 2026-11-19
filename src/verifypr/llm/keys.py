"""API keys: environment variable > OS keychain > this session only. Never plain files.

Public interface: ``ENV_VARS``, ``KeySource``, ``resolve_key(provider)``,
``save_key(provider, key)``, ``remove_key(provider)``, ``masked(key)``,
``remember_for_session(provider, key)``.

Keys are never logged, printed in full, written to config/state files, or accepted as
command-line arguments.
"""

from __future__ import annotations

import os
from typing import Literal

SERVICE = "verifypr"
ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai_compatible": "VERIFYPR_LLM_API_KEY",
}
NO_KEY_PROVIDERS = {"ollama"}
KeySource = Literal["environment", "keychain", "session", "none"]

_session: dict[str, str] = {}


class KeychainUnavailableError(Exception):
    pass


def masked(key: str) -> str:
    return "…" + key[-4:] if len(key) > 8 else "…"


def remember_for_session(provider: str, key: str) -> None:
    _session[provider] = key


def _keychain_get(provider: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE, provider)
    except Exception:  # no backend, locked keychain, etc. — treat as "not stored"
        return None


def resolve_key(provider: str) -> tuple[str | None, KeySource]:
    env = ENV_VARS.get(provider)
    if env and os.environ.get(env):
        return os.environ[env], "environment"
    stored = _keychain_get(provider)
    if stored:
        return stored, "keychain"
    if provider in _session:
        return _session[provider], "session"
    return None, "none"


def save_key(provider: str, key: str) -> None:
    """Store in the OS keychain. Raises ``KeychainUnavailableError`` instead of falling back
    to a file."""
    try:
        import keyring

        keyring.set_password(SERVICE, provider, key)
    except Exception as exc:
        raise KeychainUnavailableError(
            "No keychain is available on this computer, so the key can't be remembered. "
            f"Set the {ENV_VARS.get(provider, 'provider')} environment variable instead."
        ) from exc


def remove_key(provider: str) -> bool:
    _session.pop(provider, None)
    try:
        import keyring

        keyring.delete_password(SERVICE, provider)
        return True
    except Exception:
        return False
