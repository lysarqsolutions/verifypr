# CLAUDE.md — Build Instructions for VerifyPR (`verifypr`)

> Instructions for Claude Code. Read this whole file before writing code. Build **one phase at a time**, in order, and **stop at each phase checkpoint** for review. Do not build features from a later phase early.
>
> **Human contributors:** this is a public open-source project. This file is both the product spec and the working rules for AI coding agents used on this repo. Please follow it too; see CONTRIBUTING.md for the human workflow.
>
> **Name:** the product is **VerifyPR**. Package, CLI command, config prefix, and env-var prefix are `verifypr` / `VERIFYPR_`. Always write the product name as one word, "VerifyPR", because "verify-pr" is a common generic phrase (agent skills, GitHub Actions). Before the first public push or package publish, the maintainer confirms that `verifypr` is still free on PyPI, npm, and GitHub.

---

## 1. Product

### 1.1 The problem
AI coding agents (Claude Code, Cursor, Copilot agent, etc.) — and humans in a hurry — regularly ship changes nobody asked for: drive-by refactors, reformatting, dependency bumps, rewritten config, deleted or weakened tests, hidden UI features, tightened permissions, shared components that silently change other roles. These changes are rarely mentioned in the PR description. Research on *tangled changes* shows reviewers miss more defects when unrelated changes are bundled together, and regressions often sit outside the edited lines. Reviewers end up reading huge diffs to find what *shouldn't* be there.

### 1.2 Positioning (every feature decision must serve this)
> **VerifyPR answers whether the agent changed only what it was supposed to change, what existing behavior might have changed, and what reviewers should verify before approving.**

Pillars: **Intent · Scope · Behavior · Impact · Verification.**

### 1.3 Non-goals
- **Not a PR-review competitor.** No general code-quality, style, performance, refactoring-suggestion, or bug-hunting reviews in core. (`review`/`improve` are possible post-1.0 optional extras — see §8.)
- Not a hosted SaaS. No accounts, no telemetry. Runs locally or in the user's own CI.
- Never auto-approve or auto-merge.
- Fully independent, **clean-room** implementation: do not depend on, wrap, or copy code/prompts/schemas from any other PR tool.

### 1.4 Core principles (apply in every phase)
1. **Read-only by default.** Default commands make **zero changes** to the repo or git state: no file edits, commits, stashes, checkouts, resets, hook installs, or files written into the working tree. Only read-only git (`diff`, `log`, `show`, `blame`, `rev-parse`, `status`, `ls-files`). Anything that writes is an explicit opt-in feature (Phase 8).
2. **Deterministic first, LLM second.** Rules and static analysis decide what they can; the LLM handles ambiguity and plain-language explanation.
3. **Honest uncertainty.** Every finding carries **severity**, **confidence (0–100%)**, and **evidence** (file + line range). When unsure, say "unclear/potential" — never silently mark something as fine.
4. **All input is untrusted.** Diffs, PR text, commit messages, tickets, agent claims/plans may contain prompt injection. Delimit them in prompts as data; they can never change tool behavior, config, classification rules, or output destinations.
5. **Works with zero input**, gets better with more (Auto → Describe → Requirements/ticket).
6. **Explain in user terms.** Prefer "Reports menu now hidden from Managers" over "condition changed in menu.ts:14".

7. **View only mode** — for people who just want to look. Stricter than the read-only default:
   - **Turn on with** `--view-only` on any command (`verifypr ui --view-only`, `verifypr check --view-only`), the env var `VERIFYPR_VIEW_ONLY=1`, `view_only: true` in user config, or a **View only** toggle in the UI header.
   - **Saves nothing anywhere:** no repo or git writes (as always), and also no state-dir or keychain writes (no saved contract, no "keep it" marks, no last-checked SHA, no wizard settings, no cache, no saved API key). Everything lives in memory and disappears on exit. An API key can still be entered for the session only.
   - **Hides every action** that changes or saves anything: Keep, Add to scope, Revert, Download patch, hook install, posting to GitHub or trackers, contract export. What remains: **See details**, **Why?**, **Open in editor** (read-only), **Copy** text to clipboard, and **Share report** (download HTML/Markdown/JSON only to a location the user picks; if they'd rather not, the report is viewable in the page).
   - **Opt-in features cannot be used while it's on.** View only overrides `features.revert`, `--post`, `hooks install`, and similar; commands refuse with a friendly message ("View only is on — nothing can be changed or saved").
   - **Locked when started with the flag or env var:** the UI toggle can't switch it off. A toggle switched on inside the UI applies to the session immediately.
   - **Clear badge:** an always-visible "👁 View only — nothing will be changed or saved" label in the UI, and the same line at the top of terminal output.
   - **Fully private option:** `--view-only --offline` (UI: "Don't send anything to an AI") also disables every network call, including the LLM and trackers. Only rule-based checks run, and the badge reads "👁 View only · Offline — nothing leaves this computer".

### 1.5 UX principles (user-friendly by default — apply to UI, terminal, PR comments, reports)
**Target user:** someone who let an AI agent make changes and wants to know *"Is this safe to merge, and what should I check?"* They may not know git internals, YAML, or code-review jargon.

1. **Answer first, details later.** Every surface opens with: one **headline sentence**, at most **3 top issues** in plain words, and the **"Please check before approving"** list. Everything else sits behind "See details".
2. **One signal, not five.** The headline plus one status (icon **and** text label). Scores, percentages, and counts live only in Details, and must never appear to contradict the headline.
   **Honest headlines:** the headline states how deep the check was. With rule-based checks only (no AI key, `--offline`), a clean result reads "No problems found by basic checks" + "Add an AI key for a deeper check" — never a plain "Looks good".
3. **Plain-language labels.** UI copy uses this glossary; internal names stay in code and JSON only:

   | Internal | Shown to users |
   |----------|----------------|
   | ❌ Unintended / ❓ Unclear / 🔧 Supporting / ✅ Intended | **Not asked for** / **Not sure** / **Needed for the change** / **Asked for** |
   | Hunk | Change |
   | Intent contract (engineer docs/CLI/config: **Review Contract**) | What this change should do |
   | Verdict PASS / WARN / FAIL | "Looks good" / "N changes need your attention" / "Don't merge yet — N serious issues" |
   | Severity High / Medium / Low | Important / Worth a look / Minor |
   | Confidence ≥ 80% / 50–79% / < 50% | Sure / Likely / Not sure (exact % in a tooltip) |
   | Requirement drift | "How much of this change is about the task" |
   | Hygiene / guardrails | Tidy-up changes / Safety checks turned off |
   | Blast radius / impact | Who else this affects |
   | Behavioral Delta | What changed for users |
   | Out-of-scope changes | Changes not asked for |
   | Claims / plan verification / agent accountability | Did the agent do what it said? |
   | Please-verify list | **Please check before approving** (the only name used anywhere user-facing) |
   | Test integrity / guardrails | Tests & safety checks |

4. **Zero setup to the first result.** One command (`uvx verifypr ui` or `pipx run verifypr ui`), auto-detect the repo (current folder) and the base branch (upstream, else `main`/`master`/`develop`). **Works with no AI key**: runs the rule-based checks and shows a gentle "Add an AI key for smarter checks" banner. An optional first-run wizard has at most 3 screens and can be skipped.
5. **Results before questions.** The Auto check runs as soon as the UI opens. Only afterwards offer: **"Make the check stricter — tell me what this change was for, or paste the ticket/user story."**
6. **Every result ends with a next step.** **"Tell the agent to fix this"** copies a ready-to-paste prompt for the coding agent listing the unrequested changes with files and lines. Also **"It's fine, keep it"**, **"Always allow this kind of change here"**, **"Open in editor"** (`vscode://`/`file://` link), and **"How to undo this myself"** (plain steps; git commands shown only on expand). After a fix, **"Check again"** shows progress: "Fixed 2 of 3 · 1 still open · 1 new issue".
7. **Explain every flag.** Each item has a one-sentence **"Why?"** with the evidence snippet. No unexplained warnings.
8. **Friendly states.** Progress with named stages ("Reading changes… Checking scope… Looking for hidden features…"); empty ("No changes found compared to `main` — pick another branch?"); errors with a fix ("No AI key found — showing basic checks. [Add key]"); large diffs ("Checked the 200 most important files, skipped 40 generated files. [Why?]"); setup problems ("This folder isn't a git project — open the project folder instead [Choose folder]", "Couldn't find a main branch to compare with — pick one ▾", "You're not on a branch right now (detached HEAD) — comparing this commit with `main`").
9. **Don't overwhelm.** At most 3 top issues on the summary and ~10 items to check; the rest collapsed. Never show internal IDs (U-numbers, hunk IDs) in the UI.
10. **Accessible.** Never colour or emoji alone (always a text label); WCAG 2.1 AA contrast; full keyboard navigation; screen-reader labels; respects reduced-motion; usable at 200% zoom and on narrow windows. All UI strings in one file for future translation.
11. **Same story everywhere.** Terminal output, PR comment, HTML report, and UI share the same structure and wording. The terminal default prints headline + top 3 + Please-check list and "Run `verifypr ui` for details"; `--verbose` prints everything; `--format json` for machines.
12. **Few commands for everyday use.** Running **`verifypr`** with no arguments runs the check and prints the summary. `--help` lists the three everyday commands first — `verifypr`, `verifypr ui`, `verifypr --view-only` — and groups everything else under "Advanced".
13. **Ask before sending code.** The first time code would be sent to an AI provider (per repo + provider), show what will be sent (files, approximate size, secrets already removed), to whom, and an estimated cost, with **Send** / **Skip — basic checks only**. Remember the answer in the state dir (not in View only mode, where it's asked per session). Non-interactive/CI runs treat an explicitly configured provider as consent and print one line saying what was sent.

---

## 2. Problem Catalog → Feature → Phase

Real-world unintended-change problems this tool must catch. Each row is a requirement; tests (§9) must include a fixture for every row.

| ID | Problem seen in real PRs | Feature that catches it | Phase |
|----|--------------------------|-------------------------|-------|
| U1 | Agent edits files/areas it wasn't asked to touch | Scope rules + intent classification | 1, 3 |
| U2 | Drive-by refactors, renames, moved files bundled into the PR (tangled PR) | Theme clustering, rename/move detection, split suggestion | 1, 3, 7 |
| U3 | Formatting/whitespace churn, import reordering, **line-ending (CRLF/LF), BOM/encoding, file-mode (chmod)** changes hiding real changes | Change hygiene detector | 1 |
| U4 | Dependency bumps, new dependencies, lockfile churn | Dependency detector | 1 |
| U5 | Config/CI/infra/env files rewritten (`.env.example`, docker-compose, nginx, appsettings, YAML) | Config & operational detector | 4b, 6 |
| U6 | Accidental artifacts committed: build output, `node_modules`, IDE files, large binaries, secrets, `.env` | Artifact & secret detector | 1 |
| U7 | Debug leftovers: `console.log`/`print`, commented-out code, `debugger`, TODO/FIXME added | Leftover detector | 4b |
| U8 | Large or unexplained deletions (files, functions, docs/comments) | Deletion detector | 4b |
| U9 | **Tests deleted, skipped, or weakened** (assertions removed, expected values changed to match output, `skip`/`xfail`/`@Ignore`, snapshots blindly updated, broader mocks) | Test-integrity detector | 2 |
| U10 | **Guardrails disabled** to make things pass: lint/type suppressions (`eslint-disable`, `@ts-ignore`, `# type: ignore`, `noqa`), lowered coverage thresholds, CI steps removed or `continue-on-error` | Guardrail-weakening detector | 2 |
| U11 | Stubs, placeholders, hard-coded values or mock data left in production code to "make it work" | Stub & placeholder detector | 4b |
| U12 | Error handling degraded: swallowed exceptions, catch-all + ignore, removed logging/raises, silent fallback defaults | Error-handling degradation detector | 4b |
| U13 | Agent **reverts or overwrites recent work** by others (stale base, re-introduces old code) | Work-loss detector (read-only blame/log) | 4b |
| U14 | Change doesn't match the request (extra work / requirement drift) | Intent classification, drift score | 3, 4b |
| U15 | Change is incomplete (requirement partially or not implemented) | Requirement coverage | 4b |
| U16 | Unexpected high-risk changes nobody mentioned (migration, auth, new dep) | "What surprised me?" | 4b |
| U17 | **UI features hidden/removed**, routes/menus/buttons disappear | Visibility + frontend regression detectors | 2 (basic), 5 |
| U18 | **Permissions changed** (role checks, guards, policies, feature flags) | Permission & visibility detector | 2 (basic), 5 |
| U19 | Existing capability lost or narrowed while "in scope" (export removed, search exact-match) | Capability-loss detector, Behavioral Delta | 5 |
| U20 | **Shared component change silently affects other roles/modules** | Impact radius, shared-asset registry | 2 (basic), 6 |
| U21 | Scope expansion (affects more roles than intended) or reduction (only one path updated) | Scope direction analyzer | 6 |
| U22 | API/data contract break (field removed/renamed/required) hurting consumers (mobile, other services) | Data-contract detector + consumer awareness | 6 |
| U23 | Critical business flows (checkout, invoicing, login) touched without anyone noticing | Critical-flow impact | 6 |
| U24 | Changed areas not covered by tests | Test confidence | 6 |
| U25 | PR description / agent summary claims things the diff contradicts | Claims verifier, description-vs-diff check | 7 |
| U26 | Agent's plan said 5 files, it changed 21 | Plan-vs-actual intent divergence | 7 |
| U27 | Reviewers drown in large diffs and rubber-stamp | Please-check list, severity × confidence ranking, Safe Change Score (hidden by default) | 3, 7 |
| U28 | New commits pushed **after review** add unreviewed scope | Delta-since-last-check | 8 |
| U29 | The ticket (Jira/Azure/ClickUp) says one thing, the code does another | Tracker connectors + requirement coverage | 8 |

Out of scope (belongs to general review tools): performance regressions, concurrency bugs, code style, general security scanning.

---

## 3. Release Plan at a Glance

| Release | Phases | What users get |
|---------|--------|----------------|
| **v0.1 — "Did it stay in scope?"** | 0–4 | Focused first release: out-of-scope changes (Auto + Describe), format/line-ending churn, dependency changes, committed secrets/artifacts, weakened tests, disabled safety checks, **basic hidden-UI / permission / shared-file warnings** (U1, U3, U4, U6, U9, U10 + basic U17, U18, U20); local web UI with "Check again"; Markdown/JSON/HTML reports. Read-only. |
| **v0.1.x — "Fill the gaps"** | 4b | Config/CI, leftovers, deletions, stubs, swallowed errors, work loss; Requirements mode with coverage, drift, and "What surprised me?". Built after v0.1 feedback. |
| **v0.2 — "What behavior changed?"** | 5–6 | Behavioral Delta, visibility/permission/capability loss, impact radius, registries, critical flows, API consumers, data contracts, test confidence. |
| **v0.3 — "Hold the agent accountable"** | 7–8 | Claims & plan verification, full Please-verify + scoring, split suggestion, describe/ask/changelog, GitHub Action & Check Run, hooks, trackers, opt-in revert. |
| **v1.0** | 9 | Hardening, docs, packaging, examples, evaluation set. |

Each phase ends with a checkpoint, green CI, and a CHANGELOG entry.

---

## 4. Phases

### Phase 0 — Scaffold
- Repo structure (§6.2), `pyproject.toml`, `ruff`, `mypy --strict`, `pytest`, CI workflow (lint, types, tests, `pip-audit`; Linux + Windows + macOS matrix), Apache-2.0 LICENSE, minimal README.
- Pydantic models skeleton: `Hunk`, `Finding` (id, category, severity, confidence, evidence, message, problem_id), `Report`, `Verdict`.
- **Open-source repo setup (§7b):** `.gitattributes` (fixtures exempt from line-ending normalization), `.gitignore`, CODEOWNERS, issue templates (bug, **"False alarm"**, **"Missed change"**), PR template, Dependabot, DCO check, dependency-license check, pinned GitHub Action SHAs with minimal `permissions:`, CI that needs no secrets.
- **Read-only guarantee test harness**: a fixture repo + helper that hashes the working tree and `.git` before/after any command. Every later default command is added to this test.

*Checkpoint:* tree + CI commands; `pip install -e .[dev]`, `ruff`, `mypy`, `pytest` pass.

### Phase 1 — Deterministic Core & Change Hygiene (no LLM) · U1, U3, U4, U6
- `diff_parser`: hunks with **stable IDs**, file, line ranges, language, change kind (add/modify/delete/rename/move/mode-change/binary). Local options: `--base`, `--head`, `--staged`, `--committed-only`.
  - **Default comparison = what the agent actually did:** everything on the current branch since it split from the base branch **+ uncommitted changes + new untracked files** (read with `git status` / `git ls-files --others --exclude-standard` and file reads — never `git add` or any write). Agents often leave work uncommitted and create new files; a plain `git diff` would miss them.
  - Base branch auto-detection: upstream tracking branch, else `main`/`master`/`develop`; friendly messages for non-git folders, missing base, and detached HEAD (§1.5.8).
  - **Git edge cases handled with friendly messages, never a stack trace:** shallow clones (common in CI: no merge-base → explain and suggest `fetch-depth: 0`, or fall back to comparing with the base tip, saying so); submodules (list changed submodule pointers as one change each, don't descend unless `--include-submodules`); sparse checkouts and partial clones (only analyze what's present and say what wasn't); Git LFS pointers (treat as binary, don't fetch); linked worktrees; renamed/case-only file renames on Windows/macOS; repos with no commits yet.
  - Every output states exactly what was compared ("Your branch + unsaved changes + 3 new files, compared with `main`").
- `chunker` with token budget; ignore globs (lockfiles, generated, vendored).
- Detectors (each pluggable, configurable, with its own tests):
  - **Scope rules:** path allow/deny globs from a contract (if any).
  - **Hygiene (U3):** whitespace-only, formatting-only, import-reorder, line-ending flips, BOM/encoding change, file-mode change. Report "N files changed only in formatting".
  - **Dependencies (U4):** added/removed/bumped deps across npm, pip/poetry, Maven/Gradle, Go, NuGet; lockfile-only churn.
  - **Artifacts & secrets (U6):** build output, `node_modules`, IDE folders, large binaries, `.env`, key patterns.
  - *(Config & CI (U5), sensitive areas, leftovers (U7), and deletions (U8) are deferred to Phase 4b.)*
- **Auto mode baseline:** all the above run with no input.
- Verdict logic (PASS/WARN/FAIL from tolerances) and exit codes. **Auto-mode cap:** findings that depend on *inferred intent* can raise the verdict to WARN at most. **Clear rule-based critical findings** (committed secrets, deleted/disabled tests or CI checks, auth/permission expansion, destructive migrations) can produce FAIL ("Don't merge yet") in any mode.
- Redaction pass (secrets removed before anything could be sent to an LLM later).
- Commands: `verifypr` (no args = `check`, summary output), `verifypr diff` (facts), `verifypr check --no-llm`.
- **Allow rules:** `allow:` entries (in user state or `.verifypr.yml`) suppress a finding kind for a path glob, e.g. "formatting changes in `docs/**`". Suppressed findings are counted in Details ("2 allowed by your rules"), never silently dropped.
- Renderers: terminal, Markdown, JSON.

*Checkpoint:* on a fixture diff containing a real change plus a CRLF flip, lockfile bump, and a committed `.env` with an API key, `check --no-llm` lists each with severity/confidence/evidence and sets the exit code; repo and `.git` unchanged.

### Phase 2 — Test Integrity, Guardrails & Basic Behavior Watch (no LLM) · U9, U10, basic U17/U18/U20
- **Test integrity (U9):** deleted test files/cases, removed assertions, assertion count drop, expected values changed in the same PR as the code they test, new `skip`/`only`/`xfail`/`@Ignore`/`@Disabled`, snapshot files bulk-updated, mocks widened (e.g. `any()` matchers), test timeouts raised.
- **Guardrail weakening (U10):** new lint/type suppressions, rules disabled in lint configs, coverage thresholds lowered, CI steps removed/commented, `continue-on-error`/`|| true`, pre-commit hooks removed, strictness flags turned off (`strict: false`).
- *(Stubs (U11), error-handling degradation (U12), and work loss (U13) are deferred to Phase 4b.)*
- **Basic behavior watch (v0.1 preview of Phases 5–6; rule-based, simple patterns only):**
  - *Permission changes (U18):* changed/added/removed role or permission checks, auth decorators/attributes/middleware, route guards, and feature-flag defaults → "Access rules changed in `menu.ts:14` — check who can still see this".
  - *Hidden or removed UI (U17):* routes removed from route tables, menu/nav entries removed, buttons/links removed or wrapped in a new condition.
  - *Shared files (U20):* count how many other files/top-level areas import or reference each changed file (text/import search) → "This file is used in 3 other areas (admin, sales, supplier)".
  These are labeled "basic check" and replaced by the full detectors in Phases 5–6.
- All findings feed the "Please check before approving" list (basic version: one item per Important finding).

*Checkpoint:* fixture where an agent "fixed" a failing test by changing the expected value, added `@ts-ignore`, narrowed a menu role check, removed an Export button, and edited a form imported by three portals → all flagged with evidence; the first two as Important.

### Phase 3 — Intent & LLM Layer · U1, U2, U27
- **No-key mode:** if no LLM is configured, everything from Phases 1–2 still runs and the report says which smarter checks were skipped and how to enable them (§1.5.4). Never fail just because no key exists.
- **LLM layer:** provider-agnostic `LLMClient`; adapters for **Anthropic** (default) and **OpenAI-compatible** (OpenAI, Azure, Ollama, vLLM, OpenRouter — local models allowed so code never leaves the machine); `FakeLLM`; prompts as versioned files in `prompts/*.md`; JSON output validated by Pydantic with one retry; map-reduce for large diffs; token/cost reporting; **consent before the first send** per §1.5.13.
- **LLM failure fallback (never crash mid-review):** process the diff per chunk so one bad chunk can't sink the run. Use the provider's structured-output/tool-calling mode where available. If a chunk's output is still invalid after one retry, or times out or hits rate limits, mark that chunk's changes **"Not sure — AI check failed for this part"**, keep the rule-based findings for it, and continue. **Validate every file/line reference** the LLM returns against the parsed diff; drop or flag references that don't exist instead of showing invented line numbers. The report summarizes partial failures ("AI check skipped 2 of 14 parts. [Retry these]").
- **API key entry:** see "AI provider setup" in Phase 4. CLI: `verifypr key set [provider]` (hidden prompt; never accepts the key as a command-line argument so it can't land in shell history), `verifypr key status` (shows provider + last 4 characters only), `verifypr key remove`, and `verifypr key test`.
- **Three input levels** (Auto is default; report always states which was used and the confidence):

  | Level | User provides |
  |-------|---------------|
  | **Auto** | Nothing. Intent inferred from branch name, commits, PR text (if any), and diff themes. |
  | **Describe** | One or two plain-English sentences. |
  | **Requirements** *(added in Phase 4b / v0.1.x)* | User story, FR list (`FR-1…`), Gherkin, or acceptance criteria — pasted, file, or issue URL. |

- **Review Contract** (engineer-facing name in docs/CLI/config; internal model `IntentContract`; shown to users in the UI only as "What this change should do"; stored in the tool's state dir outside the repo by default; `--review-contract path` to pass one; never written into the repo unless opted in):
  ```yaml
  goal: "Add customer segmentation to the reporting service"
  allowed:   { paths: ["services/segment/**", "reporting/**", "tests/segment/**"],
               behaviors: ["New segmentation endpoint", "Segment column in customers report"] }
  forbidden: { paths: ["auth/**", "infra/**", ".github/**"],
               behaviors: ["Existing API response shapes", "Schema of existing tables"] }
  assumptions: ["Segments are computed nightly"]
  tolerances: { formatting_only_changes: warn, dependency_changes: block,
                new_files_outside_allowed: block, tests_required: true }
  ```
  `intent init` proposes a contract from plain English/story; the user confirms or edits.
- **Classification:** every hunk → ✅ Intended · 🔧 Supporting (imports, call-site updates, tests for intended code — linked to what they support) · ❌ Unintended · ❓ Unclear, each with reason + contract item + confidence. Unsure ⇒ ❓, never ✅.
- **Theme clustering (U2):** group hunks into themes ("pagination refactor", "search redesign"); dominant theme(s) = presumed intent in Auto mode; outliers flagged.
- *(Requirements input, requirement coverage (U15), drift score (U14), and "What surprised me?" (U16) are deferred to Phase 4b.)*
- **Ranking (U27):** sort all findings by severity × confidence; low-confidence/high-severity go to "Worth a look".
- Commands: `check` (full), `intent init`, `explain` (report format §5.1, sections from later phases omitted until built).

*Checkpoint:* (a) zero-input `check` on an agent diff labels output "inferred", flags outliers, intent-based findings never exceed WARN, while a committed secret still yields FAIL; (b) with a one-sentence description, a change outside it is classified "Not asked for", and supporting imports/tests are linked as "Needed for the change".

### Phase 4 — Local Web UI & Reports → **release v0.1**
- `verifypr ui`: FastAPI + small static front-end (Vite+React or HTMX/Alpine — simplest wins) bundled in the package (`pip install verifypr[ui]`). Binds `127.0.0.1` only, random per-session token, path validation inside repo.
- Follow the UX principles in §1.5 for every screen and string.
- **View only mode (§1.4.7)** in UI and CLI: header toggle + badge, actions hidden, no state-dir writes, `--offline` combination; shareable HTML report works the same way.
- **One-command start:** `uvx verifypr ui` / `pipx run verifypr ui` opens the browser at the summary; repo and base branch auto-detected (changeable via a small "Comparing `feature-x` with `main` ▾" control).
- **Optional first-run wizard** (≤ 3 screens, skippable, remembered): (1) Which project? — current folder preselected; (2) Compare with — detected base branch; (3) AI helper — Anthropic / OpenAI-compatible / local model / **Skip (basic checks only)**, with a "What gets sent?" link; choosing a provider opens the key form below.
- **AI provider setup (Settings → AI helper, also opened from every "Add an AI key" banner):**
  - Pick a provider: Anthropic · OpenAI · Azure OpenAI · OpenRouter · Local (Ollama/vLLM, no key needed) · Other OpenAI-compatible. Model is preselected with a sensible default; base URL field shown only for Azure/local/other.
  - **Paste your API key** in a masked input with a show/hide eye and a "Where do I get a key?" link to the provider's own key page.
  - **Test connection** sends a tiny request (no code) and shows "Connected ✓" or a plain-language error ("That key was rejected — check it was copied fully").
  - **Remember key on this computer** (default on) stores it in the OS keychain (Windows Credential Manager / macOS Keychain / Linux Secret Service via `keyring`). Off = **this session only** (memory). If no keychain is available, offer session-only and say why; **never** fall back to a plain file.
  - After saving, the key is never shown again in full (provider + "…last 4"). Buttons: **Replace key**, **Remove key**.
  - The key is posted only to the local server (127.0.0.1 with the session token), never stored in the browser (no localStorage/cookies), never logged, never included in reports, and sent only to the chosen provider.
  - If an environment variable key is set, show "Using key from environment variable `ANTHROPIC_API_KEY`" (env wins over keychain) and disable editing for that provider.
  - View only mode: session-only entry allowed (nothing saved); "Remember" is hidden. `--offline`: the whole AI section is disabled with an explanation.
- **Screen 1 — Summary (default view; the Auto check has already run):**
  ```
  ⚠️ 3 changes weren't asked for                    Comparing feature-x with main ▾
     • Login settings were edited (auth/session.py)                      [Why?]
     • A test was changed to pass instead of the code being fixed         [Why?]
     • A shared form also used by the Sales and Supplier portals changed  [Why?]

  ✅ Please check before approving (4)
     ☐ Managers can still see Reports
     ☐ Customer export still works
     ☐ …

  [Tell the agent to fix this]   [See all changes]   [Make the check stricter]
  ```
  Clean states (honest about depth): with AI — "✅ Looks good — every change matches what was asked"; basic checks only — "✅ No problems found by basic checks · [Add an AI key for a deeper check]". The Please-check list still shows if non-empty.
  The header always states what was compared ("Your branch + unsaved changes + 3 new files, compared with `main` ▾").
- **"Make the check stricter" panel:** a single text box ("What was this change for?"); pasted tickets/user stories are parsed into requirements from Phase 4b, until then the text is used as a description; **Suggest scope** turns it into editable chips ("Should change: reporting, segment service" / "Should not change: login, infrastructure"); YAML only under "Advanced". Re-check runs automatically after saving.
- **Screen 2 — All changes (Details):** changes grouped **Not asked for → Not sure → Needed for the change → Asked for** (first two expanded). One filter bar instead of many tabs: *All · Tidy-up · Tests & safety checks* (Phase 4b adds *Requirements*; later phases add *Behavior · Who else this affects*). Each change card: plain one-line reason, **Why?**, importance + certainty in words, code snippet (unified/side-by-side toggle), and buttons **It's fine, keep it** · **Always allow this kind of change here** · **Add to "what this change should do"** · **Copy undo steps** · **Open in editor**. Scores/percentages/drift shown in a collapsible "Numbers" panel here only.
- **Finish actions (always visible footer):** **Tell the agent to fix this** (copies the agent prompt), **Copy PR summary**, **Share report** (HTML/Markdown/JSON), and under "Advanced": **Download undo patch** (written outside the repo).
- **Agent fix prompt** (generated text, copied to clipboard): lists each unrequested change with file/lines and asks the agent to revert only those and confirm nothing else changed. Excludes anything marked "It's fine". Never sent anywhere automatically.
- **Check again:** a button (and simply re-running `verifypr`) re-checks and compares with the previous result: "Fixed 2 of 3 · 1 still open · 1 new issue", with the new issue highlighted. Previous result kept in the state dir (in memory only in View only mode).
- **Allow rules screen** (Settings): lists every "Always allow" rule in plain words with Remove; **Export for my team** copies the YAML snippet for `.verifypr.yml` (clipboard only; the tool doesn't write it). Hidden in View only mode.
- **First AI send consent** dialog per §1.5.13.
- Dark/light theme, keyboard shortcuts (shown via `?`), reduced-motion support.
- `check --report report.html`: static, shareable, read-only HTML report.
- `export-patch`: produces a patch removing selected hunks (stdout or state dir) for the user to review/apply themselves.
- v0.1 README: quickstart (≤ 5 min), screenshot placeholder, **data-flow section** (exactly what is sent to which LLM provider).

*Checkpoint:* (a) **Usability walk-through:** starting from a fresh machine with Python, a person who doesn't know git internals can, without reading docs, go from one command to answering "is it safe to merge and what should I check?" in under 3 minutes — with and without an AI key; (b) automated accessibility check (axe) reports no serious/critical violations; keyboard-only navigation works; (c) terminal, PR-comment Markdown, HTML report, and UI use the same headline and wording; (d) the "tell the agent → fix → Check again" loop shows progress correctly; (e) uncommitted and new untracked files made by an agent appear in the result; (f) repo and `.git` byte-identical before/after. Tag v0.1.0.

### Phase 4b — Deferred Detectors & Requirements → **release v0.1.x** · U5, U7, U8, U11–U16
Build only after v0.1 is in users' hands and its feedback is reviewed.
- **Config & CI (U5):** env files, CI workflows, Docker/compose, nginx, appsettings, YAML/TOML/INI.
- **Sensitive areas:** migrations/SQL, auth, crypto, payments, infra.
- **Leftovers (U7):** debug prints/logs, `debugger`, commented-out code blocks, new TODO/FIXME.
- **Deletions (U8):** deleted files, large removed blocks, removed docs/comments.
- **Stubs & placeholders (U11):** `NotImplementedError`/`throw new Error("TODO")`, `return true`/`return []` replacing logic, hard-coded IDs/URLs/credentials/dates, mock/fake data in non-test paths.
- **Error-handling degradation (U12):** empty `catch`/`except: pass`, catch-all added, `raise`/`throw` removed, logging of errors removed, errors replaced by silent defaults.
- **Work loss (U13):** using read-only `git log`/`blame`, flag hunks that revert lines changed by *other authors* in recent commits (configurable window), or re-introduce code previously deleted.
- **Requirements input level:** user story, FR list, Gherkin, acceptance criteria (pasted, file, or issue URL) parsed into criteria the user confirms.
- **Requirement coverage (U15):** each criterion ✅ Implemented · ⚠️ Partial · ❌ Missing with supporting changes and whether tests cover it.
- **Requirement drift score (U14):** `Ticket focus 85% · Unrelated 15%` with breakdown by theme; weighted by meaningful change (formatting and supporting changes excluded).
- **"What surprised me?" (U16):** important findings not mentioned in the Review Contract/story/PR text, ranked by unexpectedness × importance, shown near the top.
- UI: *Requirements* filter, story/ticket paste parsed into requirements, "What surprised me?" in Summary details.

*Checkpoint:* with a user story, `check` reports one missing criterion, one partial, drift %, and surprises; fixtures for U5, U7, U8, U11–U13 are detected with evidence. Tag v0.1.x.

### Phase 5 — Behavioral Change Analysis · U17–U19
Scope asks "did it change things it shouldn't?"; behavior asks "what can users now do, no longer do, or newly need permission for?" Static analysis cannot see everything, so findings are "potential" with confidence and evidence.
- **Permission & visibility detector (U18):** before→after of role/claim conditionals, feature flags (including flipped defaults), authorization policies/decorators/middleware, route guards, menu/nav visibility, API auth requirements. Direction: **Restricted** · **Expanded** (treat as potential security issue, High) · **Changed**.
  ```
  Reports menu   Before: Admin, Manager   After: Admin only   (Restricted)
  Order API      Before: Authenticated    After: Admin         (Restricted)
  ```
- **Frontend regression pack (U17):** routes removed/unregistered/hidden, menu/nav items removed or reordered, buttons/actions removed or conditionally hidden, pages/components deleted — even with no logic change. React, Vue, Angular, and server templates (Razor/Blade/Jinja) at a basic level.
- **Capability-loss detector (U19):** removed/disabled endpoints, handlers, exports, CLI flags, UI actions, parameters; **tightened behavior** (fuzzy → exact search, new required fields, stricter validation, lower limits). If the removal is in the contract, mark "intended removal" but still list it.
- **Behavioral Delta** (shown to users as **"What changed for users"**; top of every report's details — likely the most-read section; replaces the Phase 2 basic behavior watch): **Added · Changed · Removed · Restricted · Expanded · Shared impact** (shared impact filled in Phase 6), in plain user language.
- Pattern packs per language/framework, extensible via config. Start with Python, JS/TS (React), C#, Java.
- UI: the most important behavior changes appear in plain words in the Summary's top issues and Please-check list ("Managers can no longer see Reports"); full before→after table under the *Behavior* filter in All changes.
- Command: `verifypr impact`.

*Checkpoint:* fixture where the Reports menu role check narrows from Admin+Manager to Admin, an Export button is removed, and search becomes exact-match → all three appear in the Behavioral Delta with evidence and Please-verify items.

### Phase 6 — Impact Radius & Team Knowledge → **release v0.2** · U5, U20–U24
- **Usage graph — deliberately simple:** only a **file dependency graph**, an **import graph**, and a **route graph** (route tables/registrations). No whole-program analysis: no DI resolution, call graphs, or data-flow tracking. Bounded depth; says when truncated. All results are labeled **"Approximate impact"**, and the registries below fill the gaps.
- **Impact radius / blast radius (U20):** `CustomerForm.tsx → used by Admin Portal · Sales Portal · Supplier Portal (3 roles)`. Shared component (≥ 2 areas) = Medium; High if behavior (not styling) changed.
- **Team knowledge registries** (optional, in `.verifypr.yml` or `--registry file`; declared = authoritative, inferred fills gaps; each entry labeled declared/inferred):
  ```yaml
  areas:          { Admin: ["apps/admin/**"], Sales: ["apps/sales/**"] }
  shared_assets:  { CustomerForm: { affects: [Admin, Sales, Supplier] },
                    InventoryService: { affects: [Orders, Purchasing, Warehouse] } }
  business_flows: { "Create Order": { code: ["services/OrderService*"] },
                    "User Login": { code: ["auth/**"] }, "Customer Checkout": {} }
  consumers:      { "GET /customers": [Web Portal, Mobile App, Reporting Service] }
  ```
  `verifypr registry suggest` prints inferred entries to stdout; the tool never writes the registry.
- **Scope direction (U21):** compare intended audience (contract/story/ticket, or inferred) with detected: ⚠️ **Overreach** (shared component affects Admin, Manager, Sales; only Sales intended) or ⚠️ **Under-reach** (all roles intended; only Admin path changed).
- **Critical-flow impact (U23):** `Affected: ✓ Create Order ✓ Generate Invoice` in business language.
- **Data contracts + API consumers (U22):** fields removed/renamed/type-changed/newly required in OpenAPI/proto/GraphQL/DTO/serializers (`customerName → customerFullName`); list known consumers (declared in the registry, plus simple text matches of the endpoint path in the repo, labeled "approximate"; note that external consumers may exist).
- **Operational impact (U5):** new/changed env vars, ports, flags; "deployment config required".
- **Test confidence (U24):** `Areas changed 8 · covered by tests 3 · uncovered 5`, listing uncovered areas (heuristics + existing coverage reports if present; never runs the project's tests unless opted in).

*Checkpoint:* fixture with a shared `CustomerForm`, a registry, a renamed response field, and a new env var → report shows declared blast radius, overreach warning, affected flows, consumers, operational note, and test-confidence numbers. Tag v0.2.0.

### Phase 7 — Agent Accountability & Reviewer Output · U2, U25–U27
- **Claims verifier (U25):** claims from (a) fenced `agent-claims` block in PR body, (b) `.agent-claims.json/.yml` in the diff, (c) `Agent-Claim:` commit trailers, (d) LLM-extracted from the PR description ("inferred"). Each ✅ supported / ⚠️ unverified / ❌ contradicted with evidence; deterministic checks first ("no API change" → contract/route diffs; "no schema change" → migrations/models; "refactor only" → behavior-changing hunks).
- **Description-vs-diff check (U25):** things the PR description says that the diff doesn't do, and significant things the diff does that the description omits.
- **Agent plan verification (U26):** `verifypr plan` prints a plan schema + paste-ready agent instruction; `--plan plan.json` ingests `{goal, files_expected, areas_expected, assumptions}`; report **Intent divergence** (`Expected 5 files · Actual 21 · Unexpected areas: Billing, Reporting, Auth`). The plan is a claim: it can never widen allowed scope without user confirmation.
- **Please-verify generator, full version (U27):** deduplicated, prioritized (severity × confidence), ≤ ~10 items by default, concrete yes/no checks a non-author can do, each linked to evidence, no generic filler ("check for bugs"). Exportable state.
- **Safe Change Score (U27, informational):** `Intent alignment 92% · Behavioral risk 18% · Scope-expansion risk 12% → 83/100`; deterministic formula documented in `docs/scoring.md`; always shows breakdown; never affects verdict/exit code unless `tolerances.min_safe_score` is set. **Hidden by default** so people read the specific risks instead of a number: shown only with `show_score: true` / `--show-score`, and then only in Details — never in the headline, summary, or PR comments.
- **Split suggestion (U2):** propose splitting a tangled PR into coherent change sets (by theme), with a patch per group exported outside the repo.
- Reviewer outputs: `describe` (title, description incl. "Changes not asked for" and "What changed for users"), `ask "question"` (grounded answer with citations), `changelog`, `verify-list`, `claims`.
- Agent-integration snippets (docs): paste-ready text for CLAUDE.md / Cursor rules telling agents to declare a plan, stay in scope, and emit an `agent-claims` block.

*Checkpoint:* fixture PR with a false "no schema change" claim and a 5-file plan vs 21 changed files → ❌ contradicted claim, divergence report, split suggestion with 3 themes; the score appears (with breakdown) only when `--show-score` is passed.

### Phase 8 — Integrations & Opt-in Features → **release v0.3** · U28, U29
All writes in this phase are **opt-in and off by default**, and every one of them is blocked while **View only mode** is on (§1.4.7).

| Feature | Enable with | What it changes |
|---------|-------------|-----------------|
| Post to GitHub (sticky comment per command with `<!-- verifypr:<cmd> -->`, **Check Run** `verifypr`, description section between markers) | `--post` / Action input | Writes to the PR on GitHub, never to git |
| Task tracker lookup (GitHub Issues, Jira, Azure Boards, ClickUp, Linear) | tracker config + read-only token env var | Network read; ticket text sent to the LLM |
| Write summary to ticket | `--post-to-tracker` | Adds a ticket comment |
| Git hook / agent hook install | `verifypr hooks install` | Writes `.git/hooks` or agent settings |
| Export Review Contract into repo | `intent init --export` | Creates `.review-contract.yml` |
| **Revert unintended hunks** | `features.revert: true` + explicit click/flag | Edits working-tree files, local mode only |
| Watch mode | `verifypr watch` | Long-running, read-only |

- **PR mode:** `--pr owner/repo#123` via `GITHUB_TOKEN` (REST, `httpx`) behind `PRSource`/`PRSink` interfaces.
- **GitHub Action** (`action.yml`) on `pull_request` (`opened`, `synchronize`, `reopened`); fork-safe (no secret exposure; document `pull_request_target` risks; never check out untrusted code with secrets). Optional slash commands (`/verifypr check`, `/verifypr ask …`).
- **Delta since last check (U28):** store the last-checked head SHA (in the sticky comment's hidden metadata or state dir) and report only what changed since, flagging new scope added after review.
- **Task trackers (U29):** `TaskSource` interface; auto-detect IDs from branch/commits/PR (`PROJ-123`, `AB#123`, `CU-abc123`, `#123`) or `--task ID|URL`; fetch title, description, acceptance-criteria field, checklists, optionally comments; feed into Requirements mode; graceful fallback to Describe/Auto; report names the ticket checked against. UI gets a **"Link a task"** option.
- **Revert (opt-in):** refuse on dirty tree unless confirmed, save backup patch in state dir first, `revert --undo` restores byte-for-byte; never in PR/CI mode. UI revert buttons appear only when enabled.
- **Hooks:** `check --staged` as pre-commit; documented Claude Code hook / Cursor rule to warn or block out-of-scope edits during an agent session.

*Checkpoint:* real test PR on a scratch repo: Check Run + single updating comment; a second push shows "delta since last check"; a branch `PROJ-123-…` pulls a mocked Jira ticket; revert works only when enabled and undo restores. Tag v0.3.0.

### Phase 9 — Hardening & Open-Source Readiness → **v1.0**
- Docs: `architecture.md`, `commands.md`, `review-contract-spec.md`, `agent-claims-spec.md`, `registries.md`, `scoring.md`, `ui.md`, `agent-integration.md`, `configuration.md`, `trackers.md`.
- CONTRIBUTING (dev setup; how to add a detector, pattern pack, LLM provider, git platform, tracker), CODE_OF_CONDUCT, SECURITY.md (prompt-injection and secret policy), issue/PR templates, CHANGELOG.
- `examples/` with before/after reports for every problem in §2.
- **Evaluation set:** labeled fixture PRs (one per U-ID plus realistic mixed agent PRs) with precision/recall per detector tracked in CI; publish results in README.
- Performance: large monorepo diff (≥ 5k changed lines) completes within a documented budget.
- PyPI trusted-publishing release workflow, badges.

*Checkpoint:* fresh clone → quickstart in under 5 minutes; evaluation report generated; tag v1.0.0.

---

## 5. Output Formats

### 5.1 Report (`explain` / `check --format markdown`) — sections appear as their phase is built
```markdown
## ⚠️ 3 changes weren't asked for
Checked against: PROJ-123 "Add customer segmentation" — 4 requirements: 3 done, 1 partly done

**Top issues**
1. Login settings were edited (auth/session.py) — *Important · Sure* — [why]
2. A test was changed to pass instead of the code being fixed — *Important · Likely*
3. A shared form also used by Sales and Supplier portals changed — *Worth a look · Sure*

### ✅ Please check before approving
- [ ] Reports remain visible to Managers
- [ ] Customer export still works

**Next step:** paste the "fix this" prompt below to your coding agent, or mark items as fine.

<details><summary>See details</summary>

Compared: your branch + unsaved changes + 3 new files, with `main`

### 😮 What surprised me?
- A database change was added — *Important · Sure*
- Login rules were changed — *Important · Likely*

### What changed for users
- **New:** Segment filtering
- **Works differently:** Search now needs an exact match
- **Removed:** Export button
- **Fewer people can use it:** Reports are now Admin-only
- **Also affects:** Admin, Sales and Supplier portals (shared customer form)

### Changes not asked for
| File | Lines | Why it was flagged | How important · How sure |
|------|-------|--------------------|--------------------------|

### Tests & safety checks
- A test's expected result was changed to match the new code (test_orders.py:42) — *Important · Sure*

### Who else this affects
*(approximate)* Other areas using changed files · Key business flows · Apps calling changed APIs · Changed API fields · Deployment/config needs · Changes without tests

### Did the agent do what it said?
What it claimed vs. what the diff shows · Planned vs. actual files · PR description mismatches

### Numbers
3 not asked for · 1 not sure · 14 asked for · 6 needed for the change · 2 allowed by your rules
How much is about the task: 85%

### Prompt for your coding agent
<copy-ready text listing unrequested changes with file/lines>
</details>

<sub>verifypr vX · model: Y · tokens: N · input level: … · skipped: …</sub>
```
Also `--format json` (stable, versioned schema) and `--format html`.

---

## 6. Tech Stack & Layout

### 6.1 Stack & conventions
- Python 3.10+, `pyproject.toml`, `src/verifypr/` layout, PyPI-publishable. Must work on Windows, macOS, Linux.
- Pydantic v2 · Typer CLI (`verifypr`) · FastAPI + uvicorn (`[ui]` extra) · `httpx`.
- Config `.verifypr.yml` (model, ignore globs, `allow:` rules, tolerances defaults, protected areas, pattern packs, registries, tracker settings, custom instructions). Precedence: env (secrets) > CLI > config > defaults.
- Keys/tokens: precedence **env var > OS keychain (`keyring`) > session-only memory**. Users can enter keys in the UI (Phase 4 "AI provider setup") or with `verifypr key set` (hidden prompt). Never in plain files, config files, browser storage, CLI arguments, logs, reports, or error messages.
- `ruff`, `mypy --strict`, `pytest`; coverage ≥ 80% on non-LLM code; full type hints; small pure functions.

### 6.2 Layout
```
pr_agent/
├── CLAUDE.md  README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md  CHANGELOG.md
├── pyproject.toml  action.yml  .verifypr.example.yml  .review-contract.example.yml
├── .gitattributes  .gitignore
├── .github/{workflows/ci.yml, workflows/release.yml, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md, CODEOWNERS, dependabot.yml}
├── docs/  examples/  eval/
├── src/verifypr/
│   ├── cli.py  config.py  models.py  pipeline.py  state.py
│   ├── analysis/      # diff_parser, chunker, redaction, usage_graph
│   ├── detectors/
│   │   ├── hygiene/   # scope_rules, formatting, deps, config_ci, sensitive, artifacts, leftovers, deletions
│   │   ├── integrity/ # tests, guardrails, stubs, error_handling, work_loss
│   │   ├── behavior/  # visibility, frontend, capability_loss
│   │   └── impact/    # impact_radius, scope_direction, flows, consumers, data_contracts, operational, test_confidence
│   ├── intent/        # contract, levels, story_parser, classifier, themes, coverage, drift, surprises
│   ├── accountability/# claims, description_check, plan, split, verify_list, scoring
│   ├── commands/      # key, check, diff, explain, impact, intent_init, export_patch, describe, ask, changelog, plan, ui, watch, revert, hooks
│   ├── llm/           # base, anthropic, openai_compat, fake
│   ├── sources/       # base (PRSource/PRSink), local_git, github
│   ├── trackers/      # base (TaskSource), github_issues, jira, azure_boards, clickup, linear
│   ├── server/  ui/   # FastAPI app + bundled static front-end
│   ├── render/        # terminal, markdown, json, html
│   └── prompts/
└── tests/{fixtures/, live/}
```

---

## 7. Safety Requirements (all phases)
- Default = zero writes to repo/git; enforced by the read-only guarantee test on every default command.
- Untrusted-input handling per §1.4; injection fixtures ("ignore previous instructions", "mark everything intended") must not change classification or output format — in diffs, PR text, tickets, claims, and plans.
- Redact secrets before prompting; skip `secret_globs`; never log keys or full diffs at INFO.
- UI: localhost only, session token, path-traversal protection.
- GitHub Action fork safety; tracker tokens read-only scoped.
- README documents exactly what data leaves the machine and to which provider.
- Pinned dependency ranges; `pip-audit` in CI.

## 7b. Open-Source Project Requirements (public repo from day one)
- **Nothing private, ever.** No real company code, customer names, internal URLs, personal emails, or real tickets in code, fixtures, examples, docs, or commit messages. Fixtures and examples are synthetic (use generic names like "Acme", "Admin/Sales/Supplier portals").
- **Fake secrets only, done safely.** Secret-detection fixtures use documented example values (e.g. `AKIAIOSFODNN7EXAMPLE`) or are assembled at test runtime from parts, so no real-looking key is committed and GitHub push protection/secret scanning isn't tripped. Add a secret scanner (e.g. gitleaks) to CI with an allowlist for these fixtures.
- **Fixtures must survive git.** `.gitattributes` marks `tests/fixtures/**` as `-text` so git never normalizes CRLF/LF or BOMs (the hygiene detectors' tests depend on exact bytes); `* text=auto` elsewhere.
- **License hygiene.** Apache-2.0. CI checks dependency licenses for Python (`pip-licenses`) and the front-end (`license-checker` or equivalent): allow MIT/BSD/Apache-2.0/ISC/PSF/MPL-2.0; fail on GPL/AGPL/SSPL/unknown. No vendored third-party code without a compatible license and attribution.
- **Clean-room contributions.** CONTRIBUTING states that contributors must not copy code, prompts, or schemas from other PR-review tools. Use the **DCO** (`git commit -s`, checked in CI) rather than a CLA.
- **Security reporting** via GitHub private vulnerability reporting; SECURITY.md lists supported versions and response expectations. No personal email in the repo.
- **Code of Conduct:** Contributor Covenant 2.1. The enforcement contact is a placeholder `<project contact>` the maintainer fills with a project-only address. Never commit a personal email.
- **CI safe for forks.** All tests run without secrets (`FakeLLM`, recorded/mocked HTTP). Live LLM/tracker tests run only via manual `workflow_dispatch` by maintainers, never on fork PRs. No `pull_request_target` that checks out PR code. Actions pinned to commit SHAs; minimal `permissions:`; Dependabot for pip, npm, and Actions.
- **Detector feedback loop.** Issue templates **"False alarm"** (it flagged something fine) and **"Missed change"** (it missed something) ask for a minimal synthetic snippet, never real code. Confirmed reports become new fixtures in `eval/`.
- **Dogfooding.** From v0.1, the project runs its own tool on its PRs in rules-only, view-only mode (no secrets needed), and the PR template asks "What was this change for?" so the check has intent.
- **Approachable for contributors.** `good first issue` labels for new pattern packs/frameworks; CONTRIBUTING explains how to add a detector, pattern pack, fixture, LLM provider, git platform, or tracker; `make`/`nox` tasks for setup, lint, test.
- **Versioning & stability.** SemVer; Keep a Changelog; JSON output has a versioned schema; config and JSON stability promised from v1.0 (breaking changes before 1.0 are listed in CHANGELOG).
- **Names of other products.** Mention third-party tools (Claude Code, Cursor, Jira, Azure DevOps, ClickUp, Linear, GitHub) only by name to describe compatibility. No logos, and no wording that implies affiliation or endorsement.
- **Honest README.** Includes a **Limitations** section (static analysis is approximate, AI checks can be wrong, findings are prompts to check, not proof), the data-flow section, and "no telemetry".

## 8. Roadmap (after v1.0 — do not build now)
**First priority after v1.0:** a standalone installer that needs no Python (Windows/macOS/Linux) and a VS Code extension, so non-developers can use it · Optional `review`/`improve` extras (kept out of core) · GitLab/Bitbucket/Azure DevOps PR sources · VS Code extension with inline scope highlights · intent drift across a series of PRs · learned team policies (suggest `forbidden` areas from history) · Mermaid impact diagrams · business glossary mapping · runtime/telemetry-based consumer discovery · **Agent session comparison**: read the coding agent's session log (e.g. Claude Code local transcripts or hook-logged tool calls; Cursor where possible) to show "Visited 43 files · Modified 6 · Auth was modified although it wasn't in the plan", separating deliberate changes from accidental edits made while exploring. Must be opt-in, local-only, and redact secrets/prompts; builds on plan-vs-actual (U26) and the Phase 8 hooks.

## 9. Testing Requirements
- **One fixture per problem ID (U1–U29)** asserting it is detected with correct severity/direction and evidence; plus realistic mixed agent PRs.
- Detector unit tests per language/framework pattern pack.
- Read-only guarantee test for every default command (working tree + `.git` hash unchanged).
- Classification: unsure ⇒ ❓, never ✅; supporting changes linked correctly.
- Auto mode: no prompts/config needed, labeled "inferred", intent-based findings ≤ WARN, rule-based critical findings (e.g. committed secret) still FAIL.
- Default comparison includes committed branch changes, uncommitted edits, and new untracked files, without running any git write command; non-git folder, missing base, and detached HEAD give friendly messages.
- Headline honesty: rules-only clean result never says "Looks good".
- Check again: correct fixed / still open / new counts across two runs.
- Allow rules: suppress only the matching kind + path, and suppressed findings are counted, not hidden.
- Consent: no code is sent to an LLM before the first-send consent (interactive) or explicit provider config (CI).
- Basic behavior watch (Phase 2): role-check, route/menu/button removal, and shared-file usage fixtures.
- Requirements/story/Gherkin/ticket parsing → criteria; missing/partial detection.
- `FakeLLM` pipeline tests incl. malformed JSON retry; opt-in `tests/live/` against real models (skipped unless env var set).
- Golden-file tests for Markdown/HTML/JSON renderers.
- Server: token required, localhost-only, path traversal rejected.
- Opt-in features: disabled ⇒ refuse/hidden; revert + undo byte-for-byte; mocked HTTP for GitHub and trackers; tokens never in logs.
- Scoring deterministic and never changes exit code by default; hidden unless `show_score`/`--show-score`; never in headline, summary, or PR comments.
- Impact results from the usage graph are always labeled "approximate".
- LLM fallback: a chunk returning malformed JSON twice, timing out, or rate-limited is marked "Not sure" while the run completes; invented file/line references are dropped/flagged; the report counts skipped parts.
- Git edge cases: shallow clone, submodule pointer change, sparse checkout, LFS pointer, linked worktree, case-only rename, and empty repo each produce a friendly message or correct result, never a crash.
- API keys: key entered in UI or `key set` is stored only in the keychain (or memory if "Remember" is off / View only); never appears in logs, reports, HTML, JSON, error messages, browser storage, or process arguments (asserted by scanning all outputs for a canary key); env var overrides keychain; Test connection sends no code; `--offline` disables key entry.
- Repo hygiene (§7b): secret scanner passes with only allowlisted fake fixtures; fixtures' CRLF/BOM bytes survive checkout on Windows and Linux; dependency-license check passes; the whole test suite runs green with no secrets set.
- Prompt-injection fixtures across every untrusted input.
- **View only tests:** with `--view-only`, every command and UI flow leaves the repo, `.git`, **and the state dir** byte-identical (hash before/after); action buttons and write endpoints are absent or refuse (server returns 403 for any write route); opt-in features refuse even when enabled in config; a toggle locked by flag/env cannot be switched off; `--offline` makes zero network calls (asserted with a network-blocking fixture) and still produces a rules-only report.
- **UX tests:** UI copy uses only the §1.5 glossary (a test fails if internal terms like "hunk", "contract", "unintended", "blast radius", "behavioral delta", "severity", "confidence", "Please verify", or U-IDs appear in UI strings or default terminal/PR/report output); summary shows ≤ 3 top issues; headline and status never contradict the numbers; empty, no-key, error, and large-diff states render friendly messages with a fix; axe accessibility check in CI; agent fix prompt lists exactly the flagged changes.

## 10. Working Style for Claude Code
- One phase at a time; stop at each checkpoint. Commit each logical unit with Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Before each module, state in 1–2 lines what it does and its public interface.
- Every detector finding must reference its problem ID (U-number) so coverage is traceable — internally only; IDs never appear in user-facing output.
- Every user-facing string follows §1.5: plain words, a "Why?", and a next step. When adding a finding type, also add its plain-language title, explanation, Please-check wording, and agent-fix wording.
- Prefer small, readable code. Do not add features outside this spec (or from later phases) without asking.
- If ambiguous, pick the default stated here, note it in the commit message, continue; ask only when blocked.
- Keep prompts, Pydantic models, and tests in sync.
- Run `ruff`, `mypy`, `pytest` before declaring a phase done; report results honestly, including failures and skips.
- Don't guess external APIs (Anthropic SDK, GitHub REST, FastAPI, Typer, tracker APIs); check docs or installed source first.

## 11. Definition of Done per Release
- **v0.1:** `verifypr` / `check` works with zero input or a one-sentence description; sees committed, uncommitted, and new files; detects U1, U3, U4, U6, U9, U10 plus basic U17, U18, U20 per fixtures; honest headlines; Check again loop; allow rules; consent before first AI send; local UI flow works; reports in MD/JSON/HTML; zero repo/git writes; CI green on 3 OSes; one-command start works with no AI key; View only mode (incl. `--offline`) saves nothing and sends nothing; usability walk-through and accessibility checks from the Phase 4 checkpoint pass.
- **v0.1.x:** U5, U7, U8, U11–U16 per fixtures; Requirements mode (story/FR/Gherkin/issue) with coverage, drift, and "What surprised me?".
- **v0.2:** Behavioral Delta, visibility/permission, frontend regression, capability loss, impact radius, registries, scope direction, flows, consumers, data contracts, operational, test confidence (U17–U24).
- **v0.3:** claims, description check, plan divergence, full Please-check list, Safe Change Score (hidden by default), split suggestion, describe/ask/changelog; GitHub Action + Check Run + delta-since-last-check; trackers; all writes opt-in (U25–U29).
- **v1.0:** docs complete, evaluation set with published precision/recall, examples for every U-ID, PyPI release.
