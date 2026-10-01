# forge-no-branch-protection – Výchozí branche bez ochrany

**Kategorie:** Hosting · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Výchozí branche nemá na hostingu ochranu (tam, kde to API umí zjistit; jinak je kontrola přeskočena). U archivovaných rep se nehlásí.

## Proč to vadí

Bez ochrany jde hlavní větev omylem force-pushnout nebo smazat.

## Postup

1. Zapni ochranu větve v nastavení repa na hostingu (zákaz force push a mazání, případně povinné review/CI).
