"""Úklid: regenerovatelné složky (node_modules, .venv, target…) a duplicitní klony → koš.

Nic se nesmaže bez potvrzení (výchozí volba Zrušit); trvalé smazání jen s druhým
potvrzením. Repa s necommitnutými změnami a celé duplicitní klony vyžadují výslovné
potvrzení. Jádro (hledání, ověření, koš) je v `repo_doctor.cleanup`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from repo_doctor import czech
from repo_doctor.cleanup import (
    Candidate,
    CleanResult,
    apply_cleanup,
    duplicate_candidates,
    human,
    inspect_repo,
    is_inactive,
    mark_busy,
)
from repo_doctor.i18n import _
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.util import home_path
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


@dataclass
class Item:
    candidate: Candidate
    repo_name: str
    inactive: bool
    dirty: int
    selected: bool = False

    @property
    def key(self) -> str:
        return str(self.candidate.path)

    @property
    def label(self) -> str:
        """`repo/node_modules` místo dlouhé absolutní cesty; celý klon jako `~/…`."""
        c = self.candidate
        if c.kind == "clone" or c.path == c.repo:
            return home_path(str(c.path))
        try:
            return f"{self.repo_name}/{c.path.relative_to(c.repo)}"
        except ValueError:
            return home_path(str(c.path))


class CleanupScreen(BaseScreen):
    BINDINGS = [
        *BaseScreen.BINDINGS,
        *[b for b in bindings("cleanup") if b.id != "cleanup_apply"],
        # Enter by jinak spolkla tabulka (výběr řádku)
        *[
            Binding(
                b.key, b.action, b.description, key_display=b.key_display, priority=True, id=b.id
            )
            for b in bindings("cleanup")
            if b.id == "cleanup_apply"
        ],
    ]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[Item] = []
        self.loaded = False

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel") as page:
            page.border_title = _(" úklid místa ")
            yield Static(id="cleanup-note", classes="page-header")
            table: DataTable[str | Text] = DataTable(id="cleanup", cursor_type="row")
            yield table
            yield Static(id="cleanup-summary")
        yield KeyBar(["cleanup_toggle", "cleanup_all", "cleanup_apply", ("esc", _("zpět")), "help"])

    def on_mount(self) -> None:
        p = self.rd.palette
        cfg = self.rd.config.cleanup
        self.query_one("#cleanup-note", Static).update(
            Text(
                _(
                    "Složky ignorované gitem ({join}…), které jde znovu vytvořit. Předvybraná jsou repa neaktivní {inactive_days}+ dní bez změn. Výchozí je koš; trvalé smazání (D) jen po dvojím potvrzení. Nic sledovaného gitem se nemaže."
                ).format(join=", ".join(cfg.dirs[:6]), inactive_days=cfg.inactive_days),
                style=Style(color=p.muted),
            )
        )
        self.query_one("#cleanup-summary", Static).update(
            Text(_("Počítám velikosti…"), style=Style(color=p.muted))
        )
        self.load()
        self.query_one(DataTable).focus()

    @work(thread=True, exclusive=True, group="cleanup-load")
    def load(self) -> None:
        cfg = self.rd.config.cleanup
        items: list[Item] = []
        now = self.rd.now() or datetime.now(UTC)
        for repo in self.rd.result.repos:
            if repo.untrusted_owner:
                continue
            path = Path(repo.path).expanduser()
            if not path.is_dir():
                continue
            info = inspect_repo(path, cfg.dirs)
            if info.error:
                continue
            inactive = is_inactive(info, cfg.inactive_days, now)
            for c in info.candidates:
                items.append(Item(c, repo.name, inactive, info.dirty))
        for c in duplicate_candidates(self.rd.result):
            items.append(Item(c, c.path.name, True, 0))
        mark_busy([i.candidate for i in items])
        for item in items:
            item.selected = (
                item.candidate.kind == "dir"
                and item.inactive
                and not item.dirty
                and not item.candidate.busy
            )
        items.sort(key=lambda i: (-i.candidate.size, i.key))
        self.app.call_from_thread(self._loaded, items)

    def _loaded(self, items: list[Item]) -> None:
        self.items, self.loaded = items, True
        self.refresh_table()

    def refresh_table(self) -> None:
        p = self.rd.palette
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear(columns=True)
        table.add_columns(" ", "repo", _("složka"), _("velikost"), _("stav"))
        for item in self.items:
            c = item.candidate
            mark = Text(
                "[x]" if item.selected else "[ ]",
                style=Style(color=p.ok if item.selected else p.muted),
            )
            if c.busy:
                state = Text(_("běží proces – nelze"), style=Style(color=p.high))
            elif c.kind == "clone":
                state = Text(_("celý duplicitní klon"), style=Style(color=p.med))
            elif item.dirty:
                state = Text(
                    _("~{dirty} necommitnuté").format(dirty=item.dirty), style=Style(color=p.med)
                )
            elif item.inactive:
                state = Text(_("neaktivní"), style=Style(color=p.ok))
            else:
                state = Text(_("aktivní"), style=Style(color=p.muted))
            table.add_row(
                mark,
                item.repo_name,
                home_path(str(c.path)) if c.kind == "clone" else c.rel,
                Text(human(c.size), justify="right"),
                state,
                key=item.key,
            )
        if not self.items and self.loaded:
            table.add_row("", Text(_("nic k úklidu"), style=Style(color=p.muted)), "", "", "")
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self._summary()

    def _summary(self) -> None:
        p = self.rd.palette
        chosen = self.chosen()
        total = sum(i.candidate.size for i in chosen)
        t = Text(
            _("vybráno {len} · uvolní se {human}").format(len=len(chosen), human=human(total)),
            style=Style(color=p.text),
        )
        t.append(
            _("   (vše dohromady {human})").format(
                human=human(sum(i.candidate.size for i in self.items))
            ),
            style=Style(color=p.muted),
        )
        self.query_one("#cleanup-summary", Static).update(t)

    def chosen(self) -> list[Item]:
        return [i for i in self.items if i.selected and not i.candidate.busy]

    def _current(self) -> Item | None:
        table = self.query_one(DataTable)
        if not self.items or table.row_count == 0:
            return None
        return self.items[min(table.cursor_row, len(self.items) - 1)]

    # ------------------------------------------------------------------ akce
    def action_cleanup_toggle(self) -> None:
        item = self._current()
        if item is None:
            return
        if item.candidate.busy:
            self.notify(_("V této složce běží proces – nejde ji smazat."), severity="warning")
            return
        item.selected = not item.selected
        self.refresh_table()

    def action_cleanup_all(self) -> None:
        free = [i for i in self.items if not i.candidate.busy]
        target = not all(i.selected for i in free)
        for i in free:
            i.selected = target
        self.refresh_table()

    def _confirm_body(self, chosen: list[Item], *, permanent: bool) -> Text:
        p = self.rd.palette
        body = Text()
        total = sum(i.candidate.size for i in chosen)
        verb = _("trvale smaže") if permanent else _("přesune do koše")
        if permanent:
            body.append(_("\nTrvalé smazání nejde vrátit.\n"), style=Style(color=p.high, bold=True))
        body.append(f"\nrepo-doctor {verb} {czech.items(len(chosen))} ({human(total)}):\n")
        shown = 5
        for i in chosen[:shown]:
            body.append(f"  • {i.label}  {human(i.candidate.size)}\n", style=Style(color=p.text))
        if len(chosen) > shown:
            body.append(f"  {czech.more(len(chosen) - shown)}\n", style=Style(color=p.muted))
        dirty = sorted({i.repo_name for i in chosen if i.dirty})
        if dirty:
            body.append(
                _(
                    "\nRepa s necommitnutými změnami: {join}. Mažou se jen složky ignorované gitem, změny zůstanou.\n"
                ).format(join=", ".join(dirty)),
                style=Style(color=p.med),
            )
        clones = [i for i in chosen if i.candidate.kind == "clone"]
        if clones:
            body.append(
                _(
                    "\n{len}× celý duplicitní klon. Těsně před smazáním se znovu ověří, že nemá změny, nepushnuté commity, stashe ani vlastní ignorované soubory (.env).\n"
                ).format(len=len(clones)),
                style=Style(color=p.med),
            )
        return body

    def action_cleanup_apply(self) -> None:
        chosen = self.chosen()
        if not chosen:
            self.notify(_("Nic není vybráno."), severity="warning")
            return

        def done(ok: bool | None) -> None:
            if ok:
                self.do_apply(chosen, False)
            else:
                self.notify(_("Úklid zrušen – nic se nezměnilo."))

        self.app.push_screen(
            ConfirmDialog(
                _("Přesunout do koše"),
                self._confirm_body(chosen, permanent=False),
                confirm_label=_("Do koše"),
            ),
            done,
        )

    def action_cleanup_permanent(self) -> None:
        chosen = self.chosen()
        if not chosen:
            self.notify(_("Nic není vybráno."), severity="warning")
            return

        def second(ok: bool | None) -> None:
            if ok:
                self.do_apply(chosen, True)
            else:
                self.notify(_("Úklid zrušen – nic se nezměnilo."))

        def first(ok: bool | None) -> None:
            if not ok:
                self.notify(_("Úklid zrušen – nic se nezměnilo."))
                return
            self.app.push_screen(
                ConfirmDialog(
                    _("Opravdu trvale smazat?"),
                    Text(
                        _("\nPoslední potvrzení: {items} zmizí bez koše.\n").format(
                            items=czech.items(len(chosen))
                        )
                    ),
                    confirm_label=_("Trvale smazat"),
                    danger=True,
                ),
                second,
            )

        self.app.push_screen(
            ConfirmDialog(
                _("Trvale smazat"),
                self._confirm_body(chosen, permanent=True),
                confirm_label=_("Pokračovat"),
                danger=True,
            ),
            first,
        )

    @work(thread=True, exclusive=True, group="cleanup-apply")
    def do_apply(self, chosen: list[Item], permanent: bool) -> None:
        result = apply_cleanup([i.candidate for i in chosen], permanent=permanent)
        self.app.call_from_thread(self._applied, result, permanent)

    def _applied(self, result: CleanResult, permanent: bool) -> None:
        where = _("Trvale smazáno") if permanent else _("Přesunuto do koše")
        msg = _("{where}: {items}, uvolněno {human}.").format(
            where=where, items=czech.items(len(result.removed)), human=human(result.freed)
        )
        for path, reason in result.skipped[:5]:
            msg += f"\n! {home_path(str(path))}: {reason}"
        self.notify(
            msg,
            title=_("Úklid hotový"),
            timeout=12,
            severity="warning" if result.skipped else "information",
        )
        removed = {str(p) for p, _ in result.removed}
        self.items = [i for i in self.items if i.key not in removed]
        self.refresh_table()


__all__ = ["CleanupScreen"]
