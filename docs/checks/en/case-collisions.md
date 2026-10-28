# case-collisions – Paths that differ only by letter case

**Category:** Maintenance · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Compares tracked paths (including directories inside paths) case-insensitively. If two distinct paths differ only by case (`README.md` and `readme.md`, `Docs/` and `docs/`), it reports them. For nested collisions the shortest common path is reported.

## Why it matters

Linux tells them apart, but macOS and Windows (default settings) do not: a clone there overwrites one file with the other, `git status` shows phantom changes and builds behave differently than elsewhere.

## Steps

1. Pick the name that stays and rename or delete the other: `git mv Docs docs-tmp && git mv docs-tmp docs`.
2. Merge the contents by hand (files with the same name differ), then commit.
3. Afterwards keep `core.ignorecase` consistent across the team (usually leave the default).
