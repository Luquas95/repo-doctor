# no-remote – Repo bez remote (bez zálohy)

**Kategorie:** Stav gitu · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Repozitář s alespoň jedním commitem nemá žádný remote.

## Proč to vadí

Bez remote neexistuje žádná záloha mimo tento disk.

## Postup

1. Vytvoř repo na hostingu a přidej remote: `git remote add origin <url>` a `git push -u origin main`.
