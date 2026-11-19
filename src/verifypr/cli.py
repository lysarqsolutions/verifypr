"""Command-line entry point.

Public interface: ``app`` (Typer application) and ``main()`` (console script).

Everyday commands: ``verifypr`` (check your changes), ``verifypr --verbose``.
Advanced: ``verifypr check …``, ``explain``, ``diff``, ``key …``, ``intent …``.
Nothing here writes to the repo or git. The only writes are to the tool's own state folder
(your answer to "send code to the AI?", saved Review Contracts) and the OS keychain.

Exit codes: 0 looks fine, 1 needs attention, 2 don't merge yet, 3 couldn't run.
"""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import typer

from verifypr import __version__
from verifypr.errors import VerifyPRError
from verifypr.llm.setup import (
    LLMChoice,
    LLMSettings,
    SendSummary,
    choose_llm,
    store_consent,
    stored_consent,
)
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
DescribeOpt = typer.Option(
    None, "--describe", "-d", help='What this change was for, e.g. "Add export to CSV".'
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"VerifyPR {__version__}")
        raise typer.Exit()


def _fail(err: VerifyPRError) -> None:
    typer.echo(f"✖ {err.message}", err=True)
    if err.hint:
        typer.echo(f"  {err.hint}", err=True)
    raise typer.Exit(EXIT_ERROR)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def ask_consent(root: Path, summary: SendSummary, explicit: bool) -> bool:
    """§1.5.13: ask once per project + provider + model; CI needs an explicit provider."""
    remembered = stored_consent(root, summary.provider, summary.model)
    if remembered is not None:
        return remembered
    if _interactive():
        typer.echo(summary.describe(), err=True)
        allowed = typer.confirm(
            "Send it? (No = basic checks only; you can change this later)", default=False
        )
        store_consent(root, summary.provider, summary.model, allowed)
        return allowed
    if explicit:
        typer.echo(f"Note: {summary.describe()}", err=True)
        return True
    return False


def _chooser(provider: str | None, model: str | None) -> Callable[[LLMSettings], LLMChoice]:
    def choose(settings: LLMSettings) -> LLMChoice:
        return choose_llm(settings, provider=provider, model=model)

    return choose


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
    describe: str | None = DescribeOpt,
    fmt: OutputFormat = FormatOpt,
    verbose: bool = VerboseOpt,
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show the version."
    ),
) -> None:
    """Check your changes (same as `verifypr check`)."""
    if ctx.invoked_subcommand is None:
        request = CheckRequest(
            repo=repo,
            compare=CompareOptions(base=base),
            describe=describe,
            choose=_chooser(None, None),
            consent=ask_consent,
        )
        _check(request, fmt, verbose)


@app.command()
def check(
    repo: Path = RepoOpt,
    base: str | None = BaseOpt,
    describe: str | None = DescribeOpt,
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
    no_llm: bool = typer.Option(False, "--no-llm", help="Use only rule-based checks."),
    provider: str | None = typer.Option(None, "--provider", help="AI provider, e.g. anthropic."),
    model: str | None = typer.Option(None, "--model", help="AI model name."),
) -> None:
    """Advanced: check changes with extra options."""
    if staged and (head or committed_only):
        _fail(VerifyPRError("--staged can't be combined with --head or --committed-only."))
    compare = CompareOptions(base=base, head=head, staged=staged, committed_only=committed_only)
    request = CheckRequest(
        repo=repo,
        compare=compare,
        contract_path=review_contract,
        describe=describe,
        use_ai=not no_llm,
        choose=_chooser(provider, model),
        consent=ask_consent,
    )
    _check(request, fmt, verbose)


@app.command()
def explain(
    repo: Path = RepoOpt,
    base: str | None = BaseOpt,
    describe: str | None = DescribeOpt,
    no_llm: bool = typer.Option(False, "--no-llm", help="Use only rule-based checks."),
) -> None:
    """Advanced: the full report in Markdown (for a PR description or comment)."""
    request = CheckRequest(
        repo=repo,
        compare=CompareOptions(base=base),
        describe=describe,
        use_ai=not no_llm,
        choose=_chooser(None, None),
        consent=ask_consent,
    )
    _check(request, OutputFormat.MARKDOWN, True)


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


# ---- AI keys ----------------------------------------------------------------------------
key_app = typer.Typer(help="Advanced: manage AI provider keys (stored in your OS keychain).")
app.add_typer(key_app, name="key")
ProviderArg = typer.Argument("anthropic", help="anthropic, openai, azure, openrouter, …")


@key_app.command("set")
def key_set(provider: str = ProviderArg) -> None:
    """Save a key in the OS keychain (you'll be asked for it; it's never shown)."""
    from verifypr.llm.keys import KeychainUnavailableError, masked, save_key

    secret = typer.prompt(f"Paste your {provider} API key", hide_input=True).strip()
    if not secret:
        _fail(VerifyPRError("No key was entered."))
    try:
        save_key(provider, secret)
    except KeychainUnavailableError as err:
        _fail(VerifyPRError(str(err)))
    typer.echo(f"✔ Saved {provider} key {masked(secret)} in your OS keychain.")


@key_app.command("status")
def key_status() -> None:
    """Show which providers have a key and where it comes from (last 4 characters only)."""
    from verifypr.llm.keys import ENV_VARS, masked, resolve_key

    for provider in ENV_VARS:
        secret, source = resolve_key(provider)
        if secret:
            where = (
                f"environment variable {ENV_VARS[provider]}" if source == "environment" else source
            )
            typer.echo(f"{provider}: {masked(secret)} (from {where})")
        else:
            typer.echo(f"{provider}: no key")


@key_app.command("remove")
def key_remove(provider: str = ProviderArg) -> None:
    """Remove a saved key from the OS keychain."""
    from verifypr.llm.keys import remove_key

    if remove_key(provider):
        typer.echo(f"✔ Removed the saved {provider} key.")
    else:
        typer.echo(f"No saved {provider} key was found.")


@key_app.command("test")
def key_test(
    provider: str = ProviderArg,
    model: str | None = typer.Option(None, "--model", help="AI model name."),
) -> None:
    """Send a tiny request (no code) to check the key works."""
    from verifypr.llm.base import LLMError

    choice = choose_llm(LLMSettings(), provider=provider, model=model)
    if choice.client is None:
        _fail(VerifyPRError(choice.reason or "No AI provider is set up."))
        return
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    try:
        choice.client.complete_json(
            system="Reply with JSON only.",
            user='Reply with {"ok": true}.',
            schema=schema,
            max_tokens=200,
        )
    except LLMError as err:
        _fail(VerifyPRError(err.message))
    typer.echo(f"✔ Connected to {provider} ({choice.client.model}).")


# ---- What this change should do ---------------------------------------------------------
intent_app = typer.Typer(help="Advanced: say what your change should do (a Review Contract).")
app.add_typer(intent_app, name="intent")


@intent_app.command("init")
def intent_init(
    description: str = typer.Argument(..., help='e.g. "Add customer segmentation to reports"'),
    repo: Path = RepoOpt,
    save: bool = typer.Option(False, "--save", help="Save without asking."),
) -> None:
    """Turn a sentence into a proposed scope you can confirm (saved outside your repo)."""
    from verifypr.config import load_config
    from verifypr.intent.propose import contract_yaml, propose_contract, save_contract
    from verifypr.llm.base import LLMError
    from verifypr.sources.local_git import LocalGit

    try:
        git = LocalGit.open(repo)
        config = load_config(git.root)
        changes = git.collect(CompareOptions())
    except VerifyPRError as err:
        _fail(err)
        return
    choice = choose_llm(config.llm)
    if choice.client is None:
        _fail(VerifyPRError(choice.reason or "No AI provider is set up."))
        return
    summary = SendSummary(
        choice.client.provider, choice.client.model, 0, len(description), 800, 400
    )
    if not ask_consent(git.root, summary, choice.explicit):
        _fail(VerifyPRError("Not sent: you chose not to send this to the AI."))
    try:
        contract = propose_contract(choice.client, description, changes.list_files())
    except LLMError as err:
        _fail(VerifyPRError(err.message))
        return
    typer.echo("Proposed scope for this change (edit and pass it with --review-contract,")
    typer.echo("or save it so every check uses it):\n")
    typer.echo(contract_yaml(contract))
    if save or (_interactive() and typer.confirm("Save this for this project?", default=True)):
        save_contract(git.root, contract)
        typer.echo("✔ Saved (outside your repository). Remove it with `verifypr intent clear`.")


@intent_app.command("show")
def intent_show(repo: Path = RepoOpt) -> None:
    """Show the saved scope for this project."""
    from verifypr.intent.propose import contract_yaml, saved_contract
    from verifypr.sources.local_git import LocalGit

    try:
        root = LocalGit.open(repo).root
    except VerifyPRError as err:
        _fail(err)
        return
    contract = saved_contract(root)
    typer.echo(contract_yaml(contract) if contract else "No saved scope for this project.")


@intent_app.command("clear")
def intent_clear(repo: Path = RepoOpt) -> None:
    """Remove the saved scope for this project."""
    from verifypr.intent.propose import clear_contract
    from verifypr.sources.local_git import LocalGit

    try:
        root = LocalGit.open(repo).root
    except VerifyPRError as err:
        _fail(err)
        return
    typer.echo("✔ Removed." if clear_contract(root) else "No saved scope for this project.")


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower()
        if encoding.replace("-", "") != "utf8" and hasattr(stream, "reconfigure"):
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_output()
    app()
