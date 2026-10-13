# duplicate-clone – Duplicitní klon

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne (úklid přes koš po potvrzení)

## Co kontrola hledá

Napříč všemi sledovanými složkami hledá repozitáře se **stejným remotem** – SSH i HTTPS adresa téhož repa, aliasy z `~/.ssh/config` (porovnává se skutečný `HostName`), bez `.git` na konci, host malými písmeny – nebo se **stejným kořenovým commitem**, pokud remote nemají. Každý duplikát dostane nález s odkazem na ostatní klony a porovnáním stavu (větev, poslední commit, necommitnuté a nepushnuté změny). Hlavním klonem je ten s nejnovější aktivitou. Počítá se jen při skenu všech sledovaných složek.

## Proč to vadí

Dva klony téhož repa se rozjedou: změny v jednom chybí v druhém, snadno upravíš „ten špatný“ a zbytečně zabírají místo.

## Postup

1. Porovnej klony (`git -C <cesta> log --oneline -5`, `git status`) a zbytek práce přenes do hlavního klonu (push/pull, nebo `git fetch ../jiny-klon`).
2. Klon bez necommitnutých a nepushnutých změn smaž – repo-doctor ho sám nemaže; na obrazovce **Úklid** (`9`) ho po potvrzení přesune do koše.
3. Na přehledu pomůže seskupení podle remotu (`alt+g`).
