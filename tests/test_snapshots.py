"""Snapshot testy obrazovek TUI (odpovídají wireframům v docs/design/tui.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests import factory as fx
from tests.sample import sample_result
from tests.tui_helpers import make_app

SIZES = [(80, 24), (160, 48)]
THEMES = ["dark", "light"]


def _fix_app(tmp: Path, theme: str) -> Any:
    rb = fx.RepoBuilder.create(tmp / "infra-notes")
    rb.write(".gitignore", "node_modules/\ndist/\n").write("main.py", "print(1)\n").write(
        "util.py", "x=1\n"
    )
    rb.write("pyproject.toml", "[project]\nname='x'\n").commit()
    result = sample_result()
    result.repos[0].path = str(rb.path)
    return make_app(tmp, result=result, theme=theme)


async def _wait(pilot: Any) -> None:
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_dashboard(snap_compare: Any, tmp_path: Path, size: tuple[int, int], theme: str) -> None:
    assert snap_compare(make_app(tmp_path, theme=theme), terminal_size=size)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_detail(snap_compare: Any, tmp_path: Path, size: tuple[int, int], theme: str) -> None:
    assert snap_compare(make_app(tmp_path, theme=theme), terminal_size=size, press=["enter", "j"])


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_fix_confirm(snap_compare: Any, tmp_path: Path, size: tuple[int, int], theme: str) -> None:
    async def run_before(pilot: Any) -> None:
        await pilot.press("f")
        await _wait(pilot)
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(_fix_app(tmp_path, theme), terminal_size=size, run_before=run_before)


# Velikost wireframů (100×31) – zdroj obrázků v dokumentaci.
def test_wireframe_dashboard(snap_compare: Any, tmp_path: Path) -> None:
    assert snap_compare(make_app(tmp_path), terminal_size=(100, 31))


def test_wireframe_detail(snap_compare: Any, tmp_path: Path) -> None:
    assert snap_compare(make_app(tmp_path), terminal_size=(100, 31), press=["enter"])


def test_wireframe_fix(snap_compare: Any, tmp_path: Path) -> None:
    async def run_before(pilot: Any) -> None:
        await pilot.press("f")
        await _wait(pilot)
        await pilot.press("enter")
        await pilot.pause()

    assert snap_compare(_fix_app(tmp_path, "dark"), terminal_size=(100, 31), run_before=run_before)
