# Changelog

Formát podle [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/), verze podle SemVer.

## [0.1.3] – 2026-10-02

### Opraveno
- `core.sshCommand` se najde i v souborech vložených do globální/systémové konfigurace přes
  `[include]` (`git config --includes`). Podmíněné `includeIf` podle složky se mimo repo
  nevyhodnotí – takové nastavení patří do `GIT_SSH_COMMAND` nebo `~/.ssh/config`.
  Lokální konfigurace zkoumaných rep se dál nikdy nečte.

## [0.1.2] – 2026-10-02

### Opraveno
- Git respektuje globální/systémový `core.sshCommand` (vlastní klíč, `-F` konfigurace);
  `-o BatchMode=yes` se jen přidává na konec. Pořadí: proměnná `GIT_SSH_COMMAND` →
  globální/systémový `core.sshCommand` → `ssh`. Lokální `core.sshCommand` cizího repa se
  dál nikdy nepoužije. Nová volba `ssh_batch_mode = false` pro wrappery.
- Typické SSH chyby (neznámý klíč serveru, odmítnutý SSH klíč, nedostupný server) mají
  srozumitelné české hlášky s postupem při klonu, testu připojení, `--fetch` i v CLI; původní
  text gitu zůstává v detailu.
- Repo cizího vlastníka (git: „detected dubious ownership“) už nevyrábí řadu chyb: nespustí
  se v něm žádný další příkaz gitu a skóre se nepočítá (`–`, skupina NELZE ZKONTROLOVAT).

### Přidáno
- Kontrola `unsafe-ownership` (LOW) s postupem `git config --global --add safe.directory
  <cesta>` – repo-doctor sám `safe.directory` nikdy nenastavuje.
- Test připojení hostingu při `clone_protocol = "ssh"` ověří i SSH (`git ls-remote`).
- JSON report: `score` může být `null`, nové pole `untrusted_owner`, pásmo `unchecked`.

## [0.1.1] – 2026-10-01

### Změněno
- Otisk tajemství je scrypt s pevnou solí (v2) – **allowlist položky pro tajemství je nutné
  přegenerovat** (`repo-doctor scan . --offline --report json --only secrets-history`). (#8)
- Klávesy průvodce a formulářových dialogů jsou v registru zkratek (`wizard_finish`,
  `wizard_add_forge`, `dialog_save`) – jdou přemapovat a jsou v nápovědě. (#2)
- JSON report obsahuje `finding.data`, tep je na jednom řádku; MD/HTML ukazují místní čas se zónou. (#6)

### Opraveno
- Enter v poli ukládá ve všech formulářových dialozích. (#3)
- Sloupce triáže se přizpůsobí místu v panelu při zapnutém levém panelu. (#4)
- Léčba zobrazuje celé dvouřádkové položky předpisu a na repu se změnami nic nepředvybírá. (#5)
- Lokální/neregistrové balíčky (poetry directory/git, npm `file:`/`link:`) se neposílají na OSV. (#7)
- Timeout `token_cmd` ukončí celou skupinu procesů. (#9)

## [0.1.0] – 2026-10-01

### Přidáno
- TUI (Textual) v konceptu „Triáž“: přehled s pásmy a tepem, karta repa s diagnózou,
  léčba s diffem a potvrzením, složky, hostingy, vzdálená repa, nastavení, export,
  nápověda, průvodce prvním spuštěním a příkazová paleta; světlé i tmavé téma.
- 30 kontrol v kategoriích Bezpečnost, Údržba, Stav gitu a Hosting.
- Automatické opravy (`.gitignore`, citlivé soubory, licence, pre-commit, CI, README,
  `.dockerignore`) do nové větve `repo-doctor/fixes-<datum>` bez dotyku pracovního stromu.
- Hostingy GitHub (vč. Enterprise), Gitea/Forgejo a GitLab jen pro čtení; tokeny z klíčenky,
  proměnné prostředí nebo příkazu.
- Reporty Markdown, JSON (schéma v1) a samostatné HTML; CLI `scan`, `explain`, `checks`,
  `forges test`, `config path|validate`.
- Přemapování zkratek v `[keys]` s kontrolou kolizí.
