# precommit-missing – No pre-commit

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** yes

## What the check looks for

Checks that `.pre-commit-config.yaml` exists.

## Why it matters

Pre-commit catches secrets (gitleaks), large files and formatting errors before the commit.

## Steps

1. The fix (`f`) adds a basic configuration: gitleaks, trailing whitespace, end-of-file, large files, detect-private-key and, depending on the ecosystem, ruff or eslint.
2. After checking out the branch, run `pre-commit install`.
