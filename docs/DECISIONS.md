# Rozhodnutí (ADR v kostce)

Záznam rozhodnutí, která zadání nechalo otevřená. Nejnovější nahoře v rámci sekce.

## Git a bezpečnost

- **Opravy přes dočasný index, ne `git switch`.** Commity oprav se staví v dočasném
  indexu (`GIT_INDEX_FILE`) pomocí `hash-object` → `update-index` → `write-tree` →
  `commit-tree` a nakonec `git branch repo-doctor/fixes-<datum> <commit>`. Pracovní strom,
  index, aktuální branch ani HEAD se nikdy nezmění – uživatel si větev zkontroluje sám.
  `git rm --cached` u citlivých souborů se tak projeví jen ve větvi oprav, soubor na disku
  zůstává. Existující větev se nikdy nepřepíše (`-2`, `-3`… přípona).
- **Opravy odmítnou repo s jakoukoli změnou**, včetně nesledovaných souborů – je to
  nejbezpečnější výklad „nesahá na necommitnuté změny“.
- **Commity oprav** se vytváří s `--no-gpg-sign` a bez hooků (commit-tree je nespouští):
  podpisový pinentry by v TUI zamrzl. Uživatel může větev před mergem přepodepsat.
- **Git bez vedlejších efektů:** všechny příkazy běží s `GIT_OPTIONAL_LOCKS=0` (status
  nepřepisuje index), `core.fsmonitor=false`, prázdným `diff.external`, `--no-textconv`
  a `--no-ext-diff` (cizí `.git/config` nesmí spouštět programy), `GIT_TERMINAL_PROMPT=0`
  a SSH v `BatchMode`. Uživatelské cesty/refy jdou vždy za `--`/`--end-of-options`,
  názvy větví se ověřují `git check-ref-format --branch`.
- **SSH příkaz (0.1.2):** git dostává vždy `GIT_SSH_COMMAND` (proměnná má přednost před
  `core.sshCommand`, takže lokální `core.sshCommand` cizího repa se nikdy nespustí – hardening
  ho navíc přebíjí prázdnou hodnotou). Základ se bere v pořadí: proměnná `GIT_SSH_COMMAND`
  z prostředí → globální/systémový `core.sshCommand` (`git config --global/--system`,
  spuštěno v `$HOME`, timeout 5 s, výsledek cachovaný na běh) → `ssh`. Na konec se přidá
  `-o BatchMode=yes`, aby se SSH nikdy neptal na heslo a nezasekl TUI. Wrapper skript proto
  musí zbylé argumenty předat dál (`exec ssh "$@"`); pokud to neumí, vypne se přidávání
  volbou `ssh_batch_mode = false` v konfiguraci (pak odpovědnost za neinteraktivní běh
  nese wrapper).
- **České hlášky SSH chyb (0.1.2):** `sshhelp.explain_ssh_error(stderr, url)` je čistá
  funkce; rozpozná neznámý klíč serveru, odmítnutý klíč a nedostupný server, jinak vrátí
  None a zobrazí se původní (redigovaný) text. Ve výzvě `ssh -p <port> git@<host>` se `-p`
  vynechá, když URL port nemá (výchozí 22); uživatel se bere jen z SSH URL a jen když je
  „bezpečný“ (u https je v userinfo typicky token), jinak `git`. Původní text gitu zůstává
  vidět: u klonu v notifikaci „(git: …)“, u `--fetch` v `errors.fetch_detail` (reporty, karta
  repa). „Test připojení“ hostingu je API přes HTTPS – při `clone_protocol = "ssh"` proto
  navíc zkusí `git ls-remote --heads` na SSH URL prvního repa (jen čte) a problém ukáže
  jako varování.
- **`--fetch`** je jediná výjimka z „CLI nic nemění“: aktualizuje jen remote-tracking refy
  a je vypnutý ve výchozím stavu (zadání: „žádný fetch bez `--fetch`“).
- **Tajemství se v modelu vůbec nevyskytují.** Skener vrací jen maskovanou ukázku
  (`AKIA…(20 znaků)`) a sha256 otisk; surová hodnota modul `secrets_scan` neopustí.
  Tokeny hostingů jsou v objektu `Token` (repr maskovaný, nepicklovatelný) a jsou
  registrované v globálním redakčním registru, přes který jdou logy, chybové hlášky
  gitu a výsledné reporty (obrana do hloubky).
- **Otisk tajemství** je `scrypt(secret, salt=„repo-doctor/secret-fingerprint/v2“, n=2¹⁴)`,
  zkrácený na 16 hex znaků. Sůl je pevná (ne náhodná), protože otisk musí být stejný na všech
  strojích – allowlist v `.repo-doctor.toml` se commituje a používá v CI. Pomalá funkce brání
  slovníkovému útoku na sdílený report; po změně verze je potřeba allowlist přegenerovat.
- **`token_cmd`** se spouští bez shellu (`shlex.split`), s timeoutem 15 s, stdin
  `/dev/null`; bere se první neprázdný řádek (jako `pass show`). Výstup se nikdy
  nepropisuje do chyb – ani při nenulovém exit kódu. Běží ve vlastní skupině procesů, po
  timeoutu se ukončí celá skupina (i potomci, kteří by drželi rouru).
- **Skóre:** 100 − 25 za HIGH, 9 za MED, 3 za LOW, s limitem na kontrolu (max 50 / 18 / 6),
  aby deset nálezů jedné kontroly nesrazilo repo na nulu. Kalibrováno podle wireframu.
- **Pásma triáže mají prioritu** KRITICKÉ > SLEDOVAT > BEZ TEPU > ZDRAVÉ: repo s HIGH
  nálezem, které je zároveň bez tepu, patří mezi kritická.

## Kontroly

- **Nález „nekompletní sken“ má vlastní ID `scan-incomplete`** (LOW), aby šel vysvětlit
  (`explain`) i allowlistovat. Vzniká při vypršení `limits.history_timeout_s`.
- **Chybějící lockfile** je samostatná kontrola `deps-lockfile-missing` (kategorie
  Bezpečnost, funguje offline). U Rustu jen pro aplikace (`src/main.rs`) – knihovny
  lockfile commitovat nemusí.
- **`deps-outdated`** hlásí jeden nález za úroveň (major = MED, minor/patch = LOW) místo
  nálezu za balíček – jinak by zastaralé závislosti přehlušily vše ostatní. Kontrolují se
  jen přímé závislosti (PyPI a npm, jak požaduje zadání).
- **OSV:** závažnost se dohledá přes `/v1/vulns/<id>` (max. 50 ID na sken, cache 24 h);
  bez údaje → MED.
- **`gitignore-incomplete`** ověřuje pravidla skutečným `git check-ignore --no-index`
  proti reprezentativním cestám a ignoruje globální excludes uživatele (nesdílí se).
- **`public-sensitive`** skenuje jen konfigurační soubory (yml, ini, toml, json, env, tf,
  inventáře…), ne dokumentaci – ukázková IP v README by jinak dělala falešné poplachy.
  Bez znalosti viditelnosti je kontrola přeskočena. U GitHubu bez připojení se viditelnost
  zjišťuje neautentizovaným `GET /repos/{owner}/{repo}` (404 = neznámo).
- **Forgejo vs. Gitea:** společná implementace nad `/api/v1`. CI se čte z commit statusu
  výchozí větve (Gitea/Forgejo Actions ho nastavují), ochrana větve z `branches/{b}.protected`.
  Rozdíl řešíme jen v `test_connection` (upozornění, když je `type = "gitea"` ale instance
  je Forgejo). Bezpečnostní alerty Gitea/Forgejo/GitLab (Free) přes API neposkytují.
- **Přiřazení repa k hostingu** porovnává jen hostname (SSH port 2222 se liší od webového
  3000); při více účtech na stejném hostu rozhoduje shoda vlastníka s `user`/`org`.

## TUI a zkratky

- **Kolize zkratek** z výchozí tabulky zadání:
  - `1`–`8` přepínají obrazovky; filtry severity jsou `Alt+1`/`Alt+2`/`Alt+3` (filtr
    „≥ severity“, druhé stisknutí vypne).
  - `G` = konec seznamu, seskupení je `Alt+G` (triáž → složka → hosting).
  - `g`/`G` a `j`/`k` patří „pohybu“ a nesmí se přemapovat na nic jiného (pohyb je aktivní
    ve všech seznamech); globální klávesy kolidují se vším.
  - `f` (léčba) je stejná akce na přehledu i v kartě – to kolizí není.
  - `e` znamená „upravit“ ve Složkách/Hostingách a „exportovat“ v Exportu (jiný kontext).
  - `Esc` je vyhrazený (zpět / zrušit) a nejde přemapovat.
  - `space` v Léčbě přepíná opravu, ve Složkách zapíná/vypíná složku.
  - Vzdálená repa: `c` klon, `v` přepnutí pohledu, `Ctrl+R` znovu načíst.
- **Validace `[keys]`** proběhne při startu (`repo-doctor` skončí s chybou a exit kódem 2)
  i v `repo-doctor config validate`. V TUI (kdyby se konfigurace změnila za běhu) se chyba
  ukáže notifikací a použijí se výchozí zkratky.
- **Spodní lišta** je vlastní widget `KeyBar` (ne Textual `Footer`) – pořadí a výběr kláves
  je podle wireframu a na úzkém terminálu se vypouštějí méně důležité položky, `?` a `q`
  zůstávají vždy.
- **Nadpis panelu vlevo i vpravo** („repo-doctor · triáž … ● online“) se skládá do jednoho
  `border_title` podle aktuální šířky – Textual jinak umí jen jeden nadpis.
- **Průvodce „Přeskočit“** zapíše prázdnou konfiguraci, aby se průvodce neobjevoval znovu.
- **`q` na přehledu ukončí aplikaci bez dotazu** (nic se neztratí), `Ctrl+C` okamžitě.
- **Hledání `/`** filtruje podle názvu repa, cesty, ID kontroly a textu nálezu.
- **Historie „Od včerejška“** porovnává s předchozím uloženým skenem (ne nutně
  s kalendářním včerejškem) – posledních N skenů (`limits.history_size`, výchozí 30).
- **Barvy světlého tématu** jsou ztmavené varianty palety, aby text severit měl na pozadí
  `#f5f6f8` kontrast alespoň 4.5:1 (WCAG AA).

## Výkon

- Repozitáře běží paralelně (`--jobs`, výchozí počet CPU) jako asyncio úlohy; git příkazy
  a kontroly ve vláknech (`asyncio.to_thread`), síť přes async httpx se semaforem (8).
- **Benchmark:** syntetická sada 50 repozitářů musí offline projít do **60 s** (test
  `tests/test_scanner.py::test_benchmark_50_repos`; v CI na 4 jádrech typicky ~5–10 s).
- OSV se ptá dávkově (`querybatch`, až 1000 balíčků na dotaz) po repech, aby se tabulka
  v TUI plnila průběžně; odpovědi se cachují na disk.

## Repo a proces

- **Branch:** zadání chtělo `feat/initial-implementation`, prostředí ale vyžaduje vývoj na
  přidělené branchi `claude/new-session-32njj2`. Použili jsme ji (obsah je stejný).
- **Dokumentace kontrol** leží v `docs/checks/<id>.md` a do wheelu se kopíruje jako
  `repo_doctor/_checkdocs` (hatch `force-include`), takže `explain` funguje i po instalaci.
- **Python 3.12+:** zadání; CI testuje 3.12 a 3.13.
