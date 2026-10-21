# forge-mirror-drift – Local default branch differs from the hosting

**Category:** Hosting · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Compares the default branch name and its last commit locally and on the hosting (API only, no fetch). Being ahead locally is reported by `unpushed`; this is about a different name or commits from the hosting that are missing locally.

## Why it matters

You are working on a different state than the hosting has (typically `master` renamed to `main`).

## Steps

1. `git fetch` and `git pull --ff-only`.
2. After a rename: `git branch -m master main && git branch -u origin/main main && git remote set-head origin -a`.
