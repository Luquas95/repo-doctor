# license-compat – Licence závislosti nemusí být slučitelná

**Kategorie:** Údržba · **Severity:** LOW (silný copyleft MEDIUM) · **Automatická oprava:** ne

## Co kontrola hledá

Zjistí licence **přímých** závislostí z registrů – Python z PyPI (`license_expression`, `license`, klasifikátory), npm z registry, Rust z crates.io; Go se nezjišťuje (pkg.go.dev nemá stabilní API). Odpovědi se cachují stejně jako u `deps-outdated`, v offline režimu se kontrola přeskočí. Pokud má projekt **permisivní licenci** (MIT, Apache-2.0, BSD, ISC…), hlásí závislosti se **silně copyleftovou** licencí (GPL, AGPL, SSPL, EUPL, OSL) a závislosti bez licence nebo s licencí, kterou nezná. Licence se mapují na SPDX identifikátory vlastní tabulkou; u výrazu `A OR B` se bere volnější možnost, u `A AND B` přísnější (AND váže silněji než OR, závorky se respektují). Závislosti jen pro vývoj a build (`devDependencies`, `dev-dependencies`, `build-dependencies`, `[dependency-groups]`, `requirements-dev.txt` a podobné) se nekontrolují – do distribuce nejdou. Když registr neodpoví (síť, soukromý balíček), závislost se přeskočí; nehlásí se jako „bez licence“.

**Výstup je informativní – nejde o právní radu.**

## Proč to vadí

GPL/AGPL kód v projektu s permisivní licencí může (podle způsobu použití a distribuce) vyžadovat zveřejnění zdrojového kódu pod GPL. Kód bez licence ti autor formálně nedovolil použít vůbec.

## Postup

1. Ověř skutečnou licenci závislosti (repozitář, soubor LICENSE) – metadata v registru bývají nepřesná.
2. Zvaž, jak závislost používáš (knihovna linkovaná do distribuovaného programu vs. nástroj při vývoji) – u nejasných případů se poraď s právníkem.
3. Případně najdi alternativu s permisivní licencí, nebo požádej autora závislosti bez licence o doplnění.
4. Nález, který je v pořádku, skryješ allowlistem (`a` v kartě repa).
