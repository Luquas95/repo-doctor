# committed-artifacts – Committed build artifacts and caches

**Category:** Maintenance · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Looks among tracked files for the directories `node_modules`, `__pycache__`, `.venv`, `venv`, `.tox`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.next`, `.nuxt`, `.gradle`, a `target/` directory (only when `Cargo.toml` is in the root) and the files `*.pyc`, `*.pyo`, `.DS_Store`, `Thumbs.db`, `desktop.ini`. Each directory or file is one finding with a file count. `dist/` and `build/` are not reported because they sometimes hold intentional output.

## Why it matters

Generated files bloat history, cause needless conflicts, can reveal local paths and may contain third-party code without a license. Deleting them does not remove them from history.

## Steps

1. Add the path to `.gitignore` (the `gitignore-incomplete` check helps).
2. Stop tracking it but keep it on disk: `git rm -r --cached <path>` and commit.
3. If the artifact is large, consider cleaning history too (`git filter-repo`) – rewriting history is your call.
