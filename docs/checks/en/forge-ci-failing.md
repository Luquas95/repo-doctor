# forge-ci-failing – CI fails on the default branch

**Category:** Hosting · **Severity:** MED · **Automatic fix:** no

## What the check looks for

The last CI run on the default branch failed (GitHub Actions, Gitea/Forgejo Actions via commit status, GitLab pipelines).

## Why it matters

A broken main branch blocks others and hides new bugs.

## Steps

1. Open the run on the web (`w` on the repo card) and fix the cause.
