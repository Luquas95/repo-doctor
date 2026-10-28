# submodule-state – Rozbité nebo nezabezpečené submoduly

**Kategorie:** Stav gitu · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Porovnává submoduly v indexu (režim 160000) se záznamy v `.gitmodules`. Hlásí: submodul bez záznamu v `.gitmodules` (MED, klon repa pak selže hláškou „no submodule mapping“), záznam bez submodulu (LOW), submodul, který není stažený (LOW) a submodul s adresou `http://` nebo `git://` (MED). Žádná síť se nepoužívá.

## Proč to vadí

Submodul bez mapování rozbije každému klon s `--recurse-submodules`. Nešifrovaná adresa dovolí podvrhnout kód na cestě. Nestažený submodul vede k neúplnému buildu.

## Postup

1. Chybějící mapování doplň do `.gitmodules` (`git submodule add <url> <cesta>` nebo ručně) a commit.
2. Zbylý záznam odstraň: `git config -f .gitmodules --remove-section submodule.<jméno>` a commit.
3. Nestažený submodul: `git submodule update --init`. Adresu změň na `https://` nebo `ssh`.
