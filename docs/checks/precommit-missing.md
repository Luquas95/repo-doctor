# precommit-missing – Chybí pre-commit

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ano

## Co kontrola hledá

Kontroluje existenci `.pre-commit-config.yaml`.

## Proč to vadí

Pre-commit zachytí tajemství (gitleaks), velké soubory a formátovací chyby ještě před commitem.

## Postup

1. Oprava (`f`) přidá základní konfiguraci: gitleaks, trailing whitespace, end-of-file, velké soubory, detect-private-key a podle ekosystému ruff nebo eslint.
2. Po checkoutu větve spusť `pre-commit install`.
