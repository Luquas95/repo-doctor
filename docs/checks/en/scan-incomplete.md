# scan-incomplete – Incomplete scan

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

A history check (secrets, large files) did not finish within the `limits.history_timeout_s` time limit and was stopped cleanly.

## Why it matters

The result of that check may be incomplete – a finding in the unscanned part of the history may have stayed hidden.

## Steps

1. Increase `limits.history_timeout_s` in `config.toml` or in the repo's `.repo-doctor.toml`.
2. Alternatively install `gitleaks`, which is faster on large repos.
