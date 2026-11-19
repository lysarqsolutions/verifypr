"""Small helpers shared by detectors.

Public interface: ``is_test_file``, ``is_ci_file``, ``is_code_file``, ``skeleton``,
``changed_lines``, ``plural``, ``without_strings``, ``comment_part``, ``looks_like_code``.
"""

from __future__ import annotations

import re

from verifypr.analysis.globs import any_match
from verifypr.analysis.languages import language_for
from verifypr.models import Hunk

TEST_GLOBS = (
    "test_*.py",
    "*_test.py",
    "tests/**",
    "test/**",
    "**/tests/**",
    "**/test/**",
    "**/__tests__/**",
    "*.test.*",
    "*.spec.*",
    "*Test.java",
    "*Tests.java",
    "*Test.kt",
    "*Tests.cs",
    "*Test.cs",
    "*_test.go",
    "spec/**",
    "**/spec/**",
    "conftest.py",
)

CI_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    "azure-pipelines.yml",
    "azure-pipelines/**",
    "Jenkinsfile",
    ".circleci/config.yml",
    "bitbucket-pipelines.yml",
    ".travis.yml",
    "buildkite.yml",
    ".buildkite/**",
)

CODE_LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "java",
    "kotlin",
    "go",
    "csharp",
    "ruby",
    "php",
    "rust",
    "swift",
    "c",
    "cpp",
    "vue",
}

_STRING = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`[^`]*`")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
_CONSTANT = re.compile(r"\b(?:True|False|None|true|false|null|undefined|nil)\b")


_COMMENT_START = re.compile(r"#|//|/\*|<!--|^\s*\*|--\s")
_CODE_PUNCTUATION = re.compile(r"[(=\[{@]|->|=>|&&|\|\|")


_TRIPLE_QUOTE = re.compile(r'"""|\'\'\'')
_BEFORE_VALUE = re.compile(r"[=(\[{,:]\s*[rbuf]*$", re.I)


def without_strings(line: str) -> str:
    """The line with string literals emptied, so text *inside* strings never matches.

    A line touching a triple-quoted string (docstring) is prose: only code before an
    opening quote that starts a value (``x = \"\"\"...``) is kept.
    """
    triple = _TRIPLE_QUOTE.search(line)
    if triple:
        head = line[: triple.start()]
        line = head if _BEFORE_VALUE.search(head) else ""
    return _STRING.sub('""', line)


def comment_part(line: str) -> str | None:
    """The comment portion of a line (outside strings), or None if there is none."""
    code = without_strings(line)
    m = _COMMENT_START.search(code)
    return code[m.start() :] if m else None


def looks_like_code(line: str) -> bool:
    """Not a comment and has code punctuation; filters out prose in comments/docstrings."""
    code = without_strings(line).strip()
    if not code or comment_part(code) == code:
        return False
    return bool(_CODE_PUNCTUATION.search(code))


def is_test_file(path: str) -> bool:
    return any_match(TEST_GLOBS, path)


def is_ci_file(path: str) -> bool:
    return any_match(CI_GLOBS, path)


def is_code_file(path: str) -> bool:
    return language_for(path) in CODE_LANGUAGES


def skeleton(line: str) -> str:
    """A line with its literal values blanked out, to spot 'same check, different value'."""
    out = _STRING.sub("S", line.strip())
    out = _NUMBER.sub("N", out)
    out = _CONSTANT.sub("K", out)
    return "".join(out.split())


def changed_lines(hunk: Hunk) -> tuple[set[str], set[str]]:
    """Stripped removed/added lines that don't appear on the other side (real changes)."""
    removed = {r.strip() for r in hunk.removed if r.strip()}
    added = {a.strip() for a in hunk.added if a.strip()}
    return removed - added, added - removed


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {many or word + 's'}"
