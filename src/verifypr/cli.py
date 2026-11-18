"""Command-line entry point.

Public interface: ``app`` (Typer application) and ``main()`` (console script).

Everyday commands: ``verifypr`` (check your changes), ``verifypr --verbose``.
Advanced: ``verifypr check …``, ``verifypr diff``. Nothing here writes to the repo or git.

Exit codes: 0 looks fine, 1 needs attention, 2 don't merge yet, 3 couldn't run.
"""

from __future__ import annotations

import contextlib
import json
import sys
from enum import Enum
from pathlib import Path

import typer

from verifypr import __version__
from verifypr.errors import VerifyPRError
from verifypr.models import ChangeKind, Verdict
from verifypr.pipeline import CheckRequest, collect_changes, run_check
from verifypr.render.markdown import render_markdown
from verifypr.render.text import render_text
from verifypr.sources.local_git import CompareOptions

EXIT_CODES = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.FAIL: 2}
EXIT_ERROR = 3


class OutputFormat(str, Enum):
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"


app = typer.Typer(
    name="verifypr",
    help=(
        "Check that a change did only what was asked, and what to check before approving.\n\n"
        "Everyday use: run `verifypr` in your project folder. "
        "Add `--verbose` to see everything."
    ),
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode=None,
)

RepoOpt = typer.Option(Path("."), "--repo", help="Project folder (default: current folder).")
BaseOpt = typer.Option(None, "--base", help="Branch to compare with (default: main/master).")
FormatOpt = typer.Option(OutputFormat.TEXT, "--format", help="Output format.")
VerboseOpt = typer.Option(False, "--verbose", "-v", help="Show every finding.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"VerifyPR {__version__}")
        raise typer.Exit()


def _fail(err: VerifyPRError) -> None:
    typer.echo(f"✖ {err.message}", err=True)
    if err.hint:
        typer.echo(f"  {err.hint}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _check(request: CheckRequest, fmt: OutputFormat, verbose: bool) -> None:
    try:
        report, _changes = run_check(request)
    except VerifyPRError as err:
        _fail(err)
        return
    if fmt is OutputFormat.JSON:
        typer.echo(report.model_dump_json(indent=2))
    elif fmt is OutputFormat.MARKDOWN:
        typer.echo(render_markdown(report), nl=False)
    else:
        typer.echo(render_text(report, verbose=verbose), nl=False)
    raise typer.Exit(EXIT_CODES[report.verdict])


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    repo: Path = RepoOpt,
    base: str | None = BaseOpt,
    fmt: OutputFormat = FormatOpt,
    verbose: bool = VerboseOpt,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show the version."
    ),
) -> None:
    """Check your changes (same as `verifypr check`)."""
    if ctx.invoked_subcommand is None:
        _check(CheckRequest(repo=repo, compare=CompareOptions(base=base)), fmt, verbose)


@app.command()
def check(
    repo: Path = RepoOpt,
    base: str | None = BaseOpt,
    head: str | None = typer.Option(
        None, "--head", help="Check this branch/commit instead of your current work."
    ),
    staged: bool = typer.Option(False, "--staged", help="Check only staged changes."),
    committed_only: bool = typer.Option(
        False, "--committed-only", help="Ignore unsaved changes and new files."
    ),
    review_contract: Path | None = typer.Option(
        None, "--review-contract", help="Review Contract file: what this change should do."
    ),
    fmt: OutputFormat = FormatOpt,
    verbose: bool = VerboseOpt,
    no_llm: bool = typer.Option(
        False, "--no-llm", help="Use only rule-based checks (currently always the case)."
    ),
) -> None:
    """Advanced: check changes with extra options."""
    if staged and (head or committed_only):
        _fail(VerifyPRError("--staged can't be combined with --head or --committed-only."))
    compare = CompareOptions(base=base, head=head, staged=staged, committed_only=committed_only)
    _check(CheckRequest(repo=repo, compare=compare, contract_path=review_contract), fmt, verbose)


_KIND_WORDS = {
    ChangeKind.ADD: "added",
    ChangeKind.MODIFY: "changed",
    ChangeKind.DELETE: "deleted",
    ChangeKind.RENAME: "renamed",
    ChangeKind.MOVE: "moved",
    ChangeKind.MODE_CHANGE: "permissions",
    ChangeKind.BINARY: "binary",
    ChangeKind.SUBMODULE: "submodule",
}


@app.command()
def diff(
    repo: Path = RepoOpt,
    base: str | None = BaseOpt,
    staged: bool = typer.Option(False, "--staged", help="Only staged changes."),
    as_json: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Advanced: list what changed, without running any checks."""
    try:
        changes = collect_changes(
            CheckRequest(repo=repo, compare=CompareOptions(base=base, staged=staged))
        )
    except VerifyPRError as err:
        _fail(err)
        return
    if as_json:
        payload = {
            "compared": changes.compared,
            "base": changes.base_label,
            "notes": list(changes.notes),
            "files": [f.model_dump(mode="json") for f in changes.files],
        }
        typer.echo(json.dumps(payload, indent=2))
        return
    added = sum(f.added_lines for f in changes.files)
    removed = sum(f.removed_lines for f in changes.files)
    n = len(changes.files)
    typer.echo(changes.compared)
    for note in changes.notes:
        typer.echo(f"Note: {note}")
    typer.echo(f"{n} {'file' if n == 1 else 'files'} changed (+{added} -{removed} lines)")
    for f in changes.files:
        extra = " (new, not yet added to git)" if f.untracked else ""
        moved = f" (from {f.old_path})" if f.old_path else ""
        typer.echo(
            f"  {_KIND_WORDS[f.change_kind]:<11} {f.path}{moved}  "
            f"+{f.added_lines} -{f.removed_lines}{extra}"
        )


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_output()
    app()
