# VerifyPR

> **Status: pre-alpha (Phase 2 — rule-based checks).** Usable for early testing; expect changes.

## Try it

```bash
pip install -e .
```

```bash
verifypr
```

Run it inside your project folder. It compares your branch, unsaved changes, and new files with `main` (or `master`/`develop`) and prints a short summary plus a "Please check before approving" list. Add `--verbose` to see everything, or `--format markdown` / `--format json`.

Exit codes: `0` looks fine · `1` needs your attention · `2` don't merge yet · `3` couldn't run.

**What gets sent where:** nothing. This version runs only local rule-based checks and makes no network calls.

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
