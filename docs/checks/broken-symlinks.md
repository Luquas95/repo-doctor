# broken-symlinks – Rozbité symlinky

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Projde sledované symlinky (režim 120000), přečte jejich cíl a ověří, že cíl v pracovním stromu existuje. Cíl se spočítá jen z textu, od adresáře symlinku, a na disk se sahá výhradně uvnitř repa. Symlink s absolutní cestou, UNC cestou, písmenem disku nebo cílem mimo repo (`..`) se nehlásí jako rozbitý, ale jako symlink mířící mimo repozitář (jinde nefunguje) a cílová cesta se vůbec neověřuje. U bare repa se kontrola přeskočí.

## Proč to vadí

Rozbitý symlink je nejčastěji pozůstatek po přesunu nebo smazání cíle. Absolutní cesty z cizího počítače u jiných lidí nefungují a nástroje (build, editory) na nich padají.

## Postup

1. Oprav cíl: `ln -sfn <správný cíl> <symlink>` a commit.
2. Nebo symlink smaž (`git rm <symlink>`), pokud už není potřeba.
3. U symlinků na vygenerované soubory zvaž skutečnou kopii nebo krok v buildu, který je vytvoří.
