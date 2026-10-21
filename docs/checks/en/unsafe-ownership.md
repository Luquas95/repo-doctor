# unsafe-ownership – Untrusted owner

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Git refused to work with the repo because its folder belongs to a different user than the one repo-doctor runs as (`fatal: detected dubious ownership in repository`). Typically a repo copied from another disk, a mounted volume, a container or a folder created with `sudo`.

## Why it matters

A foreign repo can set commands in `.git/config` that git would run (hooks, filters, `core.fsmonitor`…), which is why git refuses it by default. For security reasons repo-doctor does not work around this in any way: it runs no further git command in it, does not read its `.repo-doctor.toml` and computes no score (triage shows `–` and the group **CANNOT BE CHECKED**).

repo-doctor never sets `safe.directory` itself and never overrides it with `git -c` either.

## Steps

1. Check who owns the folder: `ls -ld <path>`.
2. If it is your repo with the wrong owner, fix the owner: `sudo chown -R "$USER" <path>`.
3. If you trust the repo and do not want to change the owner, allow it by hand: `git config --global --add safe.directory <path>`.
4. Run the scan again.
