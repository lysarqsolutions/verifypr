from __future__ import annotations

import pytest

from verifypr.models import Classification, Severity, Verdict
from verifypr.render.labels import (
    classification_label,
    confidence_label,
    headline,
    severity_label,
)


@pytest.mark.parametrize(
    ("confidence", "label"),
    [
        (100, "Sure"),
        (80, "Sure"),
        (79, "Likely"),
        (50, "Likely"),
        (49, "Not sure"),
        (0, "Not sure"),
    ],
)
def test_confidence_label(confidence: int, label: str) -> None:
    assert confidence_label(confidence) == label


def test_confidence_label_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        confidence_label(101)


def test_severity_and_classification_labels_are_plain_language() -> None:
    assert severity_label(Severity.HIGH) == "Important"
    assert severity_label(Severity.MEDIUM) == "Worth a look"
    assert severity_label(Severity.LOW) == "Minor"
    assert classification_label(Classification.UNINTENDED) == "Not asked for"
    assert classification_label(Classification.UNCLEAR) == "Not sure"
    assert classification_label(Classification.SUPPORTING) == "Needed for the change"
    assert classification_label(Classification.INTENDED) == "Asked for"


def test_headlines() -> None:
    assert headline(Verdict.FAIL, 1, ai_used=False) == "Don't merge yet — 1 serious issue"
    assert headline(Verdict.FAIL, 2, ai_used=True) == "Don't merge yet — 2 serious issues"
    assert headline(Verdict.WARN, 1, ai_used=True) == "1 change needs your attention"
    assert headline(Verdict.WARN, 3, ai_used=False) == "3 changes need your attention"


def test_rules_only_clean_result_never_says_looks_good() -> None:
    assert headline(Verdict.PASS, 0, ai_used=False) == "No problems found by basic checks"
    assert "Looks good" in headline(Verdict.PASS, 0, ai_used=True)


@pytest.mark.parametrize("verdict", [Verdict.WARN, Verdict.FAIL])
def test_warn_or_fail_with_no_issues_is_rejected(verdict: Verdict) -> None:
    with pytest.raises(ValueError, match="needs at least one issue"):
        headline(verdict, 0, ai_used=True)
