# disk-usage – Large regenerable folders in an inactive repo

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no (Cleanup screen / `repo-doctor clean`)

## What the check looks for

For repositories without a commit for longer than `cleanup.inactive_days` (default 60 days) it adds up the size of typical regenerable folders – `node_modules`, `.venv`/`venv`, `target`, `dist`, `build`, `.next`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.gradle`, `.terraform` (the `cleanup.dirs` list). Only folders ignored by git (`git check-ignore`) that contain no tracked file count; symlinks are not followed. A finding is reported when the total exceeds `cleanup.min_mb` (default 200 MB).

## Why it matters

Dependencies and build output of old projects often take tens of GB, yet they can be recreated at any time (`npm ci`, `uv sync`, `cargo build`).

## Steps

1. Open the **Cleanup** screen (`6`): a table of repos with space to free; inactive repos without changes are preselected. Adjust the selection with Space; Enter moves the folders **to the trash** after confirmation (freedesktop Trash – they can be restored). Permanent deletion (`D`) needs two confirmations.
2. Or from the command line: `repo-doctor clean` (preview only) and `repo-doctor clean --apply` (to the trash). `--all` adds active repos, `--include-dirty` repos with uncommitted changes, `--duplicates` whole duplicate clones without changes.
3. repo-doctor never deletes anything tracked by git, anything outside the repository, a folder a running process uses (Linux `/proc`), or anything in a repo owned by someone else. It checks everything again right before deleting.
