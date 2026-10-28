# line-endings – Inconsistent line endings

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Uses `git ls-files --eol` (the index state, i.e. what gets committed). Reports files with mixed line endings (both LF and CRLF in one file) and repositories where some text files are CRLF and others LF without a `.gitattributes` rule (`text`, `eol`). `.bat`, `.cmd`, `.ps1`, `.sln`, `.vbs` and `.reg` files may legitimately use CRLF.

## Why it matters

Mixed line endings add diff noise (the whole file shows as changed), break shell scripts (a `\r` after the shebang) and cause needless conflicts between systems.

## Steps

1. Add a rule to `.gitattributes`: `* text=auto` (or `*.sh text eol=lf`).
2. Normalize existing files: `git add --renormalize .` and commit.
3. Fix files with mixed endings in your editor or with `dos2unix`/`unix2dos`.
