# env-committed – Committed sensitive file

**Category:** Security · **Severity:** HIGH · **Automatic fix:** yes

## What the check looks for

Looks among versioned files for `.env`, `.env.*` (except `.env.example`/`.sample`/`.template`), `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519`, `credentials.json`, `.netrc`, `.pgpass`, `terraform.tfvars` and similar.

## Why it matters

These files almost always contain passwords or private keys. Versioning spreads them everywhere the repo goes.

## Steps

1. The fix (`f`) adds the files to `.gitignore` and removes them from git (`git rm --cached`) – they stay on disk.
2. Treat the secrets in them as leaked and rotate them.
3. To remove them from history, proceed as for `secrets-history`.
