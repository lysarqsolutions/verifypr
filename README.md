# VerifyPR

> **Status: v0.1.0, pre-alpha — first public release ("Did it stay in scope?").** Usable for early testing; expect changes. Feedback welcome via issues ("False alarm" / "Missed change").

## Try it

```bash
pip install -e .
```

```bash
verifypr
```

Run it inside your project folder. It compares your branch, unsaved changes, and new files with `main` (or `master`/`develop`) and prints a short summary plus a "Please check before approving" list. Add `--verbose` to see everything, or `--format markdown` / `--format json`.

Exit codes: `0` looks fine · `1` needs your attention · `2` don't merge yet · `3` couldn't run.

### The web page

```bash
pip install -e ".[ui]"
```

```bash
verifypr ui
```

This opens a page in your browser (only on this computer, `127.0.0.1`) that has already
checked your changes. From there you can mark items as fine, always allow a kind of change
in a folder, copy a ready-to-paste prompt that tells your coding agent what to fix, press
**Check again** to see "Fixed 2 of 3 · 1 still open", and share the report as HTML,
Markdown or JSON. Press `?` for keyboard shortcuts.

### View only

```bash
verifypr --view-only
```

Works on every command (`verifypr ui --view-only`) or with `VERIFYPR_VIEW_ONLY=1`. Nothing is
changed or saved anywhere — not in your project and not in VerifyPR's own settings.
Add `--offline` as well and nothing leaves your computer: only the rule-based checks run.

### Reports and the agent prompt

```bash
verifypr check --report report.html
```

```bash
verifypr check --agent-prompt
```

The first writes a shareable HTML report (to the path you give). The second prints a
prompt you can paste into your coding agent listing the changes that weren't asked for.

To undo selected changes yourself, `verifypr export-patch -o undo.patch` writes a patch
that you review and apply with `git apply -R undo.patch`. VerifyPR never applies it.
(Use `-o` on Windows: redirecting with `>` in PowerShell changes the line endings.)

### A stricter check

Tell it what the change was for to get a stricter check:

```bash
verifypr --describe "Add customer segmentation to the reports page"
```

### Smarter checks with AI (optional)

Without an AI key, VerifyPR runs its rule-based checks only and says so. With a key it also
works out which changes weren't asked for:

```bash
verifypr key set
```

That saves an Anthropic key in your operating system's keychain (never in a file). Other
providers: `verifypr key set openai`, or local models with no key via Ollama — set
`llm: {provider: ollama, model: <name>}` in `.verifypr.yml`. The default model is
`claude-opus-5-5`; change it with `llm.model`.

## What gets sent where

- **Without an AI key, or with `--no-llm`:** nothing. No network calls at all.
- **With an AI key:** nothing is sent until you agree. The first time, VerifyPR shows how
  many files, roughly how much, to which provider and model, and an estimated cost, and
  asks. Your answer is remembered per project, provider and model (outside your repo). In
  CI, sending happens only when you set `llm.provider` explicitly, and one line says what
  was sent.
- **What is sent:** the changed lines (with secrets removed first), file names, the branch
  name, and commit messages — to the provider you chose, and nowhere else. Lock files and
  generated files are not sent.
- **Never:** telemetry, accounts, or anything sent to VerifyPR's authors.

Text in your code, commits, or descriptions is treated as untrusted data: instructions
hidden in it ("ignore previous instructions…") can't change VerifyPR's results, and AI
findings can only add warnings — they can never clear a rule-based one.

**VerifyPR answers whether an AI coding agent changed only what it was supposed to change, what existing behavior might have changed, and what reviewers should check before approving.**

AI coding agents often ship changes nobody asked for: drive-by refactors, dependency bumps, rewritten config, weakened tests, hidden UI features, changed permissions. VerifyPR is a free, open-source, local-first tool that tells you, in plain words:

- ⚠️ which changes **weren't asked for**
- 🔎 what **changed for users** (and who else it affects)
- ✅ a short **"Please check before approving"** list

## Principles

- **Read-only by default.** VerifyPR never changes your code or git history unless you explicitly turn on a feature that does. A **View only** mode saves nothing at all.
- **Works with no setup.** Basic checks run without an AI key; an AI key makes the checks smarter.
- **No telemetry, no accounts.** Runs on your machine or in your own CI. If you add an AI key, the README will document exactly what is sent and to whom.
- **Not another code-style reviewer.** VerifyPR focuses on intent, scope, behavior, impact, and verification.

## Roadmap

| Release | Focus |
|---------|-------|
| v0.1 | Did it stay in scope? (rule-based checks + local web UI) |
| v0.1.x | Fill the gaps (more detectors, requirements/user stories) |
| v0.2 | What behavior changed? |
| v0.3 | Hold the agent accountable (claims, plans, GitHub, trackers) |
| v1.0 | Hardening, docs, evaluation |

The full spec lives in [CLAUDE.md](CLAUDE.md).

## Development

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip install -e ".[dev]"
```

```bash
ruff check . && ruff format --check . && mypy && pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

[Apache-2.0](LICENSE)
