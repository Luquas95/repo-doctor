"""Karta repa: strom nálezů podle kategorií a diagnóza vybraného nálezu."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.widgets import Static, Tree

from repo_doctor.checkdocs import load as load_doc
from repo_doctor.config import AllowEntry, ConfigError
from repo_doctor.models import Category, Finding, RepoResult
from repo_doctor.scoring import gauge, sparkline
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import BaseScreen
from repo_doctor.tui.screens.dialogs import InputDialog
from repo_doctor.tui.util import (
    editor_command,
    git_state,
    home_path,
    open_url,
    relative_time,
    wl_copy,
)
from repo_doctor.tui.widgets.keybar import KeyBar
from repo_doctor.tui.widgets.panel import split_title

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

CATEGORY_ORDER = (Category.SECURITY, Category.FORGE, Category.MAINTENANCE, Category.GIT)


def card_header(repo: RepoResult, app: RepoDoctorApp, width: int) -> Text:
    p = app.palette
    muted = Style(color=p.muted)
    t = Text()
    t.append("SKÓRE ", style=muted)
    color = p.score(repo.score)
    t.append(f"{repo.score}/100 ", style=Style(color=color, bold=True))
    t.append(gauge(repo.score), style=Style(color=color))
    t.append("    větev ", style=muted)
    t.append(
        repo.state.branch or ("detached" if repo.state.detached else "—"), style=Style(color=p.text)
    )
    t.append("    remote ", style=muted)
    remote = repo.remotes[0] if repo.remotes else None
    if remote:
        label = f"{remote.forge or remote.host or ''}:{remote.owner_path or ''}".strip(":")
        t.append(label or remote.url, style=Style(color=p.text))
    else:
        t.append("žádný (bez zálohy)", style=Style(color=p.high))
    t.append("   ")
    if repo.visibility == "public":
        t.append("◉ veřejné", style=Style(color=p.high, bold=True))
    elif repo.visibility == "private":
        t.append("○ privátní", style=muted)
    else:
        t.append("· viditelnost neznámá", style=Style(color=p.dim))
    t.append("\nTEP  ", style=muted)
    pulse_w = max(10, min(30, width - 50))
    t.append(
        sparkline(repo.state.pulse, pulse_w) or "▁" * pulse_w,
        style=Style(color=p.accent if sum(repo.state.pulse) else p.dim),
    )
    t.append(f"   poslední commit {relative_time(repo.state.last_commit, app.now())}", style=muted)
    t.append(f" · {git_state(repo)}", style=Style(color=p.text))
    t.append("\n")
    info = repo.forge_info
    if "ci" in info:
        ci = info.get("ci")
        if ci == "failure":
            t.append(f"CI ✗ selhalo #{info.get('ci_number') or '?'}", style=Style(color=p.high))
        elif ci == "success":
            t.append("CI ✓ prošlo", style=Style(color=p.ok))
        else:
            t.append(f"CI {ci or '—'}", style=muted)
        prot = info.get("protected")
        t.append("    ochrana větve ", style=muted)
        t.append(
            "✓" if prot else "✗" if prot is False else "?",
            style=Style(color=p.ok if prot else p.high if prot is False else p.dim),
        )
        alerts = info.get("alerts")
        t.append(f"    alerty {alerts if alerts is not None else '?'}", style=muted)
        t.append(f"    otevřené PR {info.get('open_items', 0)}", style=muted)
    elif repo.skipped.get("forge-ci-failing"):
        t.append(f"hosting: {repo.skipped['forge-ci-failing']}", style=Style(color=p.dim))
    else:
        t.append("hosting: bez dat", style=Style(color=p.dim))
    if "fetch" in repo.errors:
        t.append("\nfetch ✗ ", style=Style(color=p.high))
        t.append(repo.errors["fetch"], style=Style(color=p.text))
        if "fetch_detail" in repo.errors:
            t.append(f"  (git: {repo.errors['fetch_detail']})", style=Style(color=p.dim))
    return t


def diagnosis(finding: Finding | None, app: RepoDoctorApp) -> Text:
    p = app.palette
    muted = Style(color=p.muted)
    if finding is None:
        return Text("Vyber nález vlevo (j/k).", style=muted)
    t = Text()
    t.append(
        f"{finding.severity.symbol} {finding.severity.short}",
        style=Style(color=p.severity(finding.severity), bold=True),
    )
    t.append(f" · {finding.check_id}\n", style=Style(color=p.text, bold=True))
    t.append(f"{finding.title}\n\n", style=Style(color=p.text))

    def row(label: str, value: str | Text) -> None:
        t.append(f"{label:<8}", style=muted)
        t.append(value if isinstance(value, Text) else Text(value, style=Style(color=p.text)))
        t.append("\n")

    row("nález", finding.message)
    where = finding.location.render()
    if where:
        row("kde", where)
    if finding.kind:
        row("typ", finding.kind)
    if finding.snippet:
        sn = Text(finding.snippet, style=Style(color=p.med))
        sn.append("   odmaskovat nejde · o otevře soubor", style=Style(color=p.dim))
        row("ukázka", sn)
    for key, value in finding.data.items():
        if key in ("count", "rule"):
            continue
        shown = ", ".join(map(str, value[:8])) if isinstance(value, list) else str(value)
        row(key, shown)
    doc = load_doc(finding.check_id)
    if doc:
        t.append("\nPROČ TO VADÍ\n", style=Style(color=p.accent, bold=True))
        t.append(doc.why + "\n", style=Style(color=p.text))
        t.append("\nPOSTUP\n", style=Style(color=p.accent, bold=True))
        for i, step in enumerate(doc.steps, start=1):
            t.append(f"{i}  ", style=Style(color=p.accent))
            t.append(step.replace("`", "") + "\n", style=Style(color=p.text))
        if doc.note:
            t.append("\n" + doc.note + "\n", style=Style(color=p.med))
    if finding.fixable:
        t.append(
            f"\n✓ opravitelné automaticky – {app.key('detail_fix')} připraví opravu\n",
            style=Style(color=p.ok),
        )
    t.append(
        f"\n {app.key('open_editor')}  otevřít soubor   {app.key('open_web')}  na webu   "
        f"{app.key('copy_path')}  kopírovat cestu",
        style=Style(color=p.muted),
    )
    return t


class DetailScreen(BaseScreen):
    BINDINGS = [*BaseScreen.BINDINGS, *bindings("detail")]

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.current: Finding | None = None

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    @property
    def repo(self) -> RepoResult | None:
        return self.rd.repo(self.path)

    def compose(self) -> ComposeResult:
        yield Static(id="card-header")
        with Horizontal(id="card-body"):
            with Vertical(id="findings-panel"):
                tree: Tree[Finding | None] = Tree("nálezy", id="findings")
                tree.show_root = False
                tree.guide_depth = 2
                yield tree
                yield Static(id="findings-hint")
            with VerticalScroll(id="diagnosis"):
                yield Static(id="diag")
        yield KeyBar(
            [
                ("esc", "zpět"),
                ("j/k", "nález"),
                "detail_fix",
                "allowlist",
                "open_editor",
                "open_web",
                "copy_path",
                "help",
            ]
        )

    def on_mount(self) -> None:
        self.render_all()
        self.query_one(Tree).focus()

    def on_resize(self, event: Resize) -> None:
        self.render_all()

    def on_theme_changed(self) -> None:
        self.render_all()

    def render_all(self) -> None:
        repo = self.repo
        app = self.rd
        p = app.palette
        header = self.query_one("#card-header", Static)
        if repo is None:
            header.update(Text("Repo už není ve výsledcích skenu.", style=Style(color=p.muted)))
            return
        split_title(header, f"karta · {repo.name}", home_path(repo.path))
        header.update(card_header(repo, app, self.app.size.width))
        tree = self.query_one(Tree)
        tree.clear()
        panel = self.query_one("#findings-panel")
        panel.border_title = f" NÁLEZY · {len(repo.findings)} "
        first = None
        for cat in CATEGORY_ORDER:
            items = sorted(
                (f for f in repo.findings if f.category is cat),
                key=lambda f: (-f.severity.rank, f.check_id),
            )
            label = Text(f"{cat.label:<20}", style=Style(color=p.text, bold=True))
            label.append(f"{len(items):>3}", style=Style(color=p.muted))
            node = tree.root.add(label, data=None, expand=bool(items))
            for f in items:
                leaf = Text(f"{f.severity.symbol} ", style=Style(color=p.severity(f.severity)))
                leaf.append(f"{f.check_id:<22}", style=Style(color=p.text))
                if f.fixable:
                    leaf.append(" ✓", style=Style(color=p.ok))
                n = node.add_leaf(leaf, data=f)
                if first is None:
                    first = n
        hint = Text("✓ opravitelné automaticky\n", style=Style(color=p.ok))
        hint.append("a allowlist · skryje nález", style=Style(color=p.muted))
        self.query_one("#findings-hint", Static).update(hint)
        self.query_one("#diagnosis").border_title = " DIAGNÓZA "
        if first is not None:
            tree.move_cursor(first)
            self.current = first.data
        else:
            self.current = None
        self._show()

    def _show(self) -> None:
        self.query_one("#diag", Static).update(diagnosis(self.current, self.rd))

    @on(Tree.NodeHighlighted)
    def _node(self, event: Tree.NodeHighlighted[Finding | None]) -> None:
        if event.node.data is not None:
            self.current = event.node.data
            self._show()

    # ------------------------------------------------------------------ akce
    def action_open_fix(self) -> None:
        repo = self.repo
        if repo is None:
            return
        if not any(f.fixable for f in repo.findings):
            self.notify("Repo nemá žádné automaticky opravitelné nálezy.", severity="warning")
            return
        self.rd.open_fix(
            repo.path, self.current.check_id if self.current and self.current.fixable else None
        )

    def action_allowlist(self) -> None:
        repo, finding = self.repo, self.current
        if repo is None or finding is None:
            self.notify("Vyber nález.", severity="warning")
            return
        fp = finding.fingerprint(repo.name)

        def done(reason: str | None) -> None:
            if not reason:
                return
            try:
                config = self.rd.store.add_allow(
                    AllowEntry(hash=fp, reason=reason, check=finding.check_id, repo=repo.name)
                )
            except ConfigError as err:
                self.notify(str(err), severity="error")
                return
            repo.findings = [f for f in repo.findings if f.fingerprint(repo.name) != fp]
            repo.allowlisted += 1
            self.rd.config_changed(config)
            self.notify(f"{finding.check_id} přidán do allowlistu.")
            self.render_all()

        self.app.push_screen(
            InputDialog(
                "Allowlist",
                f"Proč skrýt nález {finding.check_id}? (uloží se do config.toml)",
                placeholder="např. testovací fixtura, falešný poplach",
            ),
            done,
        )

    def action_open_editor(self) -> None:
        repo, finding = self.repo, self.current
        if repo is None:
            return
        rel = finding.location.path if finding else None
        target = Path(repo.path) / rel if rel else Path(repo.path)
        if rel and not target.exists():
            self.notify(
                f"Soubor {rel} v pracovním stromu neexistuje (je jen v historii).",
                severity="warning",
            )
            return
        cmd = editor_command(
            self.rd.config.ui.editor, target, finding.location.line if finding else None
        )
        try:
            with self.app.suspend():
                subprocess.run(cmd, check=False)
        except (OSError, Exception) as err:
            self.notify(f"Editor nejde spustit: {err}", severity="error")

    def action_open_web(self) -> None:
        repo = self.repo
        if repo is None or not repo.web_url:
            self.notify("Repo nemá webovou adresu hostingu.", severity="warning")
            return
        if not open_url(repo.web_url):
            self.notify(f"xdg-open není k dispozici: {repo.web_url}", severity="warning")

    def action_copy_path(self) -> None:
        repo = self.repo
        if repo is None:
            return
        if not wl_copy(repo.path):
            self.app.copy_to_clipboard(repo.path)  # OSC 52
        self.notify(f"Zkopírováno: {repo.path}")
