"""GitHub (REST v3), včetně GitHub Enterprise přes vlastní URL."""

from __future__ import annotations

from urllib.parse import quote

from repo_doctor.config import ForgeConfig
from repo_doctor.forges.base import (
    CIState,
    CIStatus,
    ConnectionReport,
    Forge,
    ForgeRepo,
    PullRequest,
    parse_time,
)
from repo_doctor.httpclient import ForbiddenError, HttpClient, HttpError, NotFoundError

BROAD_SCOPES = {
    "repo",
    "public_repo",
    "admin:org",
    "write:org",
    "admin:repo_hook",
    "delete_repo",
    "workflow",
    "write:packages",
    "delete:packages",
    "admin:public_key",
    "admin:gpg_key",
    "user",
    "admin:enterprise",
}


def api_base(url: str | None) -> str:
    if not url or url.rstrip("/") in ("https://api.github.com", "https://github.com"):
        return "https://api.github.com"
    url = url.rstrip("/")
    return url if url.endswith("/api/v3") else url + "/api/v3"


def auth_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _repo(d: dict[str, object]) -> ForgeRepo:
    return ForgeRepo(
        full_name=str(d.get("full_name", "")),
        default_branch=str(d["default_branch"]) if d.get("default_branch") else None,
        private=bool(d.get("private")),
        archived=bool(d.get("archived")),
        html_url=str(d.get("html_url") or ""),
        clone_ssh=str(d.get("ssh_url") or ""),
        clone_https=str(d.get("clone_url") or ""),
        pushed_at=parse_time(d.get("pushed_at")),
        fork=bool(d.get("fork")),
        description=str(d.get("description") or ""),
        id=str(d.get("id") or ""),
    )


class GitHubForge(Forge):
    kind = "github"

    def __init__(
        self, config: ForgeConfig, client: HttpClient, *, authenticated: bool = True
    ) -> None:
        super().__init__(config, client)
        self.authenticated = authenticated

    async def list_repos(self) -> list[ForgeRepo]:
        params: dict[str, str | int]
        if self.config.org:
            url, params = f"/orgs/{quote(self.config.org)}/repos", {"per_page": 100, "type": "all"}
        elif self.authenticated:
            url, params = (
                "/user/repos",
                {"per_page": 100, "affiliation": "owner,collaborator,organization_member"},
            )
        elif self.config.user:
            url, params = f"/users/{quote(self.config.user)}/repos", {"per_page": 100}
        else:
            return []
        return [_repo(d) for d in await self.client.paginate(url, params=params)]

    async def get_repo(self, owner_path: str) -> ForgeRepo:
        return _repo(await self.client.get_json(f"/repos/{owner_path}"))

    async def branch_head(self, repo: ForgeRepo, branch: str) -> tuple[str | None, bool | None]:
        data = await self.client.get_json(
            f"/repos/{repo.full_name}/branches/{quote(branch, safe='')}"
        )
        sha = (data.get("commit") or {}).get("sha")
        protected = data.get("protected")
        return sha, bool(protected) if protected is not None else None

    async def latest_ci_status(self, repo: ForgeRepo, branch: str, sha: str | None) -> CIStatus:
        try:
            data = await self.client.get_json(
                f"/repos/{repo.full_name}/actions/runs", params={"branch": branch, "per_page": 1}
            )
        except (NotFoundError, ForbiddenError):
            return CIStatus("unknown", branch)
        runs = data.get("workflow_runs") or []
        if not runs:
            return CIStatus("none", branch)
        run = runs[0]
        conclusion = run.get("conclusion")
        if run.get("status") != "completed":
            state: CIState = "pending"
        elif conclusion in ("failure", "timed_out", "startup_failure"):
            state = "failure"
        elif conclusion == "success":
            state = "success"
        else:
            state = "none"
        return CIStatus(
            state, branch, str(run.get("run_number") or ""), str(run.get("html_url") or "")
        )

    async def security_alerts(self, repo: ForgeRepo) -> dict[str, int] | None:
        result: dict[str, int] = {}
        for kind, path in (
            ("dependabot", "dependabot/alerts"),
            ("secret_scanning", "secret-scanning/alerts"),
        ):
            try:
                items = await self.client.paginate(
                    f"/repos/{repo.full_name}/{path}",
                    params={"state": "open", "per_page": 100},
                    max_pages=5,
                )
            except (NotFoundError, ForbiddenError):
                continue
            result[kind] = len(items)
        return result or None

    async def open_prs(self, repo: ForgeRepo) -> list[PullRequest]:
        items = await self.client.paginate(
            f"/repos/{repo.full_name}/issues",
            params={"state": "open", "per_page": 100},
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
                login = str(user.get("login", ""))
                scopes_header = self.client.last_headers.get("x-oauth-scopes")
            else:
                if not self.config.user and not self.config.org:
                    return ConnectionReport(
                        False, error="bez tokenu je potřeba vyplnit uživatele nebo organizaci"
                    )
                target = (
                    f"/orgs/{quote(self.config.org)}"
                    if self.config.org
                    else f"/users/{quote(self.config.user or '')}"
                )
                user = await self.client.get_json(target)
                login = str(user.get("login", ""))
                scopes_header = None
                warnings.append("bez tokenu: jen veřejná data a limit 60 dotazů za hodinu")
            repos = await self.list_repos()
        except HttpError as err:
            return ConnectionReport(False, error=str(err))
        scopes = [s.strip() for s in (scopes_header or "").split(",") if s.strip()]
        broad = sorted(set(scopes) & BROAD_SCOPES)
        if broad:
            warnings.append(
                "token má zbytečně široká práva ("
                + ", ".join(broad)
                + "); repo-doctor jen čte – stačí "
                "fine-grained token s Metadata, Contents, Actions a Dependabot alerts: read-only"
            )
        return ConnectionReport(
            True, user=login, repo_count=len(repos), scopes=scopes, warnings=warnings
        )

    async def public_visibility(self, owner_path: str) -> str:
        """Neautentizovaný dotaz: 200 → veřejné; 404 → privátní nebo neexistuje (neznámo)."""
        try:
            data = await self.client.get_json(f"/repos/{owner_path}")
        except HttpError:
            return "unknown"
        return "private" if data.get("private") else "public"
