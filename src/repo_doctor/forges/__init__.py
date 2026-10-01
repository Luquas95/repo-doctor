"""Git hostingy (GitHub, Gitea/Forgejo, GitLab). Rozhraní je výhradně čtecí."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from repo_doctor.config import Config, ForgeConfig
from repo_doctor.forges import gitea, github, gitlab
from repo_doctor.forges.base import ConnectionReport, Forge, ForgeRepo, ForgeSnapshot
from repo_doctor.forges.tokens import TokenError, resolve_token
from repo_doctor.httpclient import HttpClient, ResponseCache, build_verify

__all__ = [
    "ConnectionReport",
    "Forge",
    "ForgeManager",
    "ForgeRepo",
    "ForgeSnapshot",
    "build_forge",
]


def build_forge(
    config: ForgeConfig,
    *,
    token: str | None,
    cache: ResponseCache | None = None,
    ttl: float = 900,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Forge:
    verify = build_verify(config.verify_tls, config.ca_bundle)

    def client(base_url: str, headers: dict[str, str]) -> HttpClient:
        return HttpClient(
            base_url=base_url,
            headers=headers,
            namespace=f"forge:{config.name}",
            cache=cache,
            ttl=ttl,
            verify=verify,
            transport=transport,
        )

    if config.type == "github":
        return github.GitHubForge(
            config,
            client(github.api_base(config.url), github.auth_headers(token)),
            authenticated=bool(token),
        )
    if config.type in ("gitea", "forgejo"):
        return gitea.GiteaForge(
            config,
            client(gitea.api_base(config.base_url), gitea.auth_headers(token)),
            authenticated=bool(token),
        )
    return gitlab.GitLabForge(
        config,
        client(gitlab.api_base(config.url), gitlab.auth_headers(token)),
        authenticated=bool(token),
    )


@dataclass
class ForgeManager:
    """Připojené hostingy. Hosting, jehož token nejde získat, je `unavailable` (s důvodem)."""

    forges: dict[str, Forge] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        cache_dir: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> ForgeManager:
        mgr = cls()
        cache = ResponseCache(cache_dir) if cache_dir else ResponseCache()
        ttl = config.limits.http_cache_minutes * 60
        for fc in config.forges:
            if not fc.enabled:
                continue
            try:
                token = resolve_token(fc)
            except TokenError as err:
                mgr.unavailable[fc.name] = f"token: {err}"
                continue
            try:
                mgr.forges[fc.name] = build_forge(
                    fc,
                    token=token.reveal() if token else None,
                    cache=cache,
                    ttl=ttl,
                    transport=transport,
                )
            except OSError as err:  # např. neexistující ca_bundle
                mgr.unavailable[fc.name] = f"TLS: {err}"
        return mgr

    async def aclose(self) -> None:
        for forge in self.forges.values():
            await forge.client.aclose()
