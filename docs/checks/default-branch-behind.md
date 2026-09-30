# default-branch-behind – Výchozí branche je pozadu za remote

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Porovná výchozí branch s jejím upstreamem podle posledního fetch (bez síťového dotazu). S `repo-doctor scan --fetch` se nejdřív udělá fetch.

## Proč to vadí

Pracuješ nad starým stavem a riskuješ konflikty.

## Postup

1. `git pull --ff-only`.
