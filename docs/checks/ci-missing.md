# ci-missing – Chybí CI

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ano

## Co kontrola hledá

Hledá `.github/workflows/`, `.gitlab-ci.yml`, `.forgejo/workflows/`, `.gitea/workflows/`, Woodpecker, Drone, CircleCI, Travis a Jenkinsfile.

## Proč to vadí

Bez CI se chyby a regresní problémy dostanou do hlavní větve bez povšimnutí.

## Postup

1. Oprava (`f`) přidá `.github/workflows/ci.yml` podle ekosystému (lint + testy).
2. Pro Forgejo/Gitea Actions soubor přesuň do `.forgejo/workflows/`.
