# deps-outdated – Outdated dependencies

**Category:** Maintenance · **Severity:** LOW (major MED) · **Automatic fix:** no

## What the check looks for

For direct dependencies (Python from `pyproject.toml`/`requirements*.txt`, npm from `package.json`) it looks up the latest version in the PyPI JSON API and the npm registry and tells major / minor / patch apart. Registry results are cached for 24 h (`limits.registry_cache_hours`). Skipped in offline mode.

## Why it matters

Old versions get harder to update the longer you wait; major releases often ship security fixes only in the new line.

## Steps

1. Apply patch and minor updates regularly (Dependabot / Renovate).
2. Plan major updates with the changelog and tests.
