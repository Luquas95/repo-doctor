from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from repo_doctor.tui import util
from tests.sample import NOW, sample_result


def test_relative_time() -> None:
    assert util.relative_time(None, NOW) == "bez commitu"
    assert util.relative_time(NOW - timedelta(minutes=5), NOW) == "před chvílí"
    assert util.relative_time(NOW - timedelta(hours=3), NOW) == "před 3 h"
    assert util.relative_time(NOW - timedelta(days=1, hours=1), NOW) == "včera"
    assert util.relative_time(NOW - timedelta(days=5), NOW) == "před 5 dny"
    assert util.relative_time(NOW - timedelta(days=90), NOW) == "před 3 měs."
    assert util.relative_time(NOW - timedelta(days=1000), NOW) == "před 2 lety"


def test_git_state_and_paths() -> None:
    repos = {r.name: r for r in sample_result().repos}
    assert util.git_state(repos["infra-notes"]) == "~3 ↑2"
    assert util.git_state(repos["old-cli"]) == "bez remote"
    assert util.git_state(repos["thesis-2019"]) == "archiv"
    assert util.git_state(repos["notes"]) == "čisté"
    assert util.home_path(str(Path.home() / "x")) == "~/x"
    assert util.home_path("/etc") == "/etc"
    assert (
        util.truncate("abcdef", 4) == "abc…"
        and util.truncate("ab", 4) == "ab"
        and util.truncate("x", 0) == ""
    )


@pytest.mark.parametrize(
    ("editor", "expected"),
    [
        ("nvim", ["nvim", "+12", "/f"]),
        ("hx", ["hx", "/f:12"]),
        ("code --wait", ["code", "--wait", "--goto", "/f:12"]),
        ("zed", ["zed", "/f:12"]),
        ("gedit", ["gedit", "/f"]),
    ],
)
def test_editor_command(editor: str, expected: list[str]) -> None:
    assert util.editor_command(editor, Path("/f"), 12) == expected


def test_editor_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "nano")
    assert util.editor_command(None, Path("/f"), None) == ["nano", "/f"]


def test_open_url_and_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("repo_doctor.tui.util.shutil.which", lambda name: None)
    assert not util.open_url("https://x") and not util.wl_copy("x")
    monkeypatch.setattr("repo_doctor.tui.util.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "repo_doctor.tui.util.subprocess.Popen", lambda cmd, **kw: calls.append(cmd)
    )
    assert util.open_url("https://example.org")
    assert not util.open_url("file:///etc/passwd")
    monkeypatch.setattr("repo_doctor.tui.util.subprocess.run", lambda cmd, **kw: calls.append(cmd))
    assert util.wl_copy("text")

    def boom(cmd: list[str], **kw: object) -> None:
        raise OSError("x")

    monkeypatch.setattr("repo_doctor.tui.util.subprocess.run", boom)
    assert not util.wl_copy("text")
    assert calls[0] == ["/usr/bin/xdg-open", "https://example.org"]
