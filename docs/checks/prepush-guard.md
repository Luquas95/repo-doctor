# prepush-guard – Chybí ochrana proti pushnutí tajemství

**Kategorie:** Bezpečnost · **Severity:** LOW · **Automatická oprava:** ano (dvě varianty)

## Co kontrola hledá

Repo s remotem nemá žádný hook `pre-push` (v `.git/hooks` ani ve složce `core.hooksPath`), ani hlídač tajemství (`gitleaks`, `repo-doctor guard`, `detect-secrets`, `trufflehog`…) v `.pre-commit-config.yaml` pro stage `pre-push`.

## Proč to vadí

Tajemství, které omylem commitneš, se pushem dostane na hosting – a tam ho najdou boti během minut. Kontrola při pushi je poslední chvíle, kdy jde ještě opravit jen lokální commit.

## Postup

Léčba nabízí dvě varianty (vybereš jednu):

1. **Do repa přes pre-commit** (doporučené, sdílené s ostatními) – do `.pre-commit-config.yaml` přidá lokální hook `repo-doctor guard` pro stage `pre-push` (commit do větve oprav). Každý ho pak aktivuje `pre-commit install --hook-type pre-push`; hook potřebuje `repo-doctor` v PATH.
2. **Jen lokálně** – nainstaluje `.git/hooks/pre-push`, který spustí `repo-doctor guard`. Je to jediný případ, kdy repo-doctor zapisuje do `.git/hooks`, a jen do tvého repa (nikdy do repa cizího vlastníka; existující vlastní hook nepřepíše). Při nastaveném `core.hooksPath` se tato varianta nenabízí.

`repo-doctor guard` projde jen commity, které se chystají k pushi (rozsah z hooku), vestavěným skenerem tajemství. Při nálezu push zastaví s maskovaným výpisem; falešný poplach skryješ allowlistem, výjimečně obejdeš `git push --no-verify`.
