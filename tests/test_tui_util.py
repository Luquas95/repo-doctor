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
        ("gedit", ["gedit", "+12", "/f"]),
        ("kate", ["kate", "--line", "12", "/f"]),
        ("gnome-text-editor", ["gnome-text-editor", "/f"]),
    ],
)
def test_editor_command(editor: str, expected: list[str]) -> None:
    assert util.editor_command(editor, Path("/f"), 12) == expected


def test_editor_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "nano")
    assert util.editor_command(None, Path("/f"), None) == ["nano", "/f"]


def test_resolve_editor_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISUAL", "code --wait")
    monkeypatch.setenv("EDITOR", "nano")
    assert util.resolve_editor("hx") == ("hx", "Nastavení")
    assert util.resolve_editor(None) == ("code --wait", "$VISUAL")
    monkeypatch.delenv("VISUAL")
    assert util.resolve_editor(None) == ("nano", "$EDITOR")
    monkeypatch.delenv("EDITOR")
    assert util.resolve_editor(None) == ("vi", "výchozí")


def test_available_editors_and_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    present = {"nvim", "code", "gedit"}
    monkeypatch.setattr(
        "repo_doctor.tui.util.shutil.which", lambda n: f"/usr/bin/{n}" if n in present else None
    )
    assert util.available_editors() == [
        ("nvim", "Neovim (nvim)"),
        ("code", "VS Code (code) · okno"),
        ("gedit", "gedit (gedit) · okno"),
    ]
    assert util.is_gui_editor(["/usr/bin/code", "--wait"]) and util.is_gui_editor(["kate"])
    assert not util.is_gui_editor(["nvim"]) and not util.is_gui_editor([])
    assert util.editor_installed("code --wait") and not util.editor_installed("vi")
    assert not util.editor_installed("'neuzavřené") and not util.editor_installed("")


def test_open_in_editor_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "repo_doctor.tui.util.subprocess.Popen", lambda cmd, **kw: calls.append((cmd, kw))
    )
    util.open_in_editor_detached(["gedit", "/f"])
    assert calls[0][0] == ["gedit", "/f"] and calls[0][1]["start_new_session"] is True


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
