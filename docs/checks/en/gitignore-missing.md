# gitignore-missing – No .gitignore

**Category:** Maintenance · **Severity:** MED · **Automatic fix:** yes

## What the check looks for

The repository has no `.gitignore`.

## Why it matters

Without it, `.env`, virtual environments, `node_modules` or build output are easily committed.

## Steps

1. The fix (`f`) creates a `.gitignore` for the detected ecosystem (Python, Node, Rust, Go).
