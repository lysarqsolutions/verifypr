"""Build a patch that undoes selected changes. VerifyPR never applies it itself.

Public interface: ``undo_patch(changes, hunk_ids)``, ``hunks_for_finding(changes, finding)``,
``undo_for_findings(changes, findings) -> UndoResult``, ``how_to(path)``.

The patch is the selected hunks exactly as git showed them, so the user can review it and
undo them with ``git apply -R`` (reverse-apply). Changes git can't express as text
(binary files, permission-only changes) are listed as comments instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from verifypr.analysis.changes import ChangeSet
from verifypr.models import Finding


def how_to(path: str | None) -> str:
    if path:
        return f'To undo these changes, review the patch, then run: git apply -R "{path}"'
    return (
        "To undo these changes yourself, save this patch (for example as verifypr-undo.patch) "
        "and run: git apply -R verifypr-undo.patch"
    )


@dataclass(frozen=True)
class UndoResult:
    patch: str
    by_hand: tuple[str, ...]  # files a text patch can't undo (binary, permission-only, ...)


def undo_for_findings(changes: ChangeSet, findings: Iterable[Finding]) -> UndoResult:
    findings = list(findings)
    ids: set[str] = set()
    for f in findings:
        ids |= hunks_for_finding(changes, f)
    patch = undo_patch(changes, ids)
    known = {c.path for c in changes.files}
    covered = {
        c.path
        for c in changes.files
        if c.patch_header and any(h.id in ids and h.raw for h in changes.hunks_for(c.path))
    }
    wanted = {e.file_path for f in findings for e in f.evidence} & known
    return UndoResult(patch, tuple(sorted(wanted - covered)))


def by_hand_message(paths: tuple[str, ...]) -> str:
    return "These can't be undone with a patch; undo them by hand: " + ", ".join(paths)


def undo_patch(changes: ChangeSet, hunk_ids: set[str]) -> str:
    out: list[str] = []
    skipped: list[str] = []
    for change in changes.files:
        selected = [h for h in changes.hunks_for(change.path) if h.id in hunk_ids and h.raw]
        if not selected:
            continue
        if not change.patch_header:
            skipped.append(change.path)
            continue
        out.extend(change.patch_header)
        for hunk in selected:
            out.extend(hunk.raw)
    if not out:
        return ""
    if skipped:
        out.append("")
        out.extend(f"# Not included (undo by hand): {path}" for path in skipped)
    return "\n".join(out) + "\n"


def hunks_for_finding(changes: ChangeSet, finding: Finding) -> set[str]:
    """The changes a finding points at: hunks in its files whose lines overlap its evidence
    (all of the file's hunks for file-level evidence)."""
    ids: set[str] = set()
    for ev in finding.evidence:
        for hunk in changes.hunks_for(ev.file_path):
            if ev.file_level:
                ids.add(hunk.id)
                continue
            lines = hunk.added_at or (max(hunk.new_start, 1),)
            if min(lines) <= ev.end_line and max(lines) >= ev.start_line:
                ids.add(hunk.id)
    return ids
