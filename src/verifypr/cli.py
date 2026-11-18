"""Command-line entry point.

Public interface: ``app`` (Typer application) and ``main()`` (console script).
Phase 0 only provides ``--version`` and a placeholder default action; the real
check arrives in Phase 1. Must never write to the repo or git (CLAUDE.md §1.4).
"""

from __future__ import annotations

import typer

from verifypr import __version__

app = typer.Typer(
    name="verifypr",
    help="Check that a change did only what was asked, and what to check before approving.",
    add_completion=False,
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"VerifyPR {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Running `verifypr` with no arguments will check your changes (coming in Phase 1)."""
    if ctx.invoked_subcommand is None:
        typer.echo("VerifyPR is being set up. Checking changes arrives in the next release.")


def main() -> None:
    app()
