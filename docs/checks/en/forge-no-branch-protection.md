# forge-no-branch-protection – Default branch without protection

**Category:** Hosting · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

The default branch has no protection on the hosting (where the API can tell; otherwise the check is skipped). Not reported for archived repos.

## Why it matters

Without protection the main branch can be force-pushed or deleted by mistake.

## Steps

1. Turn on branch protection in the repo settings on the hosting (no force push or deletion, optionally required review/CI).
