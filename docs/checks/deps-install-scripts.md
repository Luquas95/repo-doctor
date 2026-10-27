# deps-install-scripts – Závislosti spouštějící skripty při instalaci

**Kategorie:** Bezpečnost · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

V `package-lock.json` a `npm-shrinkwrap.json` spočítá balíčky s příznakem `hasInstallScript` (spouštějí `preinstall`, `install` nebo `postinstall`). Přeskočí se, když `.npmrc` (ve složce lockfilu nebo v kořeni repa) obsahuje `ignore-scripts=true`. Informativní: část balíčků (esbuild, sharp…) skripty opravdu potřebuje.

## Proč to vadí

Instalační skript běží s oprávněními uživatele hned při `npm install`, dřív než cokoli zkontroluješ. Zkompromitovaný balíček tak získá kód na vývojářském stroji i v CI (kde bývají tajemství).

## Postup

1. Instaluj s `--ignore-scripts` nebo dej do `.npmrc` `ignore-scripts=true` a skripty spouštěj jen pro balíčky, které je potřebují.
2. pnpm 10+ skripty blokuje sám, povolení je v `pnpm.onlyBuiltDependencies`.
3. Prohlédni uvedené balíčky a odstraň ty, které nepotřebuješ.
