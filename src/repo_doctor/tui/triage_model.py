"""Čistá logika přehledu: filtry, řazení a seskupení (bez závislosti na Textualu)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from repo_doctor.models import Category, RepoResult, ScanResult, Severity
from repo_doctor.scoring import Band, band, is_no_pulse
from repo_doctor.tui.util import git_state

SORT_COLUMNS: tuple[str, ...] = ("score", "name", "high", "medium", "low", "git", "forge", "pulse")
SORT_LABELS = {
    "score": "skóre",
    "name": "název",
    "high": "▲",
    "medium": "◆",
    "low": "●",
    "git": "git",
    "forge": "hosting",
    "pulse": "tep",
}
GroupBy = Literal["triage", "root", "forge"]
GROUP_LABELS = {"triage": "triáž", "root": "složka", "forge": "hosting"}


@dataclass
class Filters:
    min_severity: Severity | None = None
    problems_only: bool = False
    category: Category | None = None
    root: str | None = None
    forge: str | None = None  # "-" = bez remote
    query: str = ""

    def active(self) -> bool:
        return bool(
            self.min_severity
            or self.problems_only
            or self.category
            or self.root
            or self.forge
            or self.query
        )


@dataclass
class Group:
    key: str
    label: str
    repos: list[RepoResult]
    note: str = ""
    band: Band | None = None


@dataclass
class TriageState:
    sort: str = "score"
    reverse: bool = False
    group_by: GroupBy = "triage"
    filters: Filters = field(default_factory=Filters)
    collapsed: set[str] = field(default_factory=lambda: {Band.HEALTHY.value})


def forge_key(repo: RepoResult) -> str:
    return repo.forge or "-"


def matches(repo: RepoResult, f: Filters) -> bool:
    if f.problems_only and not repo.findings:
        return False
    if f.min_severity and not any(x.severity.rank >= f.min_severity.rank for x in repo.findings):
        return False
    if f.category and not any(x.category is f.category for x in repo.findings):
        return False
    if f.root and repo.root != f.root:
        return False
    if f.forge and forge_key(repo) != f.forge:
        return False
    if f.query:
        q = f.query.lower()
        hay = (
            [repo.name, repo.path]
            + [x.check_id for x in repo.findings]
            + [x.message for x in repo.findings]
        )
        if not any(q in h.lower() for h in hay):
            return False
    return True


def sort_key(repo: RepoResult, column: str) -> tuple[object, ...]:
    c = repo.counts()
    keys: dict[str, object] = {
        "score": repo.score,
        "name": repo.name.lower(),
        "high": -c[Severity.HIGH],
        "medium": -c[Severity.MEDIUM],
        "low": -c[Severity.LOW],
        "git": git_state(repo),
        "forge": forge_key(repo),
        "pulse": -sum(repo.state.pulse),
    }
    return (keys[column], repo.score, repo.name.lower())


def build_groups(
    result: ScanResult, state: TriageState, *, no_pulse_days: int, now: datetime
) -> list[Group]:
    repos = [r for r in result.repos if matches(r, state.filters)]
    repos.sort(key=lambda r: sort_key(r, state.sort), reverse=state.reverse)
    groups: dict[str, Group] = {}
    if state.group_by == "triage":
        for b in Band:
            note = f"žádný commit {no_pulse_days}+ dní" if b is Band.NO_PULSE else ""
            groups[b.value] = Group(b.value, b.label, [], note, b)
        for r in repos:
            groups[band(r, no_pulse_days, now).value].repos.append(r)
        return [g for g in groups.values() if g.repos]
    for r in repos:
        key = r.root if state.group_by == "root" else forge_key(r)
        label = key if key != "-" else "bez remote"
        groups.setdefault(
            key, Group(key, label.upper() if state.group_by == "forge" else label, [])
        ).repos.append(r)
    return sorted(groups.values(), key=lambda g: g.label.lower())


def no_pulse_count(result: ScanResult, days: int, now: datetime) -> int:
    return sum(1 for r in result.repos if is_no_pulse(r, days, now))
