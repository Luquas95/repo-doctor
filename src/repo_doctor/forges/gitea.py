"""Gitea a Forgejo – společná implementace nad kompatibilním API /api/v1."""

from __future__ import annotations

from urllib.parse import quote

from repo_doctor.config import ForgeConfig
from repo_doctor.forges.base import (
    CIStatus,
    ConnectionReport,
    Forge,
    ForgeRepo,
    PullRequest,
    parse_time,
)
from repo_doctor.httpclient import ForbiddenError, HttpClient, HttpError, NotFoundError


def api_base(url: str) -> str:
    return url.rstrip("/") + "/api/v1"


def auth_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"token {token}"} if token else {}


def _repo(d: dict[str, object]) -> ForgeRepo:
    return ForgeRepo(
        full_name=str(d.get("full_name", "")),
        default_branch=str(d["default_branch"]) if d.get("default_branch") else None,
        private=bool(d.get("private")) or bool(d.get("internal")),
        archived=bool(d.get("archived")),
        html_url=str(d.get("html_url") or ""),
        clone_ssh=str(d.get("ssh_url") or ""),
        clone_https=str(d.get("clone_url") or ""),
        pushed_at=parse_time(d.get("updated_at")),
        fork=bool(d.get("fork")),
        description=str(d.get("description") or ""),
        id=str(d.get("id") or ""),
    )


class GiteaForge(Forge):
    kind = "gitea"

    def __init__(
        self, config: ForgeConfig, client: HttpClient, *, authenticated: bool = True
    ) -> None:
        super().__init__(config, client)
        self.authenticated = authenticated
        self.kind = config.type  # "gitea" nebo "forgejo"

    async def list_repos(self) -> list[ForgeRepo]:
        if self.config.org:
            url = f"/orgs/{quote(self.config.org)}/repos"
        elif self.authenticated:
            url = "/user/repos"
        elif self.config.user:
            url = f"/users/{quote(self.config.user)}/repos"
        else:
            return []
        return [_repo(d) for d in await self.client.paginate(url, params={"limit": 50})]

    async def get_repo(self, owner_path: str) -> ForgeRepo:
        return _repo(await self.client.get_json(f"/repos/{owner_path}"))

    async def branch_head(self, repo: ForgeRepo, branch: str) -> tuple[str | None, bool | None]:
        data = await self.client.get_json(
            f"/repos/{repo.full_name}/branches/{quote(branch, safe='')}"
        )
        commit = data.get("commit") or {}
        protected = data.get("protected")
        return commit.get("id") or commit.get("sha"), bool(
            protected
        ) if protected is not None else None

    async def latest_ci_status(self, repo: ForgeRepo, branch: str, sha: str | None) -> CIStatus:
        """Gitea/Forgejo Actions hlásí výsledek jako commit status výchozí branche."""
        if not sha:
            return CIStatus("unknown", branch)
        try:
            data = await self.client.get_json(f"/repos/{repo.full_name}/commits/{sha}/status")
        except (NotFoundError, ForbiddenError):
            return CIStatus("unknown", branch)
        if not data.get("total_count") and not data.get("statuses"):
            return CIStatus("none", branch)
        state = str(data.get("state") or "")
        mapped = {
            "success": "success",
            "failure": "failure",
            "error": "failure",
            "pending": "pending",
            "warning": "success",
        }
        statuses = data.get("statuses") or [{}]
        url = str(statuses[0].get("target_url") or "")
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        number = tail if "/runs/" in url and tail.isdigit() else ""
        return CIStatus(mapped.get(state, "none"), branch, number, url)  # type: ignore[arg-type]

    async def open_prs(self, repo: ForgeRepo) -> list[PullRequest]:
        items = await self.client.paginate(
            f"/repos/{repo.full_name}/issues",
            params={"state": "open", "type": "all", "limit": 50},
            max_pages=3,
        )
        return [
            PullRequest(
                number=int(i.get("number", 0)),
                title=str(i.get("title", "")),
                updated_at=parse_time(i.get("updated_at")),
                kind="pr" if "pull_request" in i else "issue",
            )
            for i in items
        ]

    async def test_connection(self) -> ConnectionReport:
        warnings: list[str] = []
        try:
            if self.authenticated:
                user = await self.client.get_json("/user")
            elif self.config.user:
                user = await self.client.get_json(f"/users/{quote(self.config.user)}")
                warnings.append("bez tokenu: jen veřejná repa")
            else:
                return ConnectionReport(
                    False, error="bez tokenu je potřeba vyplnit uživatele nebo organizaci"
                )
            login = str(user.get("login") or user.get("username") or "")
            repos = await self.list_repos()
            try:
                version = await self.client.get_json("/version", ttl=0)
                detected = (
                    "forgejo" if "forgejo" in str(version.get("version", "")).lower() else None
                )
                if detected and self.config.type == "gitea":
                    warnings.append('instance je Forgejo – nastav type = "forgejo"')
            except HttpError:
                pass
        except HttpError as err:
            return ConnectionReport(False, error=str(err))
        if self.authenticated:
            warnings.append(
                "rozsah tokenu Gitea/Forgejo API neprozradí – ověř, že má jen read:repository, read:user "
                "(a read:issue pro PR)"
            )
        if not self.config.verify_tls and not self.config.ca_bundle:
            warnings.append(
                "ověřování TLS je vypnuté (verify_tls = false) – raději nastav ca_bundle"
            )
        return ConnectionReport(True, user=login, repo_count=len(repos), warnings=warnings)
