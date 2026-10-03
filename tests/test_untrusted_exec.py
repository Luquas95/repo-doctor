"""Cizí repo nesmí přes `.git/` ani lokální konfiguraci spustit program (0.1.4).

Každý test postaví škodlivé repo, kde by spuštěný program vytvořil soubor-značku, a ověří,
že značka nevznikne – při skenu s fetch, při léčbě (vytvoření větve) i při klonu/sondě.
Testy potřebují spustitelné skripty (`#!/bin/sh`), běží na Linuxu a macOS.
"""

from __future__ import annotations

import http.server
import stat
import sys
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from repo_doctor import cli
from repo_doctor.fixes import apply
from repo_doctor.gitwrap import Git, GitError, _allow_protocols, reset_ssh_cache
from repo_doctor.models import FileChange, Patch
from repo_doctor.sshhelp import explain_ssh_error
from tests.factory import RepoBuilder, git

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="potřebuje POSIX shell skripty")

TODAY = date(2026, 10, 3)


def _script(path: Path, marker: Path, *, output: str = "", code: int = 1) -> Path:
    """Spustitelný skript, který při spuštění vytvoří značku."""
    body = f"#!/bin/sh\ntouch '{marker}'\n"
    if output:
        body += f"printf '%s\\n' '{output}'\n"
    path.write_text(body + f"exit {code}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "SPUSTENO"


def _upstream_and_victim(tmp_path: Path) -> tuple[RepoBuilder, RepoBuilder]:
    up = RepoBuilder.create(tmp_path / "upstream")
    up.write("a.txt", "a").commit("init")
    victim = RepoBuilder.create(tmp_path / "projekty" / "obet")
    victim.remote("origin", str(up.path))
    git(victim.path, "fetch", "-q", "origin")
    git(victim.path, "reset", "-q", "--hard", "origin/main")
    git(victim.path, "branch", "-q", "--set-upstream-to=origin/main")
    up.write("b.txt", "b").commit("nový commit v upstreamu")
    return up, victim


def _hook(victim: RepoBuilder, marker: Path, hooks_dir: Path | None = None) -> None:
    target = hooks_dir or victim.path / ".git" / "hooks"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("reference-transaction", "post-checkout", "pre-auto-gc"):
        _script(target / name, marker)
    if hooks_dir is not None:
        git(victim.path, "config", "core.hooksPath", str(hooks_dir))


def _scan_fetch(root: Path, capsys: pytest.CaptureFixture[str]) -> str:
    cli.main(["scan", str(root), "--fetch", "--report", "json"])
    return capsys.readouterr().err


def _fix_patch() -> Patch:
    return Patch(
        check_id="readme-missing",
        title="README",
        summary="přidá README",
        changes=[FileChange(path="README.md", action="create", content="# obet\n")],
    )


# ------------------------------------------------------------------ hooky
@pytest.mark.usefixtures("allow_file")
@pytest.mark.parametrize("where", ["git-dir", "hooksPath"])
def test_hooks_never_run_on_scan_fetch(
    tmp_path: Path, marker: Path, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    up, victim = _upstream_and_victim(tmp_path)
    _hook(victim, marker, tmp_path / "zle-hooky" if where == "hooksPath" else None)
    err = _scan_fetch(tmp_path / "projekty", capsys)
    assert not marker.exists()
    assert "fetch obet" not in err  # regrese: fetch přes povolený protokol funguje
    assert git(victim.path, "rev-parse", "origin/main") == git(up.path, "rev-parse", "HEAD")


@pytest.mark.parametrize("where", ["git-dir", "hooksPath"])
def test_hooks_never_run_when_fix_branch_is_created(
    tmp_path: Path, marker: Path, where: str
) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    victim.write("main.py", "print(1)\n").commit("init")
    _hook(victim, marker, tmp_path / "zle-hooky" if where == "hooksPath" else None)
    result = apply(Git(victim.path), [_fix_patch()], today=TODAY)
    assert not marker.exists()
    # regrese: větev s opravami vznikla včetně commitu
    assert result.branch == "repo-doctor/fixes-2026-10-03" and len(result.commits) == 1
    assert git(victim.path, "show", f"{result.branch}:README.md") == "# obet\n"


def test_global_hooks_are_disabled_too(tmp_path: Path, home: Path, marker: Path) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    victim.write("main.py", "x\n").commit("init")
    hooks = tmp_path / "globalni-hooky"
    hooks.mkdir()
    _script(hooks / "reference-transaction", marker)
    with (home / ".gitconfig").open("a") as fh:
        fh.write(f"[core]\n\thooksPath = {hooks}\n")
    with pytest.raises(RuntimeError):  # kontrola: bez repo-doctoru se hook spustí
        git(victim.path, "branch", "kontrola")
    assert marker.exists()
    marker.unlink()
    Git(victim.path).create_branch("pokus", "HEAD")
    assert not marker.exists()


# ------------------------------------------------------------------ příkazy z lokální konfigurace
@pytest.mark.usefixtures("allow_file")
def test_local_uploadpack_never_runs(
    tmp_path: Path, marker: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    up, victim = _upstream_and_victim(tmp_path)
    git(victim.path, "config", "remote.origin.uploadpack", str(_script(tmp_path / "up.sh", marker)))
    err = _scan_fetch(tmp_path / "projekty", capsys)
    assert not marker.exists()
    assert "fetch obet" not in err
    assert git(victim.path, "rev-parse", "origin/main") == git(up.path, "rev-parse", "HEAD")


@pytest.mark.usefixtures("allow_file")
def test_local_alternate_refs_command_never_runs(tmp_path: Path, marker: Path) -> None:
    up, victim = _upstream_and_victim(tmp_path)
    alternates = victim.path / ".git" / "objects" / "info" / "alternates"
    alternates.write_text(f"{up.path / '.git' / 'objects'}\n")
    git(
        victim.path,
        "config",
        "core.alternateRefsCommand",
        str(_script(tmp_path / "alt.sh", marker)),
    )
    Git(victim.path).fetch(timeout=20)
    assert not marker.exists()


@pytest.mark.parametrize("allow_git", [False, True])
def test_local_git_proxy_never_runs(tmp_path: Path, marker: Path, allow_git: bool) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    victim.write("a", "a").commit()
    victim.remote("origin", "git://git.example.invalid/ja/repo.git")
    git(victim.path, "config", "core.gitProxy", str(_script(tmp_path / "proxy.sh", marker)))
    if allow_git:  # i kdyby git:// povolený byl, GIT_PROXY_COMMAND="" proxy vypne
        _allow_protocols("git")
    with pytest.raises(GitError) as exc:
        Git(victim.path).fetch(timeout=20)
    assert not marker.exists()
    if not allow_git:
        assert explain_ssh_error(exc.value.stderr) == (
            "Remote používá nepovolený protokol git, repo-doctor ho z bezpečnostních "
            "důvodů nefetchuje (povolené jsou https a ssh)."
        )


# ------------------------------------------------------------------ credential helper
class _AuthHandler(http.server.BaseHTTPRequestHandler):
    """HTTP server, který vždy chce přihlášení (git se zeptá credential helperů)."""

    def do_GET(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="repo-doctor-test"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def auth_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    server = http.server.HTTPServer(("127.0.0.1", 0), _AuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # https potřebuje certifikát; pro lokální test bez sítě dočasně povolíme http
    _allow_protocols("http")
    yield f"http://127.0.0.1:{server.server_port}/ja/repo.git"
    server.shutdown()


def test_local_credential_helpers_never_run_global_ones_do(
    tmp_path: Path, home: Path, auth_server: str
) -> None:
    local_marker = tmp_path / "LOKALNI-HELPER"
    url_marker = tmp_path / "URL-HELPER"
    global_marker = tmp_path / "GLOBALNI-HELPER"
    victim = RepoBuilder.create(tmp_path / "obet")
    victim.write("a", "a").commit()
    victim.remote("origin", auth_server)
    git(victim.path, "config", "credential.helper", f"!{_script(tmp_path / 'l.sh', local_marker)}")
    host = auth_server.rsplit("/ja/", 1)[0]
    git(
        victim.path,
        "config",
        f"credential.{host}.helper",
        f"!{_script(tmp_path / 'u.sh', url_marker)}",
    )
    helper = _script(
        tmp_path / "g.sh", global_marker, output="username=ja\npassword=nespravne", code=0
    )
    with (home / ".gitconfig").open("a") as fh:
        fh.write(f'[credential]\n\thelper = "!{helper}"\n')
    reset_ssh_cache()
    with pytest.raises(GitError):
        Git(victim.path).fetch(timeout=20)
    assert not local_marker.exists() and not url_marker.exists()
    assert global_marker.exists()  # helper uživatele z globální konfigurace funguje dál


def test_credential_reset_only_when_repo_defines_helper(tmp_path: Path) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    assert all(k != "credential.helper" for k, _ in Git(victim.path).hardening_pairs())


# ------------------------------------------------------------------ protokoly
@pytest.mark.parametrize(
    ("url", "proto"),
    [("file://{up}", "file"), ("{up}", "file"), ("ext::sh -c touch% {marker}", "ext")],
)
def test_disallowed_protocols_are_refused(
    tmp_path: Path,
    marker: Path,
    capsys: pytest.CaptureFixture[str],
    url: str,
    proto: str,
) -> None:
    up, victim = _upstream_and_victim(tmp_path)
    git(victim.path, "remote", "set-url", "origin", url.format(up=up.path, marker=marker))
    git(victim.path, "config", "protocol.allow", "always")  # lokální povolení nepomůže
    err = _scan_fetch(tmp_path / "projekty", capsys)
    assert not marker.exists()
    assert f"fetch obet: Remote používá nepovolený protokol {proto}" in err


def test_disallowed_protocol_for_clone_and_probe(tmp_path: Path, marker: Path) -> None:
    src = RepoBuilder.create(tmp_path / "src")
    src.write("a", "a").commit()
    with pytest.raises(GitError) as exc:
        Git.clone(str(src.path), tmp_path / "klon")
    assert "transport 'file' not allowed" in exc.value.stderr
    with pytest.raises(GitError):
        Git.ls_remote(f"ext::sh -c touch% {marker}")
    assert not marker.exists()


# ------------------------------------------------------------------ přesměrování provozu
def test_local_proxy_and_ssl_settings_are_overridden(tmp_path: Path) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    for key, value in (
        ("remote.origin.proxy", "http://zly-proxy:8080"),
        ("http.proxy", "http://zly-proxy:8080"),
        ("http.https://git.example.com/.proxy", "http://zly-proxy:8080"),
        ("http.sslVerify", "false"),
        ("http.https://git.example.com/.sslVerify", "false"),
    ):
        git(victim.path, "config", key, value)
    pairs = dict(Git(victim.path).hardening_pairs())
    assert pairs["remote.origin.proxy"] == ""
    assert pairs["http.proxy"] == ""
    assert pairs["http.https://git.example.com/.proxy"] == ""
    assert pairs["http.sslverify"] == "true"
    assert pairs["http.https://git.example.com/.sslverify"] == "true"
    # efektivní hodnoty pro volání repo-doctoru
    g = Git(victim.path)
    assert g.run("config", "--get", "http.sslVerify").strip() == "true"
    assert g.run("config", "--get", "remote.origin.proxy").strip() == ""
    assert (
        g.run("config", "--get-urlmatch", "http.sslVerify", "https://git.example.com/x").strip()
        == "true"
    )


def test_hardening_env_disables_hooks_for_gitleaks(tmp_path: Path) -> None:
    victim = RepoBuilder.create(tmp_path / "obet")
    env = Git(victim.path).hardening_env()
    pairs = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert pairs["core.hooksPath"] == "/dev/null"
