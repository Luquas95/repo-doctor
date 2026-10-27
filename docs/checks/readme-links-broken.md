# readme-links-broken – Rozbité odkazy v README

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Prochází Markdown odkazy a obrázky v `README.md` (mimo bloky kódu) a ověřuje, že relativní odkazy vedou na soubor nebo adresář, který je v repu (sledovaný nebo nesledovaný a neignorovaný). URL, kotvy, `mailto:` a odkazy mimo repo se přeskakují. Kontroluje se jen seznam souborů, na disk se nesahá. Nálezy jsou omezené na 25.

## Proč to vadí

Rozbitý odkaz v README je první věc, na kterou čtenář narazí: chybějící dokumentace, rozbitý obrázek nebo odkaz na přejmenovaný soubor. Působí to jako opuštěný projekt.

## Postup

1. Oprav cestu, nebo cíl vrať (`git mv` přejmenování často rozbije odkazy).
2. Pokud odkaz míří na vygenerovaný soubor, který v repu není, vygeneruj ho nebo odkaz odeber.
3. Odkazy s velkými a malými písmeny kontroluj opatrně: Linux je rozlišuje, GitHub také.
