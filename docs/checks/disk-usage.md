# disk-usage – Velké regenerovatelné složky v neaktivním repu

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne (obrazovka Úklid / `repo-doctor clean`)

## Co kontrola hledá

U repozitářů bez commitu déle než `cleanup.inactive_days` (výchozí 60 dní) sečte velikost typických regenerovatelných složek – `node_modules`, `.venv`/`venv`, `target`, `dist`, `build`, `.next`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.gradle`, `.terraform` (seznam `cleanup.dirs`). Počítají se jen složky, které git ignoruje (`git check-ignore`) a které neobsahují žádný sledovaný soubor; symlinky se nenásledují. Nález vznikne, když součet přesáhne `cleanup.min_mb` (výchozí 200 MB).

## Proč to vadí

Závislosti a build výstupy starých projektů zabírají často desítky GB, přitom je jde kdykoli znovu vytvořit (`npm ci`, `uv sync`, `cargo build`).

## Postup

1. Otevři obrazovku **Úklid** (`6`): tabulka rep s místem k uvolnění, předvybraná jsou neaktivní repa bez změn. Mezerníkem upravíš výběr, Enter po potvrzení přesune složky **do koše** (freedesktop Trash – jde je obnovit). Trvalé smazání (`D`) chce dvě potvrzení.
2. Nebo z příkazové řádky: `repo-doctor clean` (jen náhled) a `repo-doctor clean --apply` (do koše). `--all` přidá i aktivní repa, `--include-dirty` repa s necommitnutými změnami, `--duplicates` celé duplicitní klony bez změn.
3. repo-doctor nikdy nesmaže nic sledovaného gitem, nic mimo repozitář, složku, ve které běží proces (Linux `/proc`), ani nic v repu cizího vlastníka. Před smazáním vše znovu ověří.
