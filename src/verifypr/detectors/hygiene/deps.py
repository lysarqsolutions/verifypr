"""U4: dependencies added, removed, or updated, and lock files changed on their own.

Public interface: ``detect(ctx)``, ``parse_manifest(path, data)``.
Supports npm (package.json), pip (requirements*.txt), Python projects (pyproject.toml:
PEP 621 and Poetry), Go (go.mod), Maven (pom.xml), Gradle (build.gradle[.kts]) and
NuGet (*.csproj, Directory.Packages.props). Reads file versions via the ChangeSet only.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys
from collections.abc import Iterable
from typing import Any

from verifypr.analysis.globs import glob_match
from verifypr.detectors.base import DetectorContext, file_evidence, hunk_evidence
from verifypr.models import ChangeKind, Evidence, Finding, Severity

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 in CI
    import tomli as tomllib

Deps = dict[str, str]

LOCKFILES: dict[str, tuple[str, ...]] = {
    "package-lock.json": ("package.json",),
    "npm-shrinkwrap.json": ("package.json",),
    "yarn.lock": ("package.json",),
    "pnpm-lock.yaml": ("package.json",),
    "poetry.lock": ("pyproject.toml",),
    "uv.lock": ("pyproject.toml",),
    "pdm.lock": ("pyproject.toml",),
    "Pipfile.lock": ("Pipfile",),
    "go.sum": ("go.mod",),
    "Cargo.lock": ("Cargo.toml",),
    "gradle.lockfile": ("build.gradle", "build.gradle.kts"),
    "packages.lock.json": ("*.csproj",),
}

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$")
_GO_REQUIRE = re.compile(r"^\s*([\w./~-]+\.[\w./~-]+)\s+(v[\w.+-]+)")
_POM_DEP = re.compile(r"<dependency>(.*?)</dependency>", re.S)
_POM_TAG = re.compile(r"<(groupId|artifactId|version)>\s*([^<]+?)\s*</\1>")
_GRADLE_DEP = re.compile(
    r"\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation|"
    r"testRuntimeOnly|annotationProcessor|kapt|classpath)\s*\(?\s*['\"]"
    r"([\w.-]+:[\w.-]+)(?::([\w.+-]+))?['\"]"
)
_NUGET = re.compile(
    r"<Package(?:Reference|Version)\s+[^>]*?Include\s*=\s*\"([^\"]+)\"[^>]*?"
    r"(?:Version\s*=\s*\"([^\"]*)\")?",
    re.S,
)


def _clean_pep508(spec: str) -> tuple[str, str] | None:
    spec = spec.split(";", 1)[0].strip()
    m = _REQ_NAME.match(spec)
    if not m:
        return None
    name = m.group(1).lower().replace("_", "-")
    return name, m.group(3).strip()


def _requirements(text: str) -> Deps:
    deps: Deps = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http:", "https:")):
            continue
        parsed = _clean_pep508(line)
        if parsed:
            deps[parsed[0]] = parsed[1]
    return deps


def _poetry_section(section: Any, prefix: str = "") -> Deps:
    deps: Deps = {}
    if isinstance(section, dict):
        for name, value in section.items():
            if name.lower() == "python":
                continue
            version = value.get("version", "") if isinstance(value, dict) else str(value)
            deps[prefix + name.lower()] = str(version)
    return deps


def _pyproject(text: str) -> Deps:
    data = tomllib.loads(text)
    deps: Deps = {}
    project = data.get("project", {})
    for spec in project.get("dependencies", []) or []:
        parsed = _clean_pep508(str(spec))
        if parsed:
            deps[parsed[0]] = parsed[1]
    for group, specs in (project.get("optional-dependencies", {}) or {}).items():
        for spec in specs or []:
            parsed = _clean_pep508(str(spec))
            if parsed:
                deps[f"{parsed[0]} ({group})"] = parsed[1]
    poetry = data.get("tool", {}).get("poetry", {})
    deps.update(_poetry_section(poetry.get("dependencies")))
    deps.update(_poetry_section(poetry.get("dev-dependencies"), "dev:"))
    for group, body in (poetry.get("group", {}) or {}).items():
        deps.update(_poetry_section((body or {}).get("dependencies"), f"{group}:"))
    return deps


def _package_json(text: str) -> Deps:
    data = json.loads(text)
    deps: Deps = {}
    sections = {
        "dependencies": "",
        "devDependencies": "dev:",
        "peerDependencies": "peer:",
        "optionalDependencies": "optional:",
    }
    for section, prefix in sections.items():
        for name, version in (data.get(section) or {}).items():
            deps[prefix + name] = str(version)
    return deps


def _go_mod(text: str) -> Deps:
    deps: Deps = {}
    in_block = False
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            line = line[len("require ") :]
        elif not in_block:
            continue
        m = _GO_REQUIRE.match(line)
        if m:
            deps[m.group(1)] = m.group(2)
    return deps


def _pom(text: str) -> Deps:
    deps: Deps = {}
    for block in _POM_DEP.findall(text):
        tags = dict(_POM_TAG.findall(block))
        if "groupId" in tags and "artifactId" in tags:
            deps[f"{tags['groupId']}:{tags['artifactId']}"] = tags.get("version", "")
    return deps


def _gradle(text: str) -> Deps:
    return {m.group(1): m.group(2) or "" for m in _GRADLE_DEP.finditer(text)}


def _nuget(text: str) -> Deps:
    return {m.group(1): m.group(2) or "" for m in _NUGET.finditer(text)}


_PARSERS: tuple[tuple[str, Any], ...] = (
    ("package.json", _package_json),
    ("requirements*.txt", _requirements),
    ("requirements*.in", _requirements),
    ("pyproject.toml", _pyproject),
    ("go.mod", _go_mod),
    ("pom.xml", _pom),
    ("build.gradle", _gradle),
    ("build.gradle.kts", _gradle),
    ("*.csproj", _nuget),
    ("Directory.Packages.props", _nuget),
)


def is_manifest(path: str) -> bool:
    return any(glob_match(pattern, path) for pattern, _ in _PARSERS)


def parse_manifest(path: str, data: bytes | None) -> Deps | None:
    """Dependencies in a manifest; ``{}`` if the file is missing; ``None`` if unparseable."""
    if data is None:
        return {}
    text = data.decode("utf-8", errors="replace").lstrip("﻿")
    for pattern, parser in _PARSERS:
        if glob_match(pattern, path):
            try:
                result: Deps = parser(text)
            except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError):
                return None
            return result
    return None


def _major(version: str) -> str | None:
    m = re.search(r"\d+", version)
    return m.group(0) if m else None


def _evidence_for(ctx: DetectorContext, path: str, names: Iterable[str]) -> tuple[Evidence, ...]:
    hunks = ctx.changes.hunks_for(path)
    wanted = [n.split(":", 1)[-1].split(" ", 1)[0] for n in names]
    evidence: list[Evidence] = []
    for hunk in hunks:
        idxs = [i for i, line in enumerate(hunk.added) if any(w and w in line for w in wanted)]
        if idxs:
            evidence.append(hunk_evidence(hunk, idxs))
    if not evidence and hunks:
        evidence.append(hunk_evidence(hunks[0]))
    return tuple(evidence) or (file_evidence(path),)


def _manifest_finding(ctx: DetectorContext, path: str) -> Finding | None:
    old = parse_manifest(path, ctx.changes.read_old(path))
    new = parse_manifest(path, ctx.changes.read_new(path))
    if old is None or new is None:
        return Finding(
            id=f"deps:{path}",
            problem_id="U4",
            category="dependencies",
            severity=Severity.LOW,
            confidence=60,
            evidence=_evidence_for(ctx, path, []),
            title=f"A dependency file changed: {path}",
            why="This file lists the project's dependencies, but VerifyPR couldn't read it "
            "to see exactly what changed.",
            check_item=f"The changes to {path} are intended",
        )
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    updated = sorted(n for n in set(old) & set(new) if old[n] != new[n])
    if not (added or removed or updated):
        return None
    parts: list[str] = []
    if added:
        parts.append("added " + ", ".join(added))
    if removed:
        parts.append("removed " + ", ".join(removed))
    if updated:
        parts.append(
            "updated " + ", ".join(f"{n} {old[n] or '?'} → {new[n] or '?'}" for n in updated)
        )
    major_bump = any(_major(old[n]) != _major(new[n]) for n in updated)
    severity = Severity.MEDIUM if (added or removed or major_bump) else Severity.LOW
    counts = [
        f"{len(added)} added" if added else "",
        f"{len(removed)} removed" if removed else "",
        f"{len(updated)} updated" if updated else "",
    ]
    if added:
        check = (
            f"The new dependency {added[0]} is wanted and trusted"
            if len(added) == 1
            else f"The {len(added)} new dependencies in {path} are wanted and trusted"
        )
    else:
        check = f"The dependency changes in {path} are intended"
    return Finding(
        id=f"deps:{path}",
        problem_id="U4",
        category="dependencies",
        severity=severity,
        confidence=90,
        evidence=_evidence_for(ctx, path, added + updated + removed),
        title=f"Dependencies changed in {path}: " + ", ".join(c for c in counts if c),
        why="Dependency changes affect security, licenses, and build size: "
        + "; ".join(parts)
        + ".",
        check_item=check,
    )


def _lockfile_findings(ctx: DetectorContext, changed_manifests: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    for change in ctx.changes.files:
        name = posixpath.basename(change.path)
        if name not in LOCKFILES or change.change_kind is ChangeKind.DELETE:
            continue
        folder = posixpath.dirname(change.path)
        siblings = [
            m
            for m in changed_manifests
            if posixpath.dirname(m) == folder
            and any(glob_match(pat, posixpath.basename(m)) for pat in LOCKFILES[name])
        ]
        if siblings:
            continue
        findings.append(
            Finding(
                id=f"deps:lockfile:{change.path}",
                problem_id="U4",
                category="dependencies",
                severity=Severity.MEDIUM,
                confidence=80,
                evidence=_evidence_for(ctx, change.path, []),
                title=f"Lock file changed without a dependency change: {change.path}",
                why="The exact versions of installed packages changed even though the list of "
                "dependencies didn't. This often happens by accident when tools are re-run.",
                check_item=f"The lock file update in {change.path} was intended",
            )
        )
    return findings


def detect(ctx: DetectorContext) -> list[Finding]:
    findings: list[Finding] = []
    changed_with_deps: set[str] = set()
    for change in ctx.changes.files:
        if change.binary or not is_manifest(change.path):
            continue
        finding = _manifest_finding(ctx, change.path)
        if finding is not None:
            findings.append(finding)
            changed_with_deps.add(change.path)
    return findings + _lockfile_findings(ctx, changed_with_deps)
