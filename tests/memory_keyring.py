"""An in-memory keychain so tests never touch the real OS keychain."""

from __future__ import annotations

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:  # KeyringBackend's own __init__ only reads env settings
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]
