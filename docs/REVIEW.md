# Revize (3 nezávislí subagenti)

Na konci implementace proběhly tři nezávislé revize: (1) bezpečnost, (2) správnost
detekce, (3) UX TUI a čitelnost reportů. Nálezy HIGH a MEDIUM jsou opravené a pokryté
regresními testy. LOW nálezy jsou opravené, pokud byly levné, jinak zapsané níže jako
známé limity.

Legenda: ✅ opraveno · 📝 známý limit / odloženo. Všechny dříve odložené položky
byly dořešené v issues #2–#9.

## 1. Bezpečnost

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | Token v URL remote jako uživatel (`https://<token>@github.com/…`) a `?private_token=` se nemaskoval – prosakoval do JSON reportu, karty repa a cache. | ✅ `redact_url_credentials` maže celou userinfo část i tokenové query parametry (`test_masking_paths`, `test_scanner`). |
| 2 | MEDIUM | Cizí `.git/config` (rozbalený archiv s `.git`) mohl přes `filter.X.clean` / `diff.X.textconv` spustit program už při `git status` / `log -p`; totéž přes gitleaks. | ✅ `Git.hardening()` přebije všechny filtry, textconv, externí diff a merge drivery z lokální konfigurace repa pro každé volání; gitleaks dostává totéž přes `GIT_CONFIG_*` (`test_repo_config_cannot_run_programs`). |
| 3 | MEDIUM | `PRIVATE-TOKEN` (GitLab) a `Authorization` mohly po přesměrování nebo přes absolutní `Link: rel=next` odejít na cizí host. | ✅ Request hook odstraní přihlašovací hlavičky na cizím originu; stránkování mimo origin se nenásleduje (`test_credentials_not_sent_to_other_origin`, `test_pagination_does_not_leave_origin`). |
| 4 | LOW | Otisk tajemství je nesolený `sha256[:16]` – u slabých hesel (generic-secret) jde slovníkově ověřit. ✅ #8: otisk je scrypt (n=2¹⁴) s pevnou solí aplikace – stabilní napříč stroji (allowlist, CI), ale ověření jednoho kandidátního hesla stojí ~40 ms místo mikrosekund. |
| 5 | LOW | `owner_path` z URL remote se po dekódování vkládal do cesty API (např. `..`). | ✅ `valid_owner_path` – neplatná cesta se na API vůbec nepošle. |
| 6 | LOW | Soubory HTTP cache krátce čitelné pro ostatní (umask, volnější adresář). | ✅ `os.open(..., 0o600)` a `ensure_private_dir` zpřísní práva adresáře. |
| 7 | HIGH | (0.1.4, revize po 0.1.3) Cizí repo mohlo spustit program přes hook (`reference-transaction` při `fetch` i `git branch` léčby; z `.git/hooks` nebo lokálního `core.hooksPath`), `remote.*.uploadpack` u lokálního upstreamu, lokální `credential.helper = !příkaz`, `core.gitProxy` u `git://`, `core.alternateRefsCommand` a protokol `ext::`. Klávesa `F` to zpřístupnila jedním stiskem. | ✅ `core.hooksPath=/dev/null` pro každé volání; fetch/ls-remote/clone s `--upload-pack=git-upload-pack` a `--no-recurse-submodules`; reset lokálních credential helperů s obnovou helperů uživatele; `GIT_PROXY_COMMAND=""`; přebití `alternateRefsCommand`, proxy a `http.sslVerify`; `GIT_ALLOW_PROTOCOL=https:ssh` s českou hláškou (`tests/test_untrusted_exec.py`, ověřeno i mutací opravy). |
| 8 | — | (0.1.4 → 0.2.0) Zákaz `http` z 0.1.4 znemožnil self-hosted Forgejo na `http://` v Tailscale. | ✅ Volba `allow_http_hosts` (jen globální konfigurace) povolí `http` per host a per operace, bez následování přesměrování; token po `http` jen na povolené hosty (`tests/test_http_hosts.py`). Záruky z 0.1.4 platí dál (`test_untrusted_exec.py`). |

Dodatečně (#9): `token_cmd` běží ve vlastní skupině procesů a po timeoutu se ukončí celá
skupina – potomek držící rouru už neobejde časový limit.

Prověřeno bez nálezu: `token_cmd` (bez shellu, timeout, výstup se nikdy nezobrazí),
klíčenka, escapování HTML reportu, `open_url` jen http(s), klonovací dialog (žádné `..`
ani `/` v názvu, existující cíl odmítne), `--` / `--end-of-options` u gitu, oprava jen přes
dočasný index, POST na OSV bez tokenu.

## 2. Správnost detekce

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | Obecné tajemství nenašlo `DB_PASSWORD="…"`, `GITHUB_TOKEN: …` (prefix s `_`) ani hodnoty bez uvozovek v `.env`. | ✅ Lookbehind místo `\b`; nové pravidlo pro hodnoty bez uvozovek jen v konfiguračních souborech (`.env*`, yaml, ini, toml…). |
| 2 | HIGH | Parser historie: názvy s mezerou (TAB za cestou), přidaný řádek `++ …` se spletl s hlavičkou `+++`. | ✅ Hlavičky se čtou jen mezi `diff --git` a `@@`, koncový TAB/uvozovky se odstraní. |
| 3 | HIGH | `deps-lockfile-missing` hlásil každého člena npm/uv/cargo workspace. | ✅ Lockfile se hledá i v nadřazených složkách. |
| 4 | MEDIUM | AWS secret key končící `/`, `+`, `=` se nenašel. | ✅ `(?![A-Za-z0-9/+=])` místo `\b`. |
| 5 | MEDIUM | `localhost.pem`, `application.pem` považované za veřejné (podřetězec `ca`). | ✅ Veřejné části jen jako celá slova (`ca.pem`, `server-cert.pem`, `fullchain.pem`). |
| 6 | MEDIUM | `public-sensitive` hlásil masky, dokumentační a benchmark rozsahy; chyběla IPv6. | ✅ Jen RFC 1918 + 100.64/10; přidána Tailscale IPv6 `fd7a:115c:a1e0::` a ULA. |
| 7 | MEDIUM | Dockerfile: `*_PASSWORD_FILE=/run/secrets/…`, `API_KEY=changeme`, `TOKEN_URL=https://…` jako HIGH. | ✅ Přeskočí přípony `_FILE/_URL/_PATH…`, cesty, URL a placeholdery. |
| 8 | MEDIUM | Discovery nenašla repo ve složce `build`, `env`, `dist`… | ✅ Nejdřív se ověří, zda jde o repo, až pak se uplatní seznam přeskakovaných složek. |
| 9 | LOW | Čerstvá větev bez vlastních commitů hlášená jako „mergnutá“. | ✅ Větev na stejném commitu jako výchozí se nehlásí. |
| 10 | LOW | `USER root:root` nebyl rozpoznán jako root. | ✅ |
| 11 | LOW | Placeholder filtr potlačoval i tokeny s pevným prefixem a slova jako „replacement“. | ✅ Filtr jen pro obecná pravidla, celá slova. |
| 12 | LOW | `postgres://postgres:postgres@db` jako HIGH. | ✅ Běžná výchozí vývojová hesla se ignorují. |
| 13 | LOW | Yarn Berry `@workspace:` položky posílané na OSV. | ✅ Lokální protokoly (`workspace/portal/link/file/patch`) se přeskakují. #7: přeskakují se i poetry zdroje `directory/file/git/url` a npm verze `file:/link:/git…`; aliasy `npm:` se převedou na skutečný balíček. |
| 14 | LOW | Windows cesta `C:\…` parsovaná jako SSH host `c`. | ✅ |
| 15 | LOW | Bez lokální výchozí větve se mergnuté větve nedetekovaly. | ✅ Fallback na `origin/<default>`. |

## 3. UX TUI a reporty

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | `d` v Nastavení mazal položku allowlistu bez potvrzení odkudkoli. | ✅ Jen s fokusem na tabulce allowlistu a přes potvrzovací dialog (výchozí Zrušit). |
| 2 | HIGH | Průvodce: Esc zahodil přidané složky; `q`/`4` ho zavřely bez uložení. | ✅ Potvrzení před zahozením; přepínání obrazovek, `q` i `/` jsou v průvodci blokované. |
| 3 | MEDIUM | „Tab doplní cestu“ nefungovalo. | ✅ `PathInput`: Tab přijme návrh, jinak přejde na další pole. |
| 4 | MEDIUM | Dialog složky se v 80×24 ořezával (chyby nebyly vidět). | ✅ Rolovací dialog, srozumitelné názvy polí v chybách. |
| 5 | MEDIUM | Po filtrování zůstalo vybrané skryté repo (`f` otevřel léčbu jiného repa). | ✅ Výběr se přepne na první viditelné repo nebo zruší. |
| 6 | MEDIUM | Ořezané informace v 80 sloupcích (hlavička léčby, sloupec připojení v Hostingách, lišta zkratek). | ✅ Výška hlaviček `auto`, stav připojení hned za názvem, lišta vypouští nejdřív `esc`, `?`/`q` drží. |
| 7 | MEDIUM | Export přepsal existující soubor bez dotazu. | ✅ Potvrzení přepsání. |
| 8 | MEDIUM | Nápověda bez `esc`/`ctrl+s`/Enter na pásmu; pevně zapsané klávesy v hláškách ignorovaly přemapování. | ✅ Nápověda doplněna; hlášky (sken, zrušit, léčba, editor/web/kopírovat, výběr) se skládají z aktuálního mapování. #2: klávesy průvodce a formulářových dialogů jsou v registru (přemapovatelné, v nápovědě, kontrola kolizí). |
| 9 | LOW | Nejednotný Enter v dialozích (hostingy, klon). | ✅ #3: Enter v poli i `ctrl+s` uloží ve všech formulářových dialozích (složka, hosting, klon), jednotná nápověda. |
| 10 | LOW | Se skrytým panelem (`b`) v 80 sloupcích se zkracují názvy rep. | ✅ #4: TEP a HOSTING se skryjí i tehdy, když by v panelu nezbylo dost místa na název repa. |
| 11 | LOW | Drobnosti textu („… a 6 další“), druhý řádek předpisu, předvýběr na špinavém repu. | ✅ skloňování; #5: předpis vykresluje dvouřádkové položky (vlastní zaškrtávací seznam), na repu se změnami nic nepředvybírá a skryje „potvrdit“, text průvodce se zalamuje sám. |
| 12 | LOW | Reporty: HTML filtr nechával čistá repa, chyběla šipka u `<details>`, hledání podle názvu repa; MD sekce pro každé čisté repo; JSON `pulse_30d` na řádky; čas v UTC bez označení. | ✅ HTML filtr, šipka, hledání podle názvu; MD čistá repa v jedné sekci. #6: místní čas s označením zóny, `finding.data` v JSON, tep na jednom řádku, backticky v MD zachované. |

---

# Revize 0.2.0 (3 nezávislí subagenti)

Stejný postup: (1) bezpečnost nových funkcí, (2) správnost detekce B1/B2/B8/B9,
(3) UX nových obrazovek a CLI. HIGH a MEDIUM jsou opravené s regresními testy (u
bezpečnostních ověřeno i mutací opravy), levné LOW také.

## 1. Bezpečnost

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | Cizí `.git/config` s `core.worktree=../jinam` (a `*` v `info/exclude`) přesměroval fast-forward Synchronizace mimo repo – šlo přepsat např. `~/.bashrc`. | ✅ Sync i úklid odmítnou repo, jehož `--show-toplevel` není jeho cesta (`Git.worktree_is_path`; `test_refused_cases_leave_repo_untouched[worktree]`). |
| 2 | MEDIUM | Fast-forward bez varování přepsal ignorovaný lokální soubor (např. `.env`), který upstream nově sleduje. | ✅ Ignorované soubory se počítají jako kolize (`[ignored-clash]`). |
| 3 | MEDIUM | Pre-push hlídač pustil push, když `git log` selhal – typicky force push nebo nefetchnutý remote (remote sha lokálně neexistuje) nebo timeout. | ✅ Neznámý remote sha → rozsah `--not --remotes`; chyba gitu push zastaví s vysvětlením (`test_guard_unknown_remote_sha_and_errors_fail_closed`). |
| 4 | LOW | Instalace hooku zapisovala přes symlink (`.git/hooks/pre-push` → `~/.local/bin/git`). | ✅ Symlink i cizí vlastník `.git` se odmítnou, zápis s `O_NOFOLLOW` (`test_symlinked_hook_is_refused`). |
| 5 | LOW | `fetch_urls` neviděl remote definovaný starým `.git/remotes/origin` – fetch bez argumentu šel na nepovolený `http` host. | ✅ Vždy se vyhodnotí `origin` i soubory v `.git/remotes` a `.git/branches` (`test_legacy_remotes_file_is_evaluated`). |
| 6 | LOW | Koš na sdíleném svazku (`$topdir/.Trash-uid`) mohl předem připravit jiný uživatel (symlink, práva pro ostatní); celý klon s vlastními ignorovanými soubory (`.env`) šel smazat. | ✅ Koš jen jako vlastní složka bez symlinku a bez práv pro ostatní, kontrola dřív, než se v něm cokoli vytvoří; klon s ignorovanými soubory mimo regenerovatelné složky, s dalšími worktrees nebo bez remote se nesmaže. |

Prověřeno bez nálezu: hooky při fast-forwardu (`post-merge`, `post-checkout`) se nespouští,
submoduly se nerekurzují ani s cizím `submodule.recurse`; MCP nástroje jen čtou, `scan` je
offline, `explain_check` validuje id; upozornění bez hlavičkové injekce (e-mail bez mezer,
`notify-send --`), ntfy dodržuje `allow_http_hosts` a nenásleduje přesměrování; workflow
přes `yaml.safe_load`; obsah unit souborů je pevný nebo validovaný.
📝 Zbytkové riziko: globální git-lfs uživatele při fast-forwardu čte `.lfsconfig` repa
(zapsáno v DECISIONS).

## 2. Správnost detekce

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | `duplicate-clone`: kopie bez remote (seskupené podle kořenového commitu) měly vždy 0 nepushnutých commitů → nabízely se ke smazání i s vlastní prací. | ✅ Kopie bez remote nejsou nikdy „removable“; úklid je odmítne i při opakovaném ověření. |
| 2 | HIGH | `git worktree` se hlásil jako duplicitní klon a nabízel ke smazání. | ✅ Pracovní stromy se nepočítají; klon s dalšími worktrees se nesmaže. |
| 3 | HIGH | `ci-security`: `echo "${{ secrets.X }}" \| docker login --password-stdin` hlášené jako výpis do logu. | ✅ Roura a přesměrování nejsou výpis; `GITHUB_TOKEN` se nepočítá (`test_piped_secret_is_not_logged`). |
| 4 | HIGH | `license-compat`: klasifikátory se zkratkou (`ISC License (ISCL)`, `GNU GPL v2 (GPLv2)`) končily jako „neznámá licence“ – `strip("()")` uřízl závorku. | ✅ Závorky se odstraní jen kolem celého textu, zkratka v závorce se zkusí zvlášť; doplněné aliasy. |
| 5 | MEDIUM | `pull_request_target` nechytal checkout přes `refs/pull/…`, `pull_request.number`, `merge_commit_sha`, `gh pr checkout`, ani `workflow_run`. | ✅ Rozšířené vzory, kontroluje se i `workflow_run` a `run:`. |
| 6 | MEDIUM | Injekce výrazů jen v `run:` – ne ve skriptu `actions/github-script`, ne v hranatých závorkách ani `format('{0}', …)`. | ✅ Normalizace výrazu a kontrola `with.script` (`test_pr_checkout_variants_and_script_injection`). |
| 7 | MEDIUM | `(MIT OR Apache-2.0) AND GPL-3.0-only` vyhodnocené jako permisivní. | ✅ Skutečný parser SPDX výrazu (AND váže silněji, závorky). |
| 8 | MEDIUM | Licence se kontrolovaly i u dev/build závislostí (GPL linter v MIT projektu). | ✅ `devDependencies`, `dev-`/`build-dependencies`, `[dependency-groups]`, `requirements-dev.txt` se vynechají. |
| 9 | MEDIUM | Chyba registru (404 soukromého balíčku, síť) hlášená jako „licence chybí“. | ✅ Závislost se přeskočí (`test_dev_deps_and_registry_errors_not_reported`). |
| 10 | LOW | Pin akce smazal uživatelův komentář; `ssh.github.com` jiný host než `github.com`; licence projektu z celého textu LICENSE (GPL-3 → AGPL). | ✅ Komentář zůstane za tagem; aliasy hostů; licence jen z nadpisu, víc názvů souborů. |
| 11 | LOW | `docker://image:tag` bez digestu, trigger `issues`, `permissions` jen u některých jobů; `email-exposure` nečte historii jen z pushnutých tagů; `.forgejo` workflow se připíná SHA z github.com. | 📝 `issues` a `discussion` doplněné mezi cizí události; zbytek známé limity. |

B1 `email-exposure` bez falešných poplachů (noreply, cizí e-maily, `my_emails`).

## 3. UX nových obrazovek a CLI

| # | Sev. | Nález | Stav |
|---|---|---|---|
| 1 | HIGH | Potvrzovací dialog s dlouhým seznamem (Úklid, 80×24) vytlačil tlačítka a varování mimo obrazovku – fokus na neviditelném „Zrušit“. | ✅ Tělo dialogu se posouvá (max. polovina výšky), varování před seznamem, krátké cesty `repo/složka`, nejvýš 5 položek (`test_long_confirm_keeps_buttons_visible_at_80x24`). |
| 2 | HIGH | Plánovaný sken v Nastavení: tlačítka uříznutá na 80 sloupcích, „Zapnout“/„Vypnout“ bez potvrzení. | ✅ Tlačítka na vlastním řádku; zapnutí i vypnutí přes potvrzení s výchozím „Zrušit“ a náhledem cest k unit souborům a `OnCalendar`. |
| 3 | MEDIUM | Záhlaví Úklidu tvrdilo „nic trvale“, ale `D` maže trvale. | ✅ „Výchozí je koš; trvalé smazání (D) jen po dvojím potvrzení.“ |
| 4 | MEDIUM | `clean` bez kandidátů mlčel o přeskočených aktivních repech a radil `--apply`. | ✅ „N rep s nedávnou aktivitou přeskočeno – zahrne je --all“, „Nic k úklidu.“ |
| 5 | MEDIUM | `sync`/`clean` s neexistující cestou skončily 0. | ✅ Chyba a exit 2. |
| 6 | MEDIUM | `sync` CLI fetchoval i v náhledu (TUI ne) – v rozporu se zárukou „CLI repozitáře nemění“. | ✅ Výchozí bez fetch, `--fetch` na požádání (stejně jako `scan`). |
| 7 | MEDIUM | `sync`/`clean` vždy exit 0 i při selhání. | ✅ Exit 1, když fetch selže nebo se něco přeskočí; zdokumentováno v nápovědě. |
| 8 | MEDIUM | `scan --scheduled` vs. nápověda exit kódů; `--report`/`--output` se tiše ignorovaly. | ✅ Zdokumentováno, kombinace se odmítne (exit 2). |
| 9 | LOW | Špatné tvary čísel („1 položek“, „1 commitů“, „a 1 dalších“), chybějící nápověda `--depth`, matoucí hláška `25:00`, surové `Mon *-*-* 08:00:00`, pole rozvrhu nečetla nainstalovaný stav, „enter potvrdit“ při fokusu na Zrušit, `alt+g` řadil repo s neznámým remotem do „bez remote“. | ✅ Modul `czech` (tvary podle čísla), nápovědy, „neplatný čas … 00:00–23:59“, „týdně v pondělí 08:00“, pole podle timeru, „enter = zvolené tlačítko“, skupina „neznámý remote“. |
