"""U20 (basic): a changed file is used by several other areas of the project.

Public interface: ``detect(ctx)``, ``area_of(path)``. Approximate on purpose: it searches
import/require lines for the changed file's name; no whole-program analysis. The full,
registry-aware version arrives in Phase 6.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict

from verifypr.analysis.globs import any_match
from verifypr.detectors.base import DetectorContext, hunk_evidence
from verifypr.detectors.behavior.basic_watch import BASIC, UI_GLOBS
from verifypr.detectors.common import is_code_file, is_test_file
from verifypr.detectors.hygiene.formatting import HunkKind, classify_hunk
from verifypr.models import ChangeKind, Finding, Severity

MAX_FILES = 4000
MAX_BYTES = 256_000
MIN_OTHER_AREAS = 2
CONTAINERS = {
    "src",
    "apps",
    "app",
    "packages",
    "services",
    "modules",
    "libs",
    "lib",
    "projects",
    "portals",
    "web",
    "frontend",
    "backend",
}
_IMPORT_LINE = re.compile(
    r"^\s*(?:import\b|from\b|export\b.*\bfrom\b|.*\brequire\s*\(|#include\b|using\b)"
)


def area_of(path: str) -> str:
    parts = path.split("/")
    if len(parts) > 2 and parts[0].lower() in CONTAINERS:
        return parts[1]
    return parts[0] if len(parts) > 1 else "project root"


def _stem(path: str) -> str:
    name = posixpath.basename(path)
    stem = name.split(".", 1)[0]
    if stem.lower() in {"index", "__init__", "mod", "main"}:
        stem = posixpath.basename(posixpath.dirname(path)) or stem
    return stem


def _searchable(path: str) -> bool:
    return (is_code_file(path) or any_match(UI_GLOBS, path)) and not is_test_file(path)


def _import_lines(ctx: DetectorContext, skipped: list[str]) -> dict[str, list[str]]:
    files = [p for p in ctx.changes.list_files() if _searchable(p)]
    if len(files) > MAX_FILES:
        skipped.append(f"only the first {MAX_FILES} of {len(files)} files were searched")
        files = files[:MAX_FILES]
    index: dict[str, list[str]] = {}
    for path in files:
        data = ctx.changes.read_new(path)
        if data is None or len(data) > MAX_BYTES or b"\0" in data[:4096]:
            continue
        lines = [
            line
            for line in data.decode("utf-8", errors="replace").splitlines()
            if _IMPORT_LINE.match(line)
        ]
        if lines:
            index[path] = lines
    return index


def detect(ctx: DetectorContext) -> list[Finding]:
    candidates = []
    for change in ctx.changes.files:
        if change.change_kind not in (ChangeKind.MODIFY, ChangeKind.RENAME, ChangeKind.MOVE):
            continue
        if not _searchable(change.path):
            continue
        hunks = ctx.changes.hunks_for(change.path)
        if hunks and any(classify_hunk(h) is HunkKind.REAL for h in hunks):
            candidates.append((change.path, hunks))
    if not candidates:
        return []
    skipped: list[str] = []
    index = _import_lines(ctx, skipped)
    out: list[Finding] = []
    for path, hunks in candidates:
        stem = _stem(path)
        if len(stem) < 3:
            continue
        word = re.compile(rf"(?<![\w-]){re.escape(stem)}(?![\w-])")
        users: dict[str, list[str]] = defaultdict(list)
        own = area_of(path)
        for other, lines in index.items():
            if other == path or not any(word.search(line) for line in lines):
                continue
            area = area_of(other)
            if area != own:
                users[area].append(other)
        if len(users) < MIN_OTHER_AREAS:
            continue
        areas = sorted(users)
        listed = ", ".join(areas[:5]) + (f" and {len(areas) - 5} more" if len(areas) > 5 else "")
        name = posixpath.basename(path)
        note = f" ({'; '.join(skipped)})" if skipped else ""
        out.append(
            Finding(
                id=f"shared:{path}",
                problem_id="U20",
                category="shared_file",
                severity=Severity.MEDIUM,
                confidence=60,
                evidence=(hunk_evidence(hunks[0]),),
                title=f"A shared file was changed: {name} is used in {len(areas)} other areas "
                f"({listed})",
                why=BASIC + f"approximate — other parts of the project import `{stem}`, so this "
                f"change may affect them too{note}.",
                check_item=f"{name} still works everywhere it's used ({listed})",
            )
        )
    return out
