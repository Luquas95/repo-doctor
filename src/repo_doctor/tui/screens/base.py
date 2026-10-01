"""Společný základ obrazovek: pohyb j/k/g/G/Ctrl+D/U přeposlaný na zaměřený widget."""

from __future__ import annotations

from typing import Any

from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import DataTable, OptionList, SelectionList, Tree

from repo_doctor.tui.bindings import bindings


def _call(widget: Widget | None, *names: str) -> bool:
    if widget is None:
        return False
    for name in names:
        fn = getattr(widget, name, None)
        if callable(fn):
            fn()
            return True
    return False


def _jump(widget: Widget | None, delta: int | None, *, to_end: bool = False) -> None:
    """Posun kurzoru o `delta` řádků, případně na začátek (delta=None) / konec."""
    if isinstance(widget, OptionList):  # včetně SelectionList
        count = widget.option_count
        if not count:
            return
        if delta is None:
            widget.action_last() if to_end else widget.action_first()
            return
        idx = (widget.highlighted or 0) + delta
        idx = max(0, min(count - 1, idx))
        step = 1 if delta > 0 else -1
        while 0 <= idx < count and widget.get_option_at_index(idx).disabled:
            idx += step
        if 0 <= idx < count:
            widget.highlighted = idx
    elif isinstance(widget, DataTable):
        if not widget.row_count:
            return
        row = (
            (widget.row_count - 1 if to_end else 0) if delta is None else widget.cursor_row + delta
        )
        widget.move_cursor(row=max(0, min(widget.row_count - 1, row)))
    elif isinstance(widget, Tree):
        if delta is None:
            widget.cursor_line = widget.last_line if to_end else 0
        else:
            widget.cursor_line = max(0, min(widget.last_line, widget.cursor_line + delta))
    elif widget is not None:
        if delta is None:
            _call(widget, "scroll_end" if to_end else "scroll_home")
        else:
            widget.scroll_relative(y=delta)


class NavMixin:
    focused: Widget | None

    def action_focus_next(self) -> None:
        self.focus_next()  # type: ignore[attr-defined]

    def action_focus_previous(self) -> None:
        self.focus_previous()  # type: ignore[attr-defined]

    def action_cursor_down(self) -> None:
        if not _call(self.focused, "action_cursor_down"):
            _call(self.focused, "action_scroll_down")

    def action_cursor_up(self) -> None:
        if not _call(self.focused, "action_cursor_up"):
            _call(self.focused, "action_scroll_up")

    def action_cursor_top(self) -> None:
        _jump(self.focused, None)

    def action_cursor_bottom(self) -> None:
        _jump(self.focused, None, to_end=True)

    def _half(self) -> int:
        widget = self.focused
        height = widget.size.height if widget is not None else 10
        return max(1, height // 2)

    def action_half_page_down(self) -> None:
        _jump(self.focused, self._half())

    def action_half_page_up(self) -> None:
        _jump(self.focused, -self._half())


class BaseScreen(NavMixin, Screen[Any]):
    """Obrazovka, kterou jde zavřít Esc (a globálně `q`)."""

    BINDINGS = [
        *bindings("nav"),
        Binding("escape", "close", "zpět", key_display="esc"),
    ]

    def action_close(self) -> None:
        self.app.pop_screen()


class BaseModal(NavMixin, ModalScreen[Any]):
    BINDINGS = [*bindings("nav"), Binding("escape", "cancel", "zrušit", key_display="esc")]

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["BaseModal", "BaseScreen", "NavMixin", "SelectionList"]
