"""Neinteraktivní CLI (pro CI a skripty) a vstupní bod `repo-doctor`.

Bez argumentů (nebo jen s cestami) na TTY spustí TUI; bez TTY vypíše nápovědu.
CLI repozitáře nikdy nemění – opravy jdou jen přes TUI.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from typing import Annotated

import typer

from repo_doctor import __version__, czech, netpolicy, paths
from repo_doctor.checkdocs import load as load_doc
from repo_doctor.checks import all_checks, check_ids
from repo_doctor.config import Config, ConfigError, ConfigStore, RootConfig
from repo_doctor.gitwrap import configure_ssh
from repo_doctor.masking import install_log_redaction, redact
from repo_doctor.models import ScanResult, Severity
from repo_doctor.reports import FORMATS, ReportFormat, render

app = typer.Typer(
    name="repo-doctor",
    help="Audit a údržba git repozitářů. Bez příkazu spustí TUI (jen na terminálu).",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)
forges_app = typer.Typer(help="Připojené git hostingy.", no_args_is_help=True)
config_app = typer.Typer(help="Konfigurace.", no_args_is_help=True)
app.add_typer(forges_app, name="forges")
app.add_typer(config_app, name="config")
schedule_app = typer.Typer(help="Plánovaný sken (uživatelský systemd timer).", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")


def _err(message: str) -> None:
    typer.echo(redact(message), err=True)


def _load_config() -> Config:
    try:
        config = ConfigStore().load()
    except ConfigError as err:
        _err(str(err))
        raise typer.Exit(2) from None
    configure_ssh(batch_mode=config.ssh_batch_mode)
    netpolicy.configure(config.allow_http_hosts)
    return config


def _split(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out = [v.strip() for item in values for v in item.split(",") if v.strip()]
    unknown = sorted(set(out) - set(check_ids()))
    if unknown:
        _err(f"Neznámé kontroly: {', '.join(unknown)}. Seznam: repo-doctor checks")
        raise typer.Exit(2)
    return out


def exit_code(result: ScanResult, fail_on: Severity) -> int:
    return (
        1 if any(f.severity.rank >= fail_on.rank for r in result.repos for f in r.findings) else 0
    )


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Vypíše verzi.")] = False,
) -> None:
    if version:
        typer.echo(f"repo-doctor {__version__}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def scan(
    path: Annotated[
        list[Path] | None, typer.Argument(help="Složky ke skenu (bez nich složky z konfigurace).")
    ] = None,
    report: Annotated[str, typer.Option("--report", "-r", help="Formát: md | json | html.")] = "md",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Soubor pro report (jinak stdout).")
    ] = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Přeskočí všechny síťové kontroly.")
    ] = False,
    no_forges: Annotated[
        bool, typer.Option("--no-forges", help="Nepřipojovat se k hostingům.")
    ] = False,
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Jen tyto kontroly (čárkami).")
    ] = None,
    skip: Annotated[
        list[str] | None, typer.Option("--skip", help="Vynechat kontroly (čárkami).")
    ] = None,
    jobs: Annotated[
        int | None, typer.Option("--jobs", "-j", min=1, help="Počet paralelně skenovaných rep.")
    ] = None,
    fail_on: Annotated[
        str | None, typer.Option("--fail-on", help="Práh exit kódu: high | medium | low.")
    ] = None,
    depth: Annotated[
        int, typer.Option("--depth", min=0, max=12, help="Hloubka pro zadané cesty.")
    ] = 3,
    fetch: Annotated[
        bool,
        typer.Option("--fetch", help="Před skenem `git fetch` (mění jen remote-tracking refy)."),
    ] = False,
    scheduled: Annotated[
        bool,
        typer.Option(
            "--scheduled",
            help="Plánovaný běh: uloží výsledek, porovná s minulým a upozorní jen na změny. "
            "Nevypisuje report a končí 0 (kromě chyby).",
        ),
    ] = False,
) -> None:
    """Naskenuje repozitáře a vypíše report. Exit: 0 bez nálezů nad prahem, 1 nálezy, 2 chyba.

    S --scheduled se report nevypisuje (--report/--output nejdou kombinovat) a exit je 0.
    """
    from repo_doctor.scanner import ScanEvent, Scanner, ScanOptions

    if scheduled and (output is not None or report != "md"):
        _err("--scheduled nejde kombinovat s --report ani --output.")
        raise typer.Exit(2)
    if report not in FORMATS:
        _err(f"Neznámý formát reportu {report!r} (povolené: {', '.join(FORMATS)}).")
        raise typer.Exit(2)
    config = _load_config()
    try:
        threshold = Severity.parse(fail_on) if fail_on else config.checks.fail_on
    except ValueError:
        _err(f"Neplatný práh --fail-on {fail_on!r} (high | medium | low).")
        raise typer.Exit(2) from None
    roots = [RootConfig(path=str(p), depth=depth) for p in path] if path else config.roots
    if not roots:
        _err(
            f"Nejsou nastavené žádné složky. Zadej cestu nebo spusť TUI (průvodce). Konfigurace: {paths.config_file()}"
        )
        raise typer.Exit(2)
    options = ScanOptions(
        offline=offline,
        use_forges=not no_forges,
        only=_split(only),
        skip=_split(skip),
        fetch=fetch or (scheduled and config.schedule.fetch),
    )
    if jobs:
        options.jobs = jobs
    interactive = sys.stderr.isatty()

    def progress(e: ScanEvent) -> None:
        if e.kind == "warning" and e.message:
            _err(f"varování: {e.message}")
        elif interactive and e.kind == "repo_done":
            typer.echo(f"\r[{e.done}/{e.total}] {e.repo or ''}".ljust(60), err=True, nl=False)

    try:
        result = asyncio.run(Scanner(config, options, on_event=progress).run(roots))
    except KeyboardInterrupt:  # pragma: no cover - interaktivní
        _err("Přerušeno.")
        raise typer.Exit(2) from None
    if interactive:
        typer.echo("", err=True)
    if scheduled:
        _scheduled_finish(result, config)
        return
    for r in result.repos:
        if "fetch" in r.errors:
            _err(f"fetch {r.name}: {r.errors['fetch']}")
    fmt: ReportFormat = report
    text = render(result, fmt, no_pulse_days=config.limits.no_pulse_days)
    if output:
        try:
            output.write_text(text, "utf-8")
        except OSError as err:
            _err(f"Report nelze zapsat do {output}: {err.strerror}")
            raise typer.Exit(2) from None
        _err(f"Report uložen: {output}")
    else:
        typer.echo(text, nl=False)
    raise typer.Exit(exit_code(result, threshold))


def _scheduled_finish(result: ScanResult, config: Config) -> None:
    """Uloží výsledek do historie, porovná s minulým a upozorní jen na změny."""
    from repo_doctor import history, notify

    previous = history.load_last_scan()
    if result.cancelled:
        return
    history.save_last_scan(result)
    history.record(
        result, keep=config.limits.history_size, no_pulse_days=config.limits.no_pulse_days
    )
    changes = notify.diff(previous, result)
    deliveries = notify.deliver(config.notify, changes.text()) if changes else []
    notify.save_state(result, changes, deliveries)
    if changes:
        typer.echo(f"Změny: {changes.text()}")
        for d in deliveries:
            typer.echo(f"  {'✓' if d.ok else '✗'} {d.channel} {d.detail}".rstrip())
    else:
        typer.echo("Beze změn – žádné upozornění.")


@app.command()
def explain(
    check_id: Annotated[str, typer.Argument(help="ID kontroly, např. secrets-history.")],
) -> None:
    """Vysvětlí kontrolu a vypíše ruční postup opravy."""
    doc = load_doc(check_id)
    if doc is None:
        _err(f"Neznámá kontrola {check_id!r}. Seznam: repo-doctor checks")
        raise typer.Exit(2)
    typer.echo(doc.text, nl=False)


@app.command("clean")
def clean_cmd(
    path: Annotated[
        list[Path] | None, typer.Argument(help="Složky s repy (bez nich složky z konfigurace).")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--apply", help="Náhled (výchozí), nebo opravdu přesunout do koše."),
    ] = True,
    all_repos: Annotated[
        bool, typer.Option("--all", help="I aktivní repa (jinak jen neaktivní podle konfigurace).")
    ] = False,
    include_dirty: Annotated[
        bool, typer.Option("--include-dirty", help="I repa s necommitnutými změnami.")
    ] = False,
    duplicates: Annotated[
        bool,
        typer.Option("--duplicates", help="I celé duplicitní klony bez změn (z posledního skenu)."),
    ] = False,
    depth: Annotated[
        int, typer.Option("--depth", min=0, max=12, help="Hloubka hledání rep v zadaných složkách.")
    ] = 3,
) -> None:
    """Úklid místa: regenerovatelné složky ignorované gitem (node_modules, .venv, target…).

    Výchozí je náhled. S --apply se složky přesunou do koše (freedesktop Trash) – nikdy
    trvale, nikdy nic sledovaného gitem ani mimo repo, nikdy repo cizího vlastníka.

    Exit: 0 = hotovo, 1 = něco se přeskočilo, 2 = chyba zadání.
    """
    from repo_doctor import history
    from repo_doctor.cleanup import (
        apply_cleanup,
        duplicate_candidates,
        human,
        inspect_repo,
        is_inactive,
        mark_busy,
    )
    from repo_doctor.discovery import discover

    config = _load_config()
    roots = _cli_roots(path, depth, config)
    chosen = []
    active, active_size = 0, 0
    for repo in discover(roots, config.ignore_repos).repos:
        info = inspect_repo(repo.path, config.cleanup.dirs)
        if info.error or not info.candidates:
            continue
        if not all_repos and not is_inactive(info, config.cleanup.inactive_days):
            active, active_size = active + 1, active_size + info.size
            continue
        mark_busy(info.candidates)
        note = (
            f"  (necommitnuté {info.dirty} – přeskočeno, viz --include-dirty)"
            if info.dirty and not include_dirty
            else ""
        )
        typer.echo(f"{repo.display}  {human(info.size)}{note}")
        for c in info.candidates:
            flag = "  [běží proces – přeskočeno]" if c.busy else ""
            typer.echo(f"    {c.rel:<30} {human(c.size):>10}{flag}")
        if not info.dirty or include_dirty:
            chosen += [c for c in info.candidates if not c.busy]
    if duplicates:
        for c in duplicate_candidates(history.load_last_scan()):
            typer.echo(f"{c.path}  {human(c.size)}  (celý duplicitní klon)")
            chosen.append(c)
    total = sum(c.size for c in chosen)
    if active:
        typer.echo(
            f"\n{czech.repos(active)} s nedávnou aktivitou přeskočeno ({human(active_size)}) "
            f"– zahrne je --all."
        )
    if not chosen:
        typer.echo("Nic k úklidu.")
        return
    if dry_run:
        typer.echo(f"\nCelkem k uvolnění: {human(total)}. Nic se nesmazalo – použij --apply.")
        return
    result = apply_cleanup(chosen)
    for p, reason in result.skipped:
        typer.echo(f"  ! přeskočeno {p}: {reason}")
    typer.echo(
        f"Přesunuto do koše: {czech.items(len(result.removed))}, uvolněno {human(result.freed)}."
    )
    if result.skipped:
        raise typer.Exit(1)


def _jde(n: int) -> str:
    return czech.plural(n, "jde", "jdou", "jde")


def _cli_roots(path: list[Path] | None, depth: int, config: Config) -> list[RootConfig]:
    if path:
        missing = [p for p in path if not p.expanduser().is_dir()]
        if missing:
            _err(f"Složka {missing[0]} neexistuje.")
            raise typer.Exit(2)
        return [RootConfig(path=str(p), depth=depth) for p in path]
    if not config.roots:
        _err("Nejsou nastavené žádné složky. Zadej cestu.")
        raise typer.Exit(2)
    return config.roots


@app.command("sync")
def sync_cmd(
    path: Annotated[
        list[Path] | None, typer.Argument(help="Složky s repy (bez nich složky z konfigurace).")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--apply", help="Náhled (výchozí), nebo opravdu dohnat fast-forwardem."
        ),
    ] = True,
    fetch: Annotated[
        bool,
        typer.Option(
            "--fetch/--no-fetch",
            help="Nejdřív git fetch (aktualizuje jen remote-tracking refy; výchozí ne).",
        ),
    ] = False,
    depth: Annotated[
        int, typer.Option("--depth", min=0, max=12, help="Hloubka hledání rep v zadaných složkách.")
    ] = 3,
) -> None:
    """Stav rep vůči remotu a „rychle dohnat“ – jen `git merge --ff-only`.

    Jen čistá repa na sledované větvi, která jsou pozadu (ne rozdělená). Nikdy merge commit,
    rebase, reset ani push. Výchozí je náhled bez sítě; --fetch stáhne novinky, --apply dožene.

    Exit: 0 = hotovo, 1 = fetch selhal nebo se něco přeskočilo, 2 = chyba zadání.
    """
    from repo_doctor.discovery import discover
    from repo_doctor.sync import STATE_LABELS, fast_forward, status

    config = _load_config()
    roots = _cli_roots(path, depth, config)
    ready = []
    fetch_failed = False
    for repo in discover(roots, config.ignore_repos).repos:
        st = status(repo.path, fetch=fetch)
        line = f"{repo.display}  {STATE_LABELS[st.state]}"
        if st.behind or st.ahead:
            line += f" (↓{st.behind} ↑{st.ahead})"
        if st.can_fast_forward:
            line += f" → dožene {czech.commits(st.behind)}, změní {czech.files(len(st.files))}"
            ready.append(repo.path)
        elif st.reason and st.state not in ("clean",):
            line += f" · {st.reason}"
        if st.fetch_error:
            line += f" · fetch: {st.fetch_error}"
            fetch_failed = True
        typer.echo(line)
    if dry_run:
        typer.echo(
            f"\nRychle dohnat {_jde(len(ready))} {czech.repos(len(ready))}. "
            "Nic se nezměnilo"
            + (" – použij --apply." if ready else ".")
            + ("" if fetch else " Bez --fetch se porovnává s naposledy staženým stavem.")
        )
        if fetch_failed:
            raise typer.Exit(1)
        return
    result = fast_forward(ready)
    for p, reason in result.skipped:
        typer.echo(f"  ! {p}: {reason}")
    typer.echo(f"Dohnáno fast-forwardem: {czech.repos(len(result.updated))}. Nic se nepushnulo.")
    if result.skipped or fetch_failed:
        raise typer.Exit(1)


@app.command("guard")
def guard_cmd(
    remote: Annotated[str | None, typer.Argument(help="Název remotu (předává git).")] = None,
    url: Annotated[str | None, typer.Argument(help="URL remotu (předává git).")] = None,
) -> None:
    """Kontrola tajemství v commitech k pushi – pro hook pre-push (rozsah čte ze stdin).

    Exit 0 = v pořádku, 1 = nalezená tajemství (push se zastaví). Výpis je maskovaný.
    """
    from repo_doctor.guard import render, run_guard

    repo = Path.cwd()
    lines = [] if sys.stdin.isatty() else sys.stdin.read().splitlines()
    try:
        config = _load_config()
    except typer.Exit:
        from repo_doctor.config import Config

        config = Config()
    result = run_guard(repo, lines, config)
    if result.blocked:
        typer.echo(render(result), err=True)
        raise typer.Exit(1)


@app.command("sbom")
def sbom_cmd(
    repo: Annotated[Path, typer.Argument(help="Cesta k repozitáři.")],
    fmt: Annotated[
        str, typer.Option("--format", help="Formát (zatím jen cyclonedx-json).")
    ] = "cyclonedx-json",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Soubor (jinak stdout). Nepřepisuje.")
    ] = None,
) -> None:
    """SBOM repozitáře (CycloneDX 1.5) z lockfilů. Bez sítě – licence jen z cache."""
    import json

    from repo_doctor.sbom import FORMATS, sbom_for_repo, write_sbom

    if fmt not in FORMATS:
        _err(f"Neznámý formát {fmt!r} (podporováno: {', '.join(FORMATS)}).")
        raise typer.Exit(2)
    path = repo.expanduser()
    if not (path / ".git").exists():
        _err(f"{repo} není git repozitář.")
        raise typer.Exit(2)
    try:
        if output is not None:
            write_sbom(path, output.expanduser())
            _err(f"SBOM uložen: {output}")
        else:
            typer.echo(json.dumps(sbom_for_repo(path), indent=2, ensure_ascii=False))
    except FileExistsError:
        _err(f"{output} už existuje – repo-doctor ho nepřepíše.")
        raise typer.Exit(2) from None
    except (ValueError, OSError) as err:
        _err(f"SBOM nejde vytvořit: {err}")
        raise typer.Exit(2) from None


@app.command("mcp")
def mcp_server() -> None:
    """Spustí MCP server (stdio) jen pro čtení – pro Claude Code, Claude Desktop apod.

    Nic neopravuje, nefetchuje ani neklonuje; bez `[mcp] network = true` skenuje offline.
    """
    from repo_doctor.mcpserver import run

    run(_load_config())


@app.command("update")
def update_cmd(
    check: Annotated[
        bool, typer.Option("--check", help="Jen zjistí, zda je venku nová verze.")
    ] = False,
) -> None:
    """Zjistí novou verzi; instalaci z tarballu i aktualizuje (po ověření podpisu).

    Balíčky .deb/.rpm a AUR aktualizuje správce balíčků systému – vypíše se jen příkaz.
    """
    from repo_doctor import update

    try:
        release = update.fetch_latest()
    except update.UpdateError as err:
        _err(str(err))
        raise typer.Exit(2) from None
    if release.version <= update.current_version():
        typer.echo(f"✓ Máš nejnovější verzi {__version__}.")
        return
    kind = update.install_kind()
    typer.echo(f"Je dostupná verze {release.version} (máš {__version__}).")
    if check or kind is not update.InstallKind.TARBALL:
        typer.echo(f"Aktualizace: {update.instructions(kind)}")
        return
    try:
        update.self_update(release, progress=typer.echo)
    except (update.UpdateError, OSError) as err:
        _err(f"Aktualizace selhala: {err}")
        raise typer.Exit(1) from None
    typer.echo(f"✓ Aktualizováno na {release.version} – platí od dalšího spuštění.")


@app.command("tools")
def tools_cmd(
    install: Annotated[
        bool, typer.Option("--install", help="Doinstaluje chybějící nástroje (po potvrzení).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Bez dotazu na potvrzení.")] = False,
    update: Annotated[
        bool,
        typer.Option(
            "--update", help="Aktualizuje stažené nástroje na verzi připnutou v repo-doctoru."
        ),
    ] = False,
    remove: Annotated[
        str | None,
        typer.Option(
            "--remove",
            help="Odebere nástroj stažený repo-doctorem (např. gitleaks).",
            metavar="NÁSTROJ",
        ),
    ] = None,
) -> None:
    """Volitelné nástroje (gitleaks, wl-clipboard, xdg-utils, libnotify) a klíčenka."""
    from repo_doctor import tools

    if remove is not None:
        tool = next((t for t in tools.TOOLS if t.id == remove), None)
        if tool is None:
            _err(f"Neznámý nástroj {remove!r} (platné: {', '.join(t.id for t in tools.TOOLS)}).")
            raise typer.Exit(2)
        try:
            path = tools.remove_download(tool)
        except tools.ToolsError as err:
            _err(str(err))
            raise typer.Exit(1) from None
        typer.echo(f"✓ {tool.id} odebrán ({path})")
        return
    statuses = tools.status()
    for st in statuses:
        mark = "✗" if not st.installed else "↑" if st.outdated else "✓"
        where = f"  [{st.source}] {st.path}" if st.path else ""
        typer.echo(f"{mark} {st.tool.id:<13} {st.tool.purpose}{where}")
    ok, detail = tools.keyring_status()
    typer.echo(f"{'✓' if ok else '✗'} {'klíčenka':<13} {detail}")
    if update:
        outdated = [st.tool for st in statuses if st.outdated]
        if not outdated:
            typer.echo("\nStažené nástroje jsou aktuální.")
            return
        p = tools.update_plan(outdated)
    else:
        missing = [st.tool for st in statuses if not st.installed]
        if not missing:
            if any(st.outdated for st in statuses):
                typer.echo("\nNovější verzi stažených nástrojů získáš: repo-doctor tools --update")
            return
        if not install:
            typer.echo("\nChybějící nástroje doinstaluješ: repo-doctor tools --install")
            return
        p = tools.plan(missing, tools.detect_manager())
    p.assume_yes = yes
    typer.echo("")
    for line in tools.describe(p):
        typer.echo(line)
    if not p.command and not p.downloads:
        return
    if not yes:
        if not sys.stdin.isatty():
            _err("Bez terminálu potvrď instalaci přepínačem --yes.")
            raise typer.Exit(2)
        if not typer.confirm("Pokračovat?", default=False):
            raise typer.Exit(1)
    try:
        for d in p.downloads:
            path = tools.install_download(d)
            typer.echo(f"✓ {d.name} {d.version} → {path}")
        code = tools.run_command(p)
    except tools.ToolsError as err:
        _err(str(err))
        raise typer.Exit(1) from None
    if code != 0:
        _err(f"Správce balíčků skončil s kódem {code}.")
        raise typer.Exit(1)


@app.command("checks")
def list_checks() -> None:
    """Vypíše všechny kontroly (ID, kategorie, severity, automatická oprava)."""
    for c in all_checks():
        fix = "oprava" if c.fixable else ""
        typer.echo(f"{c.id:<28} {c.category.label:<11} {c.severity.short:<5} {fix}")


@forges_app.command("test")
def forges_test(
    name: Annotated[str | None, typer.Argument(help="Název hostingu (jinak všechny).")] = None,
) -> None:
    """Ověří připojení nastavených hostingů. Token nikdy nevypíše."""
    from repo_doctor.forges import HTTP_NOTE, build_forge, insecure_reason
    from repo_doctor.forges.tokens import TokenError, resolve_token
    from repo_doctor.sshhelp import forge_ssh_warning

    config = _load_config()
    targets = [f for f in config.forges if name is None or f.name == name]
    if not targets:
        _err(f"Hosting {name!r} není nastavený." if name else "Nejsou nastavené žádné hostingy.")
        raise typer.Exit(2)

    async def run_all() -> int:
        failures = 0
        for fc in targets:
            if reason := insecure_reason(fc):
                typer.echo(f"✗ {fc.name}: {reason}")
                failures += 1
                continue
            try:
                token = resolve_token(fc)
            except TokenError as err:
                typer.echo(f"✗ {fc.name}: {err}")
                failures += 1
                continue
            try:
                forge = build_forge(fc, token=token.reveal() if token else None, ttl=0)
            except OSError as err:
                typer.echo(f"✗ {fc.name}: TLS – {err}")
                failures += 1
                continue
            try:
                rep = await forge.test_connection()
                if rep.ok and (ssh := await forge_ssh_warning(forge, fc)):
                    rep.warnings.append(ssh)
            finally:
                await forge.client.aclose()
            if rep.ok:
                typer.echo(
                    f"✓ {fc.name} ({fc.type}): uživatel {rep.user or '?'}, vidí {rep.repo_count} repozitářů"
                )
            else:
                typer.echo(f"✗ {fc.name} ({fc.type}): {rep.error}")
                failures += 1
            for w in rep.warnings:
                typer.echo(f"  ! {w}")
            if not fc.verify_tls and not fc.ca_bundle:
                typer.echo("  ! ověřování TLS je vypnuté")
            if fc.base_url.startswith("http://"):
                typer.echo(f"  ! {HTTP_NOTE}")
        return failures

    failures = asyncio.run(run_all())
    raise typer.Exit(1 if failures else 0)


@schedule_app.command("install")
def schedule_install(
    interval: Annotated[str, typer.Option("--interval", help="daily | weekly")] = "weekly",
    time: Annotated[str, typer.Option("--time", help="Čas spuštění HH:MM.")] = "08:00",
) -> None:
    """Vytvoří ~/.config/systemd/user/repo-doctor.{service,timer} a zapne timer (nic jako root)."""
    from repo_doctor.schedule import ScheduleError, install

    _load_config()
    if interval not in ("daily", "weekly"):
        _err("--interval musí být daily nebo weekly.")
        raise typer.Exit(2)
    try:
        files = install(interval, time)  # type: ignore[arg-type]
    except ScheduleError as err:
        _err(str(err))
        raise typer.Exit(2) from None
    typer.echo("Plánovaný sken zapnutý:\n" + "\n".join(f"  {f}" for f in files))


@schedule_app.command("status")
def schedule_status() -> None:
    """Stav plánovaného skenu a poslední běh."""
    from repo_doctor import notify
    from repo_doctor.schedule import describe, status

    st = status()
    if not st.installed:
        typer.echo("Plánovaný sken není nainstalovaný (repo-doctor schedule install).")
    else:
        typer.echo(
            f"Plánovaný sken: {'aktivní' if st.active else 'neaktivní'} · {describe(st.schedule)}"
            + (f" · další běh {st.next_run}" if st.next_run else "")
        )
    last = notify.load_state()
    if last:
        typer.echo(
            f"Poslední běh: {last.ts} · {czech.repos(last.repos)} · {last.changes or 'beze změn'}"
        )


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Vypne timer a smaže jeho soubory."""
    from repo_doctor.schedule import remove

    typer.echo("Plánovaný sken odebrán." if remove() else "Plánovaný sken nebyl nainstalovaný.")


@schedule_app.command("test")
def schedule_test() -> None:
    """Pošle zkušební upozornění všemi nastavenými kanály ([notify])."""
    from repo_doctor import notify

    config = _load_config()
    results = notify.deliver(config.notify, "Zkušební upozornění – plánovaný sken funguje.")
    if not results:
        typer.echo("Není nastavený žádný kanál ([notify] desktop, ntfy_url, email).")
    for d in results:
        typer.echo(f"{'✓' if d.ok else '✗'} {d.channel} {d.detail}".rstrip())
    raise typer.Exit(0 if results and all(d.ok for d in results) else 1)


@config_app.command("path")
def config_path() -> None:
    """Vypíše cestu ke konfiguraci."""
    typer.echo(str(paths.config_file()))


@config_app.command("validate")
def config_validate() -> None:
    """Ověří platnost konfigurace (včetně mapování kláves)."""
    store = ConfigStore()
    if not store.exists:
        typer.echo(f"Konfigurace neexistuje ({store.path}) – použijí se výchozí hodnoty.")
        raise typer.Exit(0)
    config = _load_config()
    from repo_doctor.keymap import KeymapError, build_keymap

    try:
        build_keymap(config.keys)
    except KeymapError as err:
        _err(str(err))
        raise typer.Exit(2) from None
    typer.echo(
        f"✓ {store.path} je platná ({len(config.roots)} složek, {len(config.forges)} hostingů)."
    )


def _print_help() -> None:
    with contextlib.suppress(SystemExit):
        app(["--help"], prog_name="repo-doctor", standalone_mode=True)


def run_tui(roots_override: list[str] | None) -> int:
    from repo_doctor.tui.app import run

    return run(roots_override)


def subcommands() -> set[str]:
    """Názvy podpříkazů CLI (cokoli jiného je složka pro TUI)."""
    names = {
        c.name or (c.callback.__name__.replace("_", "-") if c.callback else "")
        for c in app.registered_commands
    }
    return (names | {g.name for g in app.registered_groups if g.name}) - {""}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    install_log_redaction()
    if not args or (args[0] not in subcommands() and not args[0].startswith("-")):
        if not (sys.stdout.isatty() and sys.stdin.isatty()):
            _print_help()
            return 0 if not args else 2
        missing = [a for a in args if not paths.expand_path(a).is_dir()]
        if missing:
            _err(f"Složka neexistuje: {', '.join(missing)}")
            return 2
        return run_tui(args or None)
    try:
        app(args, prog_name="repo-doctor", standalone_mode=True)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 2
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
