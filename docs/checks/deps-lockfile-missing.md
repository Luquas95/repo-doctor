# deps-lockfile-missing – Chybí lockfile

**Kategorie:** Bezpečnost · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Manifest deklaruje závislosti (`pyproject.toml`, `package.json`, `Cargo.toml` aplikace, `go.mod`), ale vedle něj chybí lockfile (`uv.lock`/`poetry.lock`, `package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`, `Cargo.lock`, `go.sum`).

## Proč to vadí

Bez lockfilu se při každé instalaci můžou stáhnout jiné verze – build není reprodukovatelný a zranitelnosti nejde spolehlivě ověřit.

## Postup

1. Vygeneruj lockfile (`uv lock`, `npm install`, `cargo generate-lockfile`, `go mod tidy`).
2. Commitni ho a v CI instaluj přesně podle něj (`uv sync --locked`, `npm ci`).
