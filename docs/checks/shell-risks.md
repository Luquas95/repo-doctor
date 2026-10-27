# shell-risks – Rizikové vzory v shell skriptech

**Kategorie:** Bezpečnost · **Severity:** MED (některá pravidla LOW) · **Automatická oprava:** ne

## Co kontrola hledá

Čte `*.sh` a `*.bash` po řádcích (komentáře se přeskakují). Hledá: stažený skript puštěný rovnou v shellu (`curl … | sh`, `wget … | sudo bash`), `chmod 777`, `rm -rf` s cestou začínající proměnnou (`rm -rf "$DIR"/*`) a `eval` s proměnnou (všechno MED). LOW: skript s aspoň 15 příkazovými řádky a shebangem `sh`/`bash`/`zsh`, který nemá `set -e`, `set -u` ani `set -o pipefail`.

## Proč to vadí

Skript puštěný přímo z internetu spustí cokoli, co server zrovna vrátí. Prázdná proměnná v `rm -rf "$DIR"/*` smaže od kořene. Bez `set -e` skript po chybě pokračuje a může zničit data.

## Postup

1. Stažený skript si nejdřív ulož, zkontroluj a ověř kontrolní součet.
2. Používej `rm -rf "${DIR:?}"/*` (skončí chybou, když je proměnná prázdná).
3. Na začátek skriptu dej `set -euo pipefail`.
