"""Skóre repozitáře (0–100) a triážní pásma."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from repo_doctor.models import Finding, RepoResult, Severity

PENALTY = {Severity.HIGH: 25, Severity.MEDIUM: 9, Severity.LOW: 3}
# Každá kontrola může skóre srazit nejvýš o tolik (deset LOW nálezů jedné kontroly ≠ katastrofa).
PER_CHECK_CAP = {Severity.HIGH: 50, Severity.MEDIUM: 18, Severity.LOW: 6}


def score(findings: Iterable[Finding]) -> int:
    per_check: dict[tuple[str, Severity], int] = {}
    for f in findings:
        key = (f.check_id, f.severity)
        per_check[key] = min(PER_CHECK_CAP[f.severity], per_check.get(key, 0) + PENALTY[f.severity])
    return max(0, 100 - sum(per_check.values()))


class Band(StrEnum):
    CRITICAL = "critical"
    WATCH = "watch"
    NO_PULSE = "no_pulse"
    HEALTHY = "healthy"
    UNCHECKED = "unchecked"

    @property
    def label(self) -> str:
        return {
            "critical": "KRITICKÉ",
            "watch": "SLEDOVAT",
            "no_pulse": "BEZ TEPU",
            "healthy": "ZDRAVÉ",
            "unchecked": "NELZE ZKONTROLOVAT",
        }[self.value]

    @property
    def order(self) -> int:
        return list(Band).index(self)


def is_no_pulse(repo: RepoResult, days: int = 90, now: datetime | None = None) -> bool:
    last = repo.state.last_commit
    if last is None:
        return repo.state.commit_count == 0 and repo.state.head is None
    now = now or datetime.now(UTC)
    return now - last > timedelta(days=days)


def band(repo: RepoResult, no_pulse_days: int = 90, now: datetime | None = None) -> Band:
    """Priorita: KRITICKÉ > SLEDOVAT > BEZ TEPU > ZDRAVÉ; repo bez skóre je zvlášť."""
    if repo.score is None:
        return Band.UNCHECKED
    if repo.score < 40 or any(f.severity is Severity.HIGH for f in repo.findings):
        return Band.CRITICAL
    if repo.score < 70:
        return Band.WATCH
    if is_no_pulse(repo, no_pulse_days, now):
        return Band.NO_PULSE
    return Band.HEALTHY


SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int], width: int | None = None) -> str:
    """Sparkline z hodnot; při `width` se hodnoty sečtou do `width` košů."""
    if width is not None and values and len(values) != width:
        buckets = [0] * width
        for i, v in enumerate(values):
            buckets[min(width - 1, i * width // len(values))] += v
        values = buckets
    if not values:
        return ""
    top = max(values)
    if top <= 0:
        return SPARK[0] * len(values)
    return "".join(SPARK[min(7, round(v / top * 7))] if v else SPARK[0] for v in values)


def sort_score(score_value: int | None) -> int:
    """Řazení vzestupně podle skóre; repo bez skóre až na konec."""
    return 101 if score_value is None else score_value


def score_label(score_value: int | None) -> str:
    """Skóre k zobrazení; repo, které nešlo zkontrolovat, má „–“."""
    return "–" if score_value is None else str(score_value)


def gauge(score_value: int | None, blocks: int = 5) -> str:
    if score_value is None:
        return "·" * blocks
    filled = max(0, min(blocks, round(score_value / 100 * blocks)))
    if score_value > 0 and filled == 0:
        filled = 1
    return "█" * filled + "░" * (blocks - filled)
