# license-compat – Dependency license may not be compatible

**Category:** Maintenance · **Severity:** LOW (strong copyleft MEDIUM) · **Automatic fix:** no

## What the check looks for

Looks up the licenses of **direct** dependencies in registries – Python from PyPI (`license_expression`, `license`, classifiers), npm from the registry, Rust from crates.io; Go is not checked (pkg.go.dev has no stable API). Responses are cached as for `deps-outdated`; in offline mode the check is skipped. If the project has a **permissive license** (MIT, Apache-2.0, BSD, ISC…), it reports dependencies with a **strong copyleft** license (GPL, AGPL, SSPL, EUPL, OSL) and dependencies without a license or with a license it does not know. Licenses are mapped to SPDX identifiers with its own table; for `A OR B` the more permissive option is taken, for `A AND B` the stricter one (AND binds tighter than OR, parentheses are respected). Development and build-only dependencies (`devDependencies`, `dev-dependencies`, `build-dependencies`, `[dependency-groups]`, `requirements-dev.txt` and similar) are not checked – they are not distributed. When a registry does not answer (network, private package), the dependency is skipped; it is not reported as "without a license".

**The output is informational – it is not legal advice.**

## Why it matters

GPL/AGPL code in a project with a permissive license may (depending on how it is used and distributed) require publishing the source code under the GPL. Code without a license has not formally been licensed to you at all.

## Steps

1. Check the dependency's actual license (repository, LICENSE file) – registry metadata is often inaccurate.
2. Consider how you use the dependency (a library linked into a distributed program vs. a development tool) – in unclear cases ask a lawyer.
3. If needed, find an alternative with a permissive license, or ask the author of a dependency without a license to add one.
4. Hide a finding that is fine with the allowlist (`a` on the repo card).
