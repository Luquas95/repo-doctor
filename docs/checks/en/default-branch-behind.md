# default-branch-behind – Default branch is behind the remote

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Compares the default branch with its upstream as of the last fetch (no network request). `repo-doctor scan --fetch` fetches first.

## Why it matters

You are working on an old state and risk conflicts.

## Steps

1. `git pull --ff-only`.
