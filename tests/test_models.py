from __future__ import annotations

import pytest
from pydantic import ValidationError

from verifypr.models import (
    ChangeKind,
    Evidence,
    Finding,
    Hunk,
    Report,
    Severity,
    Verdict,
)


def _finding(fid: str, severity: Severity, confidence: int) -> Finding:
    return Finding(
        id=fid,
        problem_id="U9",
        category="test_integrity",
        severity=severity,
        confidence=confidence,
        evidence=(Evidence(file_path="tests/test_orders.py", start_line=42, end_line=42),),
        title="A test was changed to pass instead of the code being fixed",
        why="The expected value changed in the same change as the code it tests.",
    )


def test_hunk_round_trips_through_json() -> None:
    hunk = Hunk(
        id="app.py#1",
        file_path="app.py",
        change_kind=ChangeKind.MODIFY,
        old_start=1,
        old_lines=2,
        new_start=1,
        new_lines=6,
        added=("def avg(a, b):",),
    )
    assert Hunk.model_validate_json(hunk.model_dump_json()) == hunk


def test_evidence_rejects_reversed_range() -> None:
    with pytest.raises(ValidationError, match="end_line"):
        Evidence(file_path="a.py", start_line=10, end_line=3)


def test_finding_requires_evidence_and_valid_problem_id() -> None:
    with pytest.raises(ValidationError):
        Finding(
            id="f1",
            problem_id="U9",
            category="x",
            severity=Severity.LOW,
            confidence=50,
            evidence=(),
            title="t",
            why="w",
        )
    valid = _finding("f1", Severity.LOW, 50).model_dump()
    with pytest.raises(ValidationError, match="problem_id"):
        Finding.model_validate({**valid, "problem_id": "X1"})


@pytest.mark.parametrize("confidence", [-1, 101])
def test_finding_confidence_bounds(confidence: int) -> None:
    with pytest.raises(ValidationError):
        _finding("f", Severity.LOW, confidence)


def test_top_issues_ranks_by_severity_times_confidence() -> None:
    sure_medium = _finding("a", Severity.MEDIUM, 95)  # 190
    unsure_high = _finding("b", Severity.HIGH, 42)  # 126
    sure_high = _finding("c", Severity.HIGH, 90)  # 270
    minor = _finding("d", Severity.LOW, 100)  # 100
    report = Report(
        verdict=Verdict.WARN,
        compared="Your branch compared with main",
        findings=(unsure_high, minor, sure_medium, sure_high),
    )
    assert [f.id for f in report.top_issues()] == ["c", "a", "b"]


def test_report_json_has_schema_version() -> None:
    report = Report(verdict=Verdict.PASS, compared="Your branch compared with main")
    assert '"schema_version":"1"' in report.model_dump_json()
