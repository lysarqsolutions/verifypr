# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Breaking changes before 1.0 are listed explicitly.

## [Unreleased]

### Added — Phase 3 (AI intent checks)
- Optional AI checks that say, for every change, whether it was **asked for**, **needed
  for the change**, **not asked for**, or **not sure** — with a plain reason. Three ways
  in: no input (VerifyPR makes a labelled best guess from the branch, commits and files),
  `--describe "…"`, or a saved scope from `verifypr intent init "…"`.
- Providers: Anthropic via the official SDK (default model `claude-opus-5-5`, server-side
  refusal fallback enabled), and any OpenAI-compatible endpoint (OpenAI, Azure OpenAI,
  OpenRouter, Ollama, vLLM). A scripted fake is used for all tests.
- `verifypr key set|status|remove|test`: keys come from environment variables or the OS
  keychain; never files, arguments, logs or reports.
- Consent before the first send (what, how much, to whom, estimated cost); CI sends only
  with an explicitly configured provider.
- Never crashes mid-review: a failed or too-large part becomes "Not sure — AI check failed
  for this part"; invalid answers get one retry; invented ids are ignored; unsure "asked
  for" answers are downgraded to "not sure". Secrets are removed before sending.
- Prompt-injection hardening: repository text sits in `<untrusted_*>` blocks that it
  can't close; AI findings can only add warnings.
- `verifypr explain` (full Markdown report incl. "Changes not asked for"), "Worth a look"
  for important-but-unsure findings, and "Checked against …" in every report.

### Fixed
- `"role": "user"` in chat-message code is no longer an "access rule" (found by running
  VerifyPR on its own Phase 3 changes).

### Fixed — Phase 2 review
- No longer blocks merging for ordinary changes: tests skipped only under a condition
  (e.g. on one OS) are "worth a look", not serious; `cleanup || true` in CI or scripts
  is fine — only checks made to always pass are flagged (serious only in CI files).
- Fewer false alarms: packaging settings in `pyproject.toml`/`setup.cfg`/`tox.ini`
  (only lint sections count), `.editorconfig`, variables named `lines`, `strict` options
  in app code, HTML/JSX `role="…"` attributes, `path:` options outside route files,
  same-named files like `utils` in other areas (imports are now resolved to the real
  file), and expected-value changes when only docs changed.
- Much faster in `--committed-only`, `--head`, and `--staged` modes on large projects
  (one git process instead of one per file: 80 s → 4 s on 1,500 files).

### Added — Phase 2 (tests, safety checks, basic behavior watch)
- Tests deleted, removed, or weakened: deleted test files, removed test cases (renames
  are reported separately and more gently), fewer checks inside tests, expected values
  changed in the same change as the code they test, new skip/only/disabled markers,
  bulk snapshot updates, "accept any value" mocks, and raised time limits.
- Safety checks switched off: new `@ts-ignore` / `eslint-disable` / `# type: ignore` /
  `noqa` / `@SuppressWarnings` and similar, relaxed lint configs, lowered coverage
  limits, CI steps removed or commented out, CI files deleted, steps set to never fail
  (`continue-on-error`, `|| true`), pre-commit checks removed, strict settings off.
- Basic behavior watch (labeled "Basic check", replaced by full detectors in v0.2):
  changed role/permission/feature-flag lines, removed login/permission requirements,
  removed routes, menu items, buttons and links, buttons that became conditional, and
  changed files imported by several other areas ("used in 3 other areas").
- Deleted tests, skipped tests, removed CI checks, and removed login requirements are
  treated as serious ("Don't merge yet").
- Patterns inside strings, comments, and docstrings are ignored (found by running
  VerifyPR on its own code).

### Added — Phase 1 (rule-based checks)
- `verifypr` (no arguments) checks your work: everything on your branch since it split
  from the base branch, plus unsaved changes, plus new files git doesn't track yet.
  Base branch is detected automatically (main/master/develop, then origin's default).
- `verifypr check` (advanced options: `--base`, `--head`, `--staged`, `--committed-only`,
  `--review-contract`, `--format text|markdown|json`, `--verbose`) and `verifypr diff`.
- Checks: changes in "should not change" or outside-allowed areas (with a Review
  Contract); formatting-only, line-ending, encoding-marker, import-order and permission
  changes; added/removed/updated dependencies (npm, pip, pyproject/Poetry, Go, Maven,
  Gradle, NuGet) and lock files changed on their own; committed secrets (always
  redacted in output), environment files, build output, editor/OS files, binaries.
- Verdict and exit codes: 0 looks fine, 1 needs attention, 2 don't merge yet,
  3 couldn't run. Committed secrets and "should not change" areas always fail.
- `.verifypr.yml`: base branch, allow rules (suppressed findings are counted, never
  silently dropped), disabled detectors, tolerances, ignore globs.
- Friendly messages for non-git folders, missing base branch, detached HEAD, shallow
  clones, empty repositories, sparse checkouts, submodules, and Git LFS pointers.
- Every git call uses `--no-optional-locks`; the read-only test now covers every command.

### Fixed — Phase 1 review
- Commits made directly on the base branch (e.g. an agent working on `main`) were
  invisible; VerifyPR now compares with the branch's remote copy, or says clearly that
  there is none.
- Indentation changes in Python, YAML and Makefiles are no longer called "only
  formatting" — they can change behavior.
- Ordinary code like `token = request.headers.get(...)` is no longer flagged as a
  secret; plain `key=value` secrets are only matched in settings files (redaction
  stays strict everywhere).
- "Formatting mixed in with real changes" is now informational and no longer causes
  "needs attention".
- Allow rules work per file inside grouped findings and only count files that were
  actually hidden.
- File-level findings no longer show a made-up line number; the "no changes" message
  no longer repeats itself.

### Added — Phase 0
- Phase 0 project scaffold: package layout, core data models (`Hunk`, `Evidence`,
  `Finding`, `Report`), plain-language labels, `verifypr --version`.
- Read-only guarantee test harness: hashes the working tree and `.git` before and
  after every default command.
- CI on Linux, Windows, and macOS: lint, type-check, tests, dependency audit,
  license allow-list, secret scan, and DCO sign-off check.
- Open-source repo files: Apache-2.0 license, contributing guide, security policy,
  issue templates (bug, false alarm, missed change), PR template, Dependabot.
