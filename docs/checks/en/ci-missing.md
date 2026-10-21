# ci-missing – No CI

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** yes

## What the check looks for

Looks for `.github/workflows/`, `.gitlab-ci.yml`, `.forgejo/workflows/`, `.gitea/workflows/`, Woodpecker, Drone, CircleCI, Travis and a Jenkinsfile.

## Why it matters

Without CI, bugs and regressions reach the main branch unnoticed.

## Steps

1. The fix (`f`) adds `.github/workflows/ci.yml` for the detected ecosystem (lint + tests).
2. For Forgejo/Gitea Actions, move the file to `.forgejo/workflows/`.
