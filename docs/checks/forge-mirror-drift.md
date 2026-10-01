# forge-mirror-drift – Lokální výchozí branche se liší od hostingu

**Kategorie:** Hosting · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Porovná název výchozí branche a její poslední commit lokálně a na hostingu (jen přes API, bez fetch). Lokální náskok hlásí `unpushed`, tady jde o rozdíl názvu nebo chybějící commity z hostingu.

## Proč to vadí

Pracuješ nad jiným stavem, než je na hostingu (typicky přejmenované `master` → `main`).

## Postup

1. `git fetch` a `git pull --ff-only`.
2. Při přejmenování: `git branch -m master main && git branch -u origin/main main && git remote set-head origin -a`.
