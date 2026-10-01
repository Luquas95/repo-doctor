"""Léčba: výběr oprav (předpis), barevný náhled diffu a potvrzení."""

from __future__ import annotations

import contextlib
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.widgets import SelectionList, Static
from textual.widgets.selection_list import Selection

from repo_doctor.checks.base import RepoContext
from repo_doctor.config import ConfigError, effective_for_repo, load_repo_overrides
from repo_doctor.fixes import ApplyResult, FixRefused, apply, branch_name, plan
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.models import Patch, RepoResult
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from repo_doctor.tui.theme import Palette
from repo_doctor.tui.widgets.keybar import KeyBar
from repo_doctor.tui.widgets.panel import split_title

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


def diff_text(diff: str, p: Palette, width: int) -> Text:
    t = Text()
    for raw in diff.splitlines():
        line = raw.ljust(max(width, len(raw)))
        if raw.startswith(("+++", "---")):
            style = Style(color=p.muted)
        elif raw.startswith("+"):
            style = Style(color=p.ok, bgcolor=p.diff_add)
        elif raw.startswith("-"):
            style = Style(color=p.high, bgcolor=p.diff_del)
        elif raw.startswith("@@"):
            style = Style(color=p.accent)
        else:
            style = Style(color=p.text)
        t.append(line + "\n", style=style)
    return t


def commits_word(n: int) -> str:
    return "commit" if n == 1 else "commity" if 1 < n < 5 else "commitů"


class FixScreen(BaseScreen):
    BINDINGS = [
        *BaseScreen.BINDINGS,
        *[b for b in bindings("fix") if b.id != "confirm_fix"],
        Binding(
            "enter", "confirm_fix", "potvrdit", key_display="⏎", priority=True, id="confirm_fix"
        ),
    ]

    def __init__(self, path: str, focus_check: str | None = None) -> None:
        super().__init__()
        self.path = path
        self.focus_check = focus_check
        self.patches: list[Patch] = []
        self.branch = ""
        self.dirty = 0
        self.ready = False
        self.current: Patch | None = None

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    @property
    def repo(self) -> RepoResult | None:
        return self.rd.repo(self.path)

    def compose(self) -> ComposeResult:
        yield Static(id="fix-header")
        with Horizontal(id="fix-body"):
            with Vertical(id="rx-panel"):
                yield SelectionList[str](id="rx")
                yield Static(id="rx-summary")
            with VerticalScroll(id="diff-panel"):
                yield Static(id="diff")
        yield KeyBar(
            ["toggle_fix", "select_all", ("j/k", "pohyb"), "confirm_fix", ("esc", "zpět"), "help"]
        )

    def on_mount(self) -> None:
        self.query_one("#rx-panel").border_title = " PŘEDPIS "
        self.query_one("#diff-panel").border_title = " NÁHLED ZMĚN "
        self._header("připravuji opravy…")
        self.prepare()

    def on_resize(self, event: Resize) -> None:
        self._render_diff()

    def on_theme_changed(self) -> None:
        self._render_list()
        self._render_diff()

    def _header(self, message: str | Text) -> None:
        repo = self.repo
        header = self.query_one("#fix-header", Static)
        n = len(self.patches)
        right = f"{n} {'opravitelný nález' if n == 1 else 'opravitelné nálezy' if 1 < n < 5 else 'opravitelných nálezů'}"
        split_title(header, f"léčba · {repo.name if repo else '?'}", right if self.ready else "")
        header.update(message)

    def _repo_context(self, repo: RepoResult) -> RepoContext:
        path = Path(repo.path)
        config = self.rd.config
        with contextlib.suppress(ConfigError):
            config = effective_for_repo(config, load_repo_overrides(path))
        return RepoContext(
            path=path,
            name=repo.name,
            root=repo.root,
            config=config,
            git=Git(path),
            now=self.rd.now(),
        )

    @work(thread=True, exclusive=True, group="fix-prepare")
    def prepare(self) -> None:
        repo = self.repo
        if repo is None:
            self.app.call_from_thread(self._header, "Repo už není ve výsledcích skenu.")
            return
        try:
            ctx = self._repo_context(repo)
            patches = plan(ctx, [f for f in repo.findings if f.fixable])
            dirty = ctx.git.status().dirty
            branch = branch_name(ctx.git, self.rd.now().date())
        except (GitError, OSError) as err:
            self.app.call_from_thread(
                self._header,
                Text(f"Opravy nejde připravit: {err}", style=Style(color=self.rd.palette.high)),
            )
            return
        self.app.call_from_thread(self._prepared, patches, dirty, branch)

    def _prepared(self, patches: list[Patch], dirty: int, branch: str) -> None:
        self.patches, self.dirty, self.branch, self.ready = patches, dirty, branch, True
        p = self.rd.palette
        if not patches:
            self._header(
                Text("Žádné automaticky opravitelné nálezy. Esc zpět.", style=Style(color=p.muted))
            )
        elif dirty:
            self._header(
                Text(
                    f"Repo má necommitnuté změny (~{dirty}) – oprava se nespustí, repo-doctor na ně nesahá. "
                    "Commitni je nebo ulož do stashe.",
                    style=Style(color=p.med),
                )
            )
        else:
            self._header(
                Text(
                    "Vyber, co opravit. Změny vzniknou v nové větvi, nic se nepushne.",
                    style=Style(color=p.text),
                )
            )
        self._render_list()
        self.query_one(SelectionList).focus()

    def _render_list(self) -> None:
        p = self.rd.palette
        sl = self.query_one(SelectionList)
        selected = set(sl.selected) if sl.option_count else None
        sl.clear_options()
        options = []
        for patch in self.patches:
            prompt = Text(patch.check_id, style=Style(color=p.text, bold=True))
            prompt.append("\n    " + patch.summary[:60], style=Style(color=p.muted))
            if selected is not None:
                on_ = patch.check_id in selected
            else:
                on_ = self.focus_check is None or patch.check_id == self.focus_check
            options.append(Selection(prompt, patch.check_id, on_))
        sl.add_options(options)
        if self.focus_check:
            ids = [pt.check_id for pt in self.patches]
            if self.focus_check in ids:
                sl.highlighted = ids.index(self.focus_check)
        if self.patches and sl.highlighted is None:
            sl.highlighted = 0
        self._summary()
        self._render_diff()

    def _summary(self) -> None:
        p = self.rd.palette
        n = len(self.query_one(SelectionList).selected)
        t = Text(f"vybráno {n} · {n} {commits_word(n)}\n", style=Style(color=p.text))
        t.append(f"větev {self.branch}", style=Style(color=p.accent))
        self.query_one("#rx-summary", Static).update(t)

    def _render_diff(self) -> None:
        if not self.is_mounted:
            return
        panel = self.query_one("#diff-panel")
        patch = self.current or (self.patches[0] if self.patches else None)
        if patch is None:
            self.query_one("#diff", Static).update("")
            return
        files = ", ".join(c.path for c in patch.changes[:3])
        panel.border_title = f" NÁHLED ZMĚN · {files} "
        width = max(20, panel.size.width - 4)
        text = diff_text(patch.diff(), self.rd.palette, width)
        if patch.notes:
            text.append("\n")
            for note in patch.notes:
                text.append(f"! {note}\n", style=Style(color=self.rd.palette.med))
        self.query_one("#diff", Static).update(text)

    @on(SelectionList.SelectionHighlighted)
    def _highlighted(self, event: SelectionList.SelectionHighlighted[str]) -> None:
        check_id = event.selection.value
        self.current = next((pt for pt in self.patches if pt.check_id == check_id), None)
        self._render_diff()

    @on(SelectionList.SelectedChanged)
    def _changed(self) -> None:
        self._summary()

    def action_toggle_fix(self) -> None:
        sl = self.query_one(SelectionList)
        if sl.highlighted is not None:
            sl.toggle(sl.get_option_at_index(sl.highlighted).value)

    def action_select_all(self) -> None:
        sl = self.query_one(SelectionList)
        if len(sl.selected) == sl.option_count:
            sl.deselect_all()
        else:
            sl.select_all()

    def action_confirm_fix(self) -> None:
        if not self.ready:
            return
        if self.dirty:
            self.notify("Repo má necommitnuté změny – oprava se nespustí.", severity="error")
            return
        chosen = [
            pt for pt in self.patches if pt.check_id in set(self.query_one(SelectionList).selected)
        ]
        if not chosen:
            self.notify("Nic není vybráno (space vybere, A vše).", severity="warning")
            return
        repo = self.repo
        default = (repo.state.default_branch or repo.state.branch or "main") if repo else "main"
        n = len(chosen)
        body = Text()
        body.append("\nVznikne nová větev\n  ")
        body.append(self.branch, style=Style(color=self.rd.palette.accent, bold=True))
        body.append(
            f"\nse {n} {commits_word(n)}. Nic se nepushne, {default} zůstane\n"
            "beze změny a necommitnuté soubory nedotčené.\n"
        )

        def decided(ok: bool | None) -> None:
            if ok:
                self.do_apply(chosen)
            else:
                self.notify("Léčba zrušena – nic se nezměnilo.")

        self.app.push_screen(
            ConfirmDialog("Potvrdit léčbu", body, confirm_label="Aplikovat"), decided
        )

    @work(thread=True, exclusive=True, group="fix-apply")
    def do_apply(self, chosen: list[Patch]) -> None:
        repo = self.repo
        if repo is None:
            return
        try:
            result = apply(
                Git(Path(repo.path)),
                chosen,
                today=self.rd.now().date() if self.rd.now() else date.today(),
            )
        except (FixRefused, GitError) as err:
            message = str(err) if isinstance(err, FixRefused) else f"git selhal: {err.stderr}"
            self.app.call_from_thread(
                self.notify, message, title="Léčba se nepovedla", severity="error", timeout=10
            )
            return
        self.app.call_from_thread(self._applied, result)

    def _applied(self, result: ApplyResult) -> None:
        n = len(result.commits)
        msg = f"Vytvořena větev {result.branch} s {n} {commits_word(n)}. Nic se nepushnulo – zkontroluj ji: git log {result.branch}"
        for note in result.notes:
            msg += f"\n! {note}"
        self.notify(msg, title="Léčba hotová", timeout=15)
        self.app.pop_screen()
