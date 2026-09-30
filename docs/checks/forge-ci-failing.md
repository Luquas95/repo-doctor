# forge-ci-failing – CI na výchozí branchi selhává

**Kategorie:** Hosting · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Poslední běh CI na výchozí branchi skončil chybou (GitHub Actions, Gitea/Forgejo Actions přes commit status, GitLab pipelines).

## Proč to vadí

Rozbitá hlavní větev blokuje ostatní a skrývá nové chyby.

## Postup

1. Otevři běh na webu (`w` v kartě repa) a oprav příčinu.
