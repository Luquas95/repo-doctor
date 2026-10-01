"""Obrazovka Přehled / Triáž."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from repo_doctor.models import Category, RepoResult, Severity
from repo_doctor.scoring import Band
from repo_doctor.tui.bindings import bindings
from repo_doctor.tui.screens.base import NavMixin
from repo_doctor.tui.triage_model import (
    GROUP_LABELS,
    SORT_COLUMNS,
    SORT_LABELS,
    TriageState,
    build_groups,
    forge_key,
)
from repo_doctor.tui.util import home_path, pad
from repo_doctor.tui.widgets.keybar import KeyBar
from repo_doctor.tui.widgets.panel import split_title
from repo_doctor.tui.widgets.triage import (
    Columns,
    group_header,
    header_text,
    preview_text,
    repo_row,
)
from repo_doctor.tui.widgets.vitals import Vitals, vitals_text

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

SIDEBAR_W = 22
DASH_KEYS: list[str | tuple[str, str]] = [
    "scan_all",
    "search",
    "open_card",
    "dash_fix",
    "collapse_band",
    "screen_folders",
    "screen_forges",
    "help",
    ("back", "konec"),
]


class SideBar(OptionList):
    DEFAULT_CSS = """
    SideBar { width: 22; border: round $rd-border; padding: 0 0; background: $background; scrollbar-size-vertical: 0; }
    SideBar:focus { border: round $accent; }
    """


class TriageList(OptionList):
    DEFAULT_CSS = """
    TriageList { border: none; padding: 0; height: 1fr; background: $background; scrollbar-size-vertical: 1; }
    TriageList:focus { border: none; }
    """


class DashboardScreen(NavMixin, Screen[Any]):
    BINDINGS = [
        *bindings("nav"),
        *bindings("dashboard"),
        Binding("escape", "escape", "zrušit hledání", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.state = TriageState()
        self.sidebar_forced: bool | None = None
        self._row_paths: list[str | None] = []
        self._row_groups: list[str | None] = []

    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        yield Vitals(id="vitals")
        with Horizontal(id="body"):
            yield SideBar(id="sidebar")
            with Vertical(id="triage-panel"):
                yield Input(
                    compact=True,
                    placeholder="hledat v názvech repozitářů a nálezech…",
                    id="search",
                    classes="hidden",
                )
                yield Static(id="triage-header")
                yield TriageList(id="triage")
                yield Static(id="preview")
        yield KeyBar(DASH_KEYS)

    def on_mount(self) -> None:
        self.state.group_by = self.rd.config.ui.group_by
        self.sidebar_forced = None if self.rd.config.ui.show_sidebar else False
        self.refresh_data()
        self.query_one(TriageList).focus()

    def on_resize(self, event: Resize) -> None:
        self.refresh_data()

    def on_theme_changed(self) -> None:
        self.refresh_data()

    def on_config_changed(self) -> None:
        self.refresh_data()

    def on_screen_resume(self) -> None:
        self.refresh_data()

    # ------------------------------------------------------------------ vykreslení
    @property
    def width(self) -> int:
        return self.app.size.width

    def _sidebar_visible(self) -> bool:
        if self.sidebar_forced is not None:
            return self.sidebar_forced
        return self.width >= 100

    def refresh_data(self, *, light: bool = False) -> None:
        if not self.is_mounted:
            return
        app = self.rd
        p = app.palette
        limits = app.config.limits
        vitals = self.query_one(Vitals)
        forges = len(app.config.forges)
        mode = "○ offline" if app.offline else "● online"
        when = app.result.finished_at
        right = f"{mode} · sken {when.astimezone():%H:%M}" if when else mode
        right += f" · {forges} {'hosting' if forges == 1 else 'hostingy' if 1 < forges < 5 else 'hostingů'}"
        split_title(vitals, "repo-doctor · triáž", right)
        vitals.update(
            vitals_text(
                app.result,
                p,
                max(20, self.width - 4),
                no_pulse_days=limits.no_pulse_days,
                scanning=app.scanning,
                done=app.scan_done,
                total=app.scan_total,
                current=app.scan_current,
            )
        )
        if light:
            return
        sidebar = self.query_one(SideBar)
        sidebar.display = self._sidebar_visible()
        panel = self.query_one("#triage-panel")
        sort = f"řazeno: {SORT_LABELS[self.state.sort]} {'↓' if self.state.reverse else '↑'}"
        split_title(
            panel,
            "TRIÁŽ"
            if self.state.group_by == "triage"
            else f"PŘEHLED · {GROUP_LABELS[self.state.group_by]}",
            sort,
        )
        if sidebar.display:
            self._render_sidebar()
        self._render_triage()

    def _columns(self) -> Columns:
        panel_w = self.width - (SIDEBAR_W if self._sidebar_visible() else 0) - 4
        return Columns(width=panel_w, show_pulse=self.width >= 90, show_host=self.width >= 80)

    def _render_triage(self) -> None:
        app = self.rd
        p = app.palette
        cols = self._columns()
        self.query_one("#triage-header", Static).update(header_text(cols, p))
        lst = self.query_one(TriageList)
        previous = app.selected_path
        prev_index = lst.highlighted
        groups = build_groups(
            app.result, self.state, no_pulse_days=app.config.limits.no_pulse_days, now=app.now()
        )
        options: list[Option] = []
        self._row_paths, self._row_groups = [], []
        key = app.keymap_ids.get("collapse_band", "z")
        for g in groups:
            collapsed = g.key in self.state.collapsed
            options.append(
                Option(
                    group_header(g, cols.width, p, collapsed=collapsed, toggle_key=key),
                    id=f"g:{g.key}",
                )
            )
            self._row_paths.append(None)
            self._row_groups.append(g.key)
            if not collapsed:
                for r in g.repos:
                    options.append(Option(repo_row(r, cols, p), id=f"r:{r.path}"))
                    self._row_paths.append(r.path)
                    self._row_groups.append(g.key)
            options.append(Option("", disabled=True))
            self._row_paths.append(None)
            self._row_groups.append(None)
        if not options:
            msg = (
                "Žádná repa neodpovídají filtru."
                if self.state.filters.active()
                else "Zatím žádná data – R spustí sken."
            )
            options.append(Option(Text(f"  {msg}", style=Style(color=p.muted)), disabled=True))
            self._row_paths.append(None)
            self._row_groups.append(None)
        lst.clear_options()
        lst.add_options(options)
        target = None
        if previous and previous in self._row_paths:
            target = self._row_paths.index(previous)
        elif (
            prev_index is not None
            and prev_index < len(options)
            and not options[prev_index].disabled
        ):
            target = prev_index
        else:
            target = next((i for i, path in enumerate(self._row_paths) if path), None)
            if target is None:
                target = next((i for i, o in enumerate(options) if not o.disabled), None)
        if target is not None:
            lst.highlighted = target
        self._update_preview()

    def _update_preview(self) -> None:
        app = self.rd
        width = self._columns().width
        self.query_one("#preview", Static).update(
            preview_text(app.selected_repo, width, app.palette)
        )

    def _render_sidebar(self) -> None:
        app = self.rd
        p = app.palette
        f = self.state.filters
        sb = self.query_one(SideBar)
        w = SIDEBAR_W - 3
        hl = sb.highlighted
        opts: list[Option] = []

        def head(text: str) -> None:
            opts.append(Option(Text(text, style=Style(color=p.accent, bold=True)), disabled=True))

        def item(
            label: str,
            count: str,
            oid: str,
            *,
            active: bool = False,
            dim: bool = False,
            mark: bool = True,
        ) -> None:
            left = (("▸ " if active else "  ") if mark else "") + label
            t = Text(
                pad(left, w - len(count)).plain,
                style=Style(color=p.dim if dim else p.text, bold=active),
            )
            t.append(count, style=Style(color=p.muted))
            opts.append(Option(t, id=oid))

        head("SLOŽKY")
        roots = app.roots
        for root in roots:
            n = sum(1 for r in app.result.repos if r.root == root.path)
            name = home_path(str(root.expanded)).rstrip("/").rsplit("/", 1)[-1] or root.path
            item(
                name,
                f"{n}" if root.enabled else "vyp.",
                f"root:{root.path}",
                active=f.root == root.path,
                dim=not root.enabled,
            )
        if not roots:
            opts.append(
                Option(Text("  žádné (4 přidá)", style=Style(color=p.muted)), disabled=True)
            )
        opts.append(Option("", disabled=True))
        head("HOSTINGY")
        counts: dict[str, int] = {}
        for r in app.result.repos:
            counts[forge_key(r)] = counts.get(forge_key(r), 0) + 1
        connected = {fc.name for fc in app.config.forges}
        for name in sorted(k for k in counts if k != "-"):
            sym = "◆" if name in connected else "·"
            item(f"{sym} {name}", str(counts[name]), f"forge:{name}", active=f.forge == name)
        if "-" in counts:
            item("○ bez remote", str(counts["-"]), "forge:-", active=f.forge == "-")
        opts.append(Option("", disabled=True))
        head("FILTR")
        item(("■" if f.problems_only else "□") + " jen problémová", "", "f:problems", mark=False)
        item(
            ("■" if self.state.group_by != "triage" else "□")
            + " seskupit: "
            + GROUP_LABELS[self.state.group_by],
            "",
            "f:group",
            mark=False,
        )
        sev = f"severity ≥ {f.min_severity.short}" if f.min_severity else "severity: vše"
        item("  " + sev, "", "f:severity", active=f.min_severity is not None, mark=False)
        cat = f"kat.: {f.category.label}" if f.category else "kategorie: vše"
        item("  " + cat, "", "f:category", active=f.category is not None, mark=False)
        opts.append(Option("", disabled=True))
        head("OD VČEREJŠKA")
        delta = app.history_delta
        if not delta:
            opts.append(Option(Text("  beze změny", style=Style(color=p.muted)), disabled=True))
        labels = {"high": "HIGH", "medium": "MED", "low": "LOW", "no_pulse": "bez tepu"}
        for key in ("high", "medium", "low", "no_pulse"):
            if key in delta:
                v = delta[key]
                color = (p.high if v > 0 else p.ok) if key != "no_pulse" else p.muted
                sign = "+" if v > 0 else "−"
                opts.append(
                    Option(
                        Text(f"  {sign}{abs(v)} {labels[key]}", style=Style(color=color)),
                        disabled=True,
                    )
                )
        sb.clear_options()
        sb.add_options(opts)
        if hl is not None and hl < len(opts) and not opts[hl].disabled:
            sb.highlighted = hl

    # ------------------------------------------------------------------ události
    @on(OptionList.OptionHighlighted, "#triage")
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        idx = event.option_index
        if 0 <= idx < len(self._row_paths) and self._row_paths[idx]:
            self.rd.selected_path = self._row_paths[idx]
            self._update_preview()

    @on(OptionList.OptionSelected, "#triage")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        path = self._row_paths[idx] if 0 <= idx < len(self._row_paths) else None
        if path:
            self.rd.open_detail(path)
        elif 0 <= idx < len(self._row_groups):
            group = self._row_groups[idx]
            if group:
                self._toggle_group(group)

    @on(OptionList.OptionSelected, "#sidebar")
    def _sidebar_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id or ""
        f = self.state.filters
        if oid.startswith("root:"):
            value = oid[5:]
            f.root = None if f.root == value else value
        elif oid.startswith("forge:"):
            value = oid[6:]
            f.forge = None if f.forge == value else value
        elif oid == "f:problems":
            self.action_problems_only()
            return
        elif oid == "f:group":
            self.action_group_cycle()
            return
        elif oid == "f:severity":
            order = [None, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
            f.min_severity = order[(order.index(f.min_severity) + 1) % len(order)]
        elif oid == "f:category":
            cats: list[Category | None] = [None, *Category]
            f.category = cats[(cats.index(f.category) + 1) % len(cats)]
        self.refresh_data()

    @on(Input.Changed, "#search")
    def _search_changed(self, event: Input.Changed) -> None:
        self.state.filters.query = event.value.strip()
        self._render_triage()

    @on(Input.Submitted, "#search")
    def _search_submitted(self) -> None:
        self.query_one(TriageList).focus()

    # ------------------------------------------------------------------ akce
    def open_search(self) -> None:
        search = self.query_one("#search", Input)
        search.remove_class("hidden")
        search.focus()

    def action_escape(self) -> None:
        search = self.query_one("#search", Input)
        if not search.has_class("hidden") or self.state.filters.query:
            search.value = ""
            self.state.filters.query = ""
            search.add_class("hidden")
            self.query_one(TriageList).focus()
            self._render_triage()

    def _toggle_group(self, key: str) -> None:
        if key in self.state.collapsed:
            self.state.collapsed.discard(key)
        else:
            self.state.collapsed.add(key)
        self._render_triage()
        lst = self.query_one(TriageList)
        if f"g:{key}" in [o.id for o in lst.options]:
            lst.highlighted = [o.id for o in lst.options].index(f"g:{key}")

    def action_collapse_band(self) -> None:
        idx = self.query_one(TriageList).highlighted
        if idx is not None and idx < len(self._row_groups) and self._row_groups[idx]:
            self._toggle_group(self._row_groups[idx])  # type: ignore[arg-type]
        elif Band.HEALTHY.value in self.state.collapsed:
            self._toggle_group(Band.HEALTHY.value)

    def action_open_card(self) -> None:
        if self.rd.selected_repo is not None:
            self.rd.open_detail(self.rd.selected_repo.path)

    def action_open_fix(self) -> None:
        repo = self.rd.selected_repo
        if repo is None:
            self.notify("Nejdřív vyber repo.", severity="warning")
            return
        self.rd.open_fix(repo.path)

    def action_sort_cycle(self) -> None:
        i = SORT_COLUMNS.index(self.state.sort)
        self.state.sort = SORT_COLUMNS[(i + 1) % len(SORT_COLUMNS)]
        self.state.reverse = False
        self.refresh_data()

    def action_sort_reverse(self) -> None:
        self.state.reverse = not self.state.reverse
        self.refresh_data()

    def _severity_filter(self, sev: Severity) -> None:
        f = self.state.filters
        f.min_severity = None if f.min_severity is sev else sev
        self.refresh_data()

    def action_filter_high(self) -> None:
        self._severity_filter(Severity.HIGH)

    def action_filter_medium(self) -> None:
        self._severity_filter(Severity.MEDIUM)

    def action_filter_low(self) -> None:
        self._severity_filter(Severity.LOW)

    def action_problems_only(self) -> None:
        self.state.filters.problems_only = not self.state.filters.problems_only
        self.refresh_data()

    def action_group_cycle(self) -> None:
        order = ["triage", "root", "forge"]
        self.state.group_by = order[(order.index(self.state.group_by) + 1) % 3]  # type: ignore[assignment]
        self.refresh_data()

    def action_toggle_sidebar(self) -> None:
        self.sidebar_forced = not self._sidebar_visible()
        self.refresh_data()

    def set_category(self, category: Category | None) -> None:
        self.state.filters.category = category
        self.refresh_data()

    def select_repo(self, path: str) -> None:
        self.rd.selected_path = path
        self.state.filters = type(self.state.filters)()
        self.state.collapsed.clear()
        self.refresh_data()

    def visible_repos(self) -> list[RepoResult]:
        return [r for p in self._row_paths if p and (r := self.rd.repo(p)) is not None]
