"""Synchronizace: stav rep vůči remotu a „Rychle dohnat“ (jen `git merge --ff-only`).

Jediná obrazovka, která mění pracovní strom – a jen fast-forwardem, po potvrzení
(výchozí volba Zrušit). Fetch je samostatná akce (`f`), řídí se pravidly sítě.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from repo_doctor.sync import STATE_LABELS, SyncResult, SyncStatus, fast_forward, status
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


@dataclass
class Row:
    status: SyncStatus
    selected: bool


class SyncScreen(BaseScreen):
    BINDINGS = [
        *BaseScreen.BINDINGS,
        *[b for b in bindings("sync") if b.id != "sync_apply"],
        *[
            Binding(
                b.key, b.action, b.description, key_display=b.key_display, priority=True, id=b.id
            )
            for b in bindings("sync")
            if b.id == "sync_apply"
        ],
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Row] = []
        self.loaded = False

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel") as page:
            page.border_title = " synchronizace "
            yield Static(id="sync-note", classes="page-header")
            table: DataTable[str | Text] = DataTable(id="sync", cursor_type="row")
            yield table
            yield Static(id="sync-summary")
        yield KeyBar(["sync_fetch", "sync_toggle", "sync_apply", ("esc", "zpět"), "help"])

    def on_mount(self) -> None:
        p = self.rd.palette
        self.query_one("#sync-note", Static).update(
            Text(
                "Rychle dohnat = jen fast-forward (git merge --ff-only) u čistých rep na sledované "
                "větvi, která jsou pozadu. Nikdy merge commit, rebase, reset ani push. "
                f"{self.rd.key('sync_fetch')} nejdřív stáhne novinky.",
                style=Style(color=p.muted),
            )
        )
        self.query_one("#sync-summary", Static).update(
            Text("Zjišťuji stav…", style=Style(color=p.muted))
        )
        self.load(fetch=False)
        self.query_one(DataTable).focus()

    def _paths(self) -> list[Path]:
        out = []
        for repo in self.rd.result.repos:
            path = Path(repo.path).expanduser()
            if path.is_dir():
                out.append(path)
        return out

    @work(thread=True, exclusive=True, group="sync-load")
    def load(self, fetch: bool) -> None:
        if fetch and self.rd.offline:
            self.app.call_from_thread(
                self.notify,
                f"Fetch potřebuje síť – vypni offline režim ({self.rd.key('toggle_offline')}).",
                severity="warning",
            )
            fetch = False
        statuses = [status(p, fetch=fetch) for p in self._paths()]
        order = {
            "behind": 0,
            "diverged": 1,
            "ahead": 2,
            "no-upstream": 3,
            "detached": 4,
            "error": 5,
            "untrusted": 6,
            "clean": 7,
        }
        statuses.sort(key=lambda s: (order.get(s.state, 9), s.name))
        self.app.call_from_thread(self._loaded, statuses, fetch)

    def _loaded(self, statuses: list[SyncStatus], fetched: bool) -> None:
        self.rows = [Row(s, s.can_fast_forward) for s in statuses]
        self.loaded = True
        self.refresh_table()
        failed = [s.name for s in statuses if s.fetch_error]
        if fetched and failed:
            self.notify(
                f"Fetch selhal u {len(failed)} rep ({', '.join(failed[:3])}…) – důvod je ve sloupci stav.",
                severity="warning",
            )

    def refresh_table(self) -> None:
        p = self.rd.palette
        table = self.query_one(DataTable)
        row_i = table.cursor_row
        table.clear(columns=True)
        table.add_columns(" ", "repo", "větev", "↓ ↑", "stav")
        colors = {"behind": p.accent, "diverged": p.high, "ahead": p.med, "clean": p.ok}
        for row in self.rows:
            s = row.status
            mark = (
                Text(
                    "[x]" if row.selected else "[ ]",
                    style=Style(color=p.ok if row.selected else p.muted),
                )
                if s.can_fast_forward
                else Text(" · ", style=Style(color=p.dim))
            )
            state = Text(STATE_LABELS[s.state], style=Style(color=colors.get(s.state, p.muted)))
            if s.can_fast_forward:
                state.append(
                    f" → {s.behind} commitů, {len(s.files)} souborů", style=Style(color=p.text)
                )
            elif s.reason and s.state != "clean":
                state.append(f" · {s.reason}", style=Style(color=p.muted))
            if s.fetch_error:
                state.append(f" · fetch: {s.fetch_error}", style=Style(color=p.high))
            table.add_row(
                mark,
                s.name,
                s.branch or "—",
                f"{s.behind} {s.ahead}" if s.upstream else "—",
                state,
                key=str(s.path),
            )
        if not self.rows and self.loaded:
            table.add_row(
                "", Text("žádná repa ve výsledcích skenu", style=Style(color=p.muted)), "", "", ""
            )
        if table.row_count:
            table.move_cursor(row=min(row_i, table.row_count - 1))
        chosen = self.chosen()
        self.query_one("#sync-summary", Static).update(
            Text(
                f"vybráno {len(chosen)} · dožene se {sum(s.behind for s in chosen)} commitů "
                f"· {sum(len(s.files) for s in chosen)} souborů",
                style=Style(color=p.text),
            )
        )

    def chosen(self) -> list[SyncStatus]:
        return [r.status for r in self.rows if r.selected and r.status.can_fast_forward]

    def action_sync_fetch(self) -> None:
        self.query_one("#sync-summary", Static).update(
            Text("Stahuji (git fetch)…", style=Style(color=self.rd.palette.muted))
        )
        self.load(fetch=True)

    def action_sync_toggle(self) -> None:
        table = self.query_one(DataTable)
        if not self.rows or table.row_count == 0:
            return
        row = self.rows[min(table.cursor_row, len(self.rows) - 1)]
        if not row.status.can_fast_forward:
            self.notify(row.status.reason or "Toto repo nejde rychle dohnat.", severity="warning")
            return
        row.selected = not row.selected
        self.refresh_table()

    def action_sync_apply(self) -> None:
        chosen = self.chosen()
        if not chosen:
            self.notify("Žádné repo k dohnání není vybrané.", severity="warning")
            return
        p = self.rd.palette
        body = Text("\nFast-forward (git merge --ff-only) změní pracovní strom:\n")
        for s in chosen[:8]:
            body.append(
                f"  • {s.name}: {s.branch} ← {s.upstream} · {s.behind} commitů, {len(s.files)} souborů\n",
                style=Style(color=p.text),
            )
        if len(chosen) > 8:
            body.append(f"  … a {len(chosen) - 8} dalších\n", style=Style(color=p.muted))
        body.append(
            "\nŽádný merge commit, rebase, reset ani push. Hooky se nespouští.\n",
            style=Style(color=p.muted),
        )

        def done(ok: bool | None) -> None:
            if ok:
                self.do_apply([s.path for s in chosen])
            else:
                self.notify("Synchronizace zrušena – nic se nezměnilo.")

        self.app.push_screen(ConfirmDialog("Rychle dohnat", body, confirm_label="Dohnat"), done)

    @work(thread=True, exclusive=True, group="sync-apply")
    def do_apply(self, paths: list[Path]) -> None:
        result = fast_forward(paths)
        self.app.call_from_thread(self._applied, result)

    def _applied(self, result: SyncResult) -> None:
        msg = f"Dohnáno: {len(result.updated)} rep ({sum(n for _, n in result.updated)} commitů). Nic se nepushnulo."
        for path, reason in result.skipped[:5]:
            msg += f"\n! {path.name}: {reason}"
        self.notify(
            msg,
            title="Synchronizace",
            timeout=12,
            severity="warning" if result.skipped else "information",
        )
        self.load(fetch=False)


__all__ = ["SyncScreen"]
