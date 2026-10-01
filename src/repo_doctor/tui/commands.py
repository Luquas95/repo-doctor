"""Příkazová paleta (Ctrl+P): všechny akce a přechod na libovolné repo podle názvu."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import DiscoveryHit, Hit, Hits, Provider

from repo_doctor.keymap import ACTIONS
from repo_doctor.models import Category

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp


class RepoCommands(Provider):
    @property
    def rd(self) -> RepoDoctorApp:
        return self.app  # type: ignore[return-value]

    def _commands(self) -> list[tuple[str, object, str]]:
        app = self.rd
        cmds: list[tuple[str, object, str]] = []
        for a in ACTIONS:
            if a.context in ("global",) and a.id not in {"command_palette", "quit"}:
                cmds.append(
                    (
                        a.description.capitalize(),
                        partial(app.run_action, a.action),
                        f"klávesa {a.display}",
                    )
                )
        dash_actions = [
            a for a in ACTIONS if a.context == "dashboard" and a.id not in {"open_card"}
        ]
        for a in dash_actions:
            cmds.append(
                (f"Přehled: {a.description}", partial(self._dash, a.action), f"klávesa {a.display}")
            )
        for cat in [None, *Category]:
            label = cat.label if cat else "vše"
            cmds.append((f"Filtr kategorie: {label}", partial(self._category, cat), "přehled"))
        cmds.append(("Konec", app.exit, "Ctrl+C"))
        for repo in sorted(app.result.repos, key=lambda r: r.name):
            cmds.append(
                (f"Otevřít repo: {repo.name}", partial(app.open_detail, repo.path), repo.path)
            )
        return cmds

    def _dash(self, action: str) -> None:
        app = self.rd
        app.action_switch_screen_n(1)
        app.call_later(app.dashboard.run_action, action)

    def _category(self, cat: Category | None) -> None:
        app = self.rd
        app.action_switch_screen_n(1)
        app.dashboard.set_category(cat)

    async def discover(self) -> Hits:
        for name, callback, help_text in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)  # type: ignore[arg-type]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback, help_text in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)  # type: ignore[arg-type]
