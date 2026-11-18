"""Shared detector plumbing.

Public interface: ``DetectorContext``, ``Detector`` (callable type), ``hunk_evidence``,
``file_evidence``. A detector is a pure function ``(DetectorContext) -> list[Finding]``;
it must not write anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from verifypr.analysis.changes import ChangeSet
from verifypr.analysis.redaction import redact
from verifypr.config import Config
from verifypr.intent.contract import IntentContract
from verifypr.models import Evidence, Finding, Hunk


@dataclass(frozen=True)
class DetectorContext:
    changes: ChangeSet
    config: Config
    contract: IntentContract | None = None


Detector = Callable[[DetectorContext], list[Finding]]


def hunk_evidence(hunk: Hunk, line_indexes: list[int] | None = None) -> Evidence:
    """Evidence for added lines of a hunk (all, or the given indexes into ``hunk.added``)."""
    if hunk.added_at:
        idxs = line_indexes if line_indexes else list(range(len(hunk.added_at)))
        lines = [hunk.added_at[i] for i in idxs]
        snippet = "\n".join(redact(hunk.added[i]) for i in idxs[:3])
        return Evidence(
            file_path=hunk.file_path,
            start_line=min(lines),
            end_line=max(lines),
            snippet=snippet or None,
        )
    line = max(hunk.new_start, 1)
    removed = "\n".join(redact(r) for r in hunk.removed[:3])
    return Evidence(
        file_path=hunk.file_path, start_line=line, end_line=line, snippet=removed or None
    )


def file_evidence(path: str) -> Evidence:
    return Evidence(file_path=path, start_line=1, end_line=1)
