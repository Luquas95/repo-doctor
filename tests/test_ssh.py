"""SSH příkaz pro git: respektuje uživatelův core.sshCommand, nikdy lokální z cizího repa."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_doctor.config import ConfigStore
from repo_doctor.gitwrap import Git, GitError, configure_ssh, git_env, reset_ssh_cache, ssh_command
from tests.factory import RepoBuilder, git


def _global_config(home: Path, text: str) -> None:
    (home / ".gitconfig").write_text((home / ".gitconfig").read_text() + text)


def test_default_without_global_config() -> None:
    assert ssh_command() == "ssh -o BatchMode=yes"
    assert git_env()["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"


def test_global_ssh_command_is_used(home: Path) -> None:
    _global_config(home, "[core]\n\tsshCommand = ssh -i /tmp/klic -F /tmp/ssh_config_git\n")
    reset_ssh_cache()
    assert (
        git_env()["GIT_SSH_COMMAND"] == "ssh -i /tmp/klic -F /tmp/ssh_config_git -o BatchMode=yes"
    )


def test_environment_wins_over_global(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _global_config(home, "[core]\n\tsshCommand = ssh -i /tmp/klic\n")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /tmp/z-prostredi")
    reset_ssh_cache()
    assert ssh_command() == "ssh -i /tmp/z-prostredi -o BatchMode=yes"


def test_batch_mode_can_be_disabled(home: Path, tmp_path: Path) -> None:
    _global_config(home, "[core]\n\tsshCommand = /usr/local/bin/ssh-wrapper\n")
    configure_ssh(batch_mode=False)
    assert ssh_command() == "/usr/local/bin/ssh-wrapper"
    cfg = tmp_path / "config.toml"
    cfg.write_text("ssh_batch_mode = false\n")
    assert ConfigStore(cfg).load().ssh_batch_mode is False


def test_cached_once_per_run(home: Path) -> None:
    first = ssh_command()
    _global_config(home, "[core]\n\tsshCommand = ssh -i /tmp/pozdeji\n")
    assert ssh_command() == first  # cache – dotaz na konfiguraci jen jednou za běh
    reset_ssh_cache()
    assert "pozdeji" in ssh_command()


def test_query_failure_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # git není k dispozici
    reset_ssh_cache()
    assert ssh_command() == "ssh -o BatchMode=yes"


def test_local_ssh_command_of_foreign_repo_never_runs(home: Path, tmp_path: Path) -> None:
    """Škodlivý lokální core.sshCommand se nepoužije – poběží globální (důvěryhodný)."""
    local_marker = tmp_path / "LOCAL-RAN"
    global_marker = tmp_path / "GLOBAL-RAN"
    # v .gitconfig začíná `;` komentář – hodnotu proto do uvozovek
    _global_config(home, f"[core]\n\tsshCommand = \"sh -c 'touch {global_marker}; exit 1'\"\n")
    reset_ssh_cache()
    rb = RepoBuilder.create(tmp_path / "foreign")
    rb.write("a", "a").commit()
    # bez portu: wrapper `sh` je pro git varianta „simple“, která port neumí předat
    git(rb.path, "remote", "add", "origin", "ssh://git@git.example.invalid/o/r.git")
    git(rb.path, "config", "core.sshCommand", f"sh -c 'touch {local_marker}; exit 1'")
    with pytest.raises(GitError):
        Git(rb.path).fetch(timeout=20)
    assert global_marker.exists()
    assert not local_marker.exists()
