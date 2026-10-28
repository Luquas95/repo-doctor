# lfs-not-applied – Git LFS files stored directly in git

**Category:** Maintenance · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Applies only to repositories whose `.gitattributes` contains `filter=lfs`. For files in HEAD larger than 1 KB it looks up the `filter` attribute and reports those that should go through LFS but are stored whole in git (an LFS pointer is only a few hundred bytes). Files are only read, nothing is downloaded.

## Why it matters

Such a file bloats every clone even though the team believes LFS handles it. It typically happens after a commit on a machine without `git-lfs` installed or when the rule was added afterwards.

## Steps

1. Install `git-lfs` and run `git lfs install`.
2. Convert existing files: `git add --renormalize <file>` and commit.
3. To convert history as well, use `git lfs migrate import --include="<pattern>"` (rewrites history – the decision is yours).
