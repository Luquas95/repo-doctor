# submodule-state – Broken or insecure submodules

**Category:** Git state · **Severity:** MED · **Automatic fix:** no

## What the check looks for

Compares the submodules in the index (mode 160000) with the entries in `.gitmodules`. Reports: a submodule without a `.gitmodules` entry (MED, cloning then fails with "no submodule mapping"), an entry without a submodule (LOW), a submodule that is not checked out (LOW) and a submodule with an `http://` or `git://` URL (MED). No network is used.

## Why it matters

A submodule without a mapping breaks every `--recurse-submodules` clone. An unencrypted URL lets code be tampered with in transit. An unchecked submodule leads to an incomplete build.

## Steps

1. Add the missing mapping to `.gitmodules` (`git submodule add <url> <path>` or by hand) and commit.
2. Remove a stale entry: `git config -f .gitmodules --remove-section submodule.<name>` and commit.
3. Unchecked submodule: `git submodule update --init`. Change the URL to `https://` or `ssh`.
