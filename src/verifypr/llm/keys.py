"""API keys: environment variable > OS keychain > this session only. Never plain files.

Public interface: ``ENV_VARS``, ``KeySource``, ``resolve_key(provider)``,
``save_key(provider, key)``, ``remove_key(provider)``, ``masked(key)``,
``remember_for_session(provider, key)``.

Keys are never logged, printed in full, written to config/state files, or accepted as
command-line arguments.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
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


def anthropic_login() -> str | None:
    """Anthropic credentials the official SDK finds by itself (no key needed here):
    an ``ANTHROPIC_AUTH_TOKEN``, an ``ANTHROPIC_PROFILE``, or a profile saved by
    ``ant auth login``. Returns a plain description, or None."""
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "the ANTHROPIC_AUTH_TOKEN environment variable"
    if os.environ.get("ANTHROPIC_PROFILE"):
        return "the ANTHROPIC_PROFILE sign-in profile"
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    folder = Path(config_home) / "anthropic"
    if folder.is_dir() and any(folder.iterdir()):
        return "your `ant auth login` sign-in"
    return None


@dataclass(frozen=True)
class KeyCheck:
    """Result of ``check_key``. Messages never contain the key itself."""

    error: str | None = None  # don't save
    warning: str | None = None  # save only if the user still wants to


# Known key shapes. Only a warning on mismatch: providers add new formats over time.
_KEY_PREFIXES = {
    "anthropic": ("sk-ant-api", "Anthropic API keys start with sk-ant-api"),
    "openai": ("sk-", "OpenAI API keys start with sk-"),
    "openrouter": ("sk-or-", "OpenRouter keys start with sk-or-"),
}
MAX_KEY_LENGTH = 300


def check_key(provider: str, key: str) -> KeyCheck:
    """Catch keys that were mangled while pasting, or that aren't API keys at all."""
    if not key:
        return KeyCheck(error="No key was entered.")
    if any(not (33 <= ord(ch) <= 126) for ch in key):
        return KeyCheck(
            error="That key contains spaces, line breaks or other characters that aren't part "
            "of an API key. It may have been pasted twice or changed while pasting. Copy it "
            "again and paste it once."
        )
    if len(key) > MAX_KEY_LENGTH and provider != "openai_compatible":  # may use long tokens
        return KeyCheck(
            error=f"That key is {len(key)} characters long, which is far longer than an API "
            "key. It may have been pasted twice. Copy it again and paste it once."
        )
    if len(key) < 20:
        return KeyCheck(error="That key is too short to be an API key. Check it was copied fully.")
    known = _KEY_PREFIXES.get(provider)
    if known and not key.startswith(known[0]):
        hint = ""
        if provider == "anthropic" and key.startswith("sk-ant-"):
            hint = " This looks like a different kind of Anthropic token, not an API key."
        return KeyCheck(
            warning=f"That doesn't look like an API key for this provider: {known[1]}.{hint} "
            "Create one on the provider's API keys page."
        )
    return KeyCheck()


def save_key(provider: str, key: str) -> None:
    """Store in the OS keychain. Raises ``KeychainUnavailableError`` instead of falling back
    to a file. In View only mode nothing is saved (use ``remember_for_session``)."""
    from verifypr.state import is_frozen

    if is_frozen():
        raise KeychainUnavailableError(
            "View only is on — nothing can be changed or saved. The key is kept for this "
            "session only."
        )
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
