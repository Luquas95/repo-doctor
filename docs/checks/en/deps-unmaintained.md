# deps-unmaintained – Abandoned or deprecated packages

**Category:** Maintenance · **Severity:** MED (abandoned LOW) · **Automatic fix:** no

## What the check looks for

Uses the PyPI and npm registry responses the scan already downloads for `deps-outdated` (no extra requests), for direct dependencies only. Reports: an npm package marked `deprecated` (MED, with the author's reason), a PyPI project with the classifier `Development Status :: 7 - Inactive` (MED) and a PyPI package whose latest release is older than 3 years (LOW). Development-only dependencies are skipped for "abandoned" and get LOW for `deprecated`. Requires network.

## Why it matters

An unmaintained package gets no vulnerability fixes and eventually stops working with new language versions. The author often says what to replace it with.

## Steps

1. Read the `deprecated` message, it usually points to a successor.
2. Find a maintained alternative, or take the code into your project (mind the license).
3. If the package is intentionally finished and stable (a small library), add the finding to the allowlist.
