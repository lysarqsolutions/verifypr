"""Find and redact secrets. Used by the secret detector and before anything goes to an AI.

Public interface: ``SecretMatch``, ``find_secrets(text)``, ``redact(text)``.
Redacted output never contains the matched secret value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _Pattern:
    name: str
    label: str
    regex: re.Pattern[str]
    critical: bool


@dataclass(frozen=True)
class SecretMatch:
    name: str
    label: str
    start: int
    end: int
    critical: bool


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        "private_key",
        "private key",
        re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
        True,
    ),
    _Pattern(
        "aws_access_key", "AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), True
    ),
    _Pattern(
        "aws_secret_key",
        "AWS secret key",
        re.compile(
            r"(?i)aws_?secret_?access_?key\s*[:=]\s*['\"]?(?P<secret>[A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"
        ),
        True,
    ),
    _Pattern(
        "github_token",
        "GitHub token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),
        True,
    ),
    _Pattern("slack_token", "Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), True),
    _Pattern(
        "anthropic_key", "Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), True
    ),
    _Pattern(
        "openai_key", "OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"), True
    ),
    _Pattern(
        "stripe_key", "Stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}"), True
    ),
    _Pattern("google_api_key", "Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), True),
    _Pattern(
        "generic_secret",
        "password or secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|token|"
            r"passwd|password|client[_-]?secret)\b['\"]?\s*[:=]\s*['\"]?(?P<secret>[^\s'\"#,;]{8,})"
        ),
        False,
    ),
)

_PLACEHOLDER = re.compile(
    r"(?i)^(?:\$\{.*\}|\$[A-Z_]+|<.*>|\{\{.*\}\}|x{4,}|\*{4,}|changeme|change_me|"
    r"your[-_].*|example.*|placeholder.*|dummy.*|test.*|none|null|true|false|"
    r"os\.environ.*|process\.env.*|env\(.*)$"
)


def find_secrets(text: str) -> list[SecretMatch]:
    """Non-overlapping matches, earlier and more specific patterns first."""
    found: list[SecretMatch] = []
    taken: list[tuple[int, int]] = []
    for pattern in _PATTERNS:
        for m in pattern.regex.finditer(text):
            start, end = (
                (m.start("secret"), m.end("secret")) if "secret" in m.groupdict() else m.span()
            )
            value = text[start:end]
            if not pattern.critical and _PLACEHOLDER.match(value):
                continue
            if any(start < t_end and end > t_start for t_start, t_end in taken):
                continue
            taken.append((start, end))
            found.append(SecretMatch(pattern.name, pattern.label, start, end, pattern.critical))
    return sorted(found, key=lambda s: s.start)


def redact(text: str) -> str:
    out = text
    for match in sorted(find_secrets(text), key=lambda s: s.start, reverse=True):
        out = out[: match.start] + f"[REDACTED {match.label}]" + out[match.end :]
    return out
