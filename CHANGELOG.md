# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Breaking changes before 1.0 are listed explicitly.

## [Unreleased]

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
