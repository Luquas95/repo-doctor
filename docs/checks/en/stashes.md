# stashes – Forgotten stashes

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Reports stashes older than `limits.stash_days` (default 30).

## Why it matters

A forgotten stash is work nobody knows about.

## Steps

1. Inspect it: `git stash show -p stash@{N}`.
2. Apply it (`git stash pop`) or drop it (`git stash drop stash@{N}`).
