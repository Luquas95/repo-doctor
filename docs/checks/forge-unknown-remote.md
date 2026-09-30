# forge-unknown-remote – Remote ukazuje na neznámé repo

**Kategorie:** Hosting · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Remote patří k připojenému hostingu, ale API repo nezná (404) nebo k němu token nemá přístup (403) – smazané, přejmenované nebo převedené repo.

## Proč to vadí

Push i pull selžou a záloha, o které si myslíš, že existuje, neexistuje.

## Postup

1. Ověř repo na webu hostingu.
2. Oprav URL: `git remote set-url origin <nová-url>`.
