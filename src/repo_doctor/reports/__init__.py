"""Reporty výsledků skenu: Markdown, JSON (verzované schéma) a samostatné HTML."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from repo_doctor.masking import redact
from repo_doctor.models import ScanResult

ReportFormat = Literal["md", "json", "html"]
FORMATS: tuple[ReportFormat, ...] = ("md", "json", "html")


def render(
    result: ScanResult, fmt: ReportFormat, *, no_pulse_days: int = 90, now: datetime | None = None
) -> str:
    from repo_doctor.reports import html, jsonreport, markdown

    if fmt == "md":
        text = markdown.render(result, no_pulse_days=no_pulse_days, now=now)
    elif fmt == "json":
        text = jsonreport.render(result, no_pulse_days=no_pulse_days, now=now)
    elif fmt == "html":
        text = html.render(result, no_pulse_days=no_pulse_days, now=now)
    else:  # pragma: no cover - chráněno typem
        raise ValueError(fmt)
    # Obrana do hloubky: i kdyby se tajemství někudy dostalo do textu, zaregistrované se zamaskuje.
    return redact(text)
