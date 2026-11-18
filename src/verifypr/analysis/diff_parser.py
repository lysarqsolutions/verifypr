"""Parse ``git diff`` unified output into ``FileChange`` + ``Hunk`` models.

Public interface: ``ParsedFile`` and ``parse_diff(text) -> list[ParsedFile]``.
Pure: no git calls, no I/O. Lines are split on ``\\n`` only, so a trailing ``\\r``
(CRLF) is preserved and line-ending changes stay visible.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass, field

from verifypr.analysis.languages import language_for
from verifypr.models import ChangeKind, FileChange, Hunk

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_LFS_HEADER = "version https://git-lfs.github.com/spec/v1"
_OCTAL_RE = re.compile(r"\\([0-7]{3})")
_SIMPLE_ESCAPES = {"t": "\t", "n": "\n", '"': '"', "\\": "\\", "a": "\a", "b": "\b"}


@dataclass(frozen=True)
class ParsedFile:
    change: FileChange
    hunks: tuple[Hunk, ...]


def unquote_git_path(raw: str) -> str:
    """Undo git's C-style quoting (``"a/sp\\303\\251cial"``)."""
    if not (len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            octal = _OCTAL_RE.match(body, i)
            if octal:
                out.append(int(octal.group(1), 8))
                i += 4
                continue
            out.extend(_SIMPLE_ESCAPES.get(body[i + 1], body[i + 1]).encode("utf-8"))
            i += 2
            continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_prefix(path: str) -> str | None:
    path = unquote_git_path(path.strip())
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _header_paths(rest: str) -> tuple[str | None, str | None]:
    """Paths from ``diff --git a/X b/Y``; used only when ---/+++ lines are absent."""
    if rest.startswith('"'):
        end = rest.find('" ', 1)
        if end != -1:
            return _strip_prefix(rest[: end + 1]), _strip_prefix(rest[end + 2 :])
    candidates = [m.start() for m in re.finditer(r" b/", rest)]
    for idx in candidates:
        a, b = rest[:idx], rest[idx + 1 :]
        if _strip_prefix(a) == _strip_prefix(b):
            return _strip_prefix(a), _strip_prefix(b)
    if candidates:
        idx = candidates[0]
        return _strip_prefix(rest[:idx]), _strip_prefix(rest[idx + 1 :])
    return None, None


@dataclass
class _Builder:
    old_path: str | None = None
    new_path: str | None = None
    header_old: str | None = None
    header_new: str | None = None
    kind: ChangeKind | None = None
    old_mode: str | None = None
    new_mode: str | None = None
    binary: bool = False
    submodule: bool = False
    renamed: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    seen_ids: dict[str, int] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or self.header_new or self.header_old or "unknown"

    def hunk_id(self, removed: list[str], added: list[str]) -> str:
        digest = hashlib.sha1(
            "\0".join([self.path, "\n".join(removed), "\n".join(added)]).encode(
                "utf-8", errors="surrogatepass"
            ),
            usedforsecurity=False,
        ).hexdigest()[:12]
        base = f"{self.path}@{digest}"
        count = self.seen_ids.get(base, 0)
        self.seen_ids[base] = count + 1
        return base if count == 0 else f"{base}-{count}"

    def build(self) -> ParsedFile:
        old = self.old_path if self.old_path is not None else self.header_old
        new = self.new_path if self.new_path is not None else self.header_new
        kind = self.kind
        if self.submodule:
            kind = ChangeKind.SUBMODULE
        elif kind is None:
            if self.renamed and old and new and old != new:
                same_dir = posixpath.dirname(old) == posixpath.dirname(new)
                kind = ChangeKind.RENAME if same_dir else ChangeKind.MOVE
            elif self.binary:
                kind = ChangeKind.BINARY
            elif self.old_mode and self.new_mode and not self.hunks:
                kind = ChangeKind.MODE_CHANGE
            else:
                kind = ChangeKind.MODIFY
        path = (new if kind is not ChangeKind.DELETE else old) or self.path
        added_lines = sum(len(h.added) for h in self.hunks)
        removed_lines = sum(len(h.removed) for h in self.hunks)
        first_added = next((h.added[0] for h in self.hunks if h.added), "")
        change = FileChange(
            path=path,
            old_path=old if old != path else None,
            change_kind=kind,
            language=language_for(path),
            old_mode=self.old_mode,
            new_mode=self.new_mode,
            binary=self.binary,
            lfs_pointer=first_added.rstrip("\r") == _LFS_HEADER,
            added_lines=added_lines,
            removed_lines=removed_lines,
        )
        hunks = tuple(
            h.model_copy(update={"file_path": path, "change_kind": kind}) for h in self.hunks
        )
        return ParsedFile(change=change, hunks=hunks)


def _parse_hunk(lines: list[str], i: int, header: re.Match[str], b: _Builder) -> int:
    old_start, new_start = int(header.group(1)), int(header.group(3))
    old_count = int(header.group(2)) if header.group(2) is not None else 1
    new_count = int(header.group(4)) if header.group(4) is not None else 1
    old_left, new_left = old_count, new_count
    old_no, new_no = old_start, new_start
    added: list[str] = []
    removed: list[str] = []
    added_at: list[int] = []
    removed_at: list[int] = []
    while i < len(lines) and (old_left > 0 or new_left > 0):
        line = lines[i]
        tag, body = line[:1], line[1:]
        if tag == "\\":
            i += 1
            continue
        if tag == "+":
            added.append(body)
            added_at.append(new_no)
            new_no += 1
            new_left -= 1
        elif tag == "-":
            removed.append(body)
            removed_at.append(old_no)
            old_no += 1
            old_left -= 1
        elif tag == " " or line == "":
            old_no += 1
            new_no += 1
            old_left -= 1
            new_left -= 1
        else:
            break
        i += 1
    while i < len(lines) and lines[i].startswith("\\"):
        i += 1
    if any(body.startswith("Subproject commit ") for body in added + removed):
        b.submodule = True
    b.hunks.append(
        Hunk(
            id=b.hunk_id(removed, added),
            file_path=b.path,
            old_path=b.old_path,
            change_kind=ChangeKind.MODIFY,
            old_start=old_start,
            old_lines=old_count,
            new_start=new_start,
            new_lines=new_count,
            language=language_for(b.path),
            added=tuple(added),
            removed=tuple(removed),
            added_at=tuple(added_at),
            removed_at=tuple(removed_at),
        )
    )
    return i


def _apply_header(line: str, b: _Builder) -> None:
    if line.startswith("new file mode "):
        b.kind, b.new_mode = ChangeKind.ADD, line.split()[-1]
    elif line.startswith("deleted file mode "):
        b.kind, b.old_mode = ChangeKind.DELETE, line.split()[-1]
    elif line.startswith("old mode "):
        b.old_mode = line.split()[-1]
    elif line.startswith("new mode "):
        b.new_mode = line.split()[-1]
    elif line.startswith(("rename from ", "copy from ")):
        b.renamed = line.startswith("rename")
        b.old_path = unquote_git_path(line.split(" ", 2)[2])
    elif line.startswith(("rename to ", "copy to ")):
        b.new_path = unquote_git_path(line.split(" ", 2)[2])
        if line.startswith("copy"):
            b.kind = ChangeKind.ADD
    elif line.startswith("index "):
        if line.split()[-1] == "160000":
            b.submodule = True
    elif line.startswith("Binary files ") or line == "GIT binary patch":
        b.binary = True
    elif line.startswith("--- "):
        b.old_path = _strip_prefix(line[4:])
    elif line.startswith("+++ "):
        b.new_path = _strip_prefix(line[4:])


def parse_diff(text: str) -> list[ParsedFile]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files: list[ParsedFile] = []
    current: _Builder | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current.build())
            current = _Builder()
            current.header_old, current.header_new = _header_paths(line[len("diff --git ") :])
            i += 1
            continue
        if current is None:
            i += 1
            continue
        header = _HUNK_RE.match(line)
        if header:
            i = _parse_hunk(lines, i + 1, header, current)
            continue
        _apply_header(line, current)
        i += 1
    if current is not None:
        files.append(current.build())
    return files
