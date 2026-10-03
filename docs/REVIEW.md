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
