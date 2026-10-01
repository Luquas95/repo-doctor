# uncommitted – Necommitnuté změny

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Hlásí změněné, nesledované a konfliktní soubory (`git status`, bez zápisu indexu).

## Proč to vadí

Necommitnutá práce není nikde zálohovaná a snadno se ztratí.

## Postup

1. Commitni nebo ulož do stashe (`git stash push -m popis`).
2. Soubory, které do repa nepatří, přidej do `.gitignore`.
