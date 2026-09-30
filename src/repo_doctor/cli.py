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

from repo_doctor import __version__, paths
from repo_doctor.checkdocs import load as load_doc
from repo_doctor.checks import all_checks, check_ids
from repo_doctor.config import Config, ConfigError, ConfigStore, RootConfig
from repo_doctor.masking import install_log_redaction, redact
from repo_doctor.models import ScanResult, Severity
from repo_doctor.reports import FORMATS, ReportFormat, render

SUBCOMMANDS = {"scan", "explain", "forges", "config", "checks"}

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


def _err(message: str) -> None:
    typer.echo(redact(message), err=True)


def _load_config() -> Config:
    try:
        return ConfigStore().load()
    except ConfigError as err:
        _err(str(err))
        raise typer.Exit(2) from None


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
) -> None:
    """Naskenuje repozitáře a vypíše report. Exit: 0 bez nálezů nad prahem, 1 nálezy, 2 chyba."""
    from repo_doctor.scanner import ScanEvent, Scanner, ScanOptions

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
        offline=offline, use_forges=not no_forges, only=_split(only), skip=_split(skip), fetch=fetch
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
    from repo_doctor.forges import build_forge
    from repo_doctor.forges.tokens import TokenError, resolve_token

    config = _load_config()
    targets = [f for f in config.forges if name is None or f.name == name]
    if not targets:
        _err(f"Hosting {name!r} není nastavený." if name else "Nejsou nastavené žádné hostingy.")
        raise typer.Exit(2)

    async def run_all() -> int:
        failures = 0
        for fc in targets:
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
        return failures

    failures = asyncio.run(run_all())
    raise typer.Exit(1 if failures else 0)


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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    install_log_redaction()
    if not args or (args[0] not in SUBCOMMANDS and not args[0].startswith("-")):
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
