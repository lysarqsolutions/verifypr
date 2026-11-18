"""One or more fixtures per problem ID handled in Phase 1: U1, U3, U4, U6."""

from __future__ import annotations

import json

import pytest

from tests.detector_helpers import changeset, ctx, modify_diff, new_file_diff, untracked
from verifypr.detectors.hygiene import artifacts, deps, formatting, scope_rules
from verifypr.detectors.hygiene.formatting import HunkKind, classify_hunk
from verifypr.intent.contract import IntentContract, PathRules, Tolerance, Tolerances
from verifypr.models import Finding, Severity

FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


# ---- U1: scope rules -------------------------------------------------------------------
def _contract(**tolerances: Tolerance) -> IntentContract:
    return IntentContract(
        goal="Add segments",
        allowed=PathRules(paths=("services/segment/**", "tests/**")),
        forbidden=PathRules(paths=("auth/**",)),
        tolerances=Tolerances(**tolerances),
    )


def test_u1_no_contract_no_scope_findings() -> None:
    assert scope_rules.detect(ctx(changeset(modify_diff("auth/session.py", "a\n", "b\n")))) == []


def test_u1_forbidden_area_is_critical() -> None:
    diff = modify_diff("auth/session.py", "a\n", "b\n") + modify_diff(
        "services/segment/api.py", "a\n", "b\n"
    )
    [finding] = scope_rules.detect(ctx(changeset(diff), _contract()))
    assert finding.problem_id == "U1"
    assert finding.critical
    assert finding.severity is Severity.HIGH
    assert "auth/session.py" in finding.title


def test_u1_outside_allowed_and_new_file_tolerance() -> None:
    diff = modify_diff("billing/invoice.py", "a\n", "b\n") + new_file_diff("billing/new.py", "x\n")
    findings = scope_rules.detect(
        ctx(changeset(diff), _contract(new_files_outside_allowed=Tolerance.BLOCK))
    )
    by_cat = {f.category: f for f in findings}
    assert by_cat["scope"].severity is Severity.MEDIUM
    assert by_cat["scope_new_file"].severity is Severity.HIGH


# ---- U3: formatting / line endings / encoding / imports / permissions -------------------
def _kind(old: str, new: str) -> HunkKind:
    [hunk] = changeset(modify_diff("f.py", old, new)).hunks
    return classify_hunk(hunk)


def test_u3_hunk_classification() -> None:
    assert _kind("a\nb\n", "a\r\nb\r\n") is HunkKind.LINE_ENDINGS
    assert _kind("x = 1\n", "﻿x = 1\n") is HunkKind.BOM
    assert _kind("x=1\n", "x = 1\n") is HunkKind.WHITESPACE
    assert _kind("import os\nimport sys\n", "import sys\nimport os\n") is HunkKind.IMPORT_ORDER
    assert _kind("x = 1\n", "x = 2\n") is HunkKind.REAL


def test_u3_formatting_findings_are_grouped() -> None:
    diff = (
        modify_diff("a.py", "a\nb\n", "a\r\nb\r\n")
        + modify_diff("b.py", "a\nb\n", "a\r\nb\r\n")
        + modify_diff("c.py", "x=1\n", "x = 1\n")
    )
    findings = {f.id: f for f in formatting.detect(ctx(changeset(diff)))}
    assert findings["formatting:line_endings"].title == "Line endings changed in 2 files"
    assert len(findings["formatting:line_endings"].evidence) == 2
    assert findings["formatting:whitespace"].title == "1 file changed only in formatting"
    assert all(f.problem_id == "U3" and f.severity is Severity.LOW for f in findings.values())


def test_u3_mixed_formatting_and_real_changes() -> None:
    diff = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -1 +1 @@\n-x=1\n+x = 1\n@@ -10 +10 @@\n-y = 1\n+y = 2\n"
    )
    [finding] = formatting.detect(ctx(changeset(diff)))
    assert finding.id == "formatting:mixed"


def test_u3_file_made_executable() -> None:
    diff = "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
    [finding] = formatting.detect(ctx(changeset(diff)))
    assert finding.title == "run.sh was made executable"
    assert finding.severity is Severity.MEDIUM
    assert finding.check_item


# ---- U4: dependencies -------------------------------------------------------------------
def _deps(path: str, old: str | None, new: str) -> list[Finding]:
    diff = modify_diff(path, old or "", new) if old is not None else new_file_diff(path, new)
    return deps.detect(
        ctx(changeset(diff, old={path: old} if old is not None else {}, new={path: new}))
    )


def test_u4_npm_added_and_major_bump() -> None:
    old = json.dumps({"dependencies": {"react": "^18.2.0"}})
    new = json.dumps({"dependencies": {"react": "^19.0.0", "left-pad": "1.3.0"}})
    [finding] = _deps("package.json", old, new)
    assert finding.problem_id == "U4"
    assert finding.severity is Severity.MEDIUM
    assert "1 added" in finding.title
    assert "1 updated" in finding.title
    assert "react ^18.2.0 → ^19.0.0" in finding.why
    assert finding.check_item == "The new dependency left-pad is wanted and trusted"


def test_u4_minor_bump_is_minor() -> None:
    [finding] = _deps("requirements.txt", "requests==2.31.0\n", "requests==2.32.0\n")
    assert finding.severity is Severity.LOW


def test_u4_no_dependency_change_no_finding() -> None:
    old = json.dumps({"name": "a", "dependencies": {"x": "1"}})
    new = json.dumps({"name": "b", "dependencies": {"x": "1"}})
    assert _deps("package.json", old, new) == []


@pytest.mark.parametrize(
    ("path", "old", "new", "name"),
    [
        (
            "pyproject.toml",
            '[project]\nname="a"\ndependencies=["httpx>=0.27"]\n',
            '[project]\nname="a"\ndependencies=["httpx>=0.27","rich"]\n',
            "rich",
        ),
        (
            "pyproject.toml",
            '[tool.poetry.dependencies]\npython="^3.10"\n',
            '[tool.poetry.dependencies]\npython="^3.10"\nflask="^3.0"\n',
            "flask",
        ),
        (
            "go.mod",
            "module x\n\ngo 1.22\n",
            "module x\n\nrequire github.com/pkg/errors v0.9.1\n",
            "github.com/pkg/errors",
        ),
        (
            "pom.xml",
            "<project></project>",
            "<project><dependency><groupId>org.acme</groupId><artifactId>lib</artifactId>"
            "<version>1.0</version></dependency></project>",
            "org.acme:lib",
        ),
        (
            "build.gradle",
            "dependencies {\n}\n",
            "dependencies {\n  implementation 'com.acme:core:2.1.0'\n}\n",
            "com.acme:core",
        ),
        (
            "app/App.csproj",
            "<Project></Project>",
            '<Project><ItemGroup><PackageReference Include="Newtonsoft.Json" '
            'Version="13.0.3" /></ItemGroup></Project>',
            "Newtonsoft.Json",
        ),
    ],
)
def test_u4_ecosystems(path: str, old: str, new: str, name: str) -> None:
    [finding] = _deps(path, old, new)
    assert name in finding.why


def test_u4_unreadable_manifest_still_reported() -> None:
    [finding] = _deps("package.json", "{", '{"dependencies": {}}')
    assert finding.confidence == 60
    assert "couldn't read" in finding.why


def test_u4_lockfile_without_manifest_change() -> None:
    diff = modify_diff("web/package-lock.json", '{"v": 1}\n', '{"v": 2}\n')
    [finding] = deps.detect(ctx(changeset(diff)))
    assert finding.id == "deps:lockfile:web/package-lock.json"


def test_u4_lockfile_with_manifest_change_is_not_separate() -> None:
    old = json.dumps({"dependencies": {}})
    new = json.dumps({"dependencies": {"x": "1"}})
    diff = modify_diff("package.json", old, new) + modify_diff("package-lock.json", "a\n", "b\n")
    findings = deps.detect(
        ctx(changeset(diff, old={"package.json": old}, new={"package.json": new}))
    )
    assert [f.id for f in findings] == ["deps:package.json"]


# ---- U6: secrets, env files, artifacts --------------------------------------------------
def test_u6_secret_is_critical_and_redacted() -> None:
    diff = new_file_diff("config/settings.py", f"DEBUG = True\nAWS_KEY = '{FAKE_AWS}'\n")
    [finding] = artifacts.detect(ctx(changeset(diff)))
    assert finding.problem_id == "U6"
    assert finding.critical
    assert finding.title == "An AWS access key was added in config/settings.py"
    assert finding.evidence[0].start_line == 2
    assert FAKE_AWS not in (finding.evidence[0].snippet or "")


def test_u6_generic_password_is_not_critical() -> None:
    [finding] = artifacts.detect(
        ctx(changeset(new_file_diff("db.py", "password = 'hunter2hunter2'\n")))
    )
    assert not finding.critical
    assert finding.severity is Severity.MEDIUM


def test_u6_env_file_added() -> None:
    findings = artifacts.detect(
        ctx(changeset(new_file_diff(".env", "DEBUG=1\n") + new_file_diff(".env.example", "X=\n")))
    )
    assert [f.id for f in findings] == ["env_file:.env"]
    assert findings[0].severity is Severity.HIGH


def test_u6_build_output_junk_and_binaries() -> None:
    files = [
        untracked("dist/app.js"),
        untracked("src/__pycache__/m.cpython-313.pyc", binary=True),
        untracked(".DS_Store", binary=True),
        untracked("tools/helper.exe", binary=True),
        untracked("docs/logo.png", binary=True),
    ]
    findings = {f.id: f for f in artifacts.detect(ctx(changeset(extra_files=files)))}
    assert len(findings["artifacts:build"].evidence) == 2
    assert findings["artifacts:junk"].severity is Severity.LOW
    assert [e.file_path for e in findings["artifacts:binary"].evidence] == ["tools/helper.exe"]
