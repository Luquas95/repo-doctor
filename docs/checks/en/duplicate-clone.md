# duplicate-clone – Duplicate clone

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no (cleanup to the trash after confirmation)

## What the check looks for

Across all watched folders it looks for repositories with the **same remote** – SSH and HTTPS addresses of the same repo, aliases from `~/.ssh/config` (the real `HostName` is compared), without the trailing `.git`, host in lower case – or with the **same root commit** when they have no remote. Each duplicate gets a finding listing the other clones and comparing their state (branch, last commit, uncommitted and unpushed changes). The clone with the most recent activity is the main one. Only computed when scanning all watched folders.

## Why it matters

Two clones of the same repo drift apart: changes in one are missing in the other, it is easy to edit "the wrong one", and they waste space.

## Steps

1. Compare the clones (`git -C <path> log --oneline -5`, `git status`) and move the remaining work to the main clone (push/pull, or `git fetch ../other-clone`).
2. Delete a clone without uncommitted and unpushed changes – repo-doctor does not delete it on its own; on the **Cleanup** screen (`6`) it moves it to the trash after confirmation.
3. Grouping by remote (`alt+g`) helps on the overview.
