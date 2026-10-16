# CLAUDE.md – jak pracovat s repo-doctorem

## Spuštění

```sh
uv sync                       # závislosti (Python 3.12+)
uv run repo-doctor            # TUI (na terminálu)
uv run repo-doctor scan ~/projekty --offline --report md
uv run repo-doctor explain secrets-history
```

## Testy a kvalita

```sh
uv run pytest                 # testy nikdy nevolají síť (respx), repa se staví v tmp_path
uv run pytest --cov           # pokrytí ≥ 85 %
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy                   # --strict
uv run pytest tests/test_snapshots.py --snapshot-update   # po vědomé změně vzhledu TUI
uv run python -m repo_doctor.reports.jsonreport > docs/report-schema.json  # po změně JSON schématu
```

Testovací „tajemství“ se skládají až za běhu (`tests/factory.py`), do repa nepatří žádné
skutečné ani regexům odpovídající hodnoty. Testy TUI používají `tests/tui_helpers.py`
(`make_app`, `FakeScanner`), ukázková data jsou v `tests/sample.py`.

## Architektura

- Jádro je oddělené od UI: `discovery`, `gitwrap`, `checks/`, `scanner`, `fixes`, `reports/`,
  `forges/`, `config`, `netpolicy` (http jen pro `allow_http_hosts`), `cleanup` (koš),
  `sync` (jen ff), `guard`, `sbom`, `notify`, `schedule`, `mcpserver`. TUI (`tui/`), CLI
  (`cli.py`) i MCP server jsou tenké vrstvy nad ním.
- Co mění soubory nebo repa, je volitelné, s náhledem a potvrzením (výchozí „Zrušit“)
  a nikdy nepushuje. MCP server je jen pro čtení.
- `gitwrap.Git` je jediné místo, kde se volá `git` (timeouty, bezpečné prostředí, redakce chyb).
- Kontroly nevolají síť: scanner předem připraví `RepoContext.deps` (OSV, registry, licence),
  `RepoContext.forge_snapshot` (API hostingu), `noreply_email` a `action_shas`.
- Zkratky jsou jen v `keymap.py` (TUI, nápověda i README se generují odtud; test hlídá tabulky v README).

## Přidání nové kontroly

1. Vytvoř soubor v `src/repo_doctor/checks/` (moduly se načítají automaticky):

   ```python
   from repo_doctor.checks.base import Check, RepoContext, register
   from repo_doctor.models import Category, Finding, Severity

   @register
   class MyCheck(Check):
       id = "my-check"
       title = "Krátký název"
       severity = Severity.LOW
       category = Category.MAINTENANCE
       # network = True / needs_forge = True, pokud potřebuje síťová data

       def run(self, repo: RepoContext) -> list[Finding]:
           return [self.finding("zpráva", path="soubor", key="stabilní-klíč")]
   ```

   Nedostupná data → `raise SkipCheck("důvod")`. Tajemství nikdy do `Finding` nedávej –
   jen `masking.mask(...)`.
2. Volitelně `fix(repo, findings) -> Patch` (jen vrací změny, nic nezapisuje) a `fixable = True`.
3. Napiš `docs/checks/<id>.md` (sekce „Co kontrola hledá“, „Proč to vadí“, „Postup“) –
   test `test_every_check_is_documented` to vyžaduje.
4. Testy: pozitivní i negativní případ přes `tests/factory.py`.

## Vydání

Uživatelé instalují sestavenou aplikaci (balíčky), ne přes uv/pipx – uv je jen vývojový nástroj.

```sh
uv sync --locked --no-dev --group build && uv run packaging/build.sh   # dist/repo-doctor
packaging/package.sh        # dist/release: .deb, .rpm, tarball, PKGBUILD, SHA256SUMS (potřebuje nfpm)
```

Vydání: zvedni verzi v `pyproject.toml` a `src/repo_doctor/__init__.py`, doplň CHANGELOG
a pushni tag `vX.Y.Z` – `.github/workflows/release.yml` sestaví, otestuje instalaci na
distribucích, vytvoří GitHub Release a nasadí APT/RPM repozitář na Pages (secret
`RELEASE_SIGNING_KEY`).

## Git workflow

Conventional Commits, po každém bloku musí projít testy. Rozhodnutí zapisuj do
`docs/DECISIONS.md`.
