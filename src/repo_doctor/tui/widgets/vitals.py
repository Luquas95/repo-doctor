"""Hlavička „vitální funkce“: počty, zdraví, tep a průběh skenu."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from repo_doctor.models import ScanResult, Severity
from repo_doctor.scanner import aggregate_pulse
from repo_doctor.scoring import gauge, sparkline
from repo_doctor.tui.theme import Palette


def vitals_text(
    result: ScanResult,
    p: Palette,
    width: int,
    *,
    no_pulse_days: int,
    scanning: bool,
    done: int,
    total: int,
    current: str,
    keys: tuple[str, str] = ("R", "x"),
) -> Text:
    s = result.summary(no_pulse_days)
    t = Text()
    t.append(f"{s.repos} repozitářů", style=Style(color=p.text, bold=True))
    wide = width >= 96
    gap = "    " if wide else "  "
    t.append(gap)
    for sev in Severity:
        n = s.by_severity[sev]
        style = Style(color=p.severity(sev), bold=True) if n else Style(color=p.dim)
        t.append(f"{sev.symbol} {sev.short} {n}", style=style)
        t.append("   " if wide else "  ")
    t.append("  " if wide else "")
    t.append("zdraví ", style=Style(color=p.muted))
    blocks = 10 if width >= 90 else 5
    t.append(gauge(s.health, blocks), style=Style(color=p.score(s.health)))
    t.append(f" {s.health}", style=Style(color=p.score(s.health), bold=True))
    pulse_w = max(0, min(12, width - t.cell_len - 10))
    if pulse_w >= 6:
        t.append("    " if wide else "  ")
        t.append("tep ", style=Style(color=p.muted))
        t.append(sparkline(aggregate_pulse(result), pulse_w), style=Style(color=p.accent))
    t.append("\n")
    if scanning:
        bar_w = 20 if width >= 90 else 10
        filled = round(bar_w * done / total) if total else 0
        t.append("sken ", style=Style(color=p.muted))
        t.append("█" * filled, style=Style(color=p.accent))
        t.append("░" * (bar_w - filled), style=Style(color=p.dim))
        t.append(f" {done}/{total}", style=Style(color=p.text))
        if current:
            t.append("   › ", style=Style(color=p.muted))
            t.append(current, style=Style(color=p.text))
        t.append(f"   {keys[1]} zruší", style=Style(color=p.dim))
    else:
        when = result.finished_at
        if when is not None:
            local = when.astimezone()
            dur = (when - result.started_at).total_seconds()
            t.append(f"poslední sken {local:%-d. %-m. %H:%M}", style=Style(color=p.muted))
            t.append(f" · {dur:.0f} s", style=Style(color=p.dim))
        else:
            t.append(f"zatím bez skenu – {keys[0]} spustí sken", style=Style(color=p.muted))
        if result.cancelled:
            t.append(" · přerušený", style=Style(color=p.med))
        if result.warnings:
            t.append(f" · ⚠ {len(result.warnings)} upozornění", style=Style(color=p.med))
    t.truncate(width * 2, overflow="ellipsis")
    lines = t.split("\n")
    for line in lines:
        line.truncate(width, overflow="ellipsis")
    return Text("\n").join(lines)


class Vitals(Static):
    DEFAULT_CSS = """
    Vitals { height: 4; border: round $accent; padding: 0 1; border-title-color: $accent; }
    """
