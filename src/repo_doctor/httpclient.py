"""Asynchronní HTTP klient: omezený souběh, cache s TTL a ETagem, stránkování, rate-limit.

Nikdy neloguje ani necachuje hlavičky (tedy ani tokeny). Chyby nesou jen URL bez query.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

from repo_doctor import __version__
from repo_doctor.masking import redact

log = logging.getLogger(__name__)

USER_AGENT = f"repo-doctor/{__version__} (+https://github.com/Luquas95/repo-doctor)"


class HttpError(Exception):
    def __init__(self, message: str, *, status: int | None = None, url: str = "") -> None:
        self.status = status
        self.url = url.split("?", 1)[0]
        super().__init__(redact(message))


class AuthError(HttpError):
    """401 – neplatný nebo expirovaný token."""


class ForbiddenError(HttpError):
    """403 – token nemá oprávnění."""


class NotFoundError(HttpError):
    """404."""


class RateLimitError(HttpError):
    """Vyčerpaný rate-limit a čekání by trvalo příliš dlouho."""


class UnavailableError(HttpError):
    """Instance nedostupná (síť, TLS, timeout, 5xx)."""


@dataclass
class CachedResponse:
    status: int
    body: Any
    etag: str | None
    ts: float
    link_next: str | None = None


class ResponseCache:
    """Cache odpovědí v paměti a volitelně na disku (JSON soubory, práva 0600)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self._mem: dict[str, CachedResponse] = {}

    @staticmethod
    def key(namespace: str, method: str, url: str, body: bytes | None = None) -> str:
        h = hashlib.sha256()
        for part in (namespace, method, url):
            h.update(part.encode())
            h.update(b"\0")
        if body:
            h.update(body)
        return h.hexdigest()

    def get(self, key: str) -> CachedResponse | None:
        if key in self._mem:
            return self._mem[key]
        if self.directory is None:
            return None
        file = self.directory / f"{key}.json"
        try:
            data = json.loads(file.read_text("utf-8"))
            entry = CachedResponse(**data)
        except (OSError, ValueError, TypeError):
            return None
        self._mem[key] = entry
        return entry

    def set(self, key: str, entry: CachedResponse) -> None:
        self._mem[key] = entry
        if self.directory is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            file = self.directory / f"{key}.json"
            tmp = file.with_suffix(".tmp")
            tmp.write_text(json.dumps(entry.__dict__), "utf-8")
            tmp.chmod(0o600)
            tmp.replace(file)
        except OSError as err:  # pragma: no cover - cache je jen optimalizace
            log.debug("cache nelze zapsat: %s", err)


def _parse_link_next(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        section = part.split(";")
        if len(section) < 2:
            continue
        url = section[0].strip().strip("<>")
        if any(s.strip() in ('rel="next"', "rel=next") for s in section[1:]):
            return url
    return None


def build_verify(verify_tls: bool, ca_bundle: str | None) -> bool | ssl.SSLContext:
    if ca_bundle:
        from repo_doctor.paths import expand_path

        return ssl.create_default_context(cafile=str(expand_path(ca_bundle)))
    return verify_tls


class HttpClient:
    def __init__(
        self,
        *,
        base_url: str = "",
        headers: Mapping[str, str] | None = None,
        namespace: str = "public",
        cache: ResponseCache | None = None,
        ttl: float = 900,
        timeout: float = 15.0,
        max_concurrency: int = 8,
        verify: bool | ssl.SSLContext = True,
        max_rate_wait: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.namespace = namespace
        self.cache = cache or ResponseCache()
        self.ttl = ttl
        self.max_rate_wait = max_rate_wait
        self._sleep = sleep
        self._sem = asyncio.Semaphore(max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})},
            timeout=timeout,
            verify=verify,
            follow_redirects=True,
            transport=transport,
        )
        self.last_headers: httpx.Headers = httpx.Headers()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _url(self, url: str) -> str:
        return str(self._client.build_request("GET", url).url)

    async def _send(
        self, method: str, url: str, *, headers: dict[str, str], content: bytes | None
    ) -> httpx.Response:
        attempts = 0
        while True:
            attempts += 1
            try:
                async with self._sem:
                    resp = await self._client.request(method, url, headers=headers, content=content)
            except httpx.TimeoutException as err:
                raise UnavailableError(
                    f"časový limit při dotazu na {url.split('?')[0]}", url=url
                ) from err
            except httpx.HTTPError as err:
                raise UnavailableError(
                    f"nedostupné: {type(err).__name__} ({url.split('?')[0]})", url=url
                ) from err
            wait = self._rate_limit_wait(resp)
            if wait is None:
                return resp
            if wait > self.max_rate_wait or attempts > 2:
                raise RateLimitError(
                    f"vyčerpaný rate-limit (další pokus za {wait:.0f} s)",
                    status=resp.status_code,
                    url=url,
                )
            await self._sleep(wait)

    @staticmethod
    def _rate_limit_wait(resp: httpx.Response) -> float | None:
        remaining = resp.headers.get("x-ratelimit-remaining") or resp.headers.get(
            "ratelimit-remaining"
        )
        limited = resp.status_code == 429 or (resp.status_code == 403 and remaining == "0")
        if not limited:
            return None
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (TypeError, ValueError):
                    return 60.0
        reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("ratelimit-reset")
        if reset and reset.isdigit():
            value = int(reset)
            return max(0.0, value - time.time()) if value > 1_000_000_000 else float(value)
        return 60.0

    @staticmethod
    def _raise_for(resp: httpx.Response, url: str) -> None:
        status = resp.status_code
        if status < 400:
            return
        short = url.split("?")[0]
        if status == 401:
            raise AuthError("neplatný nebo expirovaný token (401)", status=status, url=url)
        if status == 403:
            raise ForbiddenError(f"přístup odepřen (403) – {short}", status=status, url=url)
        if status == 404:
            raise NotFoundError(f"nenalezeno (404) – {short}", status=status, url=url)
        if status >= 500:
            raise UnavailableError(f"chyba serveru {status} – {short}", status=status, url=url)
        raise HttpError(f"HTTP {status} – {short}", status=status, url=url)

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: Any = None,
        ttl: float | None = None,
    ) -> tuple[Any, str | None]:
        """Vrátí (tělo, url další stránky). Odpovědi se cachují podle TTL a revalidují ETagem."""
        full = self._url(url)
        if params:
            full = str(httpx.URL(full).copy_merge_params(dict(params)))
        content = json.dumps(json_body, sort_keys=True).encode() if json_body is not None else None
        key = self.cache.key(self.namespace, method, full, content)
        ttl = self.ttl if ttl is None else ttl
        cached = self.cache.get(key)
        now = time.time()
        if cached and ttl > 0 and now - cached.ts < ttl:
            return cached.body, cached.link_next
        headers: dict[str, str] = {}
        if content is not None:
            headers["Content-Type"] = "application/json"
        if cached and cached.etag and method == "GET":
            headers["If-None-Match"] = cached.etag
        resp = await self._send(method, full, headers=headers, content=content)
        self.last_headers = resp.headers
        if resp.status_code == 304 and cached:
            cached.ts = now
            self.cache.set(key, cached)
            return cached.body, cached.link_next
        self._raise_for(resp, full)
        try:
            body = resp.json() if resp.content else None
        except ValueError as err:
            raise HttpError(f"neplatná JSON odpověď – {full.split('?')[0]}", url=full) from err
        link_next = _parse_link_next(resp.headers.get("link"))
        if ttl > 0:
            self.cache.set(
                key,
                CachedResponse(resp.status_code, body, resp.headers.get("etag"), now, link_next),
            )
        return body, link_next

    async def get_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None, ttl: float | None = None
    ) -> Any:
        body, _ = await self.request_json("GET", url, params=params, ttl=ttl)
        return body

    async def post_json(self, url: str, payload: Any, *, ttl: float | None = None) -> Any:
        body, _ = await self.request_json("POST", url, json_body=payload, ttl=ttl)
        return body

    async def paginate(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        max_pages: int = 50,
        items_key: str | None = None,
        ttl: float | None = None,
    ) -> list[Any]:
        """Projde stránky podle hlavičky Link (rel="next")."""
        items: list[Any] = []
        next_url: str | None = url
        next_params = params
        for _ in range(max_pages):
            if next_url is None:
                break
            body, link = await self.request_json("GET", next_url, params=next_params, ttl=ttl)
            page = body.get(items_key, []) if items_key and isinstance(body, dict) else body
            if not isinstance(page, list):
                break
            items.extend(page)
            next_url, next_params = link, None
        return items
