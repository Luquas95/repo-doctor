# email-exposure – Personal e-mail in a public repo's history

**Category:** Security · **Severity:** MEDIUM · **Automatic fix:** yes (local `.git/config` only)

## What the check looks for

For repositories that are **public** on the hosting (detected the same way as for `public-sensitive`) it goes through author and committer e-mails in the published history (remote-tracking branches, at most 20,000 commits). It reports only **your** addresses: the one from `git config --global user.email`, addresses from the `my_emails` option in the configuration, and addresses at common mail providers (Gmail, Proton, Seznam…) on commits with your name (`user.name`). Hosting `noreply` addresses and other contributors are not reported. The e-mail is always masked in the output (`l***@proton.me`).

## Why it matters

An address in a public repo's history is available to anyone (`git log`, the hosting API) – spammers collect it and it can be linked to your other accounts.

## Steps

1. Turn on e-mail privacy on the hosting and use the `noreply` address: GitHub → Settings → Emails → *Keep my email addresses private* (address `ID+login@users.noreply.github.com`), GitLab → Preferences → *Commit email* → private, Gitea/Forgejo → Settings → *Hide email address*.
2. Use it for new commits: `git config --global user.email <noreply-address>` (everywhere), or only in this repo through the fix – repo-doctor writes `user.email` to `.git/config` and commits nothing.
3. The old history can be rewritten (`git filter-repo --mailmap map.txt` and a force push), but **it breaks forks, other people's clones and links to commits**. repo-doctor never does this on its own; consider whether it is worth it.
