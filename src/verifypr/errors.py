"""User-facing errors with a plain-language message and a suggested fix.

Public interface: ``VerifyPRError`` and its subclasses. The CLI prints ``message`` and
``hint`` and exits with code 3; it never shows a stack trace for these.
"""

from __future__ import annotations


class VerifyPRError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class NotAGitRepoError(VerifyPRError):
    pass


class NoBaseBranchError(VerifyPRError):
    pass


class GitError(VerifyPRError):
    pass


class ConfigError(VerifyPRError):
    pass
