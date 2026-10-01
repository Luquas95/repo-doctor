# Changelog

Formát podle [Keep a Changelog](https://keepachangelog.com/cs/1.1.0/), verze podle SemVer.

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
