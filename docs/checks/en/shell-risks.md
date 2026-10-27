# shell-risks – Risky patterns in shell scripts

**Category:** Security · **Severity:** MED (some rules LOW) · **Automatic fix:** no

## What the check looks for

Reads `*.sh` and `*.bash` line by line (comments are skipped). Looks for: a downloaded script piped straight into a shell (`curl ... | sh`, `wget ... | sudo bash`), `chmod 777`, `rm -rf` with a path starting with a variable (`rm -rf "$DIR"/*`) and `eval` with a variable (all MED). LOW: a script with at least 15 command lines and an `sh`/`bash`/`zsh` shebang that has no `set -e`, `set -u` or `set -o pipefail`.

## Why it matters

A script piped straight from the internet runs whatever the server returns at that moment. An empty variable in `rm -rf "$DIR"/*` deletes from the root. Without `set -e` a script carries on after an error and may destroy data.

## Steps

1. Save a downloaded script first, review it and verify a checksum.
2. Use `rm -rf "${DIR:?}"/*` (it fails when the variable is empty).
3. Put `set -euo pipefail` at the top of the script.
