# lint-config-missing – Linter or formatter configuration missing

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Applies to Python and Node projects with at least 5 source files. Python: looks for `[tool.ruff]`, `[tool.black]`, `[tool.flake8]`, `[tool.pylint]`, `[tool.isort]` in `pyproject.toml`, the files `ruff.toml`, `.flake8`, `.pylintrc` and sections in `setup.cfg` and `tox.ini`. Node: `eslint.config.*`, `.eslintrc*`, `biome.json`, `.prettierrc*`, `deno.json`, the `eslintConfig` and `prettier` keys in `package.json`. A matching hook in `.pre-commit-config.yaml` also counts.

## Why it matters

Without a shared linter and formatter the style differs from file to file, mistakes such as unused variables are found only at run time and diffs are full of reformatting.

## Steps

1. Python: add `[tool.ruff]` to `pyproject.toml` (`ruff check` + `ruff format`).
2. Node: `npm init @eslint/config` or `biome init`.
3. Run it in pre-commit and in CI so nobody bypasses it.
