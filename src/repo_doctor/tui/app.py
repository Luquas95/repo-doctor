"""Hlavní Textual aplikace repo-doctor."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App
from textual.binding import Binding
from textual.worker import Worker

from repo_doctor import history, paths
from repo_doctor.config import Config, ConfigError, ConfigStore, RootConfig
from repo_doctor.keymap import BY_ID, KeymapError, build_keymap, key_label
from repo_doctor.masking import install_log_redaction
from repo_doctor.models import RepoResult, ScanResult
from repo_doctor.scanner import ScanEvent, Scanner, ScanOptions
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.commands import RepoCommands
from repo_doctor.tui.theme import DARK_NAME, LIGHT_NAME, THEMES, Palette, palette_for

if TYPE_CHECKING:
    from repo_doctor.tui.screens.dashboard import DashboardScreen

ScannerFactory = Callable[[Config, ScanOptions, Callable[[ScanEvent], None]], Scanner]


class RepoDoctorApp(App[int]):
    CSS_PATH = "app.tcss"
    TITLE = "repo-doctor"
    ENABLE_COMMAND_PALETTE = True
    COMMANDS = App.COMMANDS | {RepoCommands}
    BINDINGS = [
        *[b for b in bindings("global") if b.id not in {"command_palette", "quit"}],
        Binding(
            BY_ID["command_palette"].key,
            "command_palette",
            "paleta",
            show=False,
            priority=True,
            id="command_palette",
        ),
        Binding(BY_ID["quit"].key, "quit", "konec", show=False, priority=True, id="quit"),
    ]

    def __init__(
        self,
        *,
        store: ConfigStore | None = None,
        roots_override: list[str] | None = None,
        offline: bool = False,
        initial_result: ScanResult | None = None,
        auto_scan: bool = True,
        load_cache: bool = True,
        clock: Callable[[], datetime] | None = None,
        scanner_factory: ScannerFactory | None = None,
        history_delta: dict[str, int] | None = None,
        forge_transport: Any = None,
    ) -> None:
        super().__init__()
        install_log_redaction()
        self.store = store or ConfigStore()
        self.config_error: str | None = None
        try:
            self.config = self.store.load()
        except ConfigError as err:
            self.config_error = str(err)
            self.config = Config()
        self.roots_override = roots_override
        self.offline = offline
        self.auto_scan = auto_scan
        self.clock = clock or (lambda: datetime.now(UTC))
        self.scanner_factory = scanner_factory
        self.forge_transport = forge_transport
        self.result: ScanResult = initial_result or ScanResult()
        if initial_result is None and load_cache:
            cached = history.load_last_scan()
            if cached is not None:
                self.result = cached
        self.history_delta = (
            history_delta if history_delta is not None else history.previous_delta()
        )
        self.scanner: Scanner | None = None
        self.scan_worker: Worker[Any] | None = None
        self.scan_total = 0
        self.scan_done = 0
        self.scan_current = ""
        self.selected_path: str | None = None
        self.keymap_error: str | None = None
        self.keymap_ids: dict[str, str] = build_keymap({})
        for theme in THEMES:
            self.register_theme(theme)
        self.theme = LIGHT_NAME if self.config.ui.theme == "light" else DARK_NAME
        self._dashboard: DashboardScreen | None = None

    # ------------------------------------------------------------------ vlastnosti
    def key(self, action_id: str) -> str:
        return key_label(action_id, self.keymap_ids)

    @property
    def palette(self) -> Palette:
        return palette_for(self.theme)

    @property
    def roots(self) -> list[RootConfig]:
        if self.roots_override:
            return [RootConfig(path=p, depth=3) for p in self.roots_override]
        return self.config.roots

    @property
    def scanning(self) -> bool:
        return self.scan_worker is not None and self.scan_worker.is_running

    def now(self) -> datetime:
        return self.clock()

    def repo(self, path: str | None) -> RepoResult | None:
        if path is None:
            return None
        return next((r for r in self.result.repos if r.path == path), None)

    @property
    def selected_repo(self) -> RepoResult | None:
        return self.repo(self.selected_path)

    # ------------------------------------------------------------------ start
    def on_mount(self) -> None:
        try:
            self.keymap_ids = build_keymap(self.config.keys)
            overrides = {k: v for k, v in self.keymap_ids.items() if k in self.config.keys}
            if overrides:
                self.set_keymap(overrides)
        except KeymapError as err:
            self.keymap_error = str(err)
            self.notify(
                str(err),
                title="Chyba v [keys] – používám výchozí zkratky",
                severity="error",
                timeout=20,
            )
        if self.config_error:
            self.notify(
                self.config_error, title="Neplatná konfigurace", severity="error", timeout=20
            )
        from repo_doctor.tui.screens.dashboard import DashboardScreen

        self._dashboard = DashboardScreen()
        self.push_screen(self._dashboard)
        if not self.store.exists and not self.roots_override and not self.config_error:
            from repo_doctor.tui.screens.wizard import WizardScreen

            self.push_screen(WizardScreen())
        elif self.auto_scan:
            self.start_scan()

    @property
    def dashboard(self) -> DashboardScreen:
        if self._dashboard is None:  # pragma: no cover - vzniká v on_mount
            raise RuntimeError("dashboard ještě neexistuje")
        return self._dashboard

    # ------------------------------------------------------------------ konfigurace
    def config_changed(self, config: Config) -> None:
        self.config = config
        for screen in self.screen_stack:
            refresh = getattr(screen, "on_config_changed", None)
            if callable(refresh):
                refresh()

    # ------------------------------------------------------------------ sken
    def _make_scanner(self, options: ScanOptions) -> Scanner:
        if self.scanner_factory is not None:
            return self.scanner_factory(self.config, options, self._on_scan_event)
        net = None
        if not options.offline and self.forge_transport is not None:
            from repo_doctor.scanner import NetServices

            net = NetServices.create(self.config, transport=self.forge_transport)
        return Scanner(self.config, options, on_event=self._on_scan_event, net=net)

    def start_scan(self, repo_path: str | None = None) -> None:
        if self.scanning:
            self.notify(f"Sken už běží ({self.key('cancel_scan')} ho zruší).", severity="warning")
            return
        roots = self.roots
        if not roots:
            self.notify(
                "Nejsou nastavené žádné složky – přidej je na obrazovce Složky (4).",
                severity="warning",
            )
            return
        options = ScanOptions(offline=self.offline, now=None)
        self.scanner = self._make_scanner(options)
        self.scan_done, self.scan_total, self.scan_current = 0, 0, ""
        self._seen: set[str] = set()
        target = None
        if repo_path is not None:
            from repo_doctor.discovery import DiscoveredRepo

            existing = self.repo(repo_path)
            if existing is None:
                return
            target = [
                DiscoveredRepo(
                    path=Path(repo_path).resolve(), root=existing.root, display=repo_path
                )
            ]
        self.scan_worker = self.run_worker(
            self._scan(roots, target, full=repo_path is None), group="scan", exclusive=True
        )
        self._refresh_views()

    async def _scan(self, roots: list[RootConfig], target: Any, *, full: bool) -> None:
        assert self.scanner is not None  # noqa: S101
        result = await self.scanner.run(roots, target)
        cancelled = result.cancelled or (self.scanner is not None and self.scanner.cancelled)
        if full and not cancelled:
            self.result = result
            try:
                history.save_last_scan(result)
                history.record(
                    result,
                    keep=self.config.limits.history_size,
                    no_pulse_days=self.config.limits.no_pulse_days,
                )
                self.history_delta = history.previous_delta()
            except OSError as err:  # pragma: no cover
                self.notify(f"Výsledek skenu nejde uložit: {err}", severity="warning")
        else:
            self.result.warnings = result.warnings or self.result.warnings
        self.result.offline = self.offline
        self.scan_current = ""
        self._refresh_views()
        if cancelled:
            self.notify("Sken zrušen – zobrazuji dosavadní výsledky.", severity="warning")
        else:
            n = sum(len(r.findings) for r in result.repos)
            self.notify(
                f"Sken dokončen: {len(result.repos)} repozitářů, {n} nálezů.", title="repo-doctor"
            )

    def _on_scan_event(self, event: ScanEvent) -> None:
        if event.kind == "discovered":
            self.scan_total = event.total
        elif event.kind == "check":
            self.scan_current = f"{event.repo} · {event.check}"
        elif event.kind == "repo_done" and event.result is not None:
            self.scan_done = event.done
            self._upsert(event.result)
        self._refresh_views(throttle=event.kind == "check")

    def _upsert(self, repo: RepoResult) -> None:
        repos = [r for r in self.result.repos if r.path != repo.path]
        repos.append(repo)
        self.result.repos = repos

    def _refresh_views(self, *, throttle: bool = False) -> None:
        if self._dashboard is not None and self._dashboard.is_attached:
            self._dashboard.refresh_data(light=throttle)

    def cancel_scan(self) -> None:
        if not self.scanning or self.scanner is None:
            self.notify("Žádný sken neběží.")
            return
        self.scanner.cancel()

    # ------------------------------------------------------------------ akce
    def action_help(self) -> None:
        from repo_doctor.tui.screens.help import HelpScreen

        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    def action_scan_all(self) -> None:
        self.start_scan()

    def action_scan_repo(self) -> None:
        if self.selected_path is None:
            self.notify("Není vybrané žádné repo.", severity="warning")
            return
        self.start_scan(self.selected_path)

    def action_cancel_scan(self) -> None:
        self.cancel_scan()

    def action_toggle_offline(self) -> None:
        self.offline = not self.offline
        self.result.offline = self.offline
        state = "zapnutý – síťové kontroly budou přeskočeny" if self.offline else "vypnutý"
        self.notify(f"Offline režim {state}. {self.key('scan_all')} spustí nový sken.")
        self._refresh_views()

    def action_toggle_theme(self) -> None:
        self.theme = DARK_NAME if self.theme == LIGHT_NAME else LIGHT_NAME
        for screen in self.screen_stack:
            redraw = getattr(screen, "on_theme_changed", None)
            if callable(redraw):
                redraw()

    def action_search(self) -> None:
        if self._in_wizard():
            return
        self._pop_to_dashboard()
        self.dashboard.open_search()

    def _in_wizard(self) -> bool:
        from repo_doctor.tui.screens.wizard import WizardScreen

        if isinstance(self.screen, WizardScreen):
            self.notify(
                "Nejdřív dokonči průvodce (ctrl+s) nebo ho přeskoč (esc).", severity="warning"
            )
            return True
        return False

    def action_go_back(self) -> None:
        from repo_doctor.tui.screens.dashboard import DashboardScreen

        if self._in_wizard():
            return

        if isinstance(self.screen, DashboardScreen):
            self.exit(0)
        elif len(self.screen_stack) > 1:
            self.pop_screen()

    def _pop_to_dashboard(self) -> None:
        from repo_doctor.tui.screens.dashboard import DashboardScreen

        while len(self.screen_stack) > 2 and not isinstance(self.screen, DashboardScreen):
            self.pop_screen()

    def action_switch_screen_n(self, n: int) -> None:
        if self._in_wizard():
            return
        from repo_doctor.tui.screens import (
            detail,
            export,
            fix,
            folders,
            forges,
            remote,
            settings,
        )

        if n in (2, 3) and self.selected_repo is None:
            self.notify("Nejdřív vyber repo na přehledu.", severity="warning")
            return
        self._pop_to_dashboard()
        if n == 1:
            return
        path = self.selected_path or ""
        factories: dict[int, Callable[[], Any]] = {
            2: lambda: detail.DetailScreen(path),
            3: lambda: fix.FixScreen(path),
            4: folders.FoldersScreen,
            5: forges.ForgesScreen,
            6: remote.RemoteScreen,
            7: settings.SettingsScreen,
            8: export.ExportScreen,
        }
        self.push_screen(factories[n]())

    def open_detail(self, path: str) -> None:
        self.selected_path = path
        self.action_switch_screen_n(2)

    def open_fix(self, path: str, focus_check: str | None = None) -> None:
        from repo_doctor.tui.screens.fix import FixScreen

        self.selected_path = path
        self.push_screen(FixScreen(path, focus_check))


def run(roots_override: list[str] | None) -> int:
    store = ConfigStore()
    try:
        config = store.load()
    except ConfigError as err:
        print(err, file=sys.stderr)
        return 2
    try:
        build_keymap(config.keys)
    except KeymapError as err:
        print(err, file=sys.stderr)
        print(f"Oprav sekci [keys] v {paths.config_file()}", file=sys.stderr)
        return 2
    app = RepoDoctorApp(store=store, roots_override=roots_override)
    code = app.run()
    return code or 0
