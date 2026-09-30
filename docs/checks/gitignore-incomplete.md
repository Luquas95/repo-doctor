# gitignore-incomplete – Neúplný .gitignore

**Kategorie:** Údržba · **Severity:** MED (bez `.env`), jinak LOW · **Automatická oprava:** ano

## Co kontrola hledá

Podle ekosystému ověří (`git check-ignore`), že jsou ignorované běžné položky: `.env`, `.env.*` a dále `__pycache__/`, `.venv/`, `dist/` (Python), `node_modules/`, `dist/` (Node), `target/` (Rust), `*.test` (Go). Globální excludes uživatele se nepočítají – nesdílí se s ostatními.

## Proč to vadí

Chybějící pravidla vedou k omylem commitnutým tajemstvím a zbytečně velkým repozitářům.

## Postup

1. Oprava (`f`) doplní chybějící řádky do samostatného bloku s komentářem `# repo-doctor: doplněno <datum>`, bez duplicit.
