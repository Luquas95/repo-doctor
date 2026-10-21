# forge-unknown-remote – Remote points to an unknown repo

**Category:** Hosting · **Severity:** MED · **Automatic fix:** no

## What the check looks for

The remote belongs to a connected hosting, but the API does not know the repo (404) or the token has no access to it (403) – a deleted, renamed or transferred repo.

## Why it matters

Both push and pull fail, and the backup you think exists does not.

## Steps

1. Check the repo on the hosting's website.
2. Fix the URL: `git remote set-url origin <new-url>`.
