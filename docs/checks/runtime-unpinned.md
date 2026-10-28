# runtime-unpinned – Nepřipnutá verze jazyka

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Platí pro Python a Node projekty s aspoň 5 zdrojovými soubory. Python: hledá `requires-python` v `pyproject.toml`, `python_requires` v `setup.cfg`/`setup.py`, `python_version` v `Pipfile`, soubory `.python-version`, `runtime.txt`, `.tool-versions`, `mise.toml`. Node: `engines` nebo `volta` v `package.json`, `.nvmrc`, `.node-version`, `.tool-versions`, `mise.toml`.

## Proč to vadí

Bez určené verze jazyka funguje projekt „u mě“, na CI nebo u kolegy se stáhne jiná verze a chování se liší. Instalace na příliš starém interpretu pak končí nesrozumitelnou chybou.

## Postup

1. Python: `requires-python = ">=3.12"` v `pyproject.toml`, případně `.python-version`.
2. Node: `"engines": {"node": ">=20"}` v `package.json` nebo `.nvmrc`.
3. Stejnou verzi nastav v CI.
