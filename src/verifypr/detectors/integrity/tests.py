"""U9: tests deleted, skipped, or weakened.

Public interface: ``detect(ctx)``. Covers deleted test files, removed test cases,
fewer checks (assertions), expected values changed alongside the code they test,
new skip/only/disabled markers, bulk snapshot updates, looser mocks, and longer timeouts.
"""

from __future__ import annotations

import re
from collections import defaultdict

from verifypr.analysis.globs import any_match
from verifypr.detectors.base import DetectorContext, file_evidence, hunk_evidence
from verifypr.detectors.common import is_code_file, is_test_file, plural, skeleton, without_strings
from verifypr.models import ChangeKind, Evidence, Finding, Hunk, Severity

_TEST_NAME = (
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),
    re.compile(r"\b(?:it|test)(?:\.(?:only|skip|todo|each|concurrent))?\s*\(\s*(['\"`])(.+?)\1"),
    re.compile(r"^\s*func\s+(Test\w+)\s*\("),
)
_TEST_ANNOTATION = re.compile(r"@Test\b|\[(?:Test|Fact|Theory|TestMethod|TestCase)\b")
_ASSERTION = re.compile(
    r"\bassert\b|\bexpect\s*\(|\bassert[A-Z]\w*\s*\(|\bAssert\.\w+\s*\(|\bself\.assert\w+\s*\(|"
    r"\.should\b|\bshould\.|\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail)\b|\bassertThat\s*\(|"
    r"\brequire\.\w+\s*\(|\.to(?:Be|Equal|Have|Contain|Throw|Match)\w*\s*\("
)
_SKIP = re.compile(
    r"@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\(|@unittest\.skip|"
    r"\b(?:it|test|describe|context)\.(?:skip|todo)\s*\(|\bx(?:it|describe|test)\s*\(|"
    r"@Ignore\b|@Disabled\b|\[Ignore\b|Skip\s*=\s*\"|\bt\.Skip(?:f|Now)?\s*\(|\bskip\s*\(\s*['\"]"
)
_CONDITIONAL_SKIP = re.compile(
    r"\bskip_?if\b|\bskip_?unless\b|\bimportorskip\b|\.skipIf\s*\(|\.runIf\s*\(", re.I
)
_ONLY = re.compile(r"\b(?:it|test|describe|context)\.only\s*\(|\bf(?:it|describe)\s*\(")
_LOOSE_MOCK = re.compile(
    r"\bmock\.ANY\b|\bANY\b|\bany\(\)|\banything\(\)|\bexpect\.any(?:thing)?\s*\(|"
    r"\bIt\.IsAny<|\bMockito\.any\w*\s*\(|\bArgumentMatchers\.any\w*\s*\(|\bgomock\.Any\(\)"
)
_TIMEOUT = re.compile(r"(?i)timeout\D{0,20}?(\d+(?:\.\d+)?)")
SNAPSHOT_GLOBS = ("**/__snapshots__/**", "*.snap", "**/*.snap", "**/snapshots/**")


def _names(lines: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for line in lines:
        for pattern in _TEST_NAME:
            m = pattern.search(line)
            if m:
                found.add(m.group(m.lastindex or 1))
    return found


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
        problem_id="U9",
        category="test_integrity",
        severity=severity,
        confidence=confidence,
        critical=critical,
        evidence=evidence,
        title=title,
        why=why,
        check_item=check,
    )


def _deleted_test_files(ctx: DetectorContext) -> list[Finding]:
    out: list[Finding] = []
    for change in ctx.changes.files:
        if change.change_kind is ChangeKind.DELETE and is_test_file(change.path):
            out.append(
                _finding(
                    f"tests:deleted:{change.path}",
                    Severity.HIGH,
                    95,
                    (file_evidence(change.path),),
                    f"A test file was deleted: {change.path}",
                    "Deleting tests removes the safety net that would catch mistakes in this "
                    "change.",
                    f"Deleting {change.path} was really intended",
                    critical=True,
                )
            )
    return out


def _removed_tests(ctx: DetectorContext, test_hunks: list[Hunk]) -> list[Finding]:
    removed_by_file: dict[str, set[str]] = defaultdict(set)
    added_by_file: dict[str, set[str]] = defaultdict(set)
    annotations: dict[str, int] = defaultdict(int)
    for hunk in test_hunks:
        removed_by_file[hunk.file_path] |= _names(hunk.removed)
        added_by_file[hunk.file_path] |= _names(hunk.added)
        annotations[hunk.file_path] += sum(bool(_TEST_ANNOTATION.search(x)) for x in hunk.removed)
        annotations[hunk.file_path] -= sum(bool(_TEST_ANNOTATION.search(x)) for x in hunk.added)
    all_added = set().union(*added_by_file.values()) if added_by_file else set()
    all_removed = set().union(*removed_by_file.values()) if removed_by_file else set()
    out: list[Finding] = []
    for path in sorted(set(removed_by_file) | set(annotations)):
        change = ctx.changes.file(path)
        if change is not None and change.change_kind is ChangeKind.DELETE:
            continue  # already reported as a deleted test file
        gone = sorted(removed_by_file[path] - all_added)
        new = added_by_file[path] - all_removed
        net_annotations = max(annotations[path], 0)
        count = len(gone) + net_annotations
        if count == 0:
            continue
        hunks = [h for h in test_hunks if h.file_path == path]
        evidence = (hunk_evidence(hunks[0]),) if hunks else (file_evidence(path),)
        names = f" ({', '.join(gone[:3])}{'…' if len(gone) > 3 else ''})" if gone else ""
        if len(new) >= len(gone) and gone and not net_annotations:
            out.append(
                _finding(
                    f"tests:renamed:{path}",
                    Severity.MEDIUM,
                    60,
                    evidence,
                    f"Tests were renamed or replaced in {path}{names}",
                    "Some tests disappeared and new ones appeared; make sure the new tests "
                    "check the same things.",
                    f"The replaced tests in {path} still check the same behavior",
                )
            )
            continue
        out.append(
            _finding(
                f"tests:removed:{path}",
                Severity.HIGH,
                85,
                evidence,
                f"{plural(count, 'test was', 'tests were')} removed from {path}{names}",
                "Removing tests means mistakes in this change are less likely to be caught.",
                f"Removing tests from {path} was really intended",
                critical=True,
            )
        )
    return out


def _fewer_checks(test_hunks: list[Hunk], already: set[str]) -> list[Finding]:
    by_file: dict[str, list[Hunk]] = defaultdict(list)
    for hunk in test_hunks:
        by_file[hunk.file_path].append(hunk)
    out: list[Finding] = []
    for path, hunks in by_file.items():
        if path in already:
            continue
        removed = sum(bool(_ASSERTION.search(without_strings(x))) for h in hunks for x in h.removed)
        added = sum(bool(_ASSERTION.search(without_strings(x))) for h in hunks for x in h.added)
        if removed - added <= 0:
            continue
        drop = removed - added
        target = next((h for h in hunks if any(_ASSERTION.search(x) for x in h.removed)), hunks[0])
        out.append(
            _finding(
                f"tests:fewer_checks:{path}",
                Severity.MEDIUM,
                80,
                (hunk_evidence(target),),
                f"Tests in {path} check less than before ({plural(drop, 'check')} removed)",
                "Checks inside tests were removed, so the tests may now pass even when the code "
                "is wrong.",
                f"The removed checks in {path} weren't needed",
            )
        )
    return out


def _changed_expectations(ctx: DetectorContext, test_hunks: list[Hunk]) -> list[Finding]:
    code_changed = any(
        not is_test_file(h.file_path) and is_code_file(h.file_path) and (h.added or h.removed)
        for h in ctx.changes.hunks
    )
    if not code_changed:
        return []
    out: list[Finding] = []
    for hunk in test_hunks:
        removed = [r for r in hunk.removed if _ASSERTION.search(r)]
        idxs: list[int] = []
        for i, added in enumerate(hunk.added):
            if not _ASSERTION.search(added):
                continue
            shape = skeleton(added)
            if any(skeleton(r) == shape and r.strip() != added.strip() for r in removed):
                idxs.append(i)
        if not idxs:
            continue
        ev = hunk_evidence(hunk, idxs)
        where = f"{hunk.file_path}:{ev.start_line}"
        out.append(
            _finding(
                f"tests:expected_changed:{hunk.id}",
                Severity.HIGH,
                75,
                (ev,),
                f"A test's expected result was changed to match the new code ({where})",
                "The test now expects a different value, in the same change that edits the code "
                "it tests. That's sometimes right, but it's also how a failing test gets "
                "'fixed' without fixing the code.",
                f"The new expected value in {where} is really correct (not just copied from what "
                "the code now returns)",
            )
        )
    return out


def _is_conditional_skip(line: str) -> bool:
    return bool(_CONDITIONAL_SKIP.search(without_strings(line)))


def _is_hard_skip(line: str) -> bool:
    """Skipped always (critical), as opposed to skipped only under a condition."""
    return bool(_SKIP.search(without_strings(line))) and not _is_conditional_skip(line)


def _markers(test_hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in test_hunks:
        before_skip = sum(_is_hard_skip(x) for x in hunk.removed)
        before_cond = sum(_is_conditional_skip(x) for x in hunk.removed)
        before_only = sum(bool(_ONLY.search(without_strings(x))) for x in hunk.removed)
        skip_idx = [i for i, x in enumerate(hunk.added) if _is_hard_skip(x)]
        cond_idx = [i for i, x in enumerate(hunk.added) if _is_conditional_skip(x)]
        only_idx = [i for i, x in enumerate(hunk.added) if _ONLY.search(without_strings(x))]
        if len(skip_idx) > before_skip:
            ev = hunk_evidence(hunk, skip_idx)
            out.append(
                _finding(
                    f"tests:skipped:{hunk.id}",
                    Severity.HIGH,
                    90,
                    (ev,),
                    f"A test was switched off ({hunk.file_path}:{ev.start_line})",
                    "Skipped or disabled tests don't run, so they can't catch problems.",
                    f"Skipping the test in {hunk.file_path} is intended and temporary",
                    critical=True,
                )
            )
        if len(cond_idx) > before_cond:
            ev = hunk_evidence(hunk, cond_idx)
            out.append(
                _finding(
                    f"tests:conditional_skip:{hunk.id}",
                    Severity.MEDIUM,
                    70,
                    (ev,),
                    f"A test now runs only in some situations ({hunk.file_path}:{ev.start_line})",
                    "The test is skipped under a condition (for example on one operating system), "
                    "so it won't catch problems there.",
                    f"The condition for skipping the test in {hunk.file_path} is right",
                )
            )
        if len(only_idx) > before_only:
            ev = hunk_evidence(hunk, only_idx)
            out.append(
                _finding(
                    f"tests:only:{hunk.id}",
                    Severity.HIGH,
                    90,
                    (ev,),
                    f"Only one test is set to run, so the others are skipped "
                    f"({hunk.file_path}:{ev.start_line})",
                    "Marking a test as 'only' silently stops every other test in that file or "
                    "suite from running.",
                    f"The 'only' marker in {hunk.file_path} is removed before merging",
                    critical=True,
                )
            )
    return out


def _snapshots(ctx: DetectorContext) -> list[Finding]:
    snaps = [
        f
        for f in ctx.changes.files
        if any_match(SNAPSHOT_GLOBS, f.path) and f.change_kind is not ChangeKind.ADD
    ]
    lines = sum(f.added_lines + f.removed_lines for f in snaps)
    if len(snaps) < 3 and lines < 50:
        return []
    return [
        _finding(
            "tests:snapshots",
            Severity.MEDIUM,
            70,
            tuple(file_evidence(f.path) for f in snaps[:20]),
            f"{plural(len(snaps), 'saved test snapshot was', 'saved test snapshots were')} "
            "updated in bulk",
            "Snapshot tests compare against saved output; updating many at once can hide a "
            "real change in what the code produces.",
            "The updated snapshots show the output you actually want",
        )
    ]


def _loose_mocks_and_timeouts(test_hunks: list[Hunk]) -> list[Finding]:
    out: list[Finding] = []
    for hunk in test_hunks:
        before = sum(bool(_LOOSE_MOCK.search(without_strings(x))) for x in hunk.removed)
        idx = [i for i, x in enumerate(hunk.added) if _LOOSE_MOCK.search(without_strings(x))]
        if hunk.removed and len(idx) > before:
            ev = hunk_evidence(hunk, idx)
            out.append(
                _finding(
                    f"tests:loose_mock:{hunk.id}",
                    Severity.MEDIUM,
                    60,
                    (ev,),
                    f"A test now accepts any value where it used to check a specific one "
                    f"({hunk.file_path}:{ev.start_line})",
                    "Matching 'anything' makes the test pass even when the code passes the "
                    "wrong value.",
                    f"Accepting any value in {hunk.file_path} is good enough",
                )
            )
        old = [float(m.group(1)) for x in hunk.removed for m in [_TIMEOUT.search(x)] if m]
        new_idx = [i for i, x in enumerate(hunk.added) if _TIMEOUT.search(x)]
        new = [float(m.group(1)) for i in new_idx for m in [_TIMEOUT.search(hunk.added[i])] if m]
        if old and new and max(new) > max(old):
            ev = hunk_evidence(hunk, new_idx)
            out.append(
                _finding(
                    f"tests:timeout:{hunk.id}",
                    Severity.LOW,
                    70,
                    (ev,),
                    f"A test's time limit was raised ({hunk.file_path}:{ev.start_line})",
                    "Raising time limits can hide code that has become slow or stuck.",
                    None,
                )
            )
    return out


def detect(ctx: DetectorContext) -> list[Finding]:
    test_hunks = [h for h in ctx.changes.hunks if is_test_file(h.file_path)]
    removal = _deleted_test_files(ctx) + _removed_tests(ctx, test_hunks)
    # A deleted or removed test already explains its missing checks; don't report twice.
    already = {e.file_path for f in removal for e in f.evidence}
    return (
        removal
        + _fewer_checks(test_hunks, already)
        + _changed_expectations(ctx, test_hunks)
        + _markers(test_hunks)
        + _snapshots(ctx)
        + _loose_mocks_and_timeouts(test_hunks)
    )
