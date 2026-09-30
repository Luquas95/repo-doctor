"""Společné rozhraní git hostingů. Všechny operace jsou jen čtecí."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from repo_doctor.config import ForgeConfig
from repo_doctor.httpclient import ForbiddenError, HttpClient, HttpError, NotFoundError

CIState = Literal["success", "failure", "pending", "none", "unknown"]


@dataclass
class ForgeRepo:
    full_name: str  # owner/repo (u GitLabu i s podskupinami)
    default_branch: str | None
    private: bool
    archived: bool = False
    html_url: str = ""
    clone_ssh: str = ""
    clone_https: str = ""
    pushed_at: datetime | None = None
    fork: bool = False
    description: str = ""
    id: str = ""  # interní ID (GitLab)

    @property
    def name(self) -> str:
        return self.full_name.rsplit("/", 1)[-1]

    @property
    def visibility(self) -> Literal["public", "private"]:
        return "private" if self.private else "public"


@dataclass
class CIStatus:
    state: CIState
    ref: str = ""
    number: str = ""
    url: str = ""


@dataclass
class PullRequest:
    number: int
    title: str
    updated_at: datetime | None
    kind: Literal["pr", "issue"] = "pr"


@dataclass
class ConnectionReport:
    ok: bool
    user: str | None = None
    repo_count: int | None = None
    scopes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ForgeSnapshot:
    """Data z hostingu o jednom repozitáři (předem načtená, kontroly už síť nevolají)."""

    forge: str
    kind: str
    owner_path: str
    repo: ForgeRepo | None = None
    missing_reason: str | None = None
    default_branch_sha: str | None = None
    ci: CIStatus | None = None
    protected: bool | None = None
    alerts: dict[str, int] | None = None
    open_items: list[PullRequest] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Forge(abc.ABC):
    """Základ implementace hostingu. `client` má nastavenou base URL API a autorizaci."""

    kind: str = ""

    def __init__(self, config: ForgeConfig, client: HttpClient) -> None:
        self.config = config
        self.client = client

    @property
    def name(self) -> str:
        return self.config.name

    @abc.abstractmethod
    async def list_repos(self) -> list[ForgeRepo]: ...

    @abc.abstractmethod
    async def get_repo(self, owner_path: str) -> ForgeRepo: ...

    async def default_branch(self, owner_path: str) -> str | None:
        return (await self.get_repo(owner_path)).default_branch

    @abc.abstractmethod
    async def branch_head(self, repo: ForgeRepo, branch: str) -> tuple[str | None, bool | None]:
        """(SHA posledního commitu, je chráněná?)"""

    @abc.abstractmethod
    async def latest_ci_status(self, repo: ForgeRepo, branch: str, sha: str | None) -> CIStatus: ...

    async def branch_protection(self, repo: ForgeRepo, branch: str) -> bool | None:
        return (await self.branch_head(repo, branch))[1]

    async def security_alerts(self, repo: ForgeRepo) -> dict[str, int] | None:
        return None  # hosting je neumí zjistit

    @abc.abstractmethod
    async def open_prs(self, repo: ForgeRepo) -> list[PullRequest]: ...

    @abc.abstractmethod
    async def test_connection(self) -> ConnectionReport: ...

    async def snapshot(self, owner_path: str) -> ForgeSnapshot:
        """Načte vše potřebné pro kontroly hostingu. Chyby jednotlivých částí jen zaznamená."""
        snap = ForgeSnapshot(forge=self.name, kind=self.kind, owner_path=owner_path)
        try:
            snap.repo = await self.get_repo(owner_path)
        except NotFoundError:
            snap.missing_reason = "hosting repo nezná (smazané, přejmenované nebo bez přístupu)"
            return snap
        except ForbiddenError:
            snap.missing_reason = "k repu nemá token přístup"
            return snap
        repo = snap.repo
        branch = repo.default_branch
        if branch:
            try:
                snap.default_branch_sha, snap.protected = await self.branch_head(repo, branch)
            except HttpError as err:
                snap.errors.append(f"branch: {err}")
            try:
                snap.ci = await self.latest_ci_status(repo, branch, snap.default_branch_sha)
            except HttpError as err:
                snap.errors.append(f"CI: {err}")
        try:
            snap.alerts = await self.security_alerts(repo)
        except HttpError as err:
            snap.errors.append(f"alerty: {err}")
        try:
            snap.open_items = await self.open_prs(repo)
        except HttpError as err:
            snap.errors.append(f"PR: {err}")
        return snap


def is_stale(item: PullRequest, days: int, now: datetime) -> bool:
    return item.updated_at is not None and now - item.updated_at > timedelta(days=days)
