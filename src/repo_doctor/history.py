"""Poslední sken (cache) a historie skenů pro panel „Od včerejška“."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from repo_doctor import paths
from repo_doctor.models import ScanResult, Severity


class HistoryEntry(BaseModel):
    ts: datetime
    repos: int
    by_severity: dict[Severity, int]
    health: int
    no_pulse: int
    scores: dict[str, int] = Field(default_factory=dict)


def save_last_scan(result: ScanResult, file: Path | None = None) -> Path:
    file = file or paths.last_scan_file()
    paths.ensure_private_dir(file.parent)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(result.model_dump_json(), "utf-8")
    tmp.replace(file)
    return file


def load_last_scan(file: Path | None = None) -> ScanResult | None:
    file = file or paths.last_scan_file()
    try:
        return ScanResult.model_validate_json(file.read_text("utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def record(
    result: ScanResult, *, keep: int = 30, no_pulse_days: int = 90, directory: Path | None = None
) -> HistoryEntry:
    directory = directory or paths.history_dir()
    paths.ensure_private_dir(directory)
    summary = result.summary(no_pulse_days)
    ts = result.finished_at or result.started_at
    entry = HistoryEntry(
        ts=ts,
        repos=summary.repos,
        by_severity=summary.by_severity,
        health=summary.health,
        no_pulse=summary.no_pulse,
        scores={r.path: r.score for r in result.repos},
    )
    (directory / f"scan-{ts:%Y%m%dT%H%M%S%f}.json").write_text(entry.model_dump_json(), "utf-8")
    files = sorted(directory.glob("scan-*.json"))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)
    return entry


def entries(directory: Path | None = None) -> list[HistoryEntry]:
    directory = directory or paths.history_dir()
    result = []
    for f in sorted(directory.glob("scan-*.json")):
        try:
            result.append(HistoryEntry.model_validate(json.loads(f.read_text("utf-8"))))
        except (OSError, ValueError, ValidationError):
            continue
    return result


def delta(current: HistoryEntry, previous: HistoryEntry | None) -> dict[str, int]:
    """Změna oproti předchozímu skenu: {'high': +2, 'low': -5, 'no_pulse': +1}."""
    if previous is None:
        return {}
    out: dict[str, int] = {}
    for sev in Severity:
        diff = current.by_severity.get(sev, 0) - previous.by_severity.get(sev, 0)
        if diff:
            out[sev.value] = diff
    if current.no_pulse != previous.no_pulse:
        out["no_pulse"] = current.no_pulse - previous.no_pulse
    return out


def previous_delta(directory: Path | None = None) -> dict[str, int]:
    items = entries(directory)
    if len(items) < 2:
        return {}
    return delta(items[-1], items[-2])
