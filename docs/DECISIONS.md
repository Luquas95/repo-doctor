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
- **Hooky a příkazy z cizího repa (0.1.4):**
  - **Hooky** vypíná `-c core.hooksPath=/dev/null` u každého volání (`_SAFE_CONFIG`, i clone
    a ls-remote). `/dev/null` není adresář, takže git žádný hook nenajde; ověřeno na gitu
    2.43 testem (hook `reference-transaction` z `.git/hooks` i z lokálního `core.hooksPath`
    by jinak zablokoval `git branch`). Vypnou se i globální hooky uživatele – repo-doctor
    commituje jen do vlastní větve oprav a hooky nepotřebuje.
  - **`remote.*.uploadpack`/`receivepack` nejde přebít přes `-c`**: git bere *první* hodnotu
    („more than one uploadpack given, using the first“), tedy tu z lokální konfigurace. Proto
    fetch, ls-remote i clone předávají `--upload-pack=git-upload-pack`. `receivepack` se
    nepoužívá – repo-doctor nikdy nepushuje.
  - **`core.gitProxy`** platí také „první vyhrává“; vypíná ho prázdné `GIT_PROXY_COMMAND`
    (git pak konfiguraci vůbec nečte). Vypne to i `core.gitProxy` uživatele – `git://` je
    stejně zakázaný.
  - **Credential helpery:** pokud lokální konfigurace definuje `credential.helper` nebo
    `credential.<url>.helper`, přidá se `-c credential.helper=` (v gitu prázdná hodnota
    vyprázdní seznam, tedy i helpery pro URL) a za něj znovu helpery ze systémové a globální
    konfigurace uživatele (`git config --system/--global --includes --get-regexp`, cache na
    běh). Uživatelův helper tak funguje dál; helper z `includeIf` podle složky se mimo repo
    nevyhodnotí, stejně jako u `core.sshCommand`.
  - **Navíc oproti zadání:** lokální `core.alternateRefsCommand` se při fetchi s alternates
    opravdu spustí (ověřeno) → přebíjí se prázdnou hodnotou. Fetch běží s
    `--no-recurse-submodules` (submodul má vlastní, neošetřenou konfiguraci). Lokální
    `http.sslVerify=false` (i pro konkrétní URL) se přebíjí na `true`, `http.proxy`
    a `remote.*.proxy` na prázdnou hodnotu – jinak by šlo s globálním credential helperem
    uživatele odposlechnout přihlašovací údaje.
  - **Protokoly:** `GIT_ALLOW_PROTOCOL=https:ssh` (má přednost i před lokálním
    `protocol.*.allow`). `git://` je nešifrovaný a neověřený a jen u něj se uplatní
    `core.gitProxy`; `http://` posílá přihlášení v otevřené podobě; `file`/lokální cesta by
    spustila `upload-pack` lokálně a `ext::` libovolný příkaz. Odmítnutí se překládá na
    „Remote používá nepovolený protokol X…“. Testy si `file` povolují interním přepínačem
    `_allow_protocols` (fixture `allow_file`), veřejná volba neexistuje.
- **`http://` jen pro hosty z `allow_http_hosts` (0.2.0):**
  - **Per-host, ne globální přepínač:** výchozí stav (prázdný seznam) se chová jako 0.1.4.
    Uživatel povolí jen konkrétní důvěryhodné hosty (Forgejo v Tailscale). Volba je jen
    v globálním `config.toml` – `RepoOverrides` ji nezná (`extra="forbid"`), takže cizí repo
    si `http` nepovolí.
  - **Per-operace:** `GIT_ALLOW_PROTOCOL` se o `http` rozšíří jen pro jeden příkaz, a jen když
    všechny `http://` URL, na které se může připojit, mají povolený host. U fetch se berou
    všechny remoty (i víc URL jednoho remotu a `branch.*.remote` zadané jako URL), vždy po
    přepisu `insteadOf` (`git ls-remote --get-url`) – jinak by lokální konfigurace cizího repa
    přesměrovala povolenou URL jinam. URL přes https/ssh seznam nepotřebují (zůstávají
    šifrované); proto jeden `https` remote na GitHub `http` pro Tailscale remote neblokuje.
  - **Přesměrování:** s povoleným `http` běží příkaz s `http.followRedirects=false` –
    `GIT_ALLOW_PROTOCOL` hlídá jen schéma, ne host, takže `initial` by pustil přesměrování
    z povoleného hosta na libovolný jiný http host. Lokální `http.followRedirects`
    (i pro konkrétní URL) hardening přebíjí na `false`.
  - **Porovnání hosta:** malá písmena, bez koncové tečky, IDN → punycode; IP adresy přes
    `ipaddress`. Nestandardní číselné zápisy (`100.1`, `0x64.1.1.1`) se neuznají ani jako
    hostname, ani jako IP – curl by je převedl jinak, než vypadají.
  - **API hostingů:** `HttpClient` odmítne každý `http://` požadavek (i po přesměrování) na host
    mimo seznam ještě před odesláním (`InsecureHostError`) – token tak nikdy neodejde po http
    jinam. Hosting s `http://` URL mimo seznam je „nedostupný“ s vysvětlením (načtení
    konfigurace kvůli tomu neselže, aby šlo seznam doplnit v Nastavení).
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
- **Cizí vlastník / `safe.directory` (0.1.2):** scanner nejdřív spustí jediné
  `git rev-parse --git-dir` (bez čtení lokální konfigurace). Když git odpoví „detected dubious
  ownership“, repo se označí `untrusted_owner`, žádný další příkaz gitu se nespustí, jeho
  `.repo-doctor.toml` se nečte a vznikne jediný nález `unsafe-ownership` s postupem
  `git config --global --add safe.directory <cesta>`. repo-doctor `safe.directory` nikdy
  nenastavuje ani nepřebíjí přes `-c` – rozhodnutí důvěřovat cizímu repu patří uživateli.
  **Severity LOW** (ne „info“ – žádnou takovou úroveň nemáme a nález je potřeba vidět, ale
  repo samo o sobě není v nebezpečí; CLI tak skončí s 1 jen při `--fail-on low`).
  **Skóre se nepočítá** (`score = null` v JSON, `–` v TUI a reportech), repo je v triáži ve
  skupině NELZE ZKONTROLOVAT na konci a do průměrného zdraví ani historie se nezapočítá.
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

## MCP server (0.2.0)

- **SDK `mcp` 2.x** (`MCPServer`, dřív FastMCP). Logika nástrojů je v `RepoDoctorTools` bez
  závislosti na MCP – MCP vrstva (`build_server`) jen registruje funkce s docstringy.
- **Jen čtení:** nástroje pracují nad posledním výsledkem skenu (cache repo-doctoru);
  `scan` spouští běžný sken s `offline = not mcp.network` a `fetch = False`. Jediný zápis je
  `last-scan.json` v cache repo-doctoru – stejně jako po skenu v TUI. Všechny nástroje mají
  anotaci `readOnlyHint`.
- **Maskování:** nálezy už nesou jen maskované ukázky; výstupy navíc procházejí redakčním
  registrem a texty se zkracují (500 znaků). Stránkování `offset`/`limit` (max 100).
- **Podpříkazy CLI** se zjišťují z registru typeru (`subcommands()`), ne z ručního seznamu –
  nový příkaz (`mcp`) by jinak skončil v TUI větvi a stdio server by vypsal nápovědu.

## Pre-push hlídač (0.2.0)

- **Dva směry hooků:** repo-doctor při *svých* voláních gitu hooky nikdy nespouští
  (`core.hooksPath=/dev/null`, 0.1.4). Hook `pre-push`, který léčba nainstaluje, spouští
  uživatelův *vlastní* `git push` – a ten volá `repo-doctor guard`. Tyto dvě věci se
  nepotkají: guard sám spouští git zase s vypnutými hooky.
- **Lokální hook** je jediný zápis do `.git/hooks`: jen hook `pre-push`, jen v repu uživatele
  (`apply` odmítne repo cizího vlastníka), existující cizí hook nepřepíše (pozná svůj podle
  značky) a při `core.hooksPath` se nenabízí, protože by se nespustil. Když `repo-doctor`
  chybí v PATH, hook push nezablokuje (jen vypíše varování).
- **Pre-commit varianta** používá `repo: local` s `entry: repo-doctor guard` – oficiální
  gitleaks hook pro pre-commit skenuje staged změny, což při pushi nedává smysl. Soubor se
  upraví jen tehdy, když jde blok bezpečně připojit (`repos:` je poslední klíč nejvyšší
  úrovně); jinak se nabídne jen lokální varianta.
- **Rozsah:** `lsha --not --remotes` pro novou větev, jinak `rsha..lsha`; z pre-commitu
  `PRE_COMMIT_FROM_REF..PRE_COMMIT_TO_REF`. Vestavěný skener (rychlý, bez závislostí);
  allowlist platí stejně jako v kartě repa.

## Synchronizace (0.2.0)

- **Jediná funkce, která mění pracovní strom** – a jen `git merge --ff-only @{u}` (git sám
  odmítne cokoli jiného než fast-forward). Repo musí být na sledované větvi, pozadu a ne
  rozdělené, bez změn ve sledovaných souborech a bez nesledovaných souborů, které by
  fast-forward přepsal. Stav se těsně před provedením zjistí znovu.
- **Hooky zůstávají vypnuté** (`post-merge`, `post-checkout`…) – stejná pravidla jako všude.
- **Repo s vlastními filtry/drivery v `.git/config` se nedohání:** hardening by filtry
  (např. git-crypt, smudge) při checkoutu vypnul a do pracovního stromu by se zapsal
  nefiltrovaný obsah. Takové repo je potřeba dohnat ručně (`git pull --ff-only`).
- **Fetch je samostatný krok** (`f` v TUI, výchozí v CLI) a řídí se pravidly sítě z 0.1.4
  a `allow_http_hosts`.

## Plánovaný sken a upozornění (0.2.0)

- **Uživatelský systemd timer**, ne cron ani root: `systemctl --user` je na Arch/Fedora
  standard, `Persistent=true` dožene zmeškaný běh po uspání, `Nice`/`IOSchedulingClass=idle`
  šetří stroj. Bez systemd se jen vypíše řádek pro cron – nic se nezapisuje do crontabu.
- **Upozorňuje se jen na změny** proti minulému skenu (otisky nálezů), jinak by se upozornění
  rychle ignorovala. První běh jen uloží výchozí stav.
- **Text upozornění nese jen názvy rep a počty** – ntfy i e-mail jsou cizí služby, cesty
  k souborům a maskovaná tajemství tam nemají co dělat.
- ntfy `http://` jen pro `allow_http_hosts` (ověří se při načtení konfigurace i při odeslání),
  přesměrování se nenásledují; token přes stejné zdroje jako u hostingů. E-mail jen přes
  lokální `sendmail` – žádné SMTP heslo v konfiguraci.
- Plánovaný sken ve výchozím stavu nefetchuje (`[schedule] fetch`).

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
