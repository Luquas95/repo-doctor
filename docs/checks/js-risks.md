# js-risks – Rizikové vzory v JavaScriptu a TypeScriptu

**Kategorie:** Bezpečnost · **Severity:** MED (některá pravidla LOW) · **Automatická oprava:** ne

## Co kontrola hledá

Čte `*.js`, `*.jsx`, `*.mjs`, `*.cjs`, `*.ts`, `*.tsx` po řádcích (bez `*.min.js`, `*.d.ts`, testů a `node_modules`; komentáře a řádky nad 1000 znaků se přeskakují). Hledá: `eval()`/`new Function()`, `exec()`/`execSync()` se skládaným příkazem (zřetězení nebo šablona s `${}`), `.innerHTML =` a `document.write()`, `rejectUnauthorized: false` a `NODE_TLS_REJECT_UNAUTHORIZED=0` (MED), `dangerouslySetInnerHTML` a zapomenutý `debugger` (LOW).

## Proč to vadí

Skládání příkazů a HTML z neověřeného textu je klasické vstřikování příkazů a XSS. Vypnuté ověření TLS dovolí podvrhnout server. `dangerouslySetInnerHTML` je v pořádku jen pro obsah, který nikdy nepochází od uživatele.

## Postup

1. Příkazy spouštěj přes `execFile`/`spawn` se seznamem argumentů.
2. Do DOMu vkládej `textContent` nebo sanitizovaný HTML (DOMPurify).
3. TLS nikdy nevypínej, místo toho přidej vlastní CA do úložiště důvěry.
