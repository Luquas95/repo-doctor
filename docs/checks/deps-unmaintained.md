# deps-unmaintained – Opuštěné nebo zastaralé balíčky

**Kategorie:** Údržba · **Severity:** MED (opuštěné LOW) · **Automatická oprava:** ne

## Co kontrola hledá

Využívá odpovědi registrů PyPI a npm, které sken stahuje i pro `deps-outdated` (žádné další dotazy), a jen pro přímé závislosti. Hlásí: npm balíček označený jako `deprecated` (MED, vypíše se důvod autora), PyPI projekt s klasifikátorem `Development Status :: 7 - Inactive` (MED) a PyPI balíček, jehož poslední vydání je starší než 3 roky (LOW). Závislosti jen pro vývoj se u „opuštěných“ přeskakují a u `deprecated` mají LOW. Vyžaduje síť.

## Proč to vadí

Balíček bez údržby nedostane opravy zranitelností a časem přestane fungovat s novými verzemi jazyka. Autor často sám napíše, čím ho nahradit.

## Postup

1. Přečti si zprávu o `deprecated`, obvykle ukazuje na nástupce.
2. Najdi udržovanou alternativu, nebo kód převezmi do projektu (pozor na licenci).
3. Je-li balíček záměrně hotový a stabilní (malá knihovna), dej nález do allowlistu.
