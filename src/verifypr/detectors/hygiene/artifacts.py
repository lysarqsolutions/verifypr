"""U6: secrets, environment files, build output, editor/OS junk, and binaries committed.

Public interface: ``detect(ctx)``. Evidence snippets are always redacted.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict

from verifypr.analysis.globs import any_match
from verifypr.analysis.redaction import find_secrets
from verifypr.detectors.base import DetectorContext, file_evidence, hunk_evidence
from verifypr.models import ChangeKind, Evidence, FileChange, Finding, Severity

BUILD_OUTPUT = (
    "dist/**",
    "**/dist/**",
    "out/**",
    "target/**",
    "**/target/**",
    "**/bin/Debug/**",
    "**/bin/Release/**",
    "**/obj/**",
    "**/__pycache__/**",
    "*.pyc",
    "*.pyo",
    "**/node_modules/**",
    ".next/**",
    "**/.next/**",
    "coverage/**",
    "htmlcov/**",
    "*.class",
    "*.o",
    "*.obj",
    "*.egg-info/**",
    "**/*.egg-info/**",
)
JUNK = (".DS_Store", "Thumbs.db", "desktop.ini", ".idea/**", "*.iml", "*.swp", "*~")
MEDIA_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".bmp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp3",
    ".mp4",
    ".webm",
}
ENV_SAFE = {".env.example", ".env.sample", ".env.template", ".env.dist", ".env.defaults"}


def _is_new(change: FileChange) -> bool:
    return change.change_kind is ChangeKind.ADD or change.untracked


def _is_env_file(path: str) -> bool:
    name = posixpath.basename(path)
    return (name == ".env" or name.startswith(".env.")) and name not in ENV_SAFE


SETTINGS_SUFFIXES = (".ini", ".cfg", ".conf", ".properties", ".yml", ".yaml", ".toml")
SETTINGS_NAMES = {".npmrc", ".pypirc", ".netrc"}


def _is_settings_file(path: str) -> bool:
    """Settings files hold plain ``key=value`` pairs, so unquoted secrets count there."""
    name = posixpath.basename(path).lower()
    return (
        _is_env_file(path)
        or name.startswith(".env")
        or name in SETTINGS_NAMES
        or name.endswith(SETTINGS_SUFFIXES)
    )


def _secret_findings(ctx: DetectorContext) -> list[Finding]:
    findings: list[Finding] = []
    for change in ctx.changes.files:
        if change.binary:
            continue
        evidence: list[Evidence] = []
        labels: list[str] = []
        critical = False
        for hunk in ctx.changes.hunks_for(change.path):
            for i, line in enumerate(hunk.added):
                matches = find_secrets(line, loose=_is_settings_file(change.path))
                if not matches:
                    continue
                evidence.append(hunk_evidence(hunk, [i]))
                for m in matches:
                    critical = critical or m.critical
                    if m.label not in labels:
                        labels.append(m.label)
        if not evidence:
            continue
        what = labels[0] if len(labels) == 1 else "secrets"
        article = "An" if what[0].lower() in "aeiou" else "A"
        if critical:
            title = f"{article} {what} was added in {change.path}"
            why = (
                "Anyone who can read this repository could use it. If it's real, it must be "
                "removed and replaced with a new one (rotated)."
            )
        else:
            title = f"Something that looks like a password or secret was added in {change.path}"
            why = "It looks like a hard-coded password or key; real secrets don't belong in code."
        findings.append(
            Finding(
                id=f"secrets:{change.path}",
                problem_id="U6",
                category="secrets",
                severity=Severity.HIGH if critical else Severity.MEDIUM,
                confidence=90 if critical else 60,
                critical=critical,
                evidence=tuple(evidence),
                title=title,
                why=why,
                check_item=f"No real secret was committed in {change.path} (if one was, rotate it)",
            )
        )
    return findings


def _env_findings(ctx: DetectorContext) -> list[Finding]:
    findings: list[Finding] = []
    for change in ctx.changes.files:
        if change.change_kind is ChangeKind.DELETE or not _is_env_file(change.path):
            continue
        new = _is_new(change)
        findings.append(
            Finding(
                id=f"env_file:{change.path}",
                problem_id="U6",
                category="env_file",
                severity=Severity.HIGH if new else Severity.MEDIUM,
                confidence=90,
                evidence=(file_evidence(change.path),),
                title=(
                    f"An environment settings file was added: {change.path}"
                    if new
                    else f"An environment settings file was changed: {change.path}"
                ),
                why="Files like .env usually hold passwords and API keys and normally shouldn't "
                "be in the repository.",
                check_item=f"{change.path} should be in this change and holds no real secrets",
            )
        )
    return findings


def _group_finding(
    fid: str,
    category: str,
    paths: list[str],
    severity: Severity,
    confidence: int,
    title: str,
    why: str,
    check: str | None,
) -> Finding:
    return Finding(
        id=fid,
        problem_id="U6",
        category=category,
        severity=severity,
        confidence=confidence,
        evidence=tuple(file_evidence(p) for p in paths[:20]),
        title=title,
        why=why,
        check_item=check,
    )


def _artifact_findings(ctx: DetectorContext) -> list[Finding]:
    groups: dict[str, list[str]] = defaultdict(list)
    for change in ctx.changes.files:
        if not _is_new(change):
            continue
        path = change.path
        group: str | None = None
        if any_match(BUILD_OUTPUT, path):
            group = "build"
        elif any_match(JUNK, path):
            group = "junk"
        elif (
            change.binary
            and not change.lfs_pointer
            and posixpath.splitext(path)[1].lower() not in MEDIA_EXT
        ):
            group = "binary"
        if group and not ctx.allowed("artifacts", path):
            groups[group].append(path)
    findings: list[Finding] = []
    if groups["build"]:
        paths = groups["build"]
        findings.append(
            _group_finding(
                "artifacts:build",
                "artifacts",
                paths,
                Severity.MEDIUM,
                75,
                f"Build output or generated files were added ({len(paths)} "
                f"{'file' if len(paths) == 1 else 'files'}, e.g. {paths[0]})",
                "These files are usually created by tools and shouldn't be committed; they "
                "bloat the repository and go out of date.",
                f"Generated files like {paths[0]} really belong in this change",
            )
        )
    if groups["junk"]:
        paths = groups["junk"]
        findings.append(
            _group_finding(
                "artifacts:junk",
                "artifacts",
                paths,
                Severity.LOW,
                90,
                f"Editor or system files were added ({paths[0]}"
                f"{f' and {len(paths) - 1} more' if len(paths) > 1 else ''})",
                "These are personal editor or operating-system files, not part of the project.",
                None,
            )
        )
    if groups["binary"]:
        paths = groups["binary"]
        findings.append(
            _group_finding(
                "artifacts:binary",
                "artifacts",
                paths,
                Severity.LOW,
                70,
                f"Binary files were added ({paths[0]}"
                f"{f' and {len(paths) - 1} more' if len(paths) > 1 else ''})",
                "Binary files can't be reviewed line by line and are often added by accident.",
                f"The binary file {paths[0]} is meant to be in the repository",
            )
        )
    return findings


def detect(ctx: DetectorContext) -> list[Finding]:
    return _secret_findings(ctx) + _env_findings(ctx) + _artifact_findings(ctx)
