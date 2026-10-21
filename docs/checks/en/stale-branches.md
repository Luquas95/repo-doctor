# stale-branches – Stale local branches

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Reports local branches that are merged into the default branch or have had no commit for longer than `limits.stale_branch_days` (default 90). Deletes nothing.

## Why it matters

Old branches clutter the overview and blur what is work in progress.

## Steps

1. Review them (`git log main..<branch>`) and delete them by hand: `git branch -d <branch>`.
