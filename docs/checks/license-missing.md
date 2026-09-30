# license-missing – Chybí licence

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ano

## Co kontrola hledá

V kořeni repozitáře chybí `LICENSE`, `LICENCE`, `COPYING` nebo `UNLICENSE`.

## Proč to vadí

Kód bez licence nesmí nikdo legálně použít – ani když je repo veřejné.

## Postup

1. Oprava (`f`) přidá licenci podle `license` v konfiguraci (výchozí MIT; dále ISC, BSD-2-Clause, Unlicense).
2. Jméno se bere z `git config user.name`, rok z aktuálního data.
