# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Breaking changes before 1.0 are listed explicitly.

## [Unreleased]

## [0.1.0] - 2026-11-21

First public release: "Did it stay in scope?" (phases 0-4).

### Changed
- Version set to 0.1.0 (the 0.0.1 name placeholder is already on PyPI); package
  metadata links to the GitHub repository and issue tracker.

### Fixed
- Every git command VerifyPR runs turns off git's automatic background maintenance,
  so a check can never start writes in `.git` (seen on macOS CI).
- `verifypr key set` and Settings refuse keys that were mangled while pasting (spaces,
  line breaks, other stray characters, or far too long) and ask before saving one that
  doesn't look like the provider's API key (e.g. an Anthropic key that doesn't start
  with `sk-ant-`; all Console key kinds, including user-linked `sk-ant-usr-` keys, pass). Found during the first live test. Messages never show the key.

### Fixed — Phase 4 review
- "Always allow this kind of change here" covers only that one file for serious findings
  (e.g. a committed secret), never the whole folder.
- With basic checks only, a clean result's label reads "No problems found", not "Looks
  good". The page now gets its headline and label from the same code as the terminal.
- New card button: **Add to "what this change should do"**.
- `export-patch -o FILE` prints the exact `git apply -R "FILE"` command, and changes a
  patch can't undo (binary, permission-only) are listed to undo by hand.
- Test connection refuses unknown providers; in View only the undo steps don't mention
  the (hidden) patch download.
- Web framework telemetry (OpenTelemetry in newer FastAPI) is switched off explicitly.

### Added — Phase 4 (local web page and reports)
- `verifypr ui` (`pip install "verifypr[ui]"`): a page on `127.0.0.1` with a per-session
  token, strict security headers, and paths kept inside your project. The check has
  already run when it opens: headline, up to 3 top issues, "Please check before
  approving", and all changes grouped by **Not asked for → Not sure → Needed for the
  change → Asked for**, with filters, a "Why?" and the code for each.
- Next steps on every item: **It's fine, keep it** (undo it later in Settings),
  **Always allow this kind of change here**, **Copy undo steps**, **Open in editor**.
- **Tell the agent to fix this** copies a prompt listing the changes not asked for, the
  problems to fix, and the changes to confirm. Also `verifypr check --agent-prompt`.
- **Check again** shows "Fixed 2 of 3 · 1 still open · 1 new issue" (in the terminal too).
  Items you mark as fine are not counted as fixed.
- AI helper setup in Settings: pick a provider, paste a key (stored in the OS keychain or
  for this session only, never shown again in full), test the connection. Consent before
  the first send. An optional, skippable AI setup card appears below the results.
- **View only** (`--view-only`, `VERIFYPR_VIEW_ONLY=1`, or the page toggle): nothing is
  changed or saved anywhere; every saving action is hidden and refused. `--offline` turns
  off all network use.
- Reports: `check --report report.html` (self-contained, no scripts), Markdown with a
  "Next step" and the agent prompt, and HTML/Markdown/JSON downloads from the page.
- `verifypr export-patch`: a patch that undoes selected changes, for you to review and
  apply with `git apply -R`. VerifyPR never applies it.
- Accessible: keyboard shortcuts (can be turned off), screen-reader labels, visible
  focus, reduced motion, dark mode, narrow windows. All page text is in one file.

### Fixed — Phase 3 review
- Secrets in commit messages, branch names, `--describe` text and saved scopes are now
  removed before anything is sent to the AI (only changed code lines were before).
- AI calls allow 16,000 output tokens (the default model always thinks, and thinking
  counts toward the limit) and wait up to 5 minutes, so answers aren't cut off.
- OpenAI and Azure get `max_completion_tokens`; other compatible servers keep `max_tokens`.
- `intent init` says what it actually sends (your description and folder names, no
  code) and no longer needs a base branch.
- Anthropic sign-ins without an API key (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE`,
  `ant auth login`) are recognised.
- Lower cost: the system prompt and the shared task/context are marked for prompt
  caching, and formatting-only changes are no longer sent to the AI.
- Reports show AI tokens used and the estimated cost.

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

[Unreleased]: https://github.com/lysarqsolutions/verifypr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lysarqsolutions/verifypr/releases/tag/v0.1.0
