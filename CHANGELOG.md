# Changelog

Formát podle [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/), verze podle SemVer.

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
