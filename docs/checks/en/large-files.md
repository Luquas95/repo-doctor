# large-files – Large files outside Git LFS

**Category:** Maintenance · **Severity:** MED (binaries LOW) · **Automatic fix:** no

## What the check looks for

Looks for files over `limits.large_file_mb` (default 5 MB) and binaries over `limits.binary_file_kb` (default 1 MB) in the current tree and in history (`git rev-list --objects --all` + `git cat-file --batch-check`). Files managed by Git LFS are not reported.

## Why it matters

Large blobs slow down every clone and fetch, and deleting them does not remove them from history.

## Steps

1. Use Git LFS for new binaries (`git lfs track "*.zip"`).
2. Remove them from history with `git filter-repo --strip-blobs-bigger-than 5M` (rewrites history – the decision is yours).
