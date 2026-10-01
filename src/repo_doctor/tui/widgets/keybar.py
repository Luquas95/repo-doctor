"""Spodní lišta zkratek jako „klávesové čepičky“ – generovaná z registru zkratek."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from repo_doctor.keymap import BY_ID, display_key

if TYPE_CHECKING:
    from repo_doctor.tui.app import RepoDoctorApp

Item = str | tuple[str, str]  # id akce z registru, (id akce, vlastní popis), nebo (klávesa, popis)


class KeyBar(Static):
    DEFAULT_CSS = """
    KeyBar { height: 1; dock: bottom; background: $background; padding: 0 1; }
    """

    def __init__(self, items: list[Item], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.items = items

    def on_mount(self) -> None:
        self.render_bar()

    def on_resize(self) -> None:
        self.render_bar()

    def set_items(self, items: list[Item]) -> None:
        self.items = items
        self.render_bar()

    def render_bar(self) -> None:
        app: RepoDoctorApp = self.app  # type: ignore[assignment]
        p = app.palette
        width = max(10, self.size.width or app.size.width) - 2
        parts: list[tuple[str, str, bool]] = []  # (klávesa, popis, lze vypustit)
        for item in self.items:
            action_id, desc = (item, None) if isinstance(item, str) else item
            if action_id not in BY_ID:
                parts.append((action_id, desc or "", True))
                continue
            action = BY_ID[action_id]
            key = app.keymap_ids.get(action_id, action.key)
            shown = action.label if action.label and key == action.key else display_key(key)
            parts.append((shown, desc or action.description, action_id not in {"help", "back"}))

        def total() -> int:
            return sum(len(k) + len(d) + 4 for k, d, _ in parts)

        while total() > width and any(drop for *_, drop in parts):
            idx = max(i for i, (*_, drop) in enumerate(parts) if drop)
            del parts[idx]
        t = Text()
        for key, desc, _ in parts:
            t.append(f" {key} ", style=Style(color=p.background, bgcolor=p.accent, bold=True))
            t.append(f" {desc} ", style=Style(color=p.muted))
        self.update(t)
