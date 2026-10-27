# deps-lock-drift – Lockfile out of sync with the manifest

**Category:** Security · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Compares the dependencies declared in a manifest with the lockfile in the same folder: `package.json` with `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock` or `pnpm-lock.yaml`, `pyproject.toml` with `uv.lock`, `poetry.lock` or `pdm.lock`, and `Cargo.toml` with `Cargo.lock`. Reports declared packages that are missing from the lockfile. Workspaces (npm/pnpm `workspaces`, `[tool.uv.workspace]`, Cargo `[workspace]`) are skipped because the lock lives in the root. Nothing is run or downloaded.

## Why it matters

A stale lockfile makes `npm ci`, `uv sync --locked` or `cargo build --locked` fail, or (worse) resolves the package differently than on a colleague's machine. The versions that were verified and scanned are then not the ones actually installed.

## Steps

1. Regenerate the lockfile: `npm install`, `uv lock`, `poetry lock` or `cargo update`.
2. Commit the lockfile change together with the manifest.
3. Install from the lockfile in CI (`npm ci`, `uv sync --locked`) so drift is caught immediately.
