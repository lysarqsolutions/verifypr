"""U20 (basic): a changed file is used by several other areas of the project.

Public interface: ``detect(ctx)``, ``area_of(path)``, ``import_specs(line)``,
``refers_to(spec, importer, target)``.

Approximate on purpose: it reads import/require/include lines and resolves them to files —
relative imports (``./utils``, ``from .orders import``) against the importing file's folder,
other imports (aliases like ``@/shared/Form``, ``pkg.module``) by matching the target's
folder *and* name. No whole-program analysis. The full registry-aware version is Phase 6.
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
    "src", "apps", "app", "packages", "services", "modules", "libs", "lib", "projects",
    "portals", "web", "frontend", "backend",
}  # fmt: skip
INDEX_NAMES = {"index", "__init__", "mod"}

_IMPORT_LINE = re.compile(
    r"^\s*(?:import\b|from\b|export\b.*\bfrom\b|.*\brequire\s*\(|.*\bimport\s*\(|#include\b)"
)
_QUOTED = re.compile(r"""['"]([^'"\s]+)['"]""")
_PY_FROM = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+\(?([\w\s,]+)")
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)\s*$")


def area_of(path: str) -> str:
    parts = path.split("/")
    if len(parts) > 2 and parts[0].lower() in CONTAINERS:
        return parts[1]
    return parts[0] if len(parts) > 1 else "project root"


def _module_key(path: str) -> str:
    """``src/shared/Form.tsx`` -> ``src/shared/Form``; ``pkg/__init__.py`` -> ``pkg``."""
    base = posixpath.splitext(path)[0]
    if posixpath.basename(base) in INDEX_NAMES:
        base = posixpath.dirname(base)
    return base


def import_specs(line: str) -> list[str]:
    """Module specifiers on an import line (paths for JS/C, dotted names for Python)."""
    m = _PY_FROM.match(line)
    if m:
        base, names = m.group(1), [n.strip() for n in m.group(2).split(",") if n.strip()]
        sep = "" if base.endswith(".") else "."
        return [base, *(f"{base}{sep}{n}" for n in names)]
    m = _PY_IMPORT.match(line)
    if m:
        return [x.strip() for x in m.group(1).split(",")]
    return _QUOTED.findall(line)


def _resolve_relative(spec: str, importer: str) -> str | None:
    folder = posixpath.dirname(importer)
    if spec.startswith(("./", "../")):
        joined = posixpath.normpath(posixpath.join(folder, spec))
        return _module_key(joined) if posixpath.splitext(joined)[1] else joined
    if spec.startswith("."):  # Python relative: from .orders / from ..pkg.mod
        dots = len(spec) - len(spec.lstrip("."))
        for _ in range(dots - 1):
            folder = posixpath.dirname(folder)
        rest = spec[dots:].replace(".", "/")
        return posixpath.normpath(posixpath.join(folder, rest)) if rest else folder
    return None


def refers_to(spec: str, importer: str, target: str) -> bool:
    key = _module_key(target)
    resolved = _resolve_relative(spec, importer)
    if resolved is not None:
        return resolved == key
    segments = [s for s in re.split(r"[/.]", spec) if s and s not in {"@", "~"}]
    wanted = key.split("/")[-2:] if "/" in key else [key]
    return len(segments) >= len(wanted) and segments[-len(wanted) :] == wanted


def _searchable(path: str) -> bool:
    return (is_code_file(path) or any_match(UI_GLOBS, path)) and not is_test_file(path)


def _import_index(ctx: DetectorContext, skipped: list[str]) -> dict[str, list[str]]:
    files = [p for p in ctx.changes.list_files() if _searchable(p)]
    if len(files) > MAX_FILES:
        skipped.append(f"only the first {MAX_FILES} of {len(files)} files were searched")
        files = files[:MAX_FILES]
    index: dict[str, list[str]] = {}
    for path, data in ctx.changes.read_many(files).items():
        if data is None or len(data) > MAX_BYTES or b"\0" in data[:4096]:
            continue
        specs = [
            spec
            for line in data.decode("utf-8", errors="replace").splitlines()
            if _IMPORT_LINE.match(line)
            for spec in import_specs(line)
        ]
        if specs:
            index[path] = specs
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
    index = _import_index(ctx, skipped)
    out: list[Finding] = []
    for path, hunks in candidates:
        users: dict[str, list[str]] = defaultdict(list)
        own = area_of(path)
        for other, specs in index.items():
            if other == path or not any(refers_to(s, other, path) for s in specs):
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
                why=BASIC + "approximate — other parts of the project import this file, so this "
                f"change may affect them too{note}.",
                check_item=f"{name} still works everywhere it's used ({listed})",
            )
        )
    return out
