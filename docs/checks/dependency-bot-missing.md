# dependency-bot-missing – Bez automatických aktualizací závislostí

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Platí pro repa, která mají aspoň jeden remote a manifest závislostí (`pyproject.toml`, `requirements*.txt`, `Pipfile`, `package.json`, `Cargo.toml`, `go.mod`, `Dockerfile`), ale ani `.github/dependabot.yml`, ani konfiguraci Renovate (`renovate.json`, `.renovaterc`, `.github/renovate.json`, klíč `renovate` v `package.json`).

## Proč to vadí

Bez bota se závislosti a základní image aktualizují jen když si někdo vzpomene. Bezpečnostní opravy pak do projektu doputují s měsíčním nebo ročním zpožděním.

## Postup

1. GitHub: přidej `.github/dependabot.yml` (ekosystémy `pip`/`npm`/`cargo`/`gomod`/`docker`/`github-actions`).
2. Forgejo, GitLab a ostatní: nasaď Renovate a přidej `renovate.json`.
3. Nastav skupiny a týdenní frekvenci, ať PR nezahlcují.
