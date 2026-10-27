# broken-symlinks – Rozbité symlinky

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Projde sledované symlinky (režim 120000), přečte jejich cíl a ověří, že cíl v pracovním stromu existuje. Relativní cíle se počítají od adresáře symlinku, absolutní se berou tak, jak jsou. Nic se nenásleduje mimo prosté ověření existence. U bare repa se kontrola přeskočí.

## Proč to vadí

Rozbitý symlink je nejčastěji pozůstatek po přesunu nebo smazání cíle. Absolutní cesty z cizího počítače u jiných lidí nefungují a nástroje (build, editory) na nich padají.

## Postup

1. Oprav cíl: `ln -sfn <správný cíl> <symlink>` a commit.
2. Nebo symlink smaž (`git rm <symlink>`), pokud už není potřeba.
3. U symlinků na vygenerované soubory zvaž skutečnou kopii nebo krok v buildu, který je vytvoří.
