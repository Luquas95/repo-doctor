# deps-unpinned – Nepřipnuté verze závislostí

**Kategorie:** Údržba · **Severity:** LOW · **Automatická oprava:** ne

## Co kontrola hledá

Hledá závislosti, jejichž verzi nic neupevňuje: v `package.json` hodnoty `*`, `latest`, prázdné, git adresy a GitHub zkratky `uživatel/repo` bez `#ref`; v `requirements*.txt` řádky bez verze a `git+` adresy bez `@ref`; v `pyproject.toml` závislosti `jméno @ git+…` bez `@ref`; v `Cargo.toml` verzi `*` a git závislosti bez `rev` nebo `tag`. Obyčejné rozsahy (`^1.2`, `>=2`) se nehlásí, ty řeší lockfile.

## Proč to vadí

Taková závislost se při každé instalaci může vyřešit na jiný kód, včetně nové a nezkontrolované verze nebo přepsané větve. Sestavení není reprodukovatelné a podvržená verze projde bez povšimnutí.

## Postup

1. Připni verzi: `requests==2.32.3`, `"lib": "1.4.2"` nebo `rev = "…"` v Cargu.
2. Git závislost připni na commit nebo tag (`#v1.2.0`, `@abc123`).
3. Rozsahy nech na lockfile a Renovate/Dependabot.
