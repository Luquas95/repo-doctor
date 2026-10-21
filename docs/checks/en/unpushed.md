# unpushed – Unpushed commits

**Category:** Git state · **Severity:** MED · **Automatic fix:** no

## What the check looks for

For each local branch it counts commits that are not on the upstream (or on any remote, if it has no upstream). Works with local data only – no `fetch`.

## Why it matters

Commits that exist only on this disk disappear with it.

## Steps

1. `git push` (or `git push -u origin <branch>` for a new branch).
