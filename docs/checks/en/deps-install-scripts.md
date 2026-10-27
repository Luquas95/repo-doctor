# deps-install-scripts – Dependencies running install scripts

**Category:** Security · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

In `package-lock.json` and `npm-shrinkwrap.json` it counts packages flagged `hasInstallScript` (they run `preinstall`, `install` or `postinstall`). Skipped when `.npmrc` (in the lockfile's folder or the repo root) contains `ignore-scripts=true`. Informational: some packages (esbuild, sharp...) really need scripts.

## Why it matters

An install script runs with the user's privileges right at `npm install`, before you review anything. A compromised package thus gets code execution on a developer machine and in CI (where secrets usually live).

## Steps

1. Install with `--ignore-scripts` or put `ignore-scripts=true` in `.npmrc` and run scripts only for packages that need them.
2. pnpm 10+ blocks scripts on its own; allow them in `pnpm.onlyBuiltDependencies`.
3. Review the listed packages and drop the ones you do not need.
