"""Převod registru zkratek (`repo_doctor.keymap`) na Textual Binding objekty."""

from __future__ import annotations

from textual.binding import Binding

from repo_doctor.keymap import ACTIONS


def bindings(*contexts: str, priority: bool = False) -> list[Binding]:
    out = []
    for a in ACTIONS:
        if a.context in contexts:
            out.append(
                Binding(
                    a.key,
                    a.action,
                    a.description,
                    show=a.show,
                    key_display=a.label or None,
                    id=a.id,
                    priority=priority,
                )
            )
    return out
