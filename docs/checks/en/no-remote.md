# no-remote – Repo without a remote (no backup)

**Category:** Git state · **Severity:** MED · **Automatic fix:** no

## What the check looks for

A repository with at least one commit has no remote.

## Why it matters

Without a remote there is no backup outside this disk.

## Steps

1. Create a repo on a hosting and add the remote: `git remote add origin <url>` and `git push -u origin main`.
