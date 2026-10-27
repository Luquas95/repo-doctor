# committed-artifacts – Commitnuté build artefakty a cache

**Kategorie:** Údržba · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Hledá mezi sledovanými soubory adresáře `node_modules`, `__pycache__`, `.venv`, `venv`, `.tox`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.next`, `.nuxt`, `.gradle`, adresář `target/` (jen když je v kořeni `Cargo.toml`) a soubory `*.pyc`, `*.pyo`, `.DS_Store`, `Thumbs.db`, `desktop.ini`. Každý adresář nebo soubor je jeden nález s počtem souborů. `dist/` a `build/` se nehlásí, protože je tam někdy záměrně výstup.

## Proč to vadí

Vygenerované soubory zvětšují historii, způsobují zbytečné konflikty a mohou prozradit lokální cesty nebo obsahovat cizí kód bez licence. Z historie nezmizí smazáním.

## Postup

1. Přidej cestu do `.gitignore` (kontrola `gitignore-incomplete` ti pomůže).
2. Odeber ji ze sledování, ale na disku nech: `git rm -r --cached <cesta>` a commit.
3. Je-li artefakt velký, zvaž i vyčištění historie (`git filter-repo`) – přepis historie je na tobě.
