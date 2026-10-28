# deps-unpinned – Unpinned dependency versions

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Looks for dependencies whose version nothing fixes: in `package.json` the values `*`, `latest`, empty, git URLs and GitHub `user/repo` shorthands without `#ref`; in `requirements*.txt` lines without a version and `git+` URLs without `@ref`; in `pyproject.toml` dependencies `name @ git+...` without `@ref`; in `Cargo.toml` the version `*` and git dependencies without `rev` or `tag`. Ordinary ranges (`^1.2`, `>=2`) are not reported; the lockfile handles them.

## Why it matters

Such a dependency can resolve to different code on every install, including a new unreviewed version or a rewritten branch. Builds are not reproducible and a tampered version passes unnoticed.

## Steps

1. Pin the version: `requests==2.32.3`, `"lib": "1.4.2"` or `rev = "..."` in Cargo.
2. Pin git dependencies to a commit or tag (`#v1.2.0`, `@abc123`).
3. Leave ranges to the lockfile and Renovate/Dependabot.
