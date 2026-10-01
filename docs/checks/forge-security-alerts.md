# forge-security-alerts – Otevřené bezpečnostní alerty

**Kategorie:** Hosting · **Severity:** HIGH (secret scanning), MED (Dependabot) · **Automatická oprava:** ne

## Co kontrola hledá

Počet otevřených alertů Dependabot a secret scanning na GitHubu (pokud k nim token má přístup). Ostatní hostingy alerty přes API neposkytují – kontrola je přeskočena.

## Proč to vadí

Hosting už problém našel; neřešený alert je známá díra.

## Postup

1. Projdi alerty na webu hostingu a vyřeš je (aktualizace závislosti, rotace tajemství).
