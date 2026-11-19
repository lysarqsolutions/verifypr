"""Regression tests from the Phase 2 review: each example is a legitimate change that
used to raise a false alarm (three of them wrongly blocked merging)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.detector_helpers import changeset, ctx, modify_diff, new_file_diff
from tests.gitrepo import Repo
from verifypr.detectors.behavior import basic_watch
from verifypr.detectors.impact import shared_files
from verifypr.detectors.impact.shared_files import import_specs, refers_to
from verifypr.detectors.integrity import guardrails, tests
from verifypr.models import Severity
from verifypr.sources.local_git import CompareOptions, LocalGit


# ---- no longer blocking -----------------------------------------------------------------
def test_conditional_skip_is_worth_a_look_not_serious() -> None:
    diff = modify_diff(
        "tests/test_a.py",
        "def test_a():\n",
        '@pytest.mark.skipif(sys.platform == "win32", reason="posix only")\ndef test_a():\n',
    )
    [finding] = tests.detect(ctx(changeset(diff)))
    assert finding.id.startswith("tests:conditional_skip")
    assert finding.severity is Severity.MEDIUM
    assert not finding.critical
    assert finding.title == "A test now runs only in some situations (tests/test_a.py:1)"


def test_unconditional_skip_is_still_serious() -> None:
    diff = modify_diff("tests/test_a.py", "def test_a():\n", "@pytest.mark.skip\ndef test_a():\n")
    [finding] = tests.detect(ctx(changeset(diff)))
    assert finding.critical


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        (".github/workflows/ci.yml", "      - run: docker rm -f db\n",
         "      - run: docker rm -f db || true\n"),
        ("scripts/clean.sh", "rm -f build.log\n", "rm -f build.log || true\n"),
    ],
)  # fmt: skip
def test_cleanup_or_true_is_fine(path: str, old: str, new: str) -> None:
    assert guardrails.detect(ctx(changeset(modify_diff(path, old, new)))) == []


def test_check_or_true_is_flagged_and_serious_only_in_ci() -> None:
    ci = modify_diff(
        ".github/workflows/ci.yml", "      - run: pytest\n", "      - run: pytest || true\n"
    )
    script = modify_diff("scripts/check.sh", "npm run lint\n", "npm run lint || true\n")
    findings = {f.evidence[0].file_path: f for f in guardrails.detect(ctx(changeset(ci + script)))}
    assert findings[".github/workflows/ci.yml"].critical
    assert not findings["scripts/check.sh"].critical
    assert findings["scripts/check.sh"].severity is Severity.HIGH


def test_continue_on_error_step_still_serious() -> None:
    diff = modify_diff(
        ".github/workflows/ci.yml",
        "      - run: npm test\n",
        "      - run: npm test\n        continue-on-error: true\n",
    )
    [finding] = guardrails.detect(ctx(changeset(diff)))
    assert finding.critical


# ---- config-only checks -----------------------------------------------------------------
def test_packaging_exclude_in_pyproject_is_not_a_lint_change() -> None:
    old = "[tool.hatch.build]\n"
    new = '[tool.hatch.build]\nexclude = ["docs/"]\n'
    diff = modify_diff("pyproject.toml", old, new)
    assert guardrails.detect(ctx(changeset(diff, new={"pyproject.toml": new}))) == []


def test_ignore_in_ruff_section_of_pyproject_is_flagged() -> None:
    old = "[tool.ruff.lint]\n"
    new = '[tool.ruff.lint]\nignore = ["E501"]\n'
    diff = modify_diff("pyproject.toml", old, new)
    [finding] = guardrails.detect(ctx(changeset(diff, new={"pyproject.toml": new})))
    assert finding.id.startswith("guardrails:lint_config")


def test_editorconfig_is_not_a_lint_config() -> None:
    diff = modify_diff(".editorconfig", "[*]\n", "[*]\ntrim_trailing_whitespace = false\n")
    assert guardrails.detect(ctx(changeset(diff))) == []


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        ("src/report.py", "    lines = 80\n", "    lines = 60\n"),
        ("src/models/user.js", "  strict: true,\n", "  strict: false,\n"),
    ],
)
def test_coverage_and_strict_only_in_config_files(path: str, old: str, new: str) -> None:
    assert guardrails.detect(ctx(changeset(modify_diff(path, old, new)))) == []


def test_coverage_in_jest_config_still_flagged() -> None:
    diff = modify_diff("jest.config.js", "      lines: 90,\n", "      lines: 70,\n")
    [finding] = guardrails.detect(ctx(changeset(diff)))
    assert finding.id.startswith("guardrails:coverage")


# ---- behavior watch ---------------------------------------------------------------------
def test_aria_role_is_not_an_access_rule() -> None:
    diff = modify_diff(
        "src/Card.tsx",
        '    <div role="button" onClick={open}>\n',
        '    <div role="link" onClick={open}>\n',
    )
    assert basic_watch.detect(ctx(changeset(diff))) == []


def test_quoted_roles_key_still_counts_but_regex_text_does_not() -> None:
    json_like = modify_diff(
        "src/config/menu.ts", '  { "roles": ["admin", "sales"] },\n', '  { "roles": ["admin"] },\n'
    )
    assert [f.problem_id for f in basic_watch.detect(ctx(changeset(json_like)))] == ["U18"]
    regex_line = new_file_diff(
        "src/rules.py", 'ARIA = re.compile(r"""(?<=\\s)role=(?:"[^"]*")""")\n'
    )
    assert basic_watch.detect(ctx(changeset(regex_line))) == []


def test_role_assignment_in_code_is_still_an_access_rule() -> None:
    diff = modify_diff("src/users.py", '    role = "admin"\n', '    role = "viewer"\n')
    [finding] = basic_watch.detect(ctx(changeset(diff)))
    assert finding.problem_id == "U18"


def test_non_route_path_option_is_not_a_page() -> None:
    diff = modify_diff("src/server/logger.js", "  { path: './logs/app.log', level: 'info' },\n", "")
    assert basic_watch.detect(ctx(changeset(diff))) == []


def test_jsx_route_outside_route_file_still_counts() -> None:
    diff = modify_diff("src/Shell.tsx", '      <Route path="/export" element={<Export />} />\n', "")
    titles = [f.title for f in basic_watch.detect(ctx(changeset(diff)))]
    assert "A page was removed from the app's routes: /export" in titles


def test_expected_value_with_only_readme_change_is_quiet() -> None:
    diff = modify_diff("README.md", "old\n", "new\n") + modify_diff(
        "tests/test_o.py", "    assert f() == 1\n", "    assert f() == 2\n"
    )
    assert tests.detect(ctx(changeset(diff))) == []


# ---- shared files: resolve imports to the real file -------------------------------------
@pytest.mark.parametrize(
    ("spec", "importer", "target", "expected"),
    [
        ("./utils", "apps/sales/Page.tsx", "apps/admin/utils.ts", False),
        ("../admin/utils", "apps/sales/Page.tsx", "apps/admin/utils.ts", True),
        ("@/shared/CustomerForm", "apps/sales/Page.tsx", "src/shared/CustomerForm.tsx", True),
        ("@/other/CustomerForm", "apps/sales/Page.tsx", "src/shared/CustomerForm.tsx", False),
        ("./components/Button", "src/App.tsx", "src/components/Button/index.tsx", True),
        ("src.orders", "api/views.py", "src/orders.py", True),
        (".orders", "src/api.py", "src/orders.py", True),
        ("..orders", "src/api/views.py", "src/orders.py", True),
    ],
)  # fmt: skip
def test_refers_to(spec: str, importer: str, target: str, expected: bool) -> None:
    assert refers_to(spec, importer, target) is expected


def test_import_specs() -> None:
    assert import_specs("from src.shop import orders, cart") == [
        "src.shop", "src.shop.orders", "src.shop.cart"
    ]  # fmt: skip
    assert import_specs("import os, json") == ["os", "json"]
    assert import_specs("const a = require('../lib/a')") == ["../lib/a"]


def test_same_file_name_in_other_areas_is_not_shared() -> None:
    repo = {
        "apps/admin/utils.ts": "export const a = 1\n",
        "apps/sales/Page.tsx": "import { x } from './utils';\n",
        "apps/supplier/Page.tsx": "import { y } from './utils';\n",
        "apps/billing/Page.tsx": "import { z } from '../billing/utils';\n",
    }
    diff = modify_diff("apps/admin/utils.ts", "export const a = 1\n", "export const a = 2\n")
    assert shared_files.detect(ctx(changeset(diff, new=repo))) == []


# ---- speed: one git process for many files ----------------------------------------------
def test_committed_only_reads_files_in_one_git_process(
    repo_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = Repo(repo_dir)
    for i in range(40):
        repo.write(f"src/f{i}.ts", f"import {{ a }} from './shared';\nexport const v{i} = 1;\n")
    repo.write("src/shared.ts", "export const a = 1;\n")
    repo.commit("init")
    repo.branch("feature")
    repo.write("src/shared.ts", "export const a = 2;\n")
    repo.commit("change")

    changes = LocalGit.open(repo_dir).collect(CompareOptions(committed_only=True))
    calls: list[tuple[str, ...]] = []
    original = LocalGit._exec

    def counting(
        cwd: Path, args: tuple[str, ...] | list[str], stdin: bytes | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(tuple(args))
        return original(cwd, args, stdin)

    monkeypatch.setattr(LocalGit, "_exec", staticmethod(counting))
    data = changes.read_many(changes.list_files())
    assert data["src/shared.ts"] == b"export const a = 2;\n"
    assert data["src/f7.ts"] is not None
    cat_calls = [c for c in calls if c and c[0] == "cat-file"]
    assert len(cat_calls) == 1
    missing = changes.read_many(["src/nope.ts"])
    assert missing == {"src/nope.ts": None}


def test_unknown_files_in_batch_are_none(repo_dir: Path) -> None:
    repo = Repo(repo_dir)
    repo.write("a.txt", "a\n")
    repo.commit()
    repo.branch("f")
    repo.write("a.txt", "b\n")
    repo.commit()
    changes = LocalGit.open(repo_dir).collect(CompareOptions(head="f"))
    got = changes.read_many(["a.txt", "missing.txt", "a.txt.bak"])
    assert got == {"a.txt": b"b\n", "missing.txt": None, "a.txt.bak": None}


def test_new_file_diff_helper_still_works() -> None:
    assert changeset(new_file_diff("x.py", "a\n")).files[0].path == "x.py"
