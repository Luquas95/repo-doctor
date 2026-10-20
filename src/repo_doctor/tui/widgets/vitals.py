"""Hlavička „vitální funkce“: počty, zdraví, tep a průběh skenu."""

from __future__ import annotations

from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from repo_doctor.i18n import _
from repo_doctor.models import ScanResult, Severity
from repo_doctor.notify import RunState
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
    scheduled: RunState | None = None,
) -> Text:
    s = result.summary(no_pulse_days)
    t = Text()
    t.append(_("{repos} repozitářů").format(repos=s.repos), style=Style(color=p.text, bold=True))
    wide = width >= 96
    gap = "    " if wide else "  "
    t.append(gap)
    for sev in Severity:
        n = s.by_severity[sev]
        style = Style(color=p.severity(sev), bold=True) if n else Style(color=p.dim)
        t.append(f"{sev.symbol} {sev.short} {n}", style=style)
        t.append("   " if wide else "  ")
    t.append("  " if wide else "")
    t.append(_("zdraví "), style=Style(color=p.muted))
    blocks = 10 if width >= 90 else 5
    t.append(gauge(s.health, blocks), style=Style(color=p.score(s.health)))
    t.append(f" {s.health}", style=Style(color=p.score(s.health), bold=True))
    pulse_w = max(0, min(12, width - t.cell_len - 10))
    if pulse_w >= 6:
        t.append("    " if wide else "  ")
        t.append(_("tep "), style=Style(color=p.muted))
        t.append(sparkline(aggregate_pulse(result), pulse_w), style=Style(color=p.accent))
    t.append("\n")
    if scanning:
        bar_w = 20 if width >= 90 else 10
        filled = round(bar_w * done / total) if total else 0
        t.append(_("sken "), style=Style(color=p.muted))
        t.append("█" * filled, style=Style(color=p.accent))
        t.append("░" * (bar_w - filled), style=Style(color=p.dim))
        t.append(f" {done}/{total}", style=Style(color=p.text))
        if current:
            t.append("   › ", style=Style(color=p.muted))
            t.append(current, style=Style(color=p.text))
        t.append(_("   {v} zruší sken").format(v=keys[1]), style=Style(color=p.dim))
    else:
        when = result.finished_at
        if when is not None:
            local = when.astimezone()
            dur = (when - result.started_at).total_seconds()
            t.append(
                _("poslední sken {local:%-d. %-m. %H:%M}").format(local=local),
                style=Style(color=p.muted),
            )
            t.append(f" · {dur:.0f} s", style=Style(color=p.dim))
            t.append(" · ", style=Style(color=p.dim))
            t.append(keys[0], style=Style(color=p.accent, bold=True))
            t.append(_(" nový sken všech rep"), style=Style(color=p.muted))
        else:
            t.append(_("zatím bez skenu – "), style=Style(color=p.muted))
            t.append(keys[0], style=Style(color=p.accent, bold=True))
            t.append(_(" zkontroluje všechna repa"), style=Style(color=p.muted))
        if result.cancelled:
            t.append(_(" · přerušený"), style=Style(color=p.med))
        if result.warnings:
            t.append(
                _(" · ⚠ {len} upozornění").format(len=len(result.warnings)),
                style=Style(color=p.med),
            )
        if scheduled is not None:
            try:
                at = datetime.fromisoformat(scheduled.ts).astimezone()
                label = at.strftime(_("%-d. %-m. %H:%M"))
            except ValueError:
                label = "?"
            t.append(_(" · plánovaný {label}").format(label=label), style=Style(color=p.muted))
            t.append(
                _(" ⚠ změny") if scheduled.changes else _(" beze změn"),
                style=Style(color=p.med if scheduled.changes else p.dim),
            )
    t.truncate(width * 2, overflow="ellipsis")
    lines = t.split("\n")
    for line in lines:
        line.truncate(width, overflow="ellipsis")
    return Text("\n").join(lines)


class Vitals(Static):
    DEFAULT_CSS = """
    Vitals { height: 4; border: round $accent; padding: 0 1; border-title-color: $accent; }
    """
