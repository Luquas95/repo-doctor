"""Nápověda – generovaná z registru zkratek (ne ručně psaný seznam)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from repo_doctor.keymap import grouped
from repo_doctor.tui.screens.base import NavMixin

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


class HelpScreen(NavMixin, ModalScreen[Any]):
    BINDINGS = [
        Binding("escape,question_mark,q", "dismiss_help", "zavřít", key_display="esc"),
        Binding("j,down", "scroll_down", show=False),
        Binding("k,up", "scroll_up", show=False),
    ]

    def compose(self) -> ComposeResult:
        app: RepoDoctorApp = self.app  # type: ignore[assignment]
        p = app.palette
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right")
        table.add_column(style=Style(color=p.text))
        cap = Style(color=p.background, bgcolor=p.accent, bold=True)
        for context, items in grouped(app.keymap_ids).items():
            table.add_row(Text(""), Text(""))
            table.add_row(Text(""), Text(context.upper(), style=Style(color=p.accent, bold=True)))
            for key, desc in items:
                table.add_row(Text(f" {key} ", style=cap), Text(desc))
        with VerticalScroll() as scroll:
            scroll.border_title = " nápověda · zkratky "
            yield Static(table)
            yield Static(
                Text(
                    '\nZkratky jdou přemapovat v config.toml, sekce [keys] (akce = "klávesa").\n'
                    "Esc nebo ? zavře nápovědu.",
                    style=Style(color=p.muted),
                )
            )

    def action_dismiss_help(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()
