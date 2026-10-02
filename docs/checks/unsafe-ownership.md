# unsafe-ownership – Nedůvěryhodný vlastník

**Kategorie:** Stav gitu · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Git odmítl s repem pracovat, protože jeho složka patří jinému uživateli než tomu, pod kterým běží repo-doctor (`fatal: detected dubious ownership in repository`). Typicky jde o repo zkopírované z jiného disku, připojený svazek, kontejner nebo složku vytvořenou přes `sudo`.

## Proč to vadí

Cizí repo může v `.git/config` nastavit příkazy, které by git spustil (hooky, filtry, `core.fsmonitor`…), proto ho git ve výchozím stavu odmítá. repo-doctor ho z bezpečnostních důvodů nijak neobchází: nespustí v něm žádný další příkaz gitu, nečte jeho `.repo-doctor.toml` a skóre nepočítá (v triáži je `–` a skupina **NELZE ZKONTROLOVAT**).

repo-doctor `safe.directory` nikdy sám nenastavuje a nepřebíjí ho ani přes `git -c`.

## Postup

1. Ověř, komu složka patří: `ls -ld <cesta>`.
2. Pokud je to tvoje repo s chybným vlastníkem, oprav vlastníka: `sudo chown -R "$USER" <cesta>`.
3. Pokud repu věříš a vlastníka měnit nechceš, povol ho ručně: `git config --global --add safe.directory <cesta>`.
4. Spusť sken znovu.
