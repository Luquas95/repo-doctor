# line-endings – Nejednotné konce řádků

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Používá `git ls-files --eol` (stav v indexu, tedy to, co se commituje). Hlásí soubory se smíšenými konci řádků (LF i CRLF v jednom souboru) a repa, kde je část textových souborů v CRLF a část v LF, aniž by `.gitattributes` určoval pravidlo (`text`, `eol`). Soubory `.bat`, `.cmd`, `.ps1`, `.sln`, `.vbs`, `.reg` mohou CRLF mít legitimně.

## Proč to vadí

Smíšené konce řádků dělají v diffech šum (celý soubor „změněn“), lámou shell skripty (`\r` za shebangem) a vedou ke zbytečným konfliktům mezi systémy.

## Postup

1. Přidej do `.gitattributes` pravidlo: `* text=auto` (případně `*.sh text eol=lf`).
2. Sjednoť existující soubory: `git add --renormalize .` a commit.
3. Soubory se smíšenými konci oprav v editoru nebo `dos2unix`/`unix2dos`.
