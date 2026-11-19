"""Phase 2 checkpoint, end to end through the CLI on a real (synthetic) git repo:
an agent "fixed" a failing test by changing the expected value, added @ts-ignore,
narrowed a menu role check, removed an Export button, and edited a form imported by
three portals."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tests.gitrepo import Repo
from tests.readonly import assert_unchanged, snapshot
from tests.test_cli import BANNED
from verifypr.cli import app

runner = CliRunner()
FORM_IMPORT = "import { CustomerForm } from '../../shared/CustomerForm';\n"


def _repo(path: Path) -> Repo:
    repo = Repo(path)
    repo.write("src/orders.py", "def total(a, b):\n    return a + b\n")
    repo.write(
        "tests/test_orders.py",
        "from src.orders import total\n\n\ndef test_total():\n    assert total(2, 3) == 5\n",
    )
    repo.write("src/app.ts", "export const x: number = load();\n")
    repo.write(
        "src/menu.ts",
        "export const menu = [\n"
        '  { label: "Home", roles: ["admin", "manager", "sales"] },\n'
        '  { label: "Reports", roles: ["admin", "manager"] },\n'
        "];\n",
    )
    repo.write(
        "src/ExportBar.tsx",
        "export function ExportBar() {\n  return (\n    <div>\n"
        "      <button onClick={exportCsv}>Export</button>\n    </div>\n  );\n}\n",
    )
    repo.write(
        "src/shared/CustomerForm.tsx", "export function CustomerForm() {\n  return null;\n}\n"
    )
    for portal in ("admin", "sales", "supplier"):
        repo.write(f"apps/{portal}/Page.tsx", FORM_IMPORT)
    repo.commit("initial")
    repo.branch("agent-fix")
    repo.write("src/orders.py", "def total(a, b):\n    return a + b + 1\n")
    repo.write(
        "tests/test_orders.py",
        "from src.orders import total\n\n\ndef test_total():\n    assert total(2, 3) == 6\n",
    )
    repo.write("src/app.ts", "// @ts-ignore\nexport const x: number = load();\n")
    repo.write(
        "src/menu.ts",
        "export const menu = [\n"
        '  { label: "Home", roles: ["admin", "manager", "sales"] },\n'
        '  { label: "Reports", roles: ["admin"] },\n'
        "];\n",
    )
    repo.write(
        "src/ExportBar.tsx",
        "export function ExportBar() {\n  return (\n    <div>\n    </div>\n  );\n}\n",
    )
    repo.write(
        "src/shared/CustomerForm.tsx",
        "export function CustomerForm(props) {\n  return props.children;\n}\n",
    )
    return repo


def test_phase2_checkpoint(repo_dir: Path) -> None:
    _repo(repo_dir)
    before = snapshot(repo_dir)
    result = runner.invoke(app, ["check", "--repo", str(repo_dir), "--format", "json"])
    assert_unchanged(before, snapshot(repo_dir))
    data = json.loads(result.output)
    by_problem: dict[str, list[dict[str, object]]] = {}
    for finding in data["findings"]:
        assert finding["evidence"], finding
        by_problem.setdefault(str(finding["problem_id"]), []).append(finding)

    [expected] = [f for f in by_problem["U9"] if str(f["id"]).startswith("tests:expected")]
    [ignore] = by_problem["U10"]
    assert expected["severity"] == "high"
    assert ignore["severity"] == "high"
    assert any("Access rules changed in src/menu.ts" in str(f["title"]) for f in by_problem["U18"])
    assert any(f["title"] == "A button or link was removed: Export" for f in by_problem["U17"])
    assert any("used in 3 other areas" in str(f["title"]) for f in by_problem["U20"])
    assert data["verdict"] == "warn"
    assert result.exit_code == 1

    ranked = sorted(
        data["findings"],
        key=lambda f: {"high": 3, "medium": 2, "low": 1}[f["severity"]] * f["confidence"],
        reverse=True,
    )
    assert {ranked[0]["problem_id"], ranked[1]["problem_id"]} == {"U9", "U10"}


def test_phase2_text_output_is_plain(repo_dir: Path) -> None:
    _repo(repo_dir)
    out = runner.invoke(app, ["--repo", str(repo_dir), "--verbose"]).output
    assert out.startswith("⚠ 5 changes need your attention")
    assert "Please check before approving" in out
    assert "Basic check:" in out
    assert not BANNED.search(out), BANNED.search(out)
