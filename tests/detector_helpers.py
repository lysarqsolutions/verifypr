"""Build ChangeSets for detector unit tests from diff text and in-memory file versions."""

from __future__ import annotations

from verifypr.analysis.changes import ChangeSet
from verifypr.analysis.diff_parser import parse_diff
from verifypr.config import Config
from verifypr.detectors.base import DetectorContext
from verifypr.intent.contract import IntentContract
from verifypr.models import ChangeKind, FileChange, Hunk


def new_file_diff(path: str, text: str) -> str:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def modify_diff(path: str, old: str, new: str) -> str:
    o = old.split("\n")[:-1] if old.endswith("\n") else old.split("\n")
    n = new.split("\n")[:-1] if new.endswith("\n") else new.split("\n")
    body = "".join(f"-{line}\n" for line in o) + "".join(f"+{line}\n" for line in n)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(o)} +1,{len(n)} @@\n{body}"
    )


def changeset(
    diff: str = "",
    *,
    old: dict[str, str] | None = None,
    new: dict[str, str] | None = None,
    extra_files: list[FileChange] | None = None,
    extra_hunks: list[Hunk] | None = None,
) -> ChangeSet:
    parsed = parse_diff(diff)
    old = old or {}
    new = new or {}
    return ChangeSet(
        files=tuple(p.change for p in parsed) + tuple(extra_files or ()),
        hunks=tuple(h for p in parsed for h in p.hunks) + tuple(extra_hunks or ()),
        base_label="main",
        compared="Your branch (1 commit), compared with `main`",
        read_old=lambda p: old[p].encode() if p in old else None,
        read_new=lambda p: new[p].encode() if p in new else None,
    )


def ctx(
    changes: ChangeSet, contract: IntentContract | None = None, config: Config | None = None
) -> DetectorContext:
    return DetectorContext(changes=changes, config=config or Config(), contract=contract)


def untracked(path: str, *, binary: bool = False) -> FileChange:
    return FileChange(path=path, change_kind=ChangeKind.ADD, untracked=True, binary=binary)
