# license-missing – No license

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** yes

## What the check looks for

There is no `LICENSE`, `LICENCE`, `COPYING` or `UNLICENSE` in the repository root.

## Why it matters

Nobody may legally use code without a license – not even when the repo is public.

## Steps

1. The fix (`f`) adds the license set by `license` in the configuration (default MIT; also ISC, BSD-2-Clause, Unlicense).
2. The name comes from `git config user.name`, the year from the current date.
