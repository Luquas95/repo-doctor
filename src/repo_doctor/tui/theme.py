"""Paleta „Triáž“ – tmavé téma podle zadání a světlé odvozené se stejným kontrastem (WCAG AA)."""

from __future__ import annotations

from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual.theme import Theme

from repo_doctor.models import Severity


@dataclass(frozen=True)
class Palette:
    background: str
    panel: str
    selection: str
    text: str
    muted: str
    dim: str  # potlačený (nuly)
    border: str
    accent: str
    high: str
    med: str
    low: str
    ok: str
    diff_add: str
    diff_del: str

    def severity(self, sev: Severity) -> str:
        return {Severity.HIGH: self.high, Severity.MEDIUM: self.med, Severity.LOW: self.low}[sev]

    def score(self, score: int) -> str:
        return self.high if score < 40 else self.med if score < 70 else self.ok


DARK = Palette(
    background="#12141a",
    panel="#171a21",
    selection="#223047",
    text="#c9ced8",
    muted="#6b7385",
    dim="#3a404d",
    border="#343a47",
    accent="#5fd3b0",
    high="#ff5f6d",
    med="#f5b642",
    low="#6fa8ff",
    ok="#7bd88f",
    diff_add="#16281f",
    diff_del="#2b1719",
)
# Světlé téma: barvy severit ztmavené tak, aby na pozadí #f5f6f8 měly kontrast ≥ 4.5:1.
LIGHT = Palette(
    background="#f5f6f8",
    panel="#ffffff",
    selection="#d9e4f5",
    text="#1d2330",
    muted="#566072",
    dim="#a3aab6",
    border="#c3c9d3",
    accent="#0b7a5f",
    high="#c01530",
    med="#8a5300",
    low="#1d5bb8",
    ok="#1b7532",
    diff_add="#dff3e5",
    diff_del="#fbe3e6",
)

DARK_NAME = "repo-doctor-dark"
LIGHT_NAME = "repo-doctor-light"


def _theme(name: str, p: Palette, dark: bool) -> Theme:
    return Theme(
        name=name,
        primary=p.accent,
        secondary=p.low,
        accent=p.accent,
        warning=p.med,
        error=p.high,
        success=p.ok,
        foreground=p.text,
        background=p.background,
        surface=p.panel,
        panel=p.panel,
        boost=p.selection,
        dark=dark,
        variables={
            "rd-muted": p.muted,
            "rd-dim": p.dim,
            "rd-border": p.border,
            "rd-selection": p.selection,
            "rd-high": p.high,
            "rd-med": p.med,
            "rd-low": p.low,
            "rd-ok": p.ok,
            "block-cursor-background": p.selection,
            "block-cursor-foreground": p.text,
            "block-cursor-text-style": "bold",
            "block-cursor-blurred-background": p.selection,
            "block-cursor-blurred-foreground": p.text,
            "block-hover-background": p.selection,
            "footer-background": p.background,
            "footer-key-foreground": p.background,
            "footer-key-background": p.accent,
            "footer-description-foreground": p.muted,
            "footer-item-background": p.background,
            "input-selection-background": p.selection,
            "scrollbar": p.border,
            "scrollbar-background": p.panel,
            "border": p.accent,
            "border-blurred": p.border,
        },
    )


THEMES = (_theme(DARK_NAME, DARK, True), _theme(LIGHT_NAME, LIGHT, False))


def palette_for(theme_name: str) -> Palette:
    return LIGHT if theme_name == LIGHT_NAME else DARK


def sev_text(p: Palette, sev: Severity, count: int | None = None, *, width: int = 2) -> Text:
    if count is None:
        return Text(f"{sev.symbol} {sev.short}", style=Style(color=p.severity(sev), bold=True))
    style = Style(color=p.severity(sev)) if count else Style(color=p.dim)
    return Text(f"{count:>{width}}", style=style)
