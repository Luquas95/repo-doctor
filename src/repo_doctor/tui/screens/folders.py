"""Složky: sledované složky s repozitáři (přidat, upravit, odebrat, vypnout)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from repo_doctor.config import ConfigError, RootConfig
from repo_doctor.discovery import discover
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.screens.forms import RootDialog
from repo_doctor.tui.util import home_path
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


class FoldersScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("folders")]

    def __init__(self) -> None:
        super().__init__()
        self.counts: dict[str, int | None] = {}

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel") as page:
            page.border_title = " složky "
            yield Static(id="folders-note", classes="page-header")
            table: DataTable[str | Text] = DataTable(
                id="roots", cursor_type="row", zebra_stripes=False
            )
            yield table
        yield KeyBar(
            [
                "folder_add",
                "folder_edit",
                "folder_delete",
                "folder_toggle",
                "scan_all",
                ("esc", "zpět"),
                "help",
            ]
        )

    def on_mount(self) -> None:
        self.refresh_table()
        self.count_repos()
        self.query_one(DataTable).focus()

    def on_config_changed(self) -> None:
        self.refresh_table()

    def refresh_table(self) -> None:
        app = self.rd
        p = app.palette
        note = Text("Sledované složky se ukládají do ", style=Style(color=p.muted))
        note.append(str(app.store.path), style=Style(color=p.text))
        if app.roots_override:
            note.append(
                "\nTento běh používá složky z příkazové řádky (nic se neukládá): ",
                style=Style(color=p.med),
            )
            note.append(", ".join(app.roots_override), style=Style(color=p.text))
        self.query_one("#folders-note", Static).update(note)
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear(columns=True)
        table.add_columns("stav", "cesta", "hloubka", "vylučující vzory", "symlinky", "repozitářů")
        for i, root in enumerate(app.config.roots):
            exists = root.expanded.is_dir()
            state = Text(
                "● zap." if root.enabled else "○ vyp.",
                style=Style(color=p.ok if root.enabled else p.dim),
            )
            path = Text(root.path, style=Style(color=p.text if exists else p.high))
            if not exists:
                path.append("  (neexistuje)", style=Style(color=p.high))
            count = self.counts.get(root.path)
            table.add_row(
                state,
                path,
                str(root.depth),
                ", ".join(root.exclude) or "—",
                "ano" if root.follow_symlinks else "ne",
                "…"
                if count is None and root.enabled
                else ("vyp." if not root.enabled else str(count)),
                key=str(i),
            )
        if not app.config.roots:
            table.add_row(
                Text("—", style=Style(color=p.dim)),
                Text("žádné složky – n přidá první", style=Style(color=p.muted)),
                "",
                "",
                "",
                "",
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))

    @work(thread=True, exclusive=True, group="count")
    def count_repos(self) -> None:
        counts: dict[str, int | None] = {}
        for root in self.rd.config.roots:
            if root.enabled:
                counts[root.path] = len(discover([root], self.rd.config.ignore_repos).repos)
        self.app.call_from_thread(self._counted, counts)

    def _counted(self, counts: dict[str, int | None]) -> None:
        self.counts = counts
        self.refresh_table()

    def _index(self) -> int | None:
        table = self.query_one(DataTable)
        if not self.rd.config.roots or table.row_count == 0:
            return None
        return min(table.cursor_row, len(self.rd.config.roots) - 1)

    def _save(self, mutate: str, root: RootConfig | None = None, index: int | None = None) -> None:
        store = self.rd.store
        try:
            if mutate == "upsert" and root is not None:
                config = store.upsert_root(root, index)
            elif mutate == "remove" and index is not None:
                config = store.remove_root(index)
            else:  # pragma: no cover
                return
        except ConfigError as err:
            self.notify(str(err), severity="error", timeout=10)
            return
        self.rd.config_changed(config)
        self.count_repos()
        self.notify("Uloženo do config.toml.")

    def action_folder_add(self) -> None:
        def done(root: RootConfig | None) -> None:
            if root is not None:
                if any(r.path == root.path for r in self.rd.config.roots):
                    self.notify("Tahle složka už je sledovaná.", severity="warning")
                    return
                self._save("upsert", root)

        self.app.push_screen(RootDialog(), done)

    def action_folder_edit(self) -> None:
        idx = self._index()
        if idx is None:
            return

        def done(root: RootConfig | None) -> None:
            if root is not None:
                self._save("upsert", root, idx)

        self.app.push_screen(RootDialog(self.rd.config.roots[idx]), done)

    def action_folder_delete(self) -> None:
        idx = self._index()
        if idx is None:
            return
        root = self.rd.config.roots[idx]

        def done(ok: bool | None) -> None:
            if ok:
                self._save("remove", index=idx)

        self.app.push_screen(
            ConfirmDialog(
                "Odebrat složku",
                f"\nPřestat sledovat {home_path(str(root.expanded))}?\n\nNa disku se nic nesmaže – jen se odebere z config.toml.\n",
                confirm_label="Odebrat",
                danger=True,
            ),
            done,
        )

    def action_folder_toggle(self) -> None:
        idx = self._index()
        if idx is None:
            return
        root = self.rd.config.roots[idx]
        self._save("upsert", root.model_copy(update={"enabled": not root.enabled}), idx)
