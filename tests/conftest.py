from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from repo_doctor.gitwrap import configure_ssh
from repo_doctor.masking import REGISTRY

os.environ["TZ"] = "UTC"  # deterministické časy ve snapshotech
time.tzset()


@pytest.fixture(autouse=True)
def _isolated_env(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Každý test má vlastní XDG adresáře a HOME, nikdy nesahá na skutečnou konfiguraci."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local/share"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Test Tester\n\temail = test@example.invalid\n[init]\n\tdefaultBranch = main\n"
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    configure_ssh(batch_mode=True)
    # SSH sonda „testu připojení“ by šla do sítě – testy ji nahrazují explicitně
    monkeypatch.setattr("repo_doctor.sshhelp.run_probe", lambda url: None)
    yield
    REGISTRY.clear()
    configure_ssh(batch_mode=True)


@pytest.fixture
def home() -> Path:
    return Path.home()
