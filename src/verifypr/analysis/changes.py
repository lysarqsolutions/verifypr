"""The set of changes being checked, independent of where they came from.

Public interface: ``ChangeSet``. Detectors receive one of these. ``read_old``/``read_new``
return file bytes before/after the change (``None`` if the file doesn't exist there);
``list_files`` returns every file path in the project after the change. All read-only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from verifypr.models import FileChange, Hunk

Reader = Callable[[str], "bytes | None"]
Lister = Callable[[], "list[str]"]


def _no_reader(_path: str) -> bytes | None:
    return None


def _no_files() -> list[str]:
    return []


@dataclass(frozen=True)
class ChangeSet:
    files: tuple[FileChange, ...]
    hunks: tuple[Hunk, ...]
    base_label: str
    compared: str
    notes: tuple[str, ...] = ()
    read_old: Reader = field(default=_no_reader, repr=False)
    read_new: Reader = field(default=_no_reader, repr=False)
    list_files: Lister = field(default=_no_files, repr=False)

    def hunks_for(self, path: str) -> list[Hunk]:
        return [h for h in self.hunks if h.file_path == path]

    def file(self, path: str) -> FileChange | None:
        return next((f for f in self.files if f.path == path), None)

    @property
    def is_empty(self) -> bool:
        return not self.files
