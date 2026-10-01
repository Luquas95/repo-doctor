# stashes – Zapomenuté stashe

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Hlásí stashe starší než `limits.stash_days` (výchozí 30).

## Proč to vadí

Zapomenutý stash je práce, o které nikdo neví.

## Postup

1. Prohlédni: `git stash show -p stash@{N}`.
2. Použij (`git stash pop`) nebo zahoď (`git stash drop stash@{N}`).
