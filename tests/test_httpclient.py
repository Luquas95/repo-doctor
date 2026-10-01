from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from repo_doctor.httpclient import (
    AuthError,
    ForbiddenError,
    HttpClient,
    HttpError,
    NotFoundError,
    RateLimitError,
    ResponseCache,
    UnavailableError,
    _parse_link_next,
    build_verify,
)


async def _nosleep(_: float) -> None:
    return None


@respx.mock
async def test_get_and_ttl_cache(tmp_path: Path) -> None:
    route = respx.get("https://api.test/x").respond(json={"a": 1}, headers={"ETag": '"v1"'})
    async with HttpClient(base_url="https://api.test", cache=ResponseCache(tmp_path)) as c:
        assert await c.get_json("/x") == {"a": 1}
        assert await c.get_json("/x") == {"a": 1}
    assert route.call_count == 1
    # nový klient čte z disku
    async with HttpClient(base_url="https://api.test", cache=ResponseCache(tmp_path)) as c:
        assert await c.get_json("/x") == {"a": 1}
    assert route.call_count == 1
    files = list(tmp_path.glob("*.json"))
    assert files and oct(files[0].stat().st_mode)[-3:] == "600"


@respx.mock
async def test_etag_revalidation(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, json=[1, 2], headers={"ETag": '"v1"'})

    respx.get("https://api.test/y").mock(side_effect=handler)
    cache = ResponseCache()
    async with HttpClient(base_url="https://api.test", cache=cache, ttl=0.0001) as c:
        assert await c.get_json("/y", ttl=1) == [1, 2]
        time.sleep(0.01)
        assert await c.get_json("/y", ttl=0.001) == [1, 2]
    assert len(calls) == 2
    assert calls[1].headers["if-none-match"] == '"v1"'


@respx.mock
async def test_pagination() -> None:
    respx.get("https://api.test/items", params={"page": "2"}).respond(json=[3])
    respx.get("https://api.test/items").respond(
        json=[1, 2],
        headers={
            "Link": '<https://api.test/items?page=2>; rel="next", <https://api.test/items?page=2>; rel="last"'
        },
    )
    async with HttpClient(base_url="https://api.test", ttl=0) as c:
        assert await c.paginate("/items") == [1, 2, 3]


@respx.mock
async def test_pagination_items_key() -> None:
    respx.get("https://api.test/w").respond(json={"data": [1]})
    async with HttpClient(base_url="https://api.test", ttl=0) as c:
        assert await c.paginate("/w", items_key="data") == [1]
        respx.get("https://api.test/z").respond(json={"x": 1})
        assert await c.paginate("/z") == []


@pytest.mark.parametrize(
    ("status", "exc"),
    [
        (401, AuthError),
        (403, ForbiddenError),
        (404, NotFoundError),
        (500, UnavailableError),
        (418, HttpError),
    ],
)
@respx.mock
async def test_errors(status: int, exc: type[Exception]) -> None:
    respx.get("https://api.test/e").respond(status)
    async with HttpClient(base_url="https://api.test") as c:
        with pytest.raises(exc):
            await c.get_json("/e")


@respx.mock
async def test_invalid_json() -> None:
    respx.get("https://api.test/j").respond(200, content=b"<html>")
    async with HttpClient(base_url="https://api.test") as c:
        with pytest.raises(HttpError):
            await c.get_json("/j")


@respx.mock
async def test_unavailable() -> None:
    respx.get("https://down.test/").mock(side_effect=httpx.ConnectError("boom"))
    respx.get("https://slow.test/").mock(side_effect=httpx.ReadTimeout("slow"))
    async with HttpClient() as c:
        with pytest.raises(UnavailableError):
            await c.get_json("https://down.test/")
        with pytest.raises(UnavailableError):
            await c.get_json("https://slow.test/")


@respx.mock
async def test_rate_limit_retry_then_ok() -> None:
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    respx.get("https://api.test/r").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "3"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    async with HttpClient(sleep=sleep) as c:
        assert await c.get_json("https://api.test/r") == {"ok": True}
    assert waits == [2.0, 3.0]


@respx.mock
async def test_rate_limit_too_long() -> None:
    reset = str(int(time.time()) + 3600)
    respx.get("https://api.test/r").respond(
        403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset}
    )
    async with HttpClient(sleep=_nosleep) as c:
        with pytest.raises(RateLimitError):
            await c.get_json("https://api.test/r")


@respx.mock
async def test_rate_limit_date_and_garbage() -> None:
    respx.get("https://api.test/a").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            httpx.Response(429, headers={"Retry-After": "nonsense"}),
            httpx.Response(429),
        ]
    )
    async with HttpClient(sleep=_nosleep, max_rate_wait=100) as c:
        with pytest.raises(RateLimitError):
            await c.get_json("https://api.test/a")


@respx.mock
async def test_post_cached_by_body() -> None:
    route = respx.post("https://api.test/q").respond(json={"r": 1})
    async with HttpClient() as c:
        await c.post_json("https://api.test/q", {"a": 1})
        await c.post_json("https://api.test/q", {"a": 1})
        await c.post_json("https://api.test/q", {"a": 2})
    assert route.call_count == 2


@respx.mock
async def test_auth_header_not_in_cache(tmp_path: Path) -> None:
    respx.get("https://api.test/u").respond(json={"login": "x"})
    secret = "tok_" + "z" * 30
    async with HttpClient(
        headers={"Authorization": f"token {secret}"}, cache=ResponseCache(tmp_path)
    ) as c:
        await c.get_json("https://api.test/u")
    for f in tmp_path.iterdir():
        assert secret not in f.read_text()


def test_link_parse() -> None:
    assert _parse_link_next(None) is None
    assert _parse_link_next("<x>") is None
    assert _parse_link_next('<a>; rel="prev", <b>; rel="next"') == "b"


def test_build_verify(tmp_path: Path) -> None:
    assert build_verify(False, None) is False
    assert build_verify(True, None) is True
    import ssl

    ca = ssl.get_default_verify_paths().cafile
    if ca:
        ctx = build_verify(True, ca)
        assert isinstance(ctx, ssl.SSLContext)


@respx.mock
async def test_credentials_not_sent_to_other_origin() -> None:
    seen: dict[str, httpx.Headers] = {}

    def evil(request: httpx.Request) -> httpx.Response:
        seen["evil"] = request.headers
        return httpx.Response(200, json=[2])

    respx.get("https://gitlab.example/api/v4/projects").respond(
        302, headers={"Location": "https://evil.example/steal"}
    )
    respx.get("https://evil.example/steal").mock(side_effect=evil)
    async with HttpClient(
        base_url="https://gitlab.example/api/v4",
        headers={"PRIVATE-TOKEN": "glpat-secret-value-123"},
    ) as c:
        assert await c.get_json("/projects") == [2]
    assert "private-token" not in seen["evil"]
    assert "authorization" not in seen["evil"]


@respx.mock
async def test_pagination_does_not_leave_origin() -> None:
    other = respx.get("https://evil.example/page2").respond(json=[9])
    respx.get("https://api.test/items").respond(
        json=[1], headers={"Link": '<https://evil.example/page2>; rel="next"'}
    )
    async with HttpClient(
        base_url="https://api.test", headers={"Authorization": "token x"}, ttl=0
    ) as c:
        assert await c.paginate("/items") == [1]
    assert other.call_count == 0
