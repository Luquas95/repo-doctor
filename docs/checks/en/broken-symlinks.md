# broken-symlinks – Broken symlinks

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Walks the tracked symlinks (mode 120000), reads their target and checks that the target exists among the tracked files. The target is computed from text only, from the symlink's directory, and its existence is decided from the list of tracked files; the disk is not touched. So a symlink to an untracked or ignored file is reported too (a clone will not have it). A symlink with an absolute path, a backslash (UNC), a drive letter or a target outside the repository (`..`) is reported as pointing outside the repository (it will not work elsewhere) and its target is never checked. Bare repositories are skipped.

## Why it matters

A broken symlink is usually left over after a target was moved or deleted. Absolute paths from someone else's machine do not work for other people, and tools (builds, editors) fail on them.

## Steps

1. Fix the target: `ln -sfn <right target> <symlink>` and commit.
2. Or delete the symlink (`git rm <symlink>`) if it is no longer needed.
3. For symlinks to generated files, consider a real copy or a build step that creates them.
