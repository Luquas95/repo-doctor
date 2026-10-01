"""JSON report se stabilním, verzovaným schématem (`schema_version`)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from repo_doctor import __version__
from repo_doctor.models import Finding, RepoResult, ScanResult, Severity
from repo_doctor.scoring import band

SCHEMA_VERSION = 1


class JLocation(BaseModel):
    path: str | None = None
    line: int | None = None
    commit: str | None = None
    commit_date: datetime | None = None


class JFinding(BaseModel):
    id: str = Field(description="ID kontroly, např. secrets-history")
    fingerprint: str = Field(description="Stabilní hash nálezu pro allowlist")
    severity: Severity
    category: str
    title: str
    message: str
    location: JLocation
    snippet: str | None = Field(default=None, description="Vždy maskovaná ukázka (AKIA…(20 znaků))")
    kind: str | None = None
    fixable: bool


class JState(BaseModel):
    branch: str | None
    detached: bool
    default_branch: str | None
    uncommitted: int
    unpushed: int
    last_commit: datetime | None
    pulse_30d: list[int]


class JRepo(BaseModel):
    name: str
    path: str
    root: str
    score: int
    band: str
    forge: str | None
    visibility: str
    archived: bool
    web_url: str | None
    remotes: list[dict[str, str | None]]
    state: JState
    counts: dict[str, int]
    findings: list[JFinding]
    allowlisted: int
    skipped: dict[str, str]
    errors: dict[str, str]


class JSummary(BaseModel):
    repos: int
    findings: dict[str, int]
    health: int
    no_pulse: int


class JReport(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool: dict[str, str]
    generated_at: datetime | None
    started_at: datetime
    offline: bool
    cancelled: bool
    roots: list[str]
    summary: JSummary
    repos: list[JRepo]
    warnings: list[str]


def _finding(f: Finding, repo: RepoResult) -> JFinding:
    return JFinding(
        id=f.check_id,
        fingerprint=f.fingerprint(repo.name),
        severity=f.severity,
        category=f.category.value,
        title=f.title,
        message=f.message,
        location=JLocation(**f.location.model_dump()),
        snippet=f.snippet,
        kind=f.kind,
        fixable=f.fixable,
    )


def build(result: ScanResult, *, no_pulse_days: int = 90, now: datetime | None = None) -> JReport:
    summary = result.summary(no_pulse_days, now)
    repos = []
    for r in result.repos:
        repos.append(
            JRepo(
                name=r.name,
                path=r.path,
                root=r.root,
                score=r.score,
                band=band(r, no_pulse_days, now).value,
                forge=r.forge,
                visibility=r.visibility,
                archived=r.archived,
                web_url=r.web_url,
                remotes=[{"name": rm.name, "url": rm.url, "forge": rm.forge} for rm in r.remotes],
                state=JState(
                    branch=r.state.branch,
                    detached=r.state.detached,
                    default_branch=r.state.default_branch,
                    uncommitted=r.state.uncommitted,
                    unpushed=r.state.unpushed,
                    last_commit=r.state.last_commit,
                    pulse_30d=r.state.pulse,
                ),
                counts={s.value: n for s, n in r.counts().items()},
                findings=[
                    _finding(f, r)
                    for f in sorted(r.findings, key=lambda f: (-f.severity.rank, f.check_id))
                ],
                allowlisted=r.allowlisted,
                skipped=r.skipped,
                errors=r.errors,
            )
        )
    return JReport(
        tool={"name": "repo-doctor", "version": result.tool_version or __version__},
        generated_at=result.finished_at,
        started_at=result.started_at,
        offline=result.offline,
        cancelled=result.cancelled,
        roots=result.roots,
        summary=JSummary(
            repos=summary.repos,
            findings={s.value: n for s, n in summary.by_severity.items()},
            health=summary.health,
            no_pulse=summary.no_pulse,
        ),
        repos=repos,
        warnings=result.warnings,
    )


def render(result: ScanResult, *, no_pulse_days: int = 90, now: datetime | None = None) -> str:
    return build(result, no_pulse_days=no_pulse_days, now=now).model_dump_json(indent=2) + "\n"


def json_schema() -> dict[str, Any]:
    schema = JReport.model_json_schema()
    schema["$id"] = f"https://github.com/Luquas95/repo-doctor/report-schema-v{SCHEMA_VERSION}.json"
    return schema


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover
    print(schema_text(), end="")
