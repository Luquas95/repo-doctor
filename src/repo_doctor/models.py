"""Datové modely jádra (pydantic v2). Nezávislé na UI."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 3, "medium": 2, "low": 1}[self.value]

    @property
    def symbol(self) -> str:
        return {"high": "▲", "medium": "◆", "low": "●"}[self.value]

    @property
    def short(self) -> str:
        return {"high": "HIGH", "medium": "MED", "low": "LOW"}[self.value]

    @classmethod
    def parse(cls, value: str) -> Severity:
        aliases = {"med": "medium", "hi": "high", "lo": "low"}
        return cls(aliases.get(value.lower(), value.lower()))


class Category(StrEnum):
    SECURITY = "security"
    MAINTENANCE = "maintenance"
    GIT = "git"
    FORGE = "forge"

    @property
    def label(self) -> str:
        return {
            "security": "Bezpečnost",
            "maintenance": "Údržba",
            "git": "Stav gitu",
            "forge": "Hosting",
        }[self.value]


class Location(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str | None = None
    line: int | None = None
    commit: str | None = None
    commit_date: datetime | None = None

    def render(self) -> str:
        parts: list[str] = []
        if self.path:
            parts.append(f"{self.path}:{self.line}" if self.line else self.path)
        if self.commit:
            parts.append(f"commit {self.commit[:7]}")
        if self.commit_date:
            parts.append(self.commit_date.strftime("%-d. %-m. %Y"))
        return " · ".join(parts)


class Finding(BaseModel):
    """Jeden nález. `snippet` je vždy už maskovaný – surové tajemství model nikdy nenese."""

    model_config = ConfigDict(frozen=True)

    check_id: str
    severity: Severity
    category: Category
    title: str
    message: str
    location: Location = Field(default_factory=Location)
    snippet: str | None = None
    kind: str | None = None
    fixable: bool = False
    key: str = ""
    data: dict[str, str | int | list[str]] = Field(default_factory=dict)

    def fingerprint(self, repo_name: str) -> str:
        """Stabilní hash nálezu pro allowlist (nezávislý na čísle řádku)."""
        raw = "\0".join(
            [self.check_id, repo_name, self.location.path or "", self.key or self.message]
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class RemoteInfo(BaseModel):
    name: str
    url: str  # redigovaná (bez přihlašovacích údajů)
    host: str | None = None
    owner_path: str | None = None
    forge: str | None = None  # název připojeného hostingu


class RepoState(BaseModel):
    branch: str | None = None
    detached: bool = False
    head: str | None = None
    default_branch: str | None = None
    uncommitted: int = 0
    unpushed: int = 0
    last_commit: datetime | None = None
    pulse: list[int] = Field(default_factory=list)  # commity za den, nejstarší první
    commit_count: int = 0


Visibility = Literal["public", "private", "unknown"]


class RepoResult(BaseModel):
    path: str
    name: str
    root: str
    remotes: list[RemoteInfo] = Field(default_factory=list)
    forge: str | None = None
    visibility: Visibility = "unknown"
    web_url: str | None = None
    archived: bool = False
    state: RepoState = Field(default_factory=RepoState)
    findings: list[Finding] = Field(default_factory=list)
    allowlisted: int = 0
    skipped: dict[str, str] = Field(default_factory=dict)  # check_id → důvod
    errors: dict[str, str] = Field(default_factory=dict)
    forge_info: dict[str, str | int | bool | None] = Field(default_factory=dict)
    score: int = 100
    duration_ms: int = 0

    def counts(self) -> dict[Severity, int]:
        result = dict.fromkeys(Severity, 0)
        for f in self.findings:
            result[f.severity] += 1
        return result

    @property
    def worst(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)


class ScanSummary(BaseModel):
    repos: int = 0
    by_severity: dict[Severity, int] = Field(default_factory=lambda: dict.fromkeys(Severity, 0))
    health: int = 100
    no_pulse: int = 0


class ScanResult(BaseModel):
    schema_version: int = 1
    tool_version: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    offline: bool = False
    roots: list[str] = Field(default_factory=list)
    repos: list[RepoResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cancelled: bool = False

    def summary(self, no_pulse_days: int = 90, now: datetime | None = None) -> ScanSummary:
        from repo_doctor.scoring import is_no_pulse

        by: dict[Severity, int] = dict.fromkeys(Severity, 0)
        for repo in self.repos:
            for sev, n in repo.counts().items():
                by[sev] += n
        health = round(sum(r.score for r in self.repos) / len(self.repos)) if self.repos else 100
        no_pulse = sum(1 for r in self.repos if is_no_pulse(r, no_pulse_days, now))
        return ScanSummary(repos=len(self.repos), by_severity=by, health=health, no_pulse=no_pulse)


class FileChange(BaseModel):
    path: str
    old: str | None = None  # None = soubor neexistoval
    new: str | None = None  # None = odstranit z indexu (soubor na disku zůstává)


class Patch(BaseModel):
    """Navržená oprava. Vygenerování patche nic nemění, aplikace je samostatný krok."""

    check_id: str
    title: str
    summary: str
    changes: list[FileChange]
    commit_message: str
    notes: list[str] = Field(default_factory=list)

    def diff(self) -> str:
        from repo_doctor.fixes import render_diff

        result: str = render_diff(self)
        return result
