"""Detector registry. Public interface: ``DETECTORS``, ``run_detectors(ctx)``.

Detectors can be turned off by name with ``disabled_detectors`` in ``.verifypr.yml``.
"""

from __future__ import annotations

from verifypr.detectors.base import Detector, DetectorContext
from verifypr.detectors.behavior import basic_watch
from verifypr.detectors.hygiene import artifacts, deps, formatting, scope_rules
from verifypr.detectors.impact import shared_files
from verifypr.detectors.integrity import guardrails, tests
from verifypr.models import Finding

DETECTORS: dict[str, Detector] = {
    "scope_rules": scope_rules.detect,
    "formatting": formatting.detect,
    "dependencies": deps.detect,
    "artifacts_and_secrets": artifacts.detect,
    "test_integrity": tests.detect,
    "safety_checks": guardrails.detect,
    "basic_behavior_watch": basic_watch.detect,
    "shared_files": shared_files.detect,
}


def run_detectors(ctx: DetectorContext) -> list[Finding]:
    findings: list[Finding] = []
    for name, detector in DETECTORS.items():
        if name in ctx.config.disabled_detectors:
            continue
        findings.extend(detector(ctx))
    return findings
