# detached-head – Detached HEAD

**Category:** Git state · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

HEAD points directly at a commit instead of a branch.

## Why it matters

New commits made in this state are easily lost when you switch elsewhere.

## Steps

1. Go back to a branch (`git switch main`) or create a new one (`git switch -c <name>`).
