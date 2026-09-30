# detached-head – Detached HEAD

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

HEAD neukazuje na branch, ale přímo na commit.

## Proč to vadí

Nové commity v tomto stavu snadno ztratíš při přepnutí jinam.

## Postup

1. Vrať se na branch (`git switch main`) nebo vytvoř novou (`git switch -c <nazev>`).
