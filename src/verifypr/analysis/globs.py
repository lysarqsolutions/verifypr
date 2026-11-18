"""Gitignore-style glob matching that works the same on every OS and Python 3.10+.

Public interface: ``glob_match(pattern, path)`` and ``any_match(patterns, path)``.
``**`` matches any number of folders, ``*`` and ``?`` never cross ``/``. A pattern
without ``/`` matches the file name in any folder (like ``.gitignore``).
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
            else:
                body = pattern[i + 1 : end].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(pattern: str, path: str) -> bool:
    path = path.replace("\\", "/").lstrip("/")
    pattern = pattern.replace("\\", "/").lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    if "/" not in pattern:
        name = path.rsplit("/", 1)[-1]
        return bool(_compile(pattern).match(name))
    return bool(_compile(pattern).match(path))


def any_match(patterns: tuple[str, ...] | list[str], path: str) -> bool:
    return any(glob_match(p, path) for p in patterns)
