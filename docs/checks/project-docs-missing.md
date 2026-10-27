# project-docs-missing – Chybí projektové dokumenty

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Tři nezávislé podnálezy: **changelog** (repo má tagy, ale žádný `CHANGELOG*`, `HISTORY*`, `NEWS*`, `CHANGES*` ani `RELEASES*` v kořeni, `.github/`, `docs/` nebo `.gitlab/`), **security** (veřejné repo bez `SECURITY.md`; platí jen když hosting potvrdí viditelnost) a **contributing** (aspoň 3 autoři, ale žádný `CONTRIBUTING*`).

## Proč to vadí

Bez changelogu uživatelé nevědí, co se ve vydání změnilo. Bez SECURITY.md nemá kdo nahlásit zranitelnost, kam napsat, a tak ji zveřejní nebo mlčí. Bez CONTRIBUTING musí každý nový přispěvatel hádat pravidla.

## Postup

1. Changelog veď ve formátu Keep a Changelog, krátce a po vydáních.
2. `SECURITY.md`: kam hlásit (e-mail, privátní advisory) a jak rychle odpovídáš.
3. `CONTRIBUTING.md`: jak spustit testy, styl kódu, jak poslat PR.
