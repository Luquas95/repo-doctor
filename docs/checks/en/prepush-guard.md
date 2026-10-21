# prepush-guard – No protection against pushing secrets

**Category:** Security · **Severity:** LOW · **Automatic fix:** yes (two variants)

## What the check looks for

A repo with a remote has no `pre-push` hook (neither in `.git/hooks` nor in the `core.hooksPath` folder) and no secret guard (`gitleaks`, `repo-doctor guard`, `detect-secrets`, `trufflehog`…) in `.pre-commit-config.yaml` for the `pre-push` stage.

## Why it matters

A secret you commit by mistake reaches the hosting with the push – and bots find it there within minutes. The check at push time is the last moment when fixing a purely local commit is enough.

## Steps

The fix offers two variants (you pick one):

1. **In the repo via pre-commit** (recommended, shared with others) – adds a local `repo-doctor guard` hook for the `pre-push` stage to `.pre-commit-config.yaml` (commit to the fixes branch). Everyone then activates it with `pre-commit install --hook-type pre-push`; the hook needs `repo-doctor` in PATH.
2. **Local only** – installs `.git/hooks/pre-push`, which runs `repo-doctor guard`. This is the only case where repo-doctor writes to `.git/hooks`, and only in your own repo (never in a repo owned by someone else; an existing custom hook is not overwritten). This variant is not offered when `core.hooksPath` is set.

`repo-doctor guard` scans only the commits about to be pushed (the range from the hook) with the built-in secret scanner. When it finds something it stops the push with a masked listing; hide a false alarm with the allowlist, or in exceptional cases bypass it with `git push --no-verify`.
