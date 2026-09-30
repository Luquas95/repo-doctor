# gitignore-missing – Chybí .gitignore

**Kategorie:** Údržba · **Severity:** MED · **Automatická oprava:** ano

## Co kontrola hledá

Repozitář nemá `.gitignore`.

## Proč to vadí

Bez něj se snadno commitnou `.env`, virtuální prostředí, `node_modules` nebo build výstupy.

## Postup

1. Oprava (`f`) vytvoří `.gitignore` podle zjištěného ekosystému (Python, Node, Rust, Go).
