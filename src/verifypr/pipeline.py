"""Run a check end to end. Public interface: ``CheckRequest``, ``run_check(request)``.

Read-only: loads config/contract, collects changes via read-only git, runs detectors,
applies allow rules, and builds the ``Report``. Never writes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from verifypr.analysis.changes import ChangeSet
from verifypr.config import Config, load_config
from verifypr.detectors.base import DetectorContext
from verifypr.detectors.registry import run_detectors
from verifypr.intent.contract import load_review_contract
from verifypr.models import InputLevel, Report
from verifypr.sources.local_git import CompareOptions, LocalGit
from verifypr.verdict import apply_allow_rules, decide


@dataclass(frozen=True)
class CheckRequest:
    repo: Path = field(default_factory=Path.cwd)
    compare: CompareOptions = field(default_factory=CompareOptions)
    contract_path: Path | None = None


def _prepare(request: CheckRequest) -> tuple[LocalGit, Config, CompareOptions]:
    git = LocalGit.open(request.repo)
    config = load_config(git.root)
    compare = request.compare
    if compare.base is None and config.base:
        compare = replace(compare, base=config.base)
    return git, config, compare


def collect_changes(request: CheckRequest) -> ChangeSet:
    git, _config, compare = _prepare(request)
    return git.collect(compare)


def run_check(request: CheckRequest) -> tuple[Report, ChangeSet]:
    git, config, compare = _prepare(request)
    contract = load_review_contract(request.contract_path) if request.contract_path else None
    changes = git.collect(compare)

    findings = run_detectors(DetectorContext(changes=changes, config=config, contract=contract))
    kept, allowed = apply_allow_rules(findings, config.allow)
    input_level = InputLevel.DESCRIBE if contract else InputLevel.AUTO
    tolerances = contract.tolerances if contract else config.tolerances
    verdict, attention = decide(kept, tolerances, input_level)
    report = Report(
        verdict=verdict,
        input_level=input_level,
        compared=changes.compared,
        base=changes.base_label,
        findings=tuple(kept),
        notes=changes.notes,
        ai_used=False,
        file_count=len(changes.files),
        allowed_count=allowed,
        attention_count=attention,
    )
    return report, changes
