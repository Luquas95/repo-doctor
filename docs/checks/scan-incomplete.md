# scan-incomplete – Nekompletní sken

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Kontrola historie (tajemství, velké soubory) nestihla doběhnout v časovém limitu `limits.history_timeout_s` a byla korektně přerušena.

## Proč to vadí

Výsledek dané kontroly nemusí být úplný – nález v nedoběhnuté části historie mohl zůstat skrytý.

## Postup

1. Zvyš `limits.history_timeout_s` v `config.toml` nebo v `.repo-doctor.toml` daného repa.
2. Případně nainstaluj `gitleaks`, který je na velkých repech rychlejší.
