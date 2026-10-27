# dependency-bot-missing – No automated dependency updates

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Applies to repositories that have at least one remote and a dependency manifest (`pyproject.toml`, `requirements*.txt`, `Pipfile`, `package.json`, `Cargo.toml`, `go.mod`, `Dockerfile`) but neither `.github/dependabot.yml` nor a Renovate configuration (`renovate.json`, `.renovaterc`, `.github/renovate.json`, a `renovate` key in `package.json`).

## Why it matters

Without a bot dependencies and base images are updated only when somebody remembers. Security fixes then reach the project months or years late.

## Steps

1. GitHub: add `.github/dependabot.yml` (ecosystems `pip`/`npm`/`cargo`/`gomod`/`docker`/`github-actions`).
2. Forgejo, GitLab and others: run Renovate and add `renovate.json`.
3. Set up groups and a weekly schedule so the PRs do not flood you.
