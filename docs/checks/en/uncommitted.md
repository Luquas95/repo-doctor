# uncommitted – Uncommitted changes

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Reports modified, untracked and conflicted files (`git status`, without writing the index).

## Why it matters

Uncommitted work is not backed up anywhere and is easily lost.

## Steps

1. Commit it or stash it (`git stash push -m description`).
2. Add files that do not belong in the repo to `.gitignore`.
