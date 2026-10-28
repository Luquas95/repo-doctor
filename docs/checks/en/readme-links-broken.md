# readme-links-broken – Broken links in README

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Walks the Markdown links and images in `README.md` (outside code blocks) and checks that relative links point to a file or directory that is in the repository (tracked, or untracked and not ignored). URLs, anchors, `mailto:` and links leaving the repository are skipped. Only the file list is checked, the disk is not touched. Findings are capped at 25.

## Why it matters

A broken README link is the first thing a reader hits: missing documentation, a broken image or a link to a renamed file. It makes the project look abandoned.

## Steps

1. Fix the path or restore the target (a `git mv` rename often breaks links).
2. If the link points to a generated file that is not in the repository, generate it or drop the link.
3. Be careful with letter case in links: Linux and GitHub are case-sensitive.
