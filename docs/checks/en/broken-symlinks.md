# broken-symlinks – Broken symlinks

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Walks the tracked symlinks (mode 120000), reads their target and checks that the target exists in the working tree. Relative targets are resolved from the symlink's directory, absolute ones are used as they are. Nothing is followed beyond the plain existence check. Bare repositories are skipped.

## Why it matters

A broken symlink is usually left over after a target was moved or deleted. Absolute paths from someone else's machine do not work for other people, and tools (builds, editors) fail on them.

## Steps

1. Fix the target: `ln -sfn <right target> <symlink>` and commit.
2. Or delete the symlink (`git rm <symlink>`) if it is no longer needed.
3. For symlinks to generated files, consider a real copy or a build step that creates them.
