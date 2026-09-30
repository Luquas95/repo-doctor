# deps-outdated – Zastaralé závislosti

**Kategorie:** Údržba · **Severity:** LOW (major MED) · **Automatická oprava:** ne

## Co kontrola hledá

Pro přímé závislosti (Python z `pyproject.toml`/`requirements*.txt`, npm z `package.json`) zjistí nejnovější verzi z PyPI JSON API a npm registry a rozliší major / minor / patch. Výsledky registrů se cachují 24 h (`limits.registry_cache_hours`). V offline režimu je přeskočena.

## Proč to vadí

Staré verze se hůř aktualizují, čím déle se čeká; major skoky často nesou bezpečnostní opravy jen v nové řadě.

## Postup

1. Patch a minor aktualizace dělej pravidelně (Dependabot / Renovate).
2. Major aktualizace plánuj s changelogem a testy.
