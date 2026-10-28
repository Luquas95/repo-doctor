# tests-missing – Projekt bez testů

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Platí pro repa s aspoň 5 zdrojovými soubory (Python, Node/TypeScript, Rust, Go; bez `node_modules`, `vendor` a testů). Hledá testy: adresáře `tests/`, `test/`, `__tests__/`, `spec/`, soubory `test_*.py`, `*_test.py`, `*_test.go`, `*.test.ts`, `*.spec.js` a podobně; u Rustu i `#[test]` a `#[cfg(test)]` ve zdrojácích. Žádný test se nespouští.

## Proč to vadí

Bez testů se každá změna ověřuje jen ručně a regrese se objeví až u uživatelů. Čím větší projekt, tím dražší je pozdější doplnění.

## Postup

1. Začni jedním testem nejdůležitější funkce (`pytest`, `vitest`, `cargo test`, `go test`).
2. Přidej příkaz do CI a pre-push (kontrola `tests-not-in-ci` pak ohlídá, že se opravdu spouští).
3. Malý skript nebo ukázkové repo testy mít nemusí, v takovém případě nález přidej do allowlistu.
