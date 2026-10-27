"""Nápověda: záložka k aktuální obrazovce a záložka „Vše“ (texty z `helptext`, zkratky z registru)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from rich.console import Group, RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from repo_doctor.i18n import _
from repo_doctor.keymap import CONTEXTS, grouped
from repo_doctor.tui.helptext import GENERAL, PAGES
from repo_doctor.tui.screens.base import NavMixin

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

Tab = Literal["screen", "all"]


class HelpScreen(NavMixin, ModalScreen[Any]):
    BINDINGS = [
        Binding("escape,question_mark,q", "dismiss_help", _("zavřít"), key_display="esc"),
        Binding("tab,shift+tab,left,right", "switch_tab", _("přepnout záložku"), show=False),
        Binding("j,down", "scroll_down", show=False),
        Binding("k,up", "scroll_up", show=False),
    ]

    def __init__(self, context: str = "global", tab: Tab = "screen") -> None:
        super().__init__()
        self.context = context if context in CONTEXTS else "global"
        # obrazovka bez vlastní nápovědy (globální kontext) rovnou ukáže „Vše“
        self.tab: Tab = "all" if self.context == "global" else tab

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="help-body")

    def on_mount(self) -> None:
        # modální obrazovka nepouští aplikační zkratky, tak je přidáme (včetně přemapovaných)
        keys = self.rd.keymap_ids
        self._bindings.bind(keys["help_all"], "show_all", _("úplná nápověda (vše)"), show=False)
        self._bindings.bind(keys["help"], "dismiss_help", _("zavřít"), show=False)
        self.show(self.tab)

    # ------------------------------------------------------------------ obsah
    def show(self, tab: Tab) -> None:
        self.tab = tab
        scroll = self.query_one(VerticalScroll)
        mark = {"screen": "○", "all": "○"}
        mark[tab] = "◉"
        screen_tab = f"{mark['screen']} {_('Tato obrazovka')}"
        scroll.border_title = f" {_('nápověda')} · {screen_tab}  {mark['all']} {_('Vše')} "
        scroll.border_subtitle = _(" tab přepíná · esc zavře ")
        body = self._all() if tab == "all" else self._screen()
        self.query_one("#help-body", Static).update(body)
        scroll.scroll_home(animate=False)

    def _shortcuts(
        self, contexts: tuple[str, ...], *, first_heading: bool = True
    ) -> RenderableType:
        p = self.rd.palette
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right")
        table.add_column(style=Style(color=p.text))
        cap = Style(color=p.background, bgcolor=p.accent, bold=True)
        for n, (context, items) in enumerate(grouped(self.rd.keymap_ids, contexts).items()):
            if not items:
                continue
            table.add_row(Text(""), Text(""))
            if n or first_heading:
                table.add_row(
                    Text(""), Text(context.upper(), style=Style(color=p.accent, bold=True))
                )
            for key, desc in items:
                table.add_row(Text(f" {key} ", style=cap), Text(desc))
        return table

    def _heading(self, text: str) -> Text:
        return Text(text.upper(), style=Style(color=self.rd.palette.accent, bold=True))

    def _screen(self) -> RenderableType:
        p = self.rd.palette
        page = PAGES.get(self.context)
        parts: list[RenderableType] = [self._heading(CONTEXTS[self.context])]
        if page is not None:
            parts.append(Text(_(page.intro), style=Style(color=p.text)))
            for point in page.points:
                parts.append(Text(f"  • {_(point)}", style=Style(color=p.text)))
        contexts = tuple(dict.fromkeys((self.context, "nav", "global")))
        parts.append(self._shortcuts(contexts, first_heading=False))
        parts.append(
            Text(
                _("\n{key} otevře úplnou nápovědu (záložka Vše).").format(
                    key=self.rd.key("help_all")
                ),
                style=Style(color=p.muted),
            )
        )
        return Group(*parts)

    def _all(self) -> RenderableType:
        p = self.rd.palette
        parts: list[RenderableType] = []
        for title, paragraphs in GENERAL:
            parts.append(Text(""))
            parts.append(self._heading(_(title)))
            parts.extend(Text(_(para), style=Style(color=p.text)) for para in paragraphs)
        parts.append(self._shortcuts(tuple(CONTEXTS)))
        parts.append(
            Text(
                _("\nEsc nebo ? zavře nápovědu."),
                style=Style(color=p.muted),
            )
        )
        return Group(*parts)

    # ------------------------------------------------------------------ akce
    def action_dismiss_help(self) -> None:
        self.dismiss(None)

    def action_show_all(self) -> None:
        self.show("all")

    def action_switch_tab(self) -> None:
        if self.context != "global":
            self.show("all" if self.tab == "screen" else "screen")

    def action_scroll_down(self) -> None:
        self.query_one(VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one(VerticalScroll).scroll_up()
