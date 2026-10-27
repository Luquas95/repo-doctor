"""Nápověda v TUI: záložka k obrazovce a záložka „Vše“ (#30)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from repo_doctor.keymap import CONTEXTS
from repo_doctor.tui.helptext import GENERAL, PAGES
from repo_doctor.tui.screens.cleanup import CleanupScreen
from repo_doctor.tui.screens.dashboard import DashboardScreen
from repo_doctor.tui.screens.detail import DetailScreen
from repo_doctor.tui.screens.fix import FixScreen
from repo_doctor.tui.screens.folders import FoldersScreen
from repo_doctor.tui.screens.forges import ForgesScreen
from repo_doctor.tui.screens.help import HelpScreen
from repo_doctor.tui.screens.remote import RemoteScreen
from repo_doctor.tui.screens.settings import SettingsScreen
from repo_doctor.tui.screens.sync import SyncScreen
from repo_doctor.tui.screens.tools import ToolsScreen
from tests.tui_helpers import make_app, screen_text


def body_text(screen: HelpScreen) -> str:
    """Celý obsah aktuální záložky (i to, co se nevejde na obrazovku)."""
    console = Console(width=100, record=True, file=io.StringIO())
    console.print(screen._all() if screen.tab == "all" else screen._screen())
    return console.export_text()


def tab_of(screen: HelpScreen) -> str:
    return screen.tab


def test_every_screen_context_has_help_page() -> None:
    """Nová obrazovka (kontext v keymapu) musí mít i text nápovědy."""
    assert set(CONTEXTS) - {"global", "nav"} == set(PAGES)
    assert all(page.intro for page in PAGES.values())
    assert GENERAL


@pytest.mark.parametrize(
    ("key", "cls", "context"),
    [
        ("1", FoldersScreen, "folders"),
        ("2", ForgesScreen, "forges"),
        ("3", RemoteScreen, "remote"),
        ("4", SettingsScreen, "settings"),
        ("6", CleanupScreen, "cleanup"),
        ("7", SyncScreen, "sync"),
        ("8", ToolsScreen, "tools"),
    ],
)
async def test_help_matches_screen(tmp_path: Path, key: str, cls: type, context: str) -> None:
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert isinstance(app.screen, cls)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert app.screen.context == context
        assert app.screen.tab == "screen"
        assert CONTEXTS[context].upper() in screen_text(app)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, cls)


async def test_dashboard_detail_and_fix_help(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert app.screen.context == "dashboard"
        text = body_text(app.screen)
        assert "PŘEHLED (TRIÁŽ)" in text and "POHYB" in text and "GLOBÁLNÍ" in text
        assert "KARTA REPA" not in text and "TYPICKÝ POSTUP" not in text
        await pilot.press("escape")
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen) and app.screen.context == "detail"
        await pilot.press("escape")
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FixScreen)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen) and app.screen.context == "fix"


async def test_tab_switches_between_screen_and_all(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.press("question_mark")
        await pilot.pause()
        help_screen = app.screen
        assert isinstance(help_screen, HelpScreen) and tab_of(help_screen) == "screen"
        assert "TYPICKÝ POSTUP" not in body_text(help_screen)
        await pilot.press("tab")
        await pilot.pause()
        assert tab_of(help_screen) == "all"
        text = body_text(help_screen)
        assert "TYPICKÝ POSTUP" in text and "KARTA REPA" in text
        await pilot.press("tab")
        await pilot.pause()
        assert tab_of(help_screen) == "screen"


async def test_h_opens_full_help_and_switches_tab(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await pilot.press("H")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert app.screen.tab == "all"
        assert "CO JE REPO-DOCTOR" in screen_text(app)
        await pilot.press("escape")
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen) and tab_of(app.screen) == "screen"
        await pilot.press("H")  # uvnitř nápovědy přepne na „Vše“, nepřidává další vrstvu
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen) and tab_of(app.screen) == "all"
        await pilot.press("escape")
        assert isinstance(app.screen, DashboardScreen)


async def test_help_all_key_can_be_remapped(tmp_path: Path) -> None:
    app = make_app(tmp_path, config='[keys]\nhelp_all = "F2"\n')
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen) and app.screen.tab == "all"
