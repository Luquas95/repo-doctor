"""Nástroje: volitelné programy (gitleaks, schránka, prohlížeč, upozornění) a klíčenka.

Ukáže stav a původ (systém / stažený repo-doctorem), doinstaluje chybějící, aktualizuje
stažené binárky na připnutou verzi a stažené odebere. Systémové balíčky spravuje správce
balíčků – repo-doctor je jen nainstaluje (viditelně přes sudo), neodinstalovává.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from repo_doctor.i18n import _
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.util import home_path
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tools import Tool, ToolStatus
    from repo_doctor.tui.app import RepoDoctorApp


class ToolsScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("tools")]

    def __init__(self) -> None:
        super().__init__()
        self.statuses: list[ToolStatus] = []

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel") as page:
            page.border_title = _(" nástroje ")
            yield Static(id="tools-note", classes="page-header")
            yield DataTable(id="tools", cursor_type="row")
            yield Static(id="tools-keyring", classes="page-header")
        yield KeyBar(
            [
                "tools_install",
                "tools_install_all",
                "tools_update",
                "tools_remove",
                ("esc", _("zpět")),
                "help",
            ]
        )

    def on_mount(self) -> None:
        p = self.rd.palette
        self.query_one("#tools-note", Static).update(
            Text(
                _(
                    "Volitelné – repo-doctor funguje i bez nich, s nimi umí víc. "
                    "Systémové balíčky odinstaluješ správcem balíčků."
                ),
                style=Style(color=p.muted),
            )
        )
        table = self.query_one(DataTable)
        table.add_columns("", _("nástroj"), _("k čemu"), _("původ"), _("cesta"))
        table.focus()
        self.refresh_tools()

    @work(thread=True, exclusive=True, group="tools-status")
    def refresh_tools(self) -> None:
        backend = self.rd.tools_backend
        statuses = backend.status()
        keyring = backend.keyring_status()
        self.app.call_from_thread(self._show, statuses, keyring)

    def _show(self, statuses: list[ToolStatus], keyring: tuple[bool, str]) -> None:
        p = self.rd.palette
        self.statuses = statuses
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        for st in statuses:
            if not st.installed:
                mark = Text("✗", style=Style(color=p.high))
            elif st.outdated:
                mark = Text("↑", style=Style(color=p.med))
            else:
                mark = Text("✓", style=Style(color=p.ok))
            source = st.source
            if st.outdated and st.tool.download is not None:
                source += f" → {st.tool.download.version}"
            table.add_row(
                mark,
                st.tool.id,
                st.tool.purpose,
                source,
                home_path(st.path) if st.path else "—",
                key=st.tool.id,
            )
        if statuses:
            table.move_cursor(row=min(row, len(statuses) - 1))
        ok, detail = keyring
        self.query_one("#tools-keyring", Static).update(
            Text(
                _("{v} klíčenka · {detail}").format(v="✓" if ok else "✗", detail=detail)
                + (
                    ""
                    if ok
                    else _("\nKlíčenka se neinstaluje – Secret Service musí běžet v relaci.")
                ),
                style=Style(color=p.ok if ok else p.muted),
            )
        )

    def _selected(self) -> ToolStatus | None:
        table = self.query_one(DataTable)
        if not self.statuses or table.row_count == 0:
            return None
        return self.statuses[min(table.cursor_row, len(self.statuses) - 1)]

    # ------------------------------------------------------------------ instalace
    def action_tools_install(self) -> None:
        st = self._selected()
        if st is None:
            return
        if st.installed:
            self.notify(_("{id} už je nainstalovaný.").format(id=st.tool.id), severity="warning")
            return
        self.prepare_install(st.tool)

    def action_tools_install_all(self) -> None:
        self.prepare_install(None)

    @work(thread=True, exclusive=True, group="tools-plan")
    def prepare_install(self, only: Tool | None) -> None:
        backend = self.rd.tools_backend
        missing = [only] if only is not None else backend.missing()
        if not missing:
            self.app.call_from_thread(
                self.notify, _("Všechny volitelné nástroje jsou nainstalované.")
            )
            return
        plan = backend.plan(missing, backend.detect_manager())
        self.app.call_from_thread(
            self._confirm, plan, _("Nainstalovat nástroje"), _("Nainstalovat")
        )

    def action_tools_update(self) -> None:
        backend = self.rd.tools_backend
        outdated = backend.outdated()
        if not outdated:
            self.notify(_("Stažené nástroje jsou aktuální. Systémové aktualizuje správce balíčků."))
            return
        self._confirm(backend.update_plan(outdated), _("Aktualizovat nástroje"), _("Aktualizovat"))

    def _confirm(self, plan: Any, title: str, label: str) -> None:
        lines = self.rd.tools_backend.describe(plan)
        if not plan.command and not plan.downloads:
            self.notify("\n".join(lines), severity="warning", timeout=15)
            return
        body = Text("\n" + "\n".join(lines) + "\n")
        if plan.command:
            body.append(
                _(
                    "\nTUI se na chvíli pozastaví a správce balíčků se v terminálu zeptá "
                    "na heslo (sudo) a potvrzení.\n"
                )
            )

        def done(ok: bool | None) -> None:
            if not ok:
                return
            if plan.downloads:
                self.download(plan)
            else:
                self._run_command(plan)

        self.app.push_screen(ConfirmDialog(title, body, confirm_label=label), done)

    @work(thread=True, exclusive=True, group="tools-download")
    def download(self, plan: Any) -> None:
        backend = self.rd.tools_backend
        for d in plan.downloads:
            try:
                path = backend.install_download(d)
            except backend.ToolsError as err:
                self.app.call_from_thread(self.notify, str(err), severity="error", timeout=15)
                self.refresh_tools()
                return
            self.app.call_from_thread(
                self.notify,
                _("{name} {version} nainstalován do {path}.").format(
                    name=d.name, version=d.version, path=path
                ),
            )
        self.app.call_from_thread(self._run_command, plan)

    def _run_command(self, plan: Any) -> None:
        backend = self.rd.tools_backend
        if plan.command:
            try:
                with self.app.suspend():
                    print(f"\n$ {' '.join(plan.command)}", flush=True)
                    code = backend.run_command(plan)
                    with contextlib.suppress(EOFError, OSError):
                        input(_("\nStiskni Enter pro návrat do repo-doctoru…"))
            except backend.ToolsError as err:
                self.notify(str(err), severity="error", timeout=15)
            except SuspendNotSupported:
                self.notify(
                    _("Terminál nejde pozastavit – spusť ručně: {join}").format(
                        join=" ".join(plan.command)
                    ),
                    severity="warning",
                    timeout=20,
                )
            else:
                if code == 0:
                    self.notify(_("Nástroje jsou nainstalované."))
                else:
                    self.notify(
                        _("Správce balíčků skončil s kódem {code}.").format(code=code),
                        severity="error",
                        timeout=15,
                    )
        self.refresh_tools()

    # ------------------------------------------------------------------ odebrání
    def action_tools_remove(self) -> None:
        st = self._selected()
        if st is None:
            return
        if not st.installed:
            self.notify(_("{id} není nainstalovaný.").format(id=st.tool.id), severity="warning")
            return
        if not st.downloaded:
            self.notify(
                _("{id} je ze systému – odinstaluj ho správcem balíčků.").format(id=st.tool.id),
                severity="warning",
            )
            return
        body = Text(
            _("\nSmazat {id} ({home_path})?\n").format(
                id=st.tool.id, home_path=home_path(st.path or "")
            )
        )
        body.append(_("Kontroly, které ho používají, pak poběží bez něj.\n"))

        def done(ok: bool | None) -> None:
            if not ok:
                return
            backend = self.rd.tools_backend
            try:
                backend.remove_download(st.tool)
            except backend.ToolsError as err:
                self.notify(str(err), severity="error", timeout=15)
            else:
                self.notify(_("{id} odebrán.").format(id=st.tool.id))
            self.refresh_tools()

        self.app.push_screen(
            ConfirmDialog(_("Odebrat nástroj"), body, confirm_label=_("Odebrat"), danger=True), done
        )
