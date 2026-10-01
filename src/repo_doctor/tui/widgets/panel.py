"""Pomocníci pro panely se zaobleným rámečkem a nadpisem vlevo i vpravo."""

from __future__ import annotations

from textual.widget import Widget


def split_title(widget: Widget, left: str, right: str = "") -> None:
    """Nadpis rámečku: `left` vlevo, `right` zarovnaný doprava (podle aktuální šířky)."""
    width = widget.size.width or widget.app.size.width
    inner = max(0, width - 6)
    left_part = f" {left} "
    if right:
        right_part = f" {right} "
        gap = inner - len(left_part) - len(right_part)
        if gap >= 2:
            widget.border_title = left_part + "─" * gap + right_part
            return
    widget.border_title = left_part
