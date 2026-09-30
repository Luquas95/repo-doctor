"""Deterministická ukázková data skenu (podle wireframů) pro reporty a snapshoty TUI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_doctor.checks import get_check
from repo_doctor.models import (
    Finding,
    Location,
    RemoteInfo,
    RepoResult,
    RepoState,
    ScanResult,
    Severity,
)
from repo_doctor.scoring import score

NOW = datetime(2026, 9, 30, 14, 32, tzinfo=UTC)


def F(check_id: str, message: str, sev: Severity | None = None, **kw: object) -> Finding:
    check = get_check(check_id)
    assert check is not None
    loc = Location(
        path=kw.pop("path", None),
        line=kw.pop("line", None),
        commit=kw.pop("commit", None),
        commit_date=kw.pop("commit_date", None),
    )
    return Finding(
        check_id=check_id,
        severity=sev or check.severity,
        category=check.category,
        title=check.title,
        message=message,
        location=loc,
        fixable=bool(kw.pop("fixable", check.fixable)),
        key=message,
        **kw,
    )


def _pulse(pattern: str) -> list[int]:
    blocks = "▁▂▃▄▅▆▇█"
    vals = [blocks.index(c) for c in pattern]
    out: list[int] = []
    for v in vals:
        out.extend([v, max(0, v - 1)] if len(out) < 30 else [])
    return (out + [0] * 30)[:30]


def repo(
    name: str,
    root: str,
    findings: list[Finding],
    *,
    forge: str | None = "github",
    visibility: str = "private",
    pulse: str = "▃▅▆▇▅▆▇▇▅▆▇▆",
    last_days: int = 2,
    uncommitted: int = 0,
    unpushed: int = 0,
    detached: bool = False,
    archived: bool = False,
) -> RepoResult:
    remotes = (
        []
        if forge is None
        else [RemoteInfo(name="origin", url=f"git@{forge}.example:nekdo/{name}.git", forge=forge)]
    )
    r = RepoResult(
        path=f"/home/nekdo/{root}/{name}",
        name=name,
        root=f"~/{root}",
        remotes=remotes,
        forge=forge,
        visibility=visibility,
        web_url=f"https://{forge}.example/nekdo/{name}" if forge else None,
        archived=archived,
        state=RepoState(
            branch=None if detached else "main",
            detached=detached,
            head="a81f3c2d" * 5,
            default_branch="main",
            uncommitted=uncommitted,
            unpushed=unpushed,
            last_commit=NOW - timedelta(days=last_days),
            pulse=_pulse(pulse) if last_days < 30 else [0] * 30,
            commit_count=120,
        ),
        findings=findings,
    )
    r.score = score(findings)
    return r


def sample_result() -> ScanResult:
    H, M, L = Severity.HIGH, Severity.MEDIUM, Severity.LOW
    repos = [
        repo(
            "infra-notes",
            "projekty",
            [
                F(
                    "secrets-history",
                    "AWS access key v commitu a81f3c2 · config/prod.env",
                    path="config/prod.env",
                    line=4,
                    commit="a81f3c2d9e",
                    commit_date=datetime(2026, 3, 14, tzinfo=UTC),
                    snippet="AKIA…(20 znaků)",
                    kind="AWS access key",
                ),
                F(
                    "public-sensitive",
                    "veřejné repo obsahuje adresy 100.x (Tailscale) · hosts.yml",
                    path="hosts.yml",
                ),
                F(
                    "docker-hygiene",
                    "kontejner běží pod rootem (ve finální fázi chybí USER)",
                    path="Dockerfile",
                    fixable=False,
                ),
                F("forge-ci-failing", "poslední běh CI na main selhal (#142)"),
                F("forge-stale-prs", "2 otevřené PR bez aktivity 30+ dní"),
                F(
                    "gitignore-incomplete",
                    "chybí .env, .venv/",
                    path=".gitignore",
                    data={"missing": [".env", ".venv/"]},
                ),
                F("license-missing", "V kořeni repozitáře není LICENSE (ani COPYING)."),
                F(
                    "precommit-missing",
                    "Chybí .pre-commit-config.yaml (kontrola tajemství a formátu před commitem).",
                ),
                F("uncommitted", "3 změněných souborů", data={"count": 3}),
                F("unpushed", "branch main: 2 commitů oproti origin/main", data={"count": 2}),
            ],
            visibility="public",
            pulse="▁▂▁▅▇▃▁▁▂▅▃▁",
            uncommitted=3,
            unpushed=2,
        ),
        repo(
            "api-gateway",
            "projekty",
            [
                F(
                    "deps-vulnerable",
                    "jsonwebtoken 8.5.1 (npm): GHSA-8cf7-32gw-wr33",
                    H,
                    path="package-lock.json",
                ),
                F("forge-no-branch-protection", "výchozí branche main nemá ochranu"),
                F(
                    "docker-hygiene",
                    "FROM node:latest – tag :latest",
                    path="Dockerfile",
                    fixable=False,
                ),
                F(
                    "gitignore-incomplete",
                    "chybí .env",
                    path=".gitignore",
                    data={"missing": [".env"]},
                ),
                F("unpushed", "branch main: 5 commitů oproti origin/main", data={"count": 5}),
                F("stale-branches", "feature/old: bez commitu 120 dní"),
                F("stashes", "stash@{0} (45 dní): WIP"),
            ],
            forge="forgejo",
            pulse="▃▅▆▇▅▆▇▇▅▆▇▆",
            unpushed=5,
        ),
        repo(
            "scraper",
            "projekty",
            [
                F(
                    "secrets-tree",
                    "OpenAI API klíč v souboru scrape.py",
                    path="scrape.py",
                    line=12,
                    snippet="sk-p…(56 znaků)",
                ),
                F("large-files", "soubor 48.2 MB v aktuálním stromu", path="data/dump.sqlite"),
                F(
                    "deps-lockfile-missing",
                    "pyproject.toml deklaruje závislosti, ale chybí uv.lock",
                    path="pyproject.toml",
                ),
                F("readme-missing", "V kořeni repozitáře není README."),
                F("ci-missing", "Nenalezena konfigurace CI."),
                F("uncommitted", "12 změněných souborů", data={"count": 12}),
                F("deps-outdated", "3× minor: httpx 0.25.0→0.28.1", L),
            ],
            pulse="▁▁▂▁▃▅▂▁▁▁▂▃",
            uncommitted=12,
        ),
        repo(
            "cz-tools",
            "projekty",
            [
                F("gitignore-incomplete", "chybí __pycache__/", M, path=".gitignore"),
                F("forge-no-branch-protection", "výchozí branche main nemá ochranu"),
                F("large-files", "binárka 3.1 MB v aktuálním stromu", path="dist/tool.zip"),
                F("ci-missing", "Nenalezena konfigurace CI."),
                F("precommit-missing", "Chybí .pre-commit-config.yaml."),
            ],
            visibility="public",
            pulse="▂▃▂▅▃▂▁▂▃▅▆▅",
        ),
        repo(
            "dotfiles",
            "projekty",
            [
                F("public-sensitive", "privátní IP adresy · ssh/config", M, path="ssh/config"),
                F("unpushed", "branch main: 1 commitů oproti origin/main", data={"count": 1}),
                F("license-missing", "V kořeni není LICENSE."),
                F("ci-missing", "Nenalezena konfigurace CI."),
            ],
            pulse="▅▂▃▁▂▅▃▂▁▃▂▅",
            unpushed=1,
        ),
        repo(
            "blog",
            "git-archiv",
            [
                F("deps-outdated", "2× major: astro 2.0.0→5.1.0", M),
                F("gitignore-incomplete", "chybí node_modules/", M, path=".gitignore"),
                F("stale-branches", "draft: mergnutá do main"),
                F("precommit-missing", "Chybí .pre-commit-config.yaml."),
            ],
            forge="forgejo",
            pulse="▁▁▂▁▁▁▃▁▁▂▁▁",
        ),
        repo(
            "game-proto",
            "git-archiv",
            [
                F("large-files", "binárka 2.5 MB v aktuálním stromu", path="assets/music.mp3"),
                F("detached-head", "HEAD ukazuje přímo na commit 1b2c3d4, ne na branch."),
                F("readme-missing", "V kořeni repozitáře není README."),
            ],
            pulse="▇▆▅▃▂▁▁▁▁▁▁▁",
            detached=True,
        ),
        repo(
            "old-cli",
            "git-archiv",
            [
                F(
                    "no-remote",
                    "Repozitář nemá žádný remote – commity existují jen na tomto disku.",
                ),
                F("ci-missing", "Nenalezena konfigurace CI."),
                F("readme-missing", "V kořeni repozitáře není README."),
            ],
            forge=None,
            last_days=400,
        ),
        repo(
            "thesis-2019",
            "git-archiv",
            [
                F("ci-missing", "Nenalezena konfigurace CI."),
                F("precommit-missing", "Chybí .pre-commit-config.yaml."),
                F("license-missing", "V kořeni není LICENSE."),
            ],
            last_days=900,
            archived=True,
        ),
    ]
    for i, name in enumerate(["notes", "website", "homelab", "scripts", "kbd-layout"]):
        repos.append(
            repo(
                name,
                "projekty",
                [] if i % 2 else [F("stashes", "stash@{0} (40 dní): wip")],
                last_days=1 + i,
            )
        )
    return ScanResult(
        tool_version="0.1.0",
        started_at=NOW - timedelta(seconds=41),
        finished_at=NOW,
        offline=False,
        roots=["~/projekty", "~/git-archiv"],
        repos=repos,
        warnings=["Složka ~/sandbox neexistuje – přeskočena."],
    )
