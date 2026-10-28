# conflict-markers – Zbytky po konfliktu při mergi

**Kategorie:** Údržba · **Severity:** MED · **Automatická oprava:** ne

## Co kontrola hledá

Prochází sledované textové soubory (do velikostního limitu skeneru tajemství) a hledá nevyřešené značky konfliktu: řádek začínající `<<<<<<<`, za ním řádek `=======` a potom řádek začínající `>>>>>>>`. Všechny tři musí být za sebou, takže samotná podtržítka v Markdownu nebo ukázka v dokumentaci se nehlásí. Nálezy jsou omezené na 25 souborů.

## Proč to vadí

Zbylé značky rozbijí kompilaci nebo konfiguraci a obvykle znamenají, že se do repa dostal napůl vyřešený merge nebo rebase. U dat a skriptů můžou způsobit tichou chybu až za běhu.

## Postup

1. Otevři soubor na uvedeném řádku a vyber správnou verzi (`git mergetool` nebo ručně).
2. Smaž všechny tři značky, spusť testy a udělej commit.
3. Pokud je text v souboru záměrný (např. ukázka konfliktu v dokumentaci), přidej nález do allowlistu.
