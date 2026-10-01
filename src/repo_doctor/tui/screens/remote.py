"""Vzdálená repa: repa na hostinzích bez lokálního klonu a lokální repa bez známého remote."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from repo_doctor.forges import ForgeManager
from repo_doctor.forges.base import ForgeRepo
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.httpclient import HttpError
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.forms import CloneDialog, CloneRequest
from repo_doctor.tui.util import git_state, home_path
from repo_doctor.tui.widgets.keybar import KeyBar

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


class RemoteScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("remote")]

    def __init__(self) -> None:
        super().__init__()
        self.view = "missing"  # missing | orphans
        self.missing: list[tuple[str, ForgeRepo]] = []
        self.errors: list[str] = []
        self.loaded = False
        self.known: dict[str, set[str]] = {}

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Vertical(classes="page panel", id="remote-page"):
            yield Static(id="remote-note", classes="page-header")
            yield DataTable(id="remote", cursor_type="row")
        yield KeyBar(["clone", "remote_view", "remote_refresh", ("esc", "zpět"), "help"])

    def on_mount(self) -> None:
        self.render_view()
        self.query_one(DataTable).focus()
        self.load()

    def action_remote_refresh(self) -> None:
        self.load()

    def action_remote_view(self) -> None:
        self.view = "orphans" if self.view == "missing" else "missing"
        self.render_view()

    @work(exclusive=True, group="remote-load")
    async def load(self) -> None:
        app = self.rd
        if app.offline:
            self.errors = ["Offline režim – seznam vzdálených rep není k dispozici (O ho vypne)."]
            self.loaded = True
            self.render_view()
            return
        if not app.config.forges:
            self.errors = ["Není připojený žádný hosting – přidej ho na obrazovce Hostingy (5)."]
            self.loaded = True
            self.render_view()
            return
        self.loaded = False
        self.render_view()
        mgr = await asyncio.to_thread(
            ForgeManager.from_config, app.config, transport=app.forge_transport
        )
        self.errors = [f"{name}: {reason}" for name, reason in mgr.unavailable.items()]
        local: set[tuple[str, str]] = set()
        for repo in app.result.repos:
            for remote in repo.remotes:
                if remote.forge and remote.owner_path:
                    local.add((remote.forge, remote.owner_path.lower()))
        missing: list[tuple[str, ForgeRepo]] = []
        self.known = {}
        try:
            for name, forge in mgr.forges.items():
                try:
                    repos = await forge.list_repos()
                except HttpError as err:
                    self.errors.append(f"{name}: {err}")
                    continue
                self.known[name] = {r.full_name.lower() for r in repos}
                missing.extend((name, r) for r in repos if (name, r.full_name.lower()) not in local)
        finally:
            await mgr.aclose()
        self.missing = sorted(missing, key=lambda x: (x[0], x[1].full_name.lower()))
        self.loaded = True
        self.render_view()

    def _orphans(self) -> list[tuple[str, str, str]]:
        out = []
        for repo in sorted(self.rd.result.repos, key=lambda r: r.name):
            if not repo.remotes:
                out.append((repo.name, home_path(repo.path), "bez remote"))
                continue
            unknown = any(f.check_id == "forge-unknown-remote" for f in repo.findings)
            for remote in repo.remotes:
                listing = self.known.get(remote.forge or "")
                if unknown or (
                    listing is not None
                    and remote.owner_path
                    and remote.owner_path.lower() not in listing
                ):
                    out.append(
                        (
                            repo.name,
                            home_path(repo.path),
                            f"{remote.forge}: {remote.owner_path} hosting nezná",
                        )
                    )
                    break
        return out

    def render_view(self) -> None:
        p = self.rd.palette
        page = self.query_one("#remote-page")
        table = self.query_one(DataTable)
        table.clear(columns=True)
        note = Text()
        if self.view == "missing":
            page.border_title = " vzdálená repa · na hostingu bez lokálního klonu "
            table.add_columns("hosting", "repozitář", "viditelnost", "stav", "popis")
            if not self.loaded:
                note.append("Načítám seznam repozitářů z hostingů…", style=Style(color=p.muted))
            for name, repo in self.missing:
                vis = (
                    Text("◉ veřejné", style=Style(color=p.high))
                    if not repo.private
                    else Text("○ privátní", style=Style(color=p.muted))
                )
                state = "archiv" if repo.archived else ("fork" if repo.fork else "")
                table.add_row(name, repo.full_name, vis, state, repo.description[:50])
            if self.loaded and not self.missing and not self.errors:
                note.append("Všechna repa z hostingů mají lokální klon. ✓", style=Style(color=p.ok))
            elif self.missing:
                note.append(
                    f"{len(self.missing)} repozitářů bez lokálního klonu · c naklonuje vybrané · v přepne pohled",
                    style=Style(color=p.muted),
                )
        else:
            page.border_title = " vzdálená repa · lokální bez (známého) remote "
            table.add_columns("repozitář", "cesta", "problém", "git")
            orphans = self._orphans()
            for name, path, problem in orphans:
                local = next((r for r in self.rd.result.repos if r.name == name), None)
                table.add_row(
                    name,
                    path,
                    Text(problem, style=Style(color=p.med)),
                    git_state(local) if local else "",
                )
            note.append(
                f"{len(orphans)} lokálních rep bez zálohy nebo s remote, který hosting nezná · v přepne pohled",
                style=Style(color=p.muted),
            )
        for err in self.errors:
            note.append(f"\n! {err}", style=Style(color=p.med))
        self.query_one("#remote-note", Static).update(note)

    def action_clone(self) -> None:
        if self.view != "missing" or not self.missing:
            self.notify(
                "Vyber repo v pohledu „na hostingu bez lokálního klonu“.", severity="warning"
            )
            return
        roots = [r for r in self.rd.config.roots if r.enabled]
        if not roots:
            self.notify("Není nastavená žádná sledovaná složka (4).", severity="warning")
            return
        row = self.query_one(DataTable).cursor_row
        name, repo = self.missing[min(row, len(self.missing) - 1)]
        forge = self.rd.config.forge(name)
        protocol = forge.clone_protocol if forge else "ssh"

        def done(req: CloneRequest | None) -> None:
            if req is not None:
                self.do_clone(req, name, repo)

        self.app.push_screen(CloneDialog(repo, roots, protocol), done)

    @work(thread=True, group="clone")
    def do_clone(self, req: CloneRequest, forge: str, repo: ForgeRepo) -> None:
        self.app.call_from_thread(self.notify, f"Klonuji {repo.full_name}…")
        try:
            Git.clone(req.url, req.dest)
        except (GitError, FileExistsError) as err:
            msg = err.stderr if isinstance(err, GitError) else str(err)
            self.app.call_from_thread(
                self.notify, f"Klon selhal: {msg}", severity="error", timeout=10
            )
            return
        self.app.call_from_thread(self._cloned, req.dest, forge, repo)

    def _cloned(self, dest: Path, forge: str, repo: ForgeRepo) -> None:
        self.missing = [
            (f, r) for f, r in self.missing if not (f == forge and r.full_name == repo.full_name)
        ]
        self.render_view()
        self.notify(
            f"Naklonováno do {home_path(str(dest))}. {self.rd.key('scan_all')} spustí sken."
        )
