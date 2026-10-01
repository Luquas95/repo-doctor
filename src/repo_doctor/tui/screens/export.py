"""Export reportu (md / json / html)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from repo_doctor.paths import expand_path
from repo_doctor.reports import FORMATS, ReportFormat, render
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

LABELS = {
    "md": "Markdown (.md) – do issue nebo poznámek",
    "json": "JSON (.json) – stabilní schéma pro skripty",
    "html": "HTML (.html) – samostatná stránka s filtry",
}


class ExportScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("export")]

    def __init__(self) -> None:
        super().__init__()
        self.fmt: ReportFormat = "md"
        self._auto_path = True

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def _default_path(self) -> str:
        return f"~/repo-doctor-report-{self.rd.now():%Y-%m-%d}.{self.fmt}"

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel form") as page:
            page.border_title = " export reportu "
            yield Label("Formát")
            with RadioSet(id="format"):
                for fmt in FORMATS:
                    yield RadioButton(LABELS[fmt], value=fmt == "md", name=fmt)
            yield Label("Cesta")
            yield Input(compact=True, id="path")
            yield Static("Tajemství jsou v reportu vždy maskovaná.", classes="hint")
            yield Button("Exportovat", id="do-export", variant="primary")
            yield Static(id="export-result")
        yield KeyBar(["export", ("esc", "zpět"), "help"])

    def on_mount(self) -> None:
        self.query_one("#path", Input).value = self._default_path()
        self.query_one(RadioSet).focus()

    @on(RadioSet.Changed)
    def _format(self, event: RadioSet.Changed) -> None:
        name = event.pressed.name or "md"
        self.fmt = name  # type: ignore[assignment]
        if self._auto_path:
            self.query_one("#path", Input).value = self._default_path()

    @on(Input.Changed, "#path")
    def _path_edited(self, event: Input.Changed) -> None:
        self._auto_path = event.value == self._default_path()

    @on(Input.Submitted, "#path")
    @on(Button.Pressed, "#do-export")
    def _submit(self) -> None:
        self.action_export()

    def action_export(self) -> None:
        p = self.rd.palette
        raw = self.query_one("#path", Input).value.strip()
        out = self.query_one("#export-result", Static)
        if not raw:
            out.update(Text("Zadej cestu.", style=Style(color=p.high)))
            return
        target = expand_path(raw)
        if target.is_dir():
            target = target / f"repo-doctor-report.{self.fmt}"
        if not self.rd.result.repos:
            out.update(
                Text(
                    "Zatím nejsou žádné výsledky – nejdřív spusť sken (R).",
                    style=Style(color=p.med),
                )
            )
            return
        try:
            text = render(
                self.rd.result, self.fmt, no_pulse_days=self.rd.config.limits.no_pulse_days
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, "utf-8")
        except OSError as err:
            out.update(Text(f"Nelze zapsat {target}: {err.strerror}", style=Style(color=p.high)))
            return
        out.update(Text(f"✓ Uloženo: {target}", style=Style(color=p.ok)))
        self.notify(f"Report uložen: {target}")
