# conflict-markers – Leftover merge-conflict markers

**Category:** Maintenance · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Scans tracked text files (up to the secret scanner's size limit) for unresolved conflict markers: a line starting with `<<<<<<<`, followed by a `=======` line and then a line starting with `>>>>>>>`. All three must appear in order, so a bare `=======` underline in Markdown or an example in documentation is not reported. Findings are capped at 25 files.

## Why it matters

Leftover markers break builds and configuration and usually mean a half-resolved merge or rebase got committed. In data files and scripts they can cause silent errors at runtime.

## Steps

1. Open the file at the reported line and pick the right version (`git mergetool` or by hand).
2. Delete all three markers, run the tests and commit.
3. If the text is intentional (e.g. a conflict example in documentation), add the finding to the allowlist.
