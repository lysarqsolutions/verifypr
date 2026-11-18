# Contributing to VerifyPR

Thanks for helping! VerifyPR is built in phases described in [CLAUDE.md](CLAUDE.md). It is both the product spec and the rules for AI coding agents working on this repo. Please read it, especially §1 (principles and UX) and §7b (open-source rules).

## Development setup

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip install -e ".[dev]"
```

Before pushing:

```bash
ruff check . && ruff format --check . && mypy && pytest
```

All tests run without any API keys or secrets. Tests marked `live` (real AI providers) are skipped unless `VERIFYPR_LIVE_TESTS=1` is set; maintainers run those manually.

## Sign your commits (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/) instead of a CLA. Add a sign-off to every commit:

```bash
git commit -s -m "feat: add lockfile detector"
```

This adds `Signed-off-by: Your Name <you@example.com>`, certifying you wrote the change or have the right to submit it under the Apache-2.0 license. CI checks every commit in a pull request.

## Ground rules

- **Clean-room only.** Don't copy code, prompts, or schemas from other PR-review tools.
- **Nothing private.** No real company code, customer names, internal URLs, personal emails, or real tickets in code, tests, docs, or commit messages. Use made-up examples ("Acme", "Admin/Sales portals").
- **Fake secrets only.** Use documented example values (like `AKIAIOSFODNN7EXAMPLE`) or build them at test runtime. Put secret fixtures under `tests/fixtures/secrets/`.
- **Read-only by default.** Any new default command must be added to `tests/test_readonly_guarantee.py`.
- **Plain language.** New findings need a plain-language title, a one-sentence "why", and a "Please check" wording. Internal names (U-numbers, "hunk", "contract") must never appear in user-facing output.
- **Conventional Commits:** `feat:`, `fix:`, `docs:`, `test:`, `chore:`.

## Reporting detector mistakes

Use the **False alarm** or **Missed change** issue templates with a small made-up example. Confirmed reports become test cases.

## Security

Please don't open public issues for vulnerabilities. See [SECURITY.md](SECURITY.md).
