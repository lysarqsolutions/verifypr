"""Phase 2 fixtures: U9 (tests), U10 (safety checks), basic U17/U18/U20."""

from __future__ import annotations

from tests.detector_helpers import changeset, ctx, modify_diff, new_file_diff
from verifypr.detectors.behavior import basic_watch
from verifypr.detectors.impact import shared_files
from verifypr.detectors.integrity import guardrails, tests
from verifypr.models import Finding, Severity


def _ids(findings: list[Finding]) -> list[str]:
    return [f.id.split(":")[0] + ":" + f.id.split(":")[1] for f in findings]


def _deleted(path: str, text: str) -> str:
    lines = text.splitlines()
    body = "".join(f"-{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\ndeleted file mode 100644\n--- a/{path}\n+++ /dev/null\n"
        f"@@ -1,{len(lines)} +0,0 @@\n{body}"
    )


# ---- U9: tests --------------------------------------------------------------------------
def test_u9_deleted_test_file_is_critical() -> None:
    [finding] = tests.detect(
        ctx(changeset(_deleted("tests/test_a.py", "def test_x():\n    assert 1\n")))
    )
    assert finding.problem_id == "U9"
    assert finding.critical
    assert finding.title == "A test file was deleted: tests/test_a.py"


def test_u9_removed_test_cases() -> None:
    old = "def test_a():\n    assert f() == 1\n\ndef test_b():\n    assert g() == 2\n"
    new = "def test_a():\n    assert f() == 1\n"
    findings = tests.detect(ctx(changeset(modify_diff("tests/test_m.py", old, new))))
    removed = next(f for f in findings if f.id.startswith("tests:removed"))
    assert "1 test was removed" in removed.title
    assert "test_b" in removed.title
    assert removed.critical


def test_u9_renamed_test_is_not_critical() -> None:
    old = "def test_old():\n    assert f() == 1\n"
    new = "def test_new():\n    assert f() == 1\n"
    findings = tests.detect(ctx(changeset(modify_diff("tests/test_m.py", old, new))))
    assert [f.id.split(":")[1] for f in findings] == ["renamed"]
    assert not findings[0].critical


def test_u9_fewer_checks() -> None:
    old = "def test_a():\n    assert f() == 1\n    assert g() == 2\n"
    new = "def test_a():\n    assert f() == 1\n"
    findings = tests.detect(ctx(changeset(modify_diff("tests/test_m.py", old, new))))
    assert any(f.id.startswith("tests:fewer_checks") for f in findings)


def test_u9_expected_value_changed_with_code() -> None:
    diff = modify_diff(
        "src/orders.py", "    return a + b\n", "    return a + b + 1\n"
    ) + modify_diff(
        "tests/test_orders.py", "    assert total(2, 3) == 5\n", "    assert total(2, 3) == 6\n"
    )
    findings = tests.detect(ctx(changeset(diff)))
    [finding] = [f for f in findings if f.id.startswith("tests:expected_changed")]
    assert finding.severity is Severity.HIGH
    assert finding.title == (
        "A test's expected result was changed to match the new code (tests/test_orders.py:1)"
    )


def test_u9_expected_value_alone_is_not_flagged() -> None:
    diff = modify_diff(
        "tests/test_orders.py", "    assert total(2, 3) == 5\n", "    assert total(2, 3) == 6\n"
    )
    assert not [f for f in tests.detect(ctx(changeset(diff))) if "expected" in f.id]


def test_u9_skip_and_only_markers() -> None:
    py = modify_diff("tests/test_a.py", "def test_a():\n", "@pytest.mark.skip\ndef test_a():\n")
    js = modify_diff("src/a.test.ts", "it('works', () => {\n", "it.only('works', () => {\n")
    kinds = sorted(f.id.split(":")[1] for f in tests.detect(ctx(changeset(py + js))))
    assert kinds == ["only", "skipped"]


def test_u9_snapshots_loose_mocks_and_timeouts() -> None:
    snaps = "".join(
        modify_diff(f"src/__snapshots__/c{i}.test.tsx.snap", "a\n", "b\n") for i in range(3)
    )
    mock = modify_diff(
        "tests/test_api.py",
        "    m.assert_called_with(42)\n",
        "    m.assert_called_with(mock.ANY)\n",
    )
    timeout = modify_diff("src/a.test.js", "jest.setTimeout(5000)\n", "jest.setTimeout(60000)\n")
    kinds = {f.id.split(":")[1] for f in tests.detect(ctx(changeset(snaps + mock + timeout)))}
    assert {"snapshots", "loose_mock", "timeout"} <= kinds


# ---- U10: safety checks -----------------------------------------------------------------
def test_u10_suppression_comments() -> None:
    diff = modify_diff(
        "src/app.ts", "const x: number = y;\n", "// @ts-ignore\nconst x: number = y;\n"
    )
    [finding] = guardrails.detect(ctx(changeset(diff)))
    assert finding.problem_id == "U10"
    assert finding.severity is Severity.HIGH
    assert finding.title == "Code checks were switched off in src/app.ts (1 new @ts-ignore)"


def test_u10_existing_suppression_moved_is_not_new() -> None:
    diff = modify_diff("src/a.py", "x = f()  # type: ignore\n", "x = g()  # type: ignore\n")
    assert guardrails.detect(ctx(changeset(diff))) == []


def test_u10_coverage_lowered_and_strict_off() -> None:
    cov = modify_diff("pyproject.toml", "fail_under = 90\n", "fail_under = 60\n")
    strict = modify_diff("tsconfig.json", '    "strict": true,\n', '    "strict": false,\n')
    kinds = {f.id.split(":")[1] for f in guardrails.detect(ctx(changeset(cov + strict)))}
    assert {"coverage", "strict"} <= kinds


def test_u10_ci_step_removed_and_never_fail() -> None:
    removed = modify_diff(
        ".github/workflows/ci.yml",
        "      - run: npm ci\n      - run: npm test\n",
        "      - run: npm ci\n",
    )
    never = modify_diff(
        ".github/workflows/lint.yml",
        "      - run: npm run lint\n",
        "      - run: npm run lint || true\n",
    )
    findings = guardrails.detect(ctx(changeset(removed + never)))
    kinds = {f.id.split(":")[1] for f in findings}
    assert {"ci_removed", "never_fail"} <= kinds
    assert all(f.critical for f in findings if f.id.split(":")[1] in {"ci_removed", "never_fail"})


def test_u10_ci_step_commented_out() -> None:
    diff = modify_diff(
        ".github/workflows/ci.yml", "      - run: pytest\n", "      # - run: pytest\n"
    )
    [finding] = guardrails.detect(ctx(changeset(diff)))
    assert "commented out" in finding.title


def test_u10_lint_rules_and_precommit_hooks() -> None:
    lint = modify_diff(
        ".eslintrc.json", '  "rules": {\n', '  "rules": {\n    "no-unused-vars": "off",\n'
    )
    hooks = modify_diff(".pre-commit-config.yaml", "  - id: ruff\n  - id: mypy\n", "  - id: ruff\n")
    kinds = {f.id.split(":")[1] for f in guardrails.detect(ctx(changeset(lint + hooks)))}
    assert {"lint_config", "hooks"} <= kinds


# ---- basic U18 / U17 --------------------------------------------------------------------
def test_u18_role_check_narrowed() -> None:
    diff = modify_diff(
        "src/menu.ts",
        '  { label: "Reports", roles: ["admin", "manager"] },\n',
        '  { label: "Reports", roles: ["admin"] },\n',
    )
    [finding] = [f for f in basic_watch.detect(ctx(changeset(diff))) if f.problem_id == "U18"]
    assert finding.title == "Access rules changed in src/menu.ts:1 — check who can still see this"
    assert finding.why.startswith("Basic check: ")


def test_u18_removed_login_requirement_is_critical() -> None:
    diff = modify_diff(
        "app/views.py", "@login_required\ndef export(request):\n", "def export(request):\n"
    )
    [finding] = basic_watch.detect(ctx(changeset(diff)))
    assert finding.critical
    assert "login or permission check was removed" in finding.title


def test_u17_button_removed_and_route_removed() -> None:
    button = modify_diff(
        "src/ExportBar.tsx",
        "  <div>\n    <button onClick={exportCsv}>Export</button>\n  </div>\n",
        "  <div>\n  </div>\n",
    )
    route = modify_diff(
        "src/routes.ts",
        "  { path: '/export', component: Export },\n  { path: '/home', component: Home },\n",
        "  { path: '/home', component: Home },\n",
    )
    findings = [
        f for f in basic_watch.detect(ctx(changeset(button + route))) if f.problem_id == "U17"
    ]
    titles = {f.title for f in findings}
    assert "A button or link was removed: Export" in titles
    assert "A page was removed from the app's routes: /export" in titles


def test_u17_button_now_conditional_and_menu_item_removed() -> None:
    cond = modify_diff(
        "src/Toolbar.tsx",
        "    <button onClick={exportCsv}>Export</button>\n",
        "    {isAdmin && <button onClick={exportCsv}>Export</button>}\n",
    )
    menu = modify_diff(
        "src/nav/SideMenu.ts",
        "  { label: 'Reports' },\n  { label: 'Home' },\n",
        "  { label: 'Home' },\n",
    )
    titles = {f.title for f in basic_watch.detect(ctx(changeset(cond + menu)))}
    assert "A button or link is now only shown sometimes: Export" in titles
    assert "A menu item was removed: Reports" in titles


def test_u17_moved_button_is_not_removed() -> None:
    diff = modify_diff("src/A.tsx", "<button>Save</button>\n", "") + new_file_diff(
        "src/B.tsx", "<button>Save</button>\n"
    )
    assert not [f for f in basic_watch.detect(ctx(changeset(diff))) if f.problem_id == "U17"]


# ---- basic U20 --------------------------------------------------------------------------
def _repo_with_users(*users: str) -> dict[str, str]:
    repo = {"src/shared/CustomerForm.tsx": "export function CustomerForm() {}\n"}
    for user in users:
        repo[user] = "import { CustomerForm } from '../../shared/CustomerForm';\n"
    return repo


def test_u20_shared_file_used_by_three_areas() -> None:
    repo = _repo_with_users("apps/admin/Page.tsx", "apps/sales/Page.tsx", "apps/supplier/Page.tsx")
    diff = modify_diff(
        "src/shared/CustomerForm.tsx",
        "export function CustomerForm() {}\n",
        "export function CustomerForm(props) {}\n",
    )
    [finding] = shared_files.detect(ctx(changeset(diff, new=repo)))
    assert finding.problem_id == "U20"
    assert finding.title == (
        "A shared file was changed: CustomerForm.tsx is used in 3 other areas "
        "(admin, sales, supplier)"
    )
    assert "approximate" in finding.why


def test_u20_single_user_or_formatting_only_is_quiet() -> None:
    repo = _repo_with_users("apps/admin/Page.tsx")
    real = modify_diff("src/shared/CustomerForm.tsx", "a\n", "b\n")
    assert shared_files.detect(ctx(changeset(real, new=repo))) == []
    many = _repo_with_users("apps/admin/P.tsx", "apps/sales/P.tsx")
    fmt = modify_diff("src/shared/CustomerForm.tsx", "a\nb\n", "a\r\nb\r\n")
    assert shared_files.detect(ctx(changeset(fmt, new=many))) == []


# ---- dogfooding regressions: text in strings, comments and docstrings ------------------
def test_patterns_inside_strings_and_prose_are_ignored() -> None:
    code = new_file_diff(
        "src/rules.py",
        'PATTERN = re.compile(r"@ts-ignore")\n'
        "EXAMPLE = \"it.only('x')  # type: ignore\"\n"
        "- access rules: role/permission checks, auth guards, feature flags.\n",
    )
    test = new_file_diff(
        "tests/test_x.py",
        'js = modify_diff("a.test.ts", "it(\'a\')", "it.only(\'a\')")\n'
        'py = modify_diff("t.py", "", "@pytest.mark.skip")\n',
    )
    findings = (
        guardrails.detect(ctx(changeset(code + test)))
        + tests.detect(ctx(changeset(code + test)))
        + basic_watch.detect(ctx(changeset(code + test)))
    )
    assert findings == []


def test_real_comment_suppressions_still_count() -> None:
    diff = new_file_diff("src/a.py", "x = f()  # type: ignore\n") + new_file_diff(
        "src/B.java", '@SuppressWarnings("unchecked")\nclass B {}\n'
    )
    assert len(guardrails.detect(ctx(changeset(diff)))) == 2


def test_docstring_lines_are_prose() -> None:
    diff = new_file_diff(
        "src/doc.py",
        'def f():\n    """Ignore ``// @ts-ignore`` and roles: [admin] here.\n'
        '    More text (with parens) about permissions."""\n    return 1\n',
    )
    assert guardrails.detect(ctx(changeset(diff))) == []
    assert basic_watch.detect(ctx(changeset(diff))) == []
