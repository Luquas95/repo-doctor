# project-docs-missing – Project documents missing

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Three independent sub-findings: **changelog** (the repo has tags but no `CHANGELOG*`, `HISTORY*`, `NEWS*`, `CHANGES*` or `RELEASES*` in the root, `.github/`, `docs/` or `.gitlab/`), **security** (a public repository without `SECURITY.md`; only when the hosting confirms visibility) and **contributing** (at least 3 authors but no `CONTRIBUTING*`).

## Why it matters

Without a changelog users do not know what changed in a release. Without SECURITY.md anyone who finds a vulnerability has nowhere to report it, so they publish it or stay silent. Without CONTRIBUTING every new contributor has to guess the rules.

## Steps

1. Keep the changelog in Keep a Changelog format, short and per release.
2. `SECURITY.md`: where to report (e-mail, private advisory) and how fast you respond.
3. `CONTRIBUTING.md`: how to run tests, code style, how to send a PR.
