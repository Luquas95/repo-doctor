"""Průvodce prvním spuštěním: složky (s našeptáváním), návrh hloubky a volitelně hosting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Label, Static

from repo_doctor.config import ConfigError, ForgeConfig, RootConfig
from repo_doctor.discovery import suggest_depth
from repo_doctor.forges.tokens import TokenError, store_in_keyring
from repo_doctor.paths import expand_path
from repo_doctor.tui.screens.base import NavMixin
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.screens.forms import ForgeDialog, ForgeFormResult
from repo_doctor.tui.widgets.forms import ExistingDir, IntRange, PathInput, PathSuggester
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


class WizardScreen(NavMixin, Screen[None]):
    BINDINGS = [
        Binding("ctrl+s", "finish", "uložit a skenovat"),
        Binding("ctrl+n", "add_forge", "přidat hosting"),
        Binding("escape", "skip", "přeskočit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.folders: list[tuple[str, int, int]] = []  # (cesta, navržená hloubka, počet rep)
        self.forges: list[ForgeFormResult] = []

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        p = self.rd.palette
        with VerticalScroll(classes="page panel form", id="wizard") as page:
            page.border_title = " repo-doctor · první spuštění "
            intro = Text(
                "Vítej! repo-doctor projde tvoje git repozitáře, najde bezpečnostní a hygienické problémy\n",
                style=Style(color=p.text),
            )
            intro.append(
                "a umí bezpečně připravit opravy. Ve výchozím stavu jen čte a nic nepushuje.",
                style=Style(color=p.muted),
            )
            yield Static(intro)
            yield Label("1 · Složky s repozitáři (tab doplní cestu, enter přidá)")
            yield PathInput(
                compact=True,
                placeholder="~/projekty",
                suggester=PathSuggester(),
                validators=[ExistingDir()],
                id="path",
            )
            yield Static("", classes="error", id="path-error")
            yield DataTable(id="folders", cursor_type="row")
            yield Label("2 · Hloubka prohledávání (návrh podle nalezených rep)")
            yield Input(compact=True, value="3", validators=[IntRange(0, 12)], id="depth")
            yield Label("3 · Git hosting (volitelné) – připojení jen pro čtení")
            with Horizontal(classes="row"):
                yield Button("Přidat hosting…  (ctrl+n)", id="add-forge")
            yield Static("", id="forge-list", classes="hint")
            with Horizontal(classes="row"):
                yield Button("Uložit a skenovat  (ctrl+s)", id="finish", variant="primary")
                yield Button("Přeskočit  (esc)", id="skip")
            yield Static("", classes="error", id="wizard-error")
        yield KeyBar(
            [
                ("enter", "přidat složku"),
                ("ctrl+s", "uložit a skenovat"),
                ("ctrl+n", "hosting"),
                ("esc", "přeskočit"),
            ]
        )

    def on_mount(self) -> None:
        self.query_one("#folders", DataTable).add_columns(
            "složka", "repozitářů", "navržená hloubka"
        )
        self.query_one("#path", Input).focus()

    @on(Input.Submitted, "#path")
    def _add(self, event: Input.Submitted) -> None:
        value = event.value.strip().rstrip("/")
        res = event.input.validate(event.value)
        err = self.query_one("#path-error", Static)
        if res is not None and not res.is_valid:
            err.update("; ".join(res.failure_descriptions))
            return
        if any(f[0] == value for f in self.folders):
            err.update("Složka už je v seznamu.")
            return
        err.update("zjišťuji repozitáře…")
        self.probe(value)
        event.input.value = ""

    @work(thread=True, group="wizard-probe")
    def probe(self, value: str) -> None:
        depth, count = suggest_depth(expand_path(value), max_depth=5)
        self.app.call_from_thread(self._probed, value, depth, count)

    def _probed(self, value: str, depth: int, count: int) -> None:
        self.folders.append((value, depth, count))
        table = self.query_one("#folders", DataTable)
        table.add_row(value, str(count), str(depth))
        suggestion = max(f[1] for f in self.folders)
        self.query_one("#depth", Input).value = str(suggestion)
        self.query_one("#path-error", Static).update(
            "" if count else f"V {value} zatím nejsou žádná repa (do hloubky 5)."
        )

    def action_add_forge(self) -> None:
        names = {f.config.name for f in self.forges}

        def done(result: ForgeFormResult | None) -> None:
            if result is not None:
                self.forges.append(result)
                self.query_one("#forge-list", Static).update(
                    "přidáno: "
                    + ", ".join(f"{f.config.name} ({f.config.type})" for f in self.forges)
                )

        self.app.push_screen(ForgeDialog(None, names), done)

    @on(Button.Pressed, "#add-forge")
    def _add_forge_btn(self) -> None:
        self.action_add_forge()

    @on(Button.Pressed, "#finish")
    def _finish_btn(self) -> None:
        self.action_finish()

    @on(Button.Pressed, "#skip")
    def _skip_btn(self) -> None:
        self.action_skip()

    def action_finish(self) -> None:
        err = self.query_one("#wizard-error", Static)
        pending = self.query_one("#path", Input).value.strip()
        if not self.folders and not pending:
            err.update("Přidej aspoň jednu složku (nebo přeskoč průvodce klávesou esc).")
            return
        depth_in = self.query_one("#depth", Input)
        res = depth_in.validate(depth_in.value)
        if res is not None and not res.is_valid:
            err.update("Hloubka: " + "; ".join(res.failure_descriptions))
            return
        depth = int(depth_in.value)
        paths = [f[0] for f in self.folders]
        if pending and pending.rstrip("/") not in paths:
            check = ExistingDir().validate(pending)
            if not check.is_valid:
                err.update("; ".join(check.failure_descriptions))
                return
            paths.append(pending.rstrip("/"))
        store = self.rd.store
        try:
            for path in paths:
                store.upsert_root(RootConfig(path=path, depth=depth))
            for f in self.forges:
                store.upsert_forge(f.config)
            config = store.save()
        except ConfigError as exc:
            err.update(str(exc))
            return
        for f in self.forges:
            if f.token:
                try:
                    store_in_keyring(f.config.name, f.token)
                except TokenError as exc:
                    self.notify(str(exc), severity="error", timeout=10)
        self.rd.config_changed(config)
        self.app.pop_screen()
        self.notify(f"Uloženo do {store.path}. Spouštím první sken…")
        self.rd.start_scan()

    def action_skip(self) -> None:
        pending = len(self.folders) + len(self.forges)
        if pending:

            def done(ok: bool | None) -> None:
                if ok:
                    self._skip()

            self.app.push_screen(
                ConfirmDialog(
                    "Přeskočit průvodce",
                    f"\nZahodit {pending} přidaných položek (složky, hostingy)?\n"
                    "Uložit je můžeš klávesou ctrl+s.\n",
                    confirm_label="Zahodit",
                    danger=True,
                ),
                done,
            )
            return
        self._skip()

    def _skip(self) -> None:
        try:
            config = self.rd.store.save()
        except ConfigError as exc:  # pragma: no cover
            self.notify(str(exc), severity="error")
            return
        self.rd.config_changed(config)
        self.app.pop_screen()
        self.notify("Průvodce přeskočen. Složky přidáš na obrazovce Složky (4).")


__all__ = ["ForgeConfig", "WizardScreen"]
