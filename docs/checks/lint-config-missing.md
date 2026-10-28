# lint-config-missing – Chybí konfigurace linteru nebo formátovače

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Platí pro Python a Node projekty s aspoň 5 zdrojovými soubory. Python: hledá `[tool.ruff]`, `[tool.black]`, `[tool.flake8]`, `[tool.pylint]`, `[tool.isort]` v `pyproject.toml`, soubory `ruff.toml`, `.flake8`, `.pylintrc`, sekce v `setup.cfg` a `tox.ini`. Node: `eslint.config.*`, `.eslintrc*`, `biome.json`, `.prettierrc*`, `deno.json`, klíče `eslintConfig` a `prettier` v `package.json`. Za konfiguraci se počítá i odpovídající hook v `.pre-commit-config.yaml`.

## Proč to vadí

Bez společného linteru a formátovače se styl liší soubor od souboru, chyby typu nepoužitá proměnná se najdou až při běhu a diffy jsou plné přeformátování.

## Postup

1. Python: přidej `[tool.ruff]` do `pyproject.toml` (`ruff check` + `ruff format`).
2. Node: `npm init @eslint/config` nebo `biome init`.
3. Spouštěj ho v pre-commit a v CI, ať ho nikdo neobchází.
