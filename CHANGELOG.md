# Changelog

Formát podle [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/), verze podle SemVer.

## [0.2.0] – nevydáno

### Přidáno
- `repo-doctor mcp`: MCP server (stdio) jen pro čtení – nástroje `list_repos`, `repo_status`,
  `repo_findings`, `search_findings`, `last_scan_summary`, `scan`, `explain_check`; offline
  ve výchozím stavu (`[mcp] network`), maskované výstupy, stránkování.
- Kontrola `email-exposure`: tvůj osobní e-mail v historii veřejného repa (maskovaný
  `l***@proton.me`); léčba nastaví v repu lokálně `user.email` na noreply adresu hostingu.
- Kontrola `ci-security`: nepřipnuté akce, `pull_request_target` s kódem z PR, injekce výrazů
  do `run:`, široká oprávnění tokenu, tajemství v logu, self-hosted runner ve veřejném repu;
  léčba připne akce na SHA zjištěné přes API GitHubu (`@<sha> # v4`).
- Kontrola `duplicate-clone`: stejný remote (SSH/HTTPS, aliasy) nebo kořenový commit napříč
  sledovanými složkami, s porovnáním stavu klonů; přehled jde seskupit podle remotu (`alt+g`).
- Kontrola `license-compat`: licence přímých závislostí (PyPI, npm, crates.io) vs. permisivní
  licence projektu – silný copyleft a chybějící licence; informativní, ne právní rada.
- `repo-doctor sbom REPO` a export z karty repa (`b`): SBOM CycloneDX 1.5 z lockfilů, bez sítě
  (licence z cache registrů).
- Léčba umí i lokální akce bez commitu (`.git/config`, hook) a varianty oprav.

### Bezpečnost
- `http://` jen pro hosty výslovně povolené v `allow_http_hosts` (hostname, `*.domena`, IP,
  CIDR) – rozhoduje se pro každý příkaz gitu zvlášť, přesměrování se nenásledují, token
  hostingu po `http` odejde jen na povolené hosty. Výchozí chování se nemění.

## [0.1.4] – 2026-10-03

### Bezpečnost
- Cizí repo už přes `.git/` ani lokální konfiguraci nespustí program při skenu, `--fetch`, `F`
  ani léčbě: hooky jsou vypnuté (`core.hooksPath=/dev/null`, i globální), fetch/ls-remote/clone
  předávají `--upload-pack=git-upload-pack` a nestahují submoduly, lokální credential helpery,
  `core.gitProxy`, `core.alternateRefsCommand`, proxy a `http.sslVerify` se neutralizují.
  Helpery a SSH nastavení z tvé globální konfigurace fungují dál.
- Síťové operace jen přes `https` a `ssh` (`GIT_ALLOW_PROTOCOL`); remote s `git://`, `http://`,
  `file://`, lokální cestou nebo `ext::` se nefetchuje a nahlásí se česky proč.

### Přidáno
- TUI: zkratka `F` spustí sken s `git fetch` (jako `repo-doctor scan --fetch`); selhání
  fetche ohlásí notifikací, přeložená SSH hláška je v kartě repa. V offline režimu se odmítne. (#15)
- Testy karty repa, reportů a okrajových větví SSH sondy a detekce cizího vlastníka. (#13, #14)

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
