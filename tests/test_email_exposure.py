"""Kontrola email-exposure: jen veřejná repa, jen e-maily uživatele, vždy maskované."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from repo_doctor.checks import get_check
from repo_doctor.config import Config
from repo_doctor.fixes import apply, plan, render_diff
from repo_doctor.gitwrap import Git, reset_ssh_cache
from repo_doctor.models import Finding, RepoResult, ScanResult
from repo_doctor.reports import render
from tests.factory import RepoBuilder, git
from tests.helpers import ctx

MINE = "lukas.osobni@proton.me"
NOREPLY = "1234+ja@users.noreply.github.com"


def _commit(rb: RepoBuilder, name: str, email: str, msg: str) -> None:
    rb.write(f"{msg}.txt", msg)
    env = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    git(rb.path, "add", "-A")
    git(rb.path, "commit", "-q", "-m", msg, env=env)


@pytest.fixture
def repo(tmp_path: Path, home: Path) -> RepoBuilder:
    with (home / ".gitconfig").open("a") as fh:
        fh.write(f"[user]\n\temail = {MINE}\n\tname = Lukas Test\n")
    reset_ssh_cache()
    rb = RepoBuilder.create(tmp_path / "verejne")
    _commit(rb, "Lukas Test", MINE, "a")
    _commit(rb, "Lukas Test", "lukas.jiny@gmail.com", "b")  # osobní doména + moje jméno
    _commit(rb, "Lukas Test", NOREPLY, "c")  # noreply se nehlásí
    _commit(rb, "Cizí Přispěvatel", "cizi@gmail.com", "d")  # cizí člověk se nehlásí
    _commit(rb, "Lukas Test", "lukas@firma.example", "e")  # pracovní, není na seznamu
    return rb


def _run(path: Path, **kw: Any) -> list[Finding]:
    check = get_check("email-exposure")
    assert check is not None
    return check.run(ctx(path, **kw))


def test_reports_only_my_personal_emails_masked(repo: RepoBuilder) -> None:
    findings = _run(repo.path, visibility="public")
    emails = sorted(str(f.data["email"]) for f in findings)
    assert emails == ["l***@gmail.com", "l***@proton.me"]
    for f in findings:
        assert MINE not in f.message and "lukas.jiny" not in f.message
        assert not f.fixable  # bez připojeného hostingu neznáme noreply adresu


def test_my_emails_option(repo: RepoBuilder) -> None:
    findings = _run(
        repo.path, visibility="public", config=Config(my_emails=["Lukas@Firma.example"])
    )
    assert "l***@firma.example" in {f.data["email"] for f in findings}


def test_private_or_unknown_visibility(repo: RepoBuilder) -> None:
    from repo_doctor.checks.base import SkipCheck

    assert _run(repo.path, visibility="private") == []
    with pytest.raises(SkipCheck):
        _run(repo.path, visibility="unknown")


def test_without_identity_is_skipped(tmp_path: Path) -> None:
    from repo_doctor.checks.base import SkipCheck

    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    git(tmp_path, "config", "--global", "--unset", "user.email")
    git(tmp_path, "config", "--global", "--unset", "user.name")
    reset_ssh_cache()
    with pytest.raises(SkipCheck):
        _run(rb.path, visibility="public")


def test_masked_in_all_report_formats(repo: RepoBuilder) -> None:
    findings = _run(repo.path, visibility="public")
    result = ScanResult(
        repos=[RepoResult(path=str(repo.path), name="verejne", root="~", findings=findings)]
    )
    for fmt in ("md", "json", "html"):
        text = render(result, fmt)
        assert MINE not in text and "lukas.jiny@gmail.com" not in text
        assert "l***@proton.me" in text
    data = json.loads(render(result, "json"))
    assert all(MINE not in json.dumps(f) for r in data["repos"] for f in r["findings"])


def test_fix_sets_local_noreply_email_only_after_apply(repo: RepoBuilder) -> None:
    before = repo.snapshot()
    c = ctx(repo.path, visibility="public", noreply_email=NOREPLY)
    check = get_check("email-exposure")
    assert check is not None
    findings = check.run(c)
    assert all(f.fixable for f in findings)
    patches = plan(c, findings)
    assert len(patches) == 1 and patches[0].local_only
    diff = render_diff(patches[0])
    # továrna nastavuje lokální user.email – v náhledu je jen maskovaný
    assert f"+user.email = {NOREPLY}" in diff and "-user.email = t***@example.invalid" in diff
    assert MINE not in diff and "test@example.invalid" not in diff
    # plánování nic nezměnilo
    assert repo.snapshot() == before
    assert git(repo.path, "config", "--local", "--get", "user.email").strip() != NOREPLY
    result = apply(Git(repo.path), patches, today=date(2026, 10, 13))
    assert result.branch is None and result.commits == []
    assert git(repo.path, "config", "--local", "--get", "user.email").strip() == NOREPLY
    after = repo.snapshot()
    assert after["refs"] == before["refs"] and after["head"] == before["head"]
    # podruhé už není co opravit
    assert plan(ctx(repo.path, visibility="public", noreply_email=NOREPLY), findings) == []


def test_fix_works_on_dirty_repo(repo: RepoBuilder) -> None:
    repo.write("rozdelane.txt", "x")
    c = ctx(repo.path, visibility="public", noreply_email=NOREPLY)
    check = get_check("email-exposure")
    assert check is not None
    patches = plan(c, check.run(c))
    apply(Git(repo.path), patches, today=date(2026, 10, 13))
    assert (repo.path / "rozdelane.txt").read_text() == "x"


def test_untrusted_owner_repo_is_never_changed(
    repo: RepoBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repo_doctor.fixes import FixRefused

    c = ctx(repo.path, visibility="public", noreply_email=NOREPLY)
    check = get_check("email-exposure")
    assert check is not None
    patches = plan(c, check.run(c))
    before = git(repo.path, "config", "--local", "--get", "user.email")
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(FixRefused):
        apply(Git(repo.path), patches)
    monkeypatch.delenv("GIT_TEST_ASSUME_DIFFERENT_OWNER")
    assert git(repo.path, "config", "--local", "--get", "user.email") == before


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("1+ja@users.noreply.github.com", True),
        ("ja@noreply.git.tailnet.ts.net", True),
        ("123-ja@users.noreply.gitlab.com", True),
        ("noreply@github.com", True),
        ("ja@localhost", True),
        ("ja@gmail.com", False),
    ],
)
def test_noreply_detection(email: str, expected: bool) -> None:
    from repo_doctor.checks.privacy import is_noreply

    assert is_noreply(email) is expected


@pytest.mark.parametrize(
    ("ftype", "url", "api", "body", "expected"),
    [
        (
            "github",
            None,
            "https://api.github.com/user",
            {"id": 7, "login": "ja"},
            "7+ja@users.noreply.github.com",
        ),
        (
            "github",
            "https://ghe.firma.example",
            "https://ghe.firma.example/api/v3/user",
            {"id": 7, "login": "ja"},
            "7+ja@users.noreply.ghe.firma.example",
        ),
        (
            "gitlab",
            None,
            "https://gitlab.com/api/v4/user",
            {"private_commit_email": "7-ja@users.noreply.gitlab.com"},
            "7-ja@users.noreply.gitlab.com",
        ),
        (
            "forgejo",
            "https://git.tailnet.ts.net",
            "https://git.tailnet.ts.net/api/v1/user",
            {"email": "ja@noreply.git.tailnet.ts.net"},
            "ja@noreply.git.tailnet.ts.net",
        ),
        (
            "forgejo",
            "https://git.tailnet.ts.net",
            "https://git.tailnet.ts.net/api/v1/user",
            {"email": "ja@proton.me"},
            None,
        ),
    ],
)
async def test_forge_noreply_email(
    ftype: str, url: str | None, api: str, body: dict[str, object], expected: str | None
) -> None:
    import respx

    from repo_doctor.config import ForgeConfig
    from repo_doctor.forges import build_forge

    with respx.mock:
        route = respx.get(api).respond(json=body)
        forge = build_forge(
            ForgeConfig(name="h", type=ftype, url=url, token_env="X"),
            token="tok-" + "z" * 20,
        )
        try:
            assert await forge.noreply_email() == expected
            assert await forge.noreply_email() == expected  # cache – jen jeden dotaz
        finally:
            await forge.client.aclose()
        assert route.call_count == 1
