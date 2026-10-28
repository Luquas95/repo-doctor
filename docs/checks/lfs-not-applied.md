# lfs-not-applied – Soubory určené pro Git LFS uložené přímo v gitu

**Kategorie:** Údržba · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Platí jen pro repa, jejichž `.gitattributes` obsahuje `filter=lfs`. Pro soubory v HEAD větší než 1 KB zjistí atribut `filter` a ty, které mají jít přes LFS, ale v gitu jsou uložené celé (LFS pointer má jen pár set bajtů), nahlásí. Soubory jsou jen čteny, nic se nestahuje.

## Proč to vadí

Takový soubor zvětšuje každý klon, i když tým věří, že LFS ho řeší. Bývá to po commitu na stroji bez nainstalovaného `git-lfs` nebo po přidání pravidla až dodatečně.

## Postup

1. Nainstaluj `git-lfs` a spusť `git lfs install`.
2. Převeď existující soubory: `git add --renormalize <soubor>` a commit.
3. Chceš-li převést i historii, použij `git lfs migrate import --include="<vzor>"` (přepis historie – rozhodnutí je na tobě).
