# deps-lockfile-missing – No lockfile

**Category:** Security · **Severity:** MED · **Automatic fix:** no

## What the check looks for

A manifest declares dependencies (`pyproject.toml`, `package.json`, an application's `Cargo.toml`, `go.mod`), but there is no lockfile next to it (`uv.lock`/`poetry.lock`, `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`, `Cargo.lock`, `go.sum`).

## Why it matters

Without a lockfile every install may pull different versions – the build is not reproducible and vulnerabilities cannot be checked reliably.

## Steps

1. Generate a lockfile (`uv lock`, `npm install`, `cargo generate-lockfile`, `go mod tidy`).
2. Commit it and install exactly from it in CI (`uv sync --locked`, `npm ci`).
