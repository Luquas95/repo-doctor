# unpushed – Nepushnuté commity

**Kategorie:** Stav gitu · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Pro každou lokální branch spočítá commity, které nejsou na upstreamu (nebo na žádném remote, pokud upstream nemá). Pracuje jen s lokálními daty – bez `fetch`.

## Proč to vadí

Commity, které existují jen na tomto disku, zmizí s ním.

## Postup

1. `git push` (případně `git push -u origin <branch>` pro novou branch).
