"""České hlášky pro typické SSH chyby gitu (klon, test připojení, --fetch, CLI)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import respx

from repo_doctor import cli, paths, sshhelp
from repo_doctor.gitwrap import GitError, reset_ssh_cache
from repo_doctor.sshhelp import (
    PUBLICKEY_MSG,
    UNREACHABLE_MSG,
    explain_ssh_error,
    friendly_git_error,
)
from tests.factory import RepoBuilder

PORT_URL = "ssh://git@git.example.ts.net:2222/ja/repo.git"
SCP_URL = "git@git.example.ts.net:ja/repo.git"


@pytest.mark.parametrize(
    "stderr",
    [
        "Host key verification failed.\nfatal: Could not read from remote repository.",
        "No ED25519 host key is known for [git.example.ts.net]:2222 and you have requested "
        "strict checking.\nHost key verification failed.",
    ],
)
def test_unknown_host_key_custom_port(stderr: str) -> None:
    msg = explain_ssh_error(stderr, PORT_URL)
    assert msg == (
        "Server zatím neznáš. Připoj se k němu jednou ručně: "
        "`ssh -p 2222 git@git.example.ts.net` a potvrď otisk klíče. Pak to zkus znovu."
    )


def test_unknown_host_key_scp_form() -> None:
    msg = explain_ssh_error("Host key verification failed.", SCP_URL)
    assert msg is not None
    assert "`ssh git@git.example.ts.net`" in msg and "-p" not in msg


def test_publickey() -> None:
    err = "git@git.example.ts.net: Permission denied (publickey).\nfatal: Could not read"
    assert explain_ssh_error(err, PORT_URL) == PUBLICKEY_MSG
    assert "core.sshCommand" in PUBLICKEY_MSG and "~/.ssh/config" in PUBLICKEY_MSG


@pytest.mark.parametrize(
    "stderr",
    [
        "ssh: Could not resolve hostname git.example.ts.net: Name or service not known",
        "ssh: connect to host git.example.ts.net port 2222: Connection timed out",
        "ssh: connect to host git.example.ts.net port 2222: Connection refused",
    ],
)
def test_unreachable(stderr: str) -> None:
    assert explain_ssh_error(stderr, PORT_URL) == UNREACHABLE_MSG


def test_other_errors_stay_unchanged() -> None:
    err = "fatal: repository 'ja/repo' not found"
    assert explain_ssh_error(err, PORT_URL) is None
    assert friendly_git_error(err, PORT_URL) == err


def test_no_password_or_token_in_message() -> None:
    secret = "tajneHeslo" + "123"
    for url in (
        f"ssh://ja:{secret}@git.example.ts.net:2222/ja/repo.git",
        f"https://x-access-token:{secret}@github.com/ja/repo.git",
        f"https://{secret}@github.com/ja/repo.git",
    ):
        for err in ("Host key verification failed.", "Permission denied (publickey)."):
            msg = explain_ssh_error(err, url)
            assert msg is not None and secret not in msg


def test_unsafe_host_is_not_echoed() -> None:
    msg = explain_ssh_error("Host key verification failed.", "ssh://git@ex$(id).com/a/b.git")
    assert msg is not None and "$(" not in msg and "<server>" in msg


def test_without_url() -> None:
    msg = explain_ssh_error("Host key verification failed.")
    assert msg is not None and "`ssh git@<server>`" in msg


def _fake_ssh(tmp_path: Path, message: str) -> str:
    """Falešné `ssh`, které vypíše danou chybu – nic nejde do sítě."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    script = d / "ssh"
    script.write_text(f"#!/bin/sh\necho '{message}' >&2\nexit 255\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_fetch_error_is_translated_in_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", _fake_ssh(tmp_path, "Host key verification failed."))
    reset_ssh_cache()
    rb = RepoBuilder.create(tmp_path / "projekty" / "app")
    rb.write("a", "a").commit()
    rb.remote("origin", PORT_URL)
    code = cli.main(["scan", str(tmp_path / "projekty"), "--fetch", "--report", "json"])
    captured = capsys.readouterr()
    assert code in (0, 1)
    assert "fetch app: Server zatím neznáš" in captured.err
    assert "ssh -p 2222 git@git.example.ts.net" in captured.err
    # původní text zůstává v detailu
    assert "Host key verification failed" in captured.out


def test_probe_ssh_translates(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(url: str) -> None:
        raise GitError(["ls-remote", url], 128, "git@h: Permission denied (publickey).")

    monkeypatch.setattr(sshhelp, "run_probe", failing)
    assert sshhelp.probe_ssh(PORT_URL) == PUBLICKEY_MSG

    def other(url: str) -> None:
        raise GitError(["ls-remote", url], 128, "fatal: repository not found")

    monkeypatch.setattr(sshhelp, "run_probe", other)
    assert sshhelp.probe_ssh(PORT_URL) is None


def test_real_ls_remote_probe_with_fake_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", _fake_ssh(tmp_path, "Connection refused"))
    reset_ssh_cache()
    monkeypatch.setattr(sshhelp, "run_probe", sshhelp._ls_remote)
    assert sshhelp.probe_ssh(SCP_URL) == UNREACHABLE_MSG


@respx.mock
def test_forges_test_reports_ssh_problem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing(url: str) -> None:
        assert url == PORT_URL
        raise GitError(["ls-remote", url], 128, "No ED25519 host key is known for x")

    monkeypatch.setattr(sshhelp, "run_probe", failing)
    paths.config_file().parent.mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(
        '[[forges]]\nname="home"\ntype="forgejo"\nurl="https://git.example.ts.net"\nuser="ja"\n'
    )
    api = "https://git.example.ts.net/api/v1"
    respx.get(f"{api}/version").respond(json={"version": "9.0.0+gitea-1.22"})
    respx.get(f"{api}/users/ja").respond(json={"login": "ja"})
    respx.get(f"{api}/users/ja/repos").respond(
        json=[{"full_name": "ja/repo", "private": False, "ssh_url": PORT_URL}]
    )
    cli.main(["forges", "test", "home"])
    out = capsys.readouterr().out
    assert "! SSH: Server zatím neznáš" in out, out
    assert "ssh -p 2222 git@git.example.ts.net" in out


async def test_tui_clone_shows_czech_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from repo_doctor.forges.base import ForgeRepo
    from repo_doctor.tui.screens.forms import CloneRequest
    from repo_doctor.tui.screens.remote import RemoteScreen
    from tests.tui_helpers import make_app

    monkeypatch.setenv("GIT_SSH_COMMAND", _fake_ssh(tmp_path, "Permission denied (publickey)."))
    reset_ssh_cache()
    app = make_app(tmp_path, offline=True)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("6")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RemoteScreen)
        messages: list[str] = []
        monkeypatch.setattr(screen, "notify", lambda msg, **kw: messages.append(msg))
        repo = ForgeRepo("ja/repo", "main", private=True, clone_ssh=PORT_URL)
        screen.do_clone(CloneRequest(PORT_URL, tmp_path / "klon"), "home", repo)
        await app.workers.wait_for_complete()
        await pilot.pause()
    failed = [m for m in messages if m.startswith("Klon selhal")]
    assert failed and PUBLICKEY_MSG in failed[0]
    assert "(git: " in failed[0] and "Permission denied" in failed[0]
