# runtime-unpinned – Language version not pinned

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Applies to Python and Node projects with at least 5 source files. Python: looks for `requires-python` in `pyproject.toml`, `python_requires` in `setup.cfg`/`setup.py`, `python_version` in `Pipfile`, the files `.python-version`, `runtime.txt`, `.tool-versions`, `mise.toml`. Node: `engines` or `volta` in `package.json`, `.nvmrc`, `.node-version`, `.tool-versions`, `mise.toml`.

## Why it matters

Without a declared language version the project works "on my machine", while CI or a colleague gets a different version and behavior differs. Installing on too old an interpreter then ends with a cryptic error.

## Steps

1. Python: `requires-python = ">=3.12"` in `pyproject.toml`, optionally `.python-version`.
2. Node: `"engines": {"node": ">=20"}` in `package.json` or `.nvmrc`.
3. Use the same version in CI.
