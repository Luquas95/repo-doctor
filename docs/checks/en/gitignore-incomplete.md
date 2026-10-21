# gitignore-incomplete – Incomplete .gitignore

**Category:** Maintenance · **Severity:** MED (without `.env`), otherwise LOW · **Automatic fix:** yes

## What the check looks for

Depending on the ecosystem it verifies (`git check-ignore`) that common entries are ignored: `.env`, `.env.*` and also `__pycache__/`, `.venv/`, `dist/` (Python), `node_modules/`, `dist/` (Node), `target/` (Rust), `*.test` (Go). The user's global excludes do not count – they are not shared with others.

## Why it matters

Missing rules lead to accidentally committed secrets and needlessly large repositories.

## Steps

1. The fix (`f`) adds the missing lines in a separate block with the comment `# repo-doctor: added <date>`, without duplicates.
