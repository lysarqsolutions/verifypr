from __future__ import annotations

from pathlib import Path

import pytest

from verifypr.config import AllowRule, Config, load_config
from verifypr.errors import ConfigError
from verifypr.intent.contract import Tolerance, Tolerances, load_review_contract
from verifypr.models import Evidence, Finding, InputLevel, Severity, Verdict
from verifypr.verdict import apply_allow_rules, decide


def _f(category: str = "x", severity: Severity = Severity.LOW, **kw: bool) -> Finding:
    return Finding(
        id=f"{category}:{severity.value}:{kw}",
        problem_id="U3",
        category=category,
        severity=severity,
        confidence=90,
        evidence=(Evidence(file_path="docs/a.md", start_line=1, end_line=1),),
        title="t",
        why="w",
        **kw,
    )


def test_verdicts() -> None:
    tol = Tolerances(formatting_only_changes=Tolerance.ALLOW)
    auto = InputLevel.AUTO
    assert decide([], tol, auto) == (Verdict.PASS, 0)
    assert decide([_f(severity=Severity.LOW)], tol, auto) == (Verdict.PASS, 0)
    assert decide([_f(severity=Severity.MEDIUM)], tol, auto) == (Verdict.WARN, 1)
    assert decide([_f(critical=True), _f(severity=Severity.HIGH)], tol, auto) == (Verdict.FAIL, 1)
    assert decide([_f("formatting", Severity.HIGH)], tol, auto) == (Verdict.PASS, 0)
    blocking = Tolerances(dependency_changes=Tolerance.BLOCK)
    assert decide([_f("dependencies")], blocking, auto) == (Verdict.FAIL, 1)
    assert decide([_f("formatting")], Tolerances(), auto) == (Verdict.WARN, 1)


def test_inferred_findings_capped_at_warn_in_auto_mode() -> None:
    finding = _f(critical=True, inferred=True)
    assert decide([finding], Tolerances(), InputLevel.AUTO)[0] is Verdict.WARN
    assert decide([finding], Tolerances(), InputLevel.DESCRIBE)[0] is Verdict.FAIL


def test_allow_rules_suppress_and_count() -> None:
    rules = (AllowRule(kind="formatting", paths=("docs/**",)),)
    kept, allowed = apply_allow_rules([_f("formatting"), _f("dependencies")], rules)
    assert allowed == 1
    assert [f.category for f in kept] == ["dependencies"]
    kept, allowed = apply_allow_rules(
        [_f("formatting")], (AllowRule(kind="formatting", paths=("src/**",)),)
    )
    assert allowed == 0


def test_config_loading(tmp_path: Path) -> None:
    assert load_config(tmp_path) == Config()
    (tmp_path / ".verifypr.yml").write_text(
        "base: develop\nallow:\n  - kind: formatting\n    paths: ['docs/**']\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.base == "develop"
    assert config.allow[0].kind == "formatting"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("allow: [", "isn't valid YAML"),
        ("- a\n- b\n", "should contain settings"),
        ("bsae: main\n", "has a problem at 'bsae'"),
    ],
)
def test_config_errors_are_friendly(tmp_path: Path, content: str, message: str) -> None:
    (tmp_path / ".verifypr.yml").write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(tmp_path)


def test_review_contract_loading(tmp_path: Path) -> None:
    path = tmp_path / "contract.yml"
    path.write_text(
        "goal: Add segments\nforbidden:\n  paths: ['auth/**']\n"
        "tolerances:\n  dependency_changes: block\n",
        encoding="utf-8",
    )
    contract = load_review_contract(path)
    assert contract.forbidden.paths == ("auth/**",)
    assert contract.tolerances.dependency_changes is Tolerance.BLOCK
    with pytest.raises(ConfigError, match="Couldn't find"):
        load_review_contract(tmp_path / "missing.yml")
    (tmp_path / "empty.yml").write_text("", encoding="utf-8")
    assert load_review_contract(tmp_path / "empty.yml").goal is None
