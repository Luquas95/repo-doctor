"""Nastavení: kontroly, limity, allowlist, téma, editor… Ukládá se okamžitě, když je hodnota platná."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Input, Label, Select, SelectionList, Static
from textual.widgets.selection_list import Selection

from repo_doctor.checks import all_checks
from repo_doctor.config import ConfigError, LimitsConfig
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.theme import DARK_NAME, LIGHT_NAME
from repo_doctor.tui.widgets.forms import IntRange, PositiveNumber, split_list
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

LIMIT_LABELS: dict[str, str] = {
    "large_file_mb": "velký soubor (MB)",
    "binary_file_kb": "binárka mimo LFS (KB)",
    "stale_branch_days": "stará branch (dní)",
    "stash_days": "zapomenutý stash (dní)",
    "no_pulse_days": "bez tepu (dní)",
    "stale_pr_days": "neaktivní PR (dní)",
    "history_timeout_s": "limit skenu historie (s)",
    "git_timeout_s": "limit příkazu git (s)",
    "history_size": "historie skenů (počet)",
    "http_cache_minutes": "cache API hostingů (min)",
    "registry_cache_hours": "cache registrů a OSV (h)",
    "max_file_kb": "max. soubor pro sken tajemství (KB)",
}
FLOAT_LIMITS = {"large_file_mb", "history_timeout_s", "git_timeout_s"}


class SettingsScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("settings")]

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        cfg = self.rd.config
        with VerticalScroll(classes="page panel form", id="settings") as page:
            page.border_title = " nastavení "
            yield Static(
                Text(
                    f"Změny se ukládají okamžitě do {self.rd.store.path}",
                    style=Style(color=self.rd.palette.muted),
                )
            )
            yield Label("Vzhled")
            yield Select(
                compact=True,
                options=[("tmavé", "dark"), ("světlé", "light")],
                value=cfg.ui.theme,
                allow_blank=False,
                id="theme",
            )
            yield Label("Editor (prázdné = $VISUAL / $EDITOR)")
            yield Input(compact=True, value=cfg.ui.editor or "", placeholder="nvim", id="editor")
            yield Label("Práh pro exit kód CLI (fail-on)")
            yield Select(
                compact=True,
                options=[("▲ HIGH", "high"), ("◆ MEDIUM", "medium"), ("● LOW", "low")],
                value=cfg.checks.fail_on.value,
                allow_blank=False,
                id="fail_on",
            )
            yield Label("Licence pro opravu license-missing")
            yield Select(
                compact=True,
                options=[(x, x) for x in ("MIT", "ISC", "BSD-2-Clause", "Unlicense")],
                value=cfg.license,
                allow_blank=False,
                id="license",
            )
            yield Label("Vlastní šablony oprav (složka, volitelné)")
            yield Input(
                compact=True,
                value=cfg.templates_dir or "",
                placeholder="~/.config/repo-doctor/templates",
                id="templates_dir",
            )
            yield Label("Aktivní kontroly (space přepne)")
            yield SelectionList[str](
                *[
                    Selection(f"{c.id}  · {c.title}", c.id, c.id not in cfg.checks.disabled)
                    for c in all_checks()
                ],
                id="checks",
            )
            yield Label("Limity")
            for key, label in LIMIT_LABELS.items():
                validator = (
                    PositiveNumber()
                    if key in FLOAT_LIMITS
                    else IntRange(0 if "cache" in key else 1, 1_000_000)
                )
                yield Static(label, classes="hint")
                yield Input(
                    compact=True,
                    value=str(getattr(cfg.limits, key)),
                    validators=[validator],
                    id=f"limit-{key}",
                )
            yield Label("Ignorované cesty v repech (glob, čárkami)")
            yield Input(
                compact=True,
                value=", ".join(cfg.ignore_paths),
                placeholder="vendor/**, docs/examples/**",
                id="ignore_paths",
            )
            yield Label("Ignorované repozitáře (název nebo glob, čárkami)")
            yield Input(compact=True, value=", ".join(cfg.ignore_repos), id="ignore_repos")
            yield Label("Allowlist nálezů (d odebere vybraný)")
            yield DataTable(id="allowlist", cursor_type="row")
            yield Static("", classes="error", id="settings-error")
        yield KeyBar(
            [
                ("space", "přepnout"),
                ("tab", "další pole"),
                "settings_allow_remove",
                ("esc", "zpět"),
                "help",
            ]
        )

    def on_mount(self) -> None:
        table = self.query_one("#allowlist", DataTable)
        table.add_columns("hash", "kontrola", "repo", "důvod")
        self._fill_allowlist()
        self.query_one("#theme", Select).focus()

    def _fill_allowlist(self) -> None:
        table = self.query_one("#allowlist", DataTable)
        table.clear()
        for entry in self.rd.config.allowlist:
            table.add_row(
                entry.hash, entry.check or "—", entry.repo or "—", entry.reason, key=entry.hash
            )
        if not self.rd.config.allowlist:
            table.add_row("—", "", "", "prázdný (nález skryješ klávesou a v kartě repa)")

    def _save(self, fn: Any, *args: Any) -> bool:
        err = self.query_one("#settings-error", Static)
        try:
            config = fn(*args)
        except ConfigError as exc:
            err.update(str(exc))
            return False
        err.update("")
        self.rd.config_changed(config)
        return True

    @on(Select.Changed)
    def _select(self, event: Select.Changed) -> None:
        store = self.rd.store
        wid, value = event.select.id, event.value
        if wid == "theme" and value != self.rd.config.ui.theme:
            if self._save(store.set_value, "ui", "theme", value):
                self.app.theme = LIGHT_NAME if value == "light" else DARK_NAME
        elif wid == "fail_on" and value != self.rd.config.checks.fail_on.value:
            self._save(store.set_value, "checks", "fail_on", value)
        elif wid == "license" and value != self.rd.config.license:
            self._save(store.set_top, "license", value)

    @on(Input.Changed)
    def _input(self, event: Input.Changed) -> None:
        wid = event.input.id or ""
        store = self.rd.store
        if event.validation_result is not None and not event.validation_result.is_valid:
            self.query_one("#settings-error", Static).update(
                "; ".join(event.validation_result.failure_descriptions)
            )
            return
        value = event.value.strip()
        if wid.startswith("limit-"):
            key = wid[6:]
            number: float | int = float(value) if key in FLOAT_LIMITS else int(value)
            if getattr(self.rd.config.limits, key) != number:
                self._save(store.set_value, "limits", key, number)
        elif wid == "editor" and value != (self.rd.config.ui.editor or ""):
            self._save(store.set_value, "ui", "editor", value or None)
        elif wid == "templates_dir" and value != (self.rd.config.templates_dir or ""):
            self._save(store.set_top, "templates_dir", value or None)
        elif wid in ("ignore_paths", "ignore_repos"):
            items = split_list(value)
            if items != getattr(self.rd.config, wid):
                self._save(store.set_top, wid, items or None)

    @on(SelectionList.SelectedChanged, "#checks")
    def _checks(self, event: SelectionList.SelectedChanged[str]) -> None:
        enabled = set(event.selection_list.selected)
        disabled = sorted(c.id for c in all_checks() if c.id not in enabled)
        if disabled != sorted(self.rd.config.checks.disabled):
            self._save(self.rd.store.set_value, "checks", "disabled", disabled or None)

    def action_settings_allow_remove(self) -> None:
        table = self.query_one("#allowlist", DataTable)
        if not self.rd.config.allowlist or table.row_count == 0:
            return
        entry = self.rd.config.allowlist[min(table.cursor_row, len(self.rd.config.allowlist) - 1)]
        if self._save(self.rd.store.remove_allow, entry.hash):
            self._fill_allowlist()
            self.notify(
                f"Odebráno z allowlistu – nález se znovu ukáže po dalším skenu ({entry.check})."
            )


__all__ = ["LIMIT_LABELS", "LimitsConfig", "SettingsScreen"]
