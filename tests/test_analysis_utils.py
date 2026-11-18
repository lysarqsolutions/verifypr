from __future__ import annotations

import pytest

from verifypr.analysis.chunker import chunk_hunks, estimate_tokens, split_for_analysis
from verifypr.analysis.globs import any_match, glob_match
from verifypr.analysis.redaction import find_secrets, redact
from verifypr.models import ChangeKind, Hunk

# Fake secrets are assembled at runtime so no secret-looking literal is committed.
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"
FAKE_GITHUB = "ghp_" + "Ab1" * 12
FAKE_ANTHROPIC = "sk-ant-" + "x9Y8" * 6


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("auth/**", "auth/session.py", True),
        ("auth/**", "src/auth/session.py", False),
        ("**/auth/**", "src/auth/session.py", True),
        ("*.lock", "deep/dir/yarn.lock", True),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("docs/", "docs/a/b.md", True),
        ("file?.txt", "file1.txt", True),
        ("[ab].txt", "a.txt", True),
        ("[!ab].txt", "a.txt", False),
        ("**/vendor/**", "vendor/x.js", True),
    ],
)
def test_glob_match(pattern: str, path: str, expected: bool) -> None:
    assert glob_match(pattern, path) is expected


def test_any_match_handles_backslashes() -> None:
    assert any_match(("src/**",), "src\\a\\b.py")


def _hunk(path: str, n: int) -> Hunk:
    return Hunk(
        id=f"{path}@{n}",
        file_path=path,
        change_kind=ChangeKind.MODIFY,
        old_start=1,
        old_lines=0,
        new_start=1,
        new_lines=n,
        added=tuple("x" * 40 for _ in range(n)),
    )


def test_split_for_analysis_skips_ignored() -> None:
    kept, skipped = split_for_analysis(
        [_hunk("src/a.py", 1), _hunk("package-lock.json", 1)], ("**/package-lock.json",)
    )
    assert [h.file_path for h in kept] == ["src/a.py"]
    assert skipped == ["package-lock.json"]


def test_chunking_respects_budget_and_marks_oversize() -> None:
    small = [_hunk(f"f{i}.py", 1) for i in range(5)]
    big = _hunk("big.py", 200)
    chunks = chunk_hunks([*small[:2], big, *small[2:]], max_tokens=30)
    assert any(c.oversize and c.hunks == (big,) for c in chunks)
    assert all(c.tokens <= 30 for c in chunks if not c.oversize)
    assert sum(len(c.hunks) for c in chunks) == 6
    with pytest.raises(ValueError, match="positive"):
        chunk_hunks(small, 0)
    assert estimate_tokens("abcd") == 2


@pytest.mark.parametrize(
    ("line", "name"),
    [
        (f"key = '{FAKE_AWS}'", "aws_access_key"),
        (f"GITHUB_TOKEN={FAKE_GITHUB}", "github_token"),
        (f"ANTHROPIC_API_KEY={FAKE_ANTHROPIC}", "anthropic_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key"),
        ("password = 'hunter2hunter2'", "generic_secret"),
    ],
)
def test_find_secrets(line: str, name: str) -> None:
    assert name in [m.name for m in find_secrets(line)]


@pytest.mark.parametrize(
    "line",
    [
        "password = os.environ['DB_PASSWORD']",
        "api_key: ${API_KEY}",
        "token = '<your-token-here>'",
        "secret = 'changeme'",
        "def password_strength(value):",
    ],
)
def test_placeholders_are_not_secrets(line: str) -> None:
    assert find_secrets(line) == []


def test_redact_removes_values() -> None:
    text = f"aws={FAKE_AWS} gh={FAKE_GITHUB} password='hunter2hunter2'"
    out = redact(text)
    assert FAKE_AWS not in out
    assert FAKE_GITHUB not in out
    assert "hunter2hunter2" not in out
    assert "[REDACTED AWS access key]" in out
