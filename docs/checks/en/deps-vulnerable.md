# deps-vulnerable – Vulnerable dependencies

**Category:** Security · **Severity:** HIGH (by severity from OSV) · **Automatic fix:** no

## What the check looks for

Parses lockfiles (`uv.lock`, `poetry.lock`, `requirements*.txt` with `==`, `pyproject.toml` with a pin, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `Cargo.lock`, `go.sum`) and queries **OSV.dev** in batches (`/v1/querybatch`, no key). Severity comes from the database (GHSA: CRITICAL/HIGH → HIGH, MODERATE → MED, LOW → LOW). Skipped in offline mode. Results are cached.

## Why it matters

Known vulnerabilities have public exploits; updating is usually the cheapest defence.

## Steps

1. Look up the vulnerability ID (GHSA/CVE/PYSEC) and find the fixed version.
2. Update the dependency (`uv lock --upgrade-package X`, `npm update X`, `cargo update -p X`, `go get X@latest`).
3. If you cannot update, assess the impact and add the finding to the allowlist with a reason.
