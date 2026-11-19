"""U10: safety checks turned off to make things pass.

Public interface: ``detect(ctx)``. Covers new lint/type suppressions, lint rules turned off
in config, lowered coverage thresholds, CI checks removed or commented out, CI steps set to
never fail, pre-commit hooks removed, and strict settings switched off.
"""

from __future__ import annotations

import re
from collections import defaultdict

from verifypr.analysis.globs import any_match
from verifypr.detectors.base import DetectorContext, file_evidence, hunk_evidence
from verifypr.detectors.common import changed_lines, comment_part, is_ci_file, without_strings
from verifypr.models import ChangeKind, Evidence, Finding, Hunk, Severity

_SUPPRESSIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("@ts-ignore", re.compile(r"@ts-ignore\b")),
    ("@ts-nocheck", re.compile(r"@ts-nocheck\b")),
    ("@ts-expect-error", re.compile(r"@ts-expect-error\b")),
    ("eslint-disable", re.compile(r"eslint-disable(?:-next-line|-line)?\b")),
    ("type: ignore", re.compile(r"#\s*type:\s*ignore\b")),
    ("noqa", re.compile(r"#\s*noqa\b", re.I)),
    ("pylint: disable", re.compile(r"#\s*pylint:\s*disable\b")),
    ("pragma: no cover", re.compile(r"#\s*pragma:\s*no\s*cover\b")),
    ("istanbul ignore", re.compile(r"istanbul\s+ignore\b")),
    ("c8 ignore", re.compile(r"\bc8\s+ignore\b")),
    ("nolint", re.compile(r"//\s*nolint\b")),
    ("#pragma warning disable", re.compile(r"#pragma\s+warning\s+disable\b")),
    ("@SuppressWarnings", re.compile(r"@SuppressWarnings\b")),
    ("NOSONAR", re.compile(r"\bNOSONAR\b")),
    ("rubocop:disable", re.compile(r"rubocop:disable\b")),
    ("phpcs:ignore", re.compile(r"phpcs:(?:ignore|disable)\b")),
    ("@Suppress", re.compile(r"@Suppress\(")),
)

LINT_CONFIG_GLOBS = (
    ".eslintrc",
    ".eslintrc.*",
    "eslint.config.*",
    ".flake8",
    "setup.cfg",
    "tox.ini",
    "ruff.toml",
    ".ruff.toml",
    "pyproject.toml",
    ".pylintrc",
    "pylintrc",
    "tslint.json",
    ".rubocop.yml",
    ".golangci.yml",
    ".golangci.yaml",
    "checkstyle*.xml",
    "biome.json",
    ".stylelintrc*",
    "mypy.ini",
    ".mypy.ini",
    "phpcs.xml*",
)
_LINT_OFF = re.compile(
    r"""(?ix)
    (["']off["']|:\s*["']?0["']?\s*[,}]?\s*$|\bignore\b|\bextend-ignore\b|\bper-file-ignores\b|
     \bdisable\b|\bexclude\b|\bignore_errors\s*=\s*true)"""
)
_COVERAGE_KEY = re.compile(
    r"(?i)(fail[_-]under|cov-fail-under|coverageThreshold|minimum[_-]coverage|"
    r"\b(?:branches|lines|functions|statements)\b|min[_-]?coverage|coverage[_-]?threshold)"
    r"\D{0,12}?(\d+(?:\.\d+)?)"
)
_CHECK_WORDS = re.compile(
    r"(?i)\b(test|tests|pytest|jest|vitest|mocha|lint|eslint|ruff|flake8|pylint|mypy|tsc|"
    r"typecheck|type-check|check|audit|scan|coverage|security|codeql|gitleaks|build|verify)\b"
)
_STEP_LINE = re.compile(r"^\s*(?:-\s*)?(?:run|script|name|uses|command|cmd)\s*:|^\s*-\s+\S")
# A whole CI step allowed to fail (always worth flagging in CI files).
_STEP_NEVER_FAIL = re.compile(
    r"(?i)continue-on-error\s*:\s*true|allow_failure\s*:\s*true|ignore-errors\s*:\s*true|"
    r"failOnStderr\s*:\s*false"
)
# A single command made to "succeed"; only matters when that command is a check.
_CMD_NEVER_FAIL = re.compile(r"\|\|\s*true\b|\|\|\s*exit\s+0\b|\|\|\s*:\s*$|\bset\s+\+e\b")
_CHECK_COMMAND = re.compile(
    r"(?i)\b(?:pytest|jest|vitest|mocha|eslint|ruff|flake8|pylint|mypy|tsc|tox|nox|audit|"
    r"codeql|gitleaks|coverage|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|lint|check|typecheck)|"
    r"go\s+(?:test|vet)|cargo\s+(?:test|clippy)|dotnet\s+test|mvn\s+(?:test|verify)|"
    r"gradlew?\s+(?:test|check)|make\s+(?:test|lint|check))\b"
)
# Multi-purpose files: only their lint/type-check sections count as "code-check rules".
SHARED_CONFIG_FILES = ("pyproject.toml", "setup.cfg", "tox.ini")
_LINT_SECTION = re.compile(
    r"(?i)^\[\s*(?:tool\.)?(?:ruff|mypy|pylint|flake8|pycodestyle|pydocstyle|black|isort|"
    r"pyright|bandit|pylama|pyflakes)\b"
)
_SECTION_HEADER = re.compile(r"^\s*\[")
COVERAGE_CONFIG_GLOBS = (
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    ".coveragerc",
    "pytest.ini",
    "jest.config.*",
    "vitest.config.*",
    "vite.config.*",
    "karma.conf.*",
    "package.json",
    "codecov.yml",
    ".codecov.yml",
    ".nycrc",
    ".nycrc.*",
    ".c8rc",
    ".c8rc.*",
    "sonar-project.properties",
)
STRICT_CONFIG_GLOBS = (
    "tsconfig*.json",
    "jsconfig*.json",
    "mypy.ini",
    ".mypy.ini",
    "pyproject.toml",
    "setup.cfg",
    "pyrightconfig.json",
    ".eslintrc",
    ".eslintrc.*",
    "eslint.config.*",
    "phpstan.neon*",
    "deno.json",
    "biome.json",
    "*.csproj",
    "Directory.Build.props",
)
_STRICT_ON = re.compile(
    r"(?i)[\"']?(strict\w*|noImplicit\w+|disallow_\w+|warn_\w+|noUnused\w+|"
    r"noFallthroughCasesInSwitch|exactOptionalPropertyTypes|forceConsistentCasingInFileNames)"
    r"[\"']?\s*[:=]\s*(true|false)\b"
)
PRECOMMIT_GLOBS = (".pre-commit-config.yaml", ".pre-commit-config.yml", ".husky/**", "lefthook.yml")
_HOOK_ID = re.compile(r"^\s*-\s*id\s*:\s*(\S+)")


def _finding(
    fid: str,
    severity: Severity,
    confidence: int,
    evidence: tuple[Evidence, ...],
    title: str,
    why: str,
    check: str | None,
    *,
    critical: bool = False,
) -> Finding:
    return Finding(
        id=fid,
        problem_id="U10",
        category="guardrails",
        severity=severity,
        confidence=confidence,
        critical=critical,
        evidence=evidence,
        title=title,
        why=why,
        check_item=check,
    )


def _suppresses(pattern: re.Pattern[str], line: str) -> bool:
    """A real suppression: in a comment (``// @ts-ignore``) or an annotation/pragma at the
    start of the code (``@SuppressWarnings``) — never text inside a string or prose."""
    comment = comment_part(line)
    if comment is not None and pattern.search(comment):
        return True
    code = without_strings(line).lstrip()
    return code.startswith(("@", "#pragma")) and bool(pattern.match(code))


def _suppressions(hunks: list[Hunk]) -> list[Finding]:
    per_file: dict[str, list[tuple[Hunk, int, str]]] = defaultdict(list)
    for hunk in hunks:
        for name, pattern in _SUPPRESSIONS:
            before = sum(_suppresses(pattern, x) for x in hunk.removed)
            idx = [i for i, x in enumerate(hunk.added) if _suppresses(pattern, x)]
            for i in idx[before:]:
                per_file[hunk.file_path].append((hunk, i, name))
    out: list[Finding] = []
    for path, hits in per_file.items():
        names = sorted({name for _h, _i, name in hits})
        by_hunk: dict[str, tuple[Hunk, list[int]]] = {}
        for hunk, i, _name in hits:
            by_hunk.setdefault(hunk.id, (hunk, []))[1].append(i)
        evidence = tuple(hunk_evidence(h, idx) for h, idx in by_hunk.values())
        what = f"new {names[0]}" if len(names) == 1 else "new check suppressions"
        out.append(
            _finding(
                f"guardrails:suppress:{path}",
                Severity.HIGH,
                85,
                evidence,
                f"Code checks were switched off in {path} ({len(hits)} {what})",
                "Comments like " + ", ".join(f"`{n}`" for n in names[:3]) + " tell type checkers "
                "or linters to ignore a problem instead of fixing it.",
                f"Each check switched off in {path} hides a real false alarm, not a real problem",
            )
        )
    return out


def _section_of_lines(ctx: DetectorContext, path: str) -> list[str] | None:
    """For each line (1-based) of the new file, the ``[section]`` header it sits under."""
    data = ctx.changes.read_new(path)
    if data is None:
        return None
    sections = [""]
    current = ""
    for line in data.decode("utf-8", errors="replace").splitlines():
        if _SECTION_HEADER.match(line):
            current = line.strip()
        sections.append(current)
    return sections


def _lint_config(ctx: DetectorContext, hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in hunks:
        if not any_match(LINT_CONFIG_GLOBS, hunk.file_path):
            continue
        _gone, new = changed_lines(hunk)
        idx = [
            i
            for i, x in enumerate(hunk.added)
            if x.strip() in new and _LINT_OFF.search(x) and not x.strip().startswith(("#", "//"))
        ]
        if any_match(SHARED_CONFIG_FILES, hunk.file_path):
            sections = _section_of_lines(ctx, hunk.file_path) or []
            idx = [
                i
                for i in idx
                if hunk.added_at[i] < len(sections)
                and _LINT_SECTION.match(sections[hunk.added_at[i]])
            ]
        if not idx:
            continue
        ev = hunk_evidence(hunk, idx)
        out.append(
            _finding(
                f"guardrails:lint_config:{hunk.id}",
                Severity.MEDIUM,
                70,
                (ev,),
                f"Code-check rules were turned off or relaxed in {hunk.file_path}",
                "Turning rules off or adding ignores lets problems through that the checks used "
                "to catch.",
                f"The relaxed rules in {hunk.file_path} are intended",
            )
        )
    return out


def _coverage(hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in hunks:
        if not (any_match(COVERAGE_CONFIG_GLOBS, hunk.file_path) or is_ci_file(hunk.file_path)):
            continue
        old = {
            m.group(1).lower(): float(m.group(2))
            for x in hunk.removed
            for m in [_COVERAGE_KEY.search(x)]
            if m
        }
        lowered: list[int] = []
        for i, x in enumerate(hunk.added):
            m = _COVERAGE_KEY.search(x)
            if m and m.group(1).lower() in old and float(m.group(2)) < old[m.group(1).lower()]:
                lowered.append(i)
        if lowered:
            ev = hunk_evidence(hunk, lowered)
            out.append(
                _finding(
                    f"guardrails:coverage:{hunk.id}",
                    Severity.HIGH,
                    85,
                    (ev,),
                    f"The minimum test coverage was lowered in {hunk.file_path}",
                    "Lowering the required coverage lets less-tested code pass the checks.",
                    f"Lowering the coverage limit in {hunk.file_path} is intended",
                )
            )
    return out


def _never_fails(line: str, *, in_ci: bool) -> bool:
    """A check made to always pass. ``cleanup || true`` is fine; ``pytest || true`` isn't."""
    if in_ci and _STEP_NEVER_FAIL.search(line):
        return True
    return bool(_CMD_NEVER_FAIL.search(line) and _CHECK_COMMAND.search(line))


def _ci(ctx: DetectorContext, hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for change in ctx.changes.files:
        if change.change_kind is ChangeKind.DELETE and is_ci_file(change.path):
            out.append(
                _finding(
                    f"guardrails:ci_deleted:{change.path}",
                    Severity.HIGH,
                    90,
                    (file_evidence(change.path),),
                    f"An automatic check (CI) file was deleted: {change.path}",
                    "Deleting a CI workflow stops its checks from running on future changes.",
                    f"Deleting {change.path} was really intended",
                    critical=True,
                )
            )
    for hunk in hunks:
        if not is_ci_file(hunk.file_path):
            continue
        gone, new = changed_lines(hunk)
        uncommented = {n.lstrip("#").strip() for n in new if n.startswith("#")}
        removed_checks = [
            r
            for r in gone
            if _STEP_LINE.search(r) and _CHECK_WORDS.search(r) and not r.startswith("#")
        ]
        commented = [r for r in removed_checks if r in uncommented]
        if removed_checks:
            label = "commented out" if commented else "removed"
            sample = (commented or removed_checks)[0][:80]
            out.append(
                _finding(
                    f"guardrails:ci_removed:{hunk.id}",
                    Severity.HIGH,
                    80,
                    (hunk_evidence(hunk),),
                    f"An automatic check (CI) step was {label} in {hunk.file_path}",
                    f"The step `{sample}` no longer runs, so problems it used to catch can slip "
                    "through.",
                    f"Removing the CI step in {hunk.file_path} was really intended",
                    critical=True,
                )
            )
    for hunk in hunks:
        in_ci = is_ci_file(hunk.file_path)
        if not (in_ci or hunk.language == "shell"):
            continue
        before = sum(_never_fails(x, in_ci=in_ci) for x in hunk.removed)
        idx = [i for i, x in enumerate(hunk.added) if _never_fails(x, in_ci=in_ci)]
        if len(idx) > before:
            ev = hunk_evidence(hunk, idx)
            out.append(
                _finding(
                    f"guardrails:never_fail:{hunk.id}",
                    Severity.HIGH,
                    85,
                    (ev,),
                    f"A check was set to never fail ({hunk.file_path}:{ev.start_line})",
                    "Settings like `continue-on-error: true` or `|| true` make a failing check "
                    "look like it passed.",
                    f"The check in {hunk.file_path} is allowed to fail on purpose",
                    critical=in_ci,
                )
            )
    return out


def _precommit(ctx: DetectorContext, hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for change in ctx.changes.files:
        if change.change_kind is ChangeKind.DELETE and any_match(PRECOMMIT_GLOBS, change.path):
            out.append(
                _finding(
                    f"guardrails:hook_deleted:{change.path}",
                    Severity.MEDIUM,
                    85,
                    (file_evidence(change.path),),
                    f"A pre-commit check was deleted: {change.path}",
                    "Pre-commit checks run before each commit; deleting them lets problems in "
                    "unnoticed.",
                    f"Deleting {change.path} was intended",
                )
            )
    for hunk in hunks:
        if not any_match(PRECOMMIT_GLOBS, hunk.file_path):
            continue
        old = {m.group(1) for x in hunk.removed for m in [_HOOK_ID.search(x)] if m}
        new = {m.group(1) for x in hunk.added for m in [_HOOK_ID.search(x)] if m}
        gone = sorted(old - new)
        if gone:
            out.append(
                _finding(
                    f"guardrails:hooks:{hunk.id}",
                    Severity.MEDIUM,
                    85,
                    (hunk_evidence(hunk),),
                    f"Pre-commit checks were removed: {', '.join(gone[:3])}",
                    "These checks ran before every commit and no longer will.",
                    "Removing the pre-commit checks was intended",
                )
            )
    return out


def _strictness(hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in hunks:
        if not any_match(STRICT_CONFIG_GLOBS, hunk.file_path):
            continue
        was_on = {
            m.group(1)
            for x in hunk.removed
            for m in [_STRICT_ON.search(x)]
            if m and m.group(2).lower() == "true"
        }
        idx = [
            i
            for i, x in enumerate(hunk.added)
            for m in [_STRICT_ON.search(x)]
            if m
            and m.group(2).lower() == "false"
            and (m.group(1) in was_on or m.group(1).lower().startswith("strict"))
        ]
        if idx:
            ev = hunk_evidence(hunk, idx)
            out.append(
                _finding(
                    f"guardrails:strict:{hunk.id}",
                    Severity.HIGH,
                    85,
                    (ev,),
                    f"Strict checking was switched off in {hunk.file_path}",
                    "Strict settings catch whole kinds of mistakes; turning them off hides those "
                    "mistakes instead of fixing them.",
                    f"Switching off strict checking in {hunk.file_path} is intended",
                )
            )
    return out


def detect(ctx: DetectorContext) -> list[Finding]:
    hunks = list(ctx.changes.hunks)
    return (
        _suppressions(hunks)
        + _lint_config(ctx, hunks)
        + _coverage(hunks)
        + _ci(ctx, hunks)
        + _precommit(ctx, hunks)
        + _strictness(hunks)
    )
