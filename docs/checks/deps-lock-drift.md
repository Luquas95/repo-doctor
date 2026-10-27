# deps-lock-drift – Lockfile nesedí s manifestem

**Kategorie:** Bezpečnost · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Porovnává závislosti deklarované v manifestu se zámkem ve stejné složce: `package.json` s `package-lock.json`, `npm-shrinkwrap.json`, `yarn.lock` nebo `pnpm-lock.yaml`, `pyproject.toml` s `uv.lock`, `poetry.lock` nebo `pdm.lock` a `Cargo.toml` s `Cargo.lock`. Hlásí deklarované balíčky, které v zámku chybí. Workspaces (npm/pnpm `workspaces`, `[tool.uv.workspace]`, `[workspace]` v Cargu) se přeskakují, zámek je tam v kořeni. Nic se nespouští ani nestahuje.

## Proč to vadí

Zastaralý zámek znamená, že `npm ci`, `uv sync --locked` nebo `cargo build --locked` selžou, nebo (hůř) se balíček dořeší jinak než u kolegů. Ověřené a skenované verze pak nejsou ty, které se skutečně nainstalují.

## Postup

1. Přegeneruj zámek: `npm install`, `uv lock`, `poetry lock` nebo `cargo update`.
2. Změnu zámku commitni spolu s manifestem.
3. V CI instaluj ze zámku (`npm ci`, `uv sync --locked`), ať se rozjetí odhalí hned.
