# case-collisions – Cesty lišící se jen velikostí písmen

**Kategorie:** Údržba · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Porovnává sledované cesty (i adresáře uvnitř cest) bez ohledu na velikost písmen. Najde-li dvě různé cesty, které se liší jen velikostí písmen (`README.md` a `readme.md`, `Docs/` a `docs/`), nahlásí je. U vnořených kolizí se hlásí nejkratší společná cesta.

## Proč to vadí

Linux je rozliší, ale macOS a Windows (výchozí nastavení) ne: klon na nich přepíše jeden soubor druhým, `git status` ukazuje fantomové změny a build se chová jinak než u ostatních.

## Postup

1. Vyber, který název platí, a druhý přejmenuj nebo smaž: `git mv Docs docs-tmp && git mv docs-tmp docs`.
2. Obsah slouč ručně (soubory se stejným názvem se liší), pak commit.
3. Po sloučení nastav v týmu `core.ignorecase` konzistentně (obvykle ponech výchozí).
