# stale-branches – Zastaralé lokální branche

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Hlásí lokální branche, které jsou mergnuté do výchozí branche, nebo nemají commit déle než `limits.stale_branch_days` (výchozí 90). Nic nemaže.

## Proč to vadí

Staré branche zahlcují přehled a matou, co je rozpracované.

## Postup

1. Zkontroluj je (`git log main..<branch>`) a smaž ručně: `git branch -d <branch>`.
