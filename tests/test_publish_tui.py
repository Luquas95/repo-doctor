"""Odeslání oprav v TUI: klávesa → náhled v dialogu (výchozí „Zrušit“) → provedení."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from repo_doctor.tui.app import RepoDoctorApp
from repo_doctor.tui.screens.detail import DetailScreen
from repo_doctor.tui.screens.dialogs import ConfirmDialog
from tests.factory import RepoBuilder, git
from tests.sample import sample_result
from tests.test_publish import (
    BRANCH,
    GREEN,
    REPO_API,
    SUBJECT,
    TOKEN,
    fix_repo,
    mock_pr_state,
    pr_json,
    remote_branches,
    repo_json,
)
from tests.tui_helpers import CONFIG, make_app

pytestmark = pytest.mark.usefixtures("allow_file")


def result_for(path: Path) -> Any:
    result = sample_result()
    result.repos[0].path = str(path)
    return result


async def settle(app: RepoDoctorApp, pilot: Any) -> None:
    await pilot.pause(0.3)
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_detail(app: RepoDoctorApp, pilot: Any) -> DetailScreen:
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, DetailScreen)
    return app.screen


async def confirm(app: RepoDoctorApp, pilot: Any) -> ConfirmDialog:
    """Počká na dialog; ověří, že výchozí volba je Zrušit."""
    await settle(app, pilot)
    dialog = app.screen
    assert isinstance(dialog, ConfirmDialog)
    assert app.focused is not None and app.focused.id == "cancel"
    return dialog


async def press_ok(app: RepoDoctorApp, pilot: Any) -> None:
    await pilot.press("tab", "enter")
    await settle(app, pilot)


async def test_push_cancel_then_confirm(tmp_path: Path) -> None:
    rb, bare = fix_repo(tmp_path)
    app = make_app(tmp_path, result=result_for(rb.path))
    async with app.run_test(size=(120, 40)) as pilot:
        await open_detail(app, pilot)
        await pilot.press("P")
        dialog = await confirm(app, pilot)
        assert BRANCH in str(dialog.body) and SUBJECT in str(dialog.body)
        await pilot.press("enter")  # Zrušit
        await settle(app, pilot)
        assert isinstance(app.screen, DetailScreen)
        assert remote_branches(bare) == {"main"}
        await pilot.press("P")
        await confirm(app, pilot)
        await press_ok(app, pilot)
    assert remote_branches(bare) == {"main", BRANCH}


async def test_refusal_is_only_a_notification(tmp_path: Path) -> None:
    rb, _ = with_no_fix_branch(tmp_path)
    app = make_app(tmp_path, result=result_for(rb.path))
    async with app.run_test(size=(120, 40)) as pilot:
        await open_detail(app, pilot)
        await pilot.press("P")
        await settle(app, pilot)
        assert isinstance(app.screen, DetailScreen)  # žádný dialog
        assert any("nemá žádnou opravnou větev" in n.message for n in app._notifications)


def with_no_fix_branch(tmp_path: Path) -> tuple[RepoBuilder, Path]:
    from tests.factory import with_remote

    return with_remote(tmp_path)


async def test_local_merge_then_push_default(tmp_path: Path) -> None:
    rb, bare = fix_repo(tmp_path)
    app = make_app(tmp_path, result=result_for(rb.path))
    async with app.run_test(size=(120, 40)) as pilot:
        await open_detail(app, pilot)
        await pilot.press("L")
        dialog = await confirm(app, pilot)
        assert "fast-forward" in str(dialog.body) and "Nic se nepushne" in str(dialog.body)
        await press_ok(app, pilot)
        assert rb.git("rev-parse", "main").strip() == rb.git("rev-parse", BRANCH).strip()
        await pilot.press("U")
        await confirm(app, pilot)
        await press_ok(app, pilot)
    assert git(bare, "rev-parse", "main").strip() == rb.git("rev-parse", "main").strip()


@respx.mock
async def test_create_pr_and_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RD_TEST_TOKEN", TOKEN)
    rb, _ = fix_repo(tmp_path)
    rb.git("remote", "set-url", "origin", "https://github.com/nekdo/proj.git")
    sha = rb.git("rev-parse", BRANCH).strip()
    rb.git("update-ref", f"refs/remotes/origin/{BRANCH}", sha)
    config = CONFIG.replace(
        'name = "github"\ntype = "github"',
        'name = "github"\ntype = "github"\ntoken_env = "RD_TEST_TOKEN"',
    )
    respx.get(REPO_API).respond(json=repo_json())
    respx.get(f"{REPO_API}/pulls").respond(json=[])
    created = respx.post(f"{REPO_API}/pulls").respond(201, json=pr_json(sha))
    app = make_app(tmp_path, config=config, result=result_for(rb.path))
    async with app.run_test(size=(120, 40)) as pilot:
        await open_detail(app, pilot)
        await pilot.press("C")
        dialog = await confirm(app, pilot)
        assert "github" in str(dialog.body) and SUBJECT in str(dialog.body)
        await press_ok(app, pilot)
        assert created.called
        # merge: PR už existuje, CI běží → jen upozornění; po zelené CI dialog
        mock_pr_state(sha, checks=[{"status": "in_progress", "conclusion": None}])
        merged = respx.put(f"{REPO_API}/pulls/7/merge").respond(200, json={"merged": True})
        await pilot.press("M")
        await settle(app, pilot)
        assert isinstance(app.screen, DetailScreen)
        assert any("CI ještě běží" in n.message for n in app._notifications)
        assert not merged.called
        detail = mock_pr_state(sha, checks=GREEN)
        # náhled a kontrola před zápisem vidí otevřený PR, teprve po merge je mergnutý
        detail.side_effect = [
            httpx.Response(200, json=pr_json(sha)),
            httpx.Response(200, json=pr_json(sha)),
            httpx.Response(200, json=pr_json(sha, merged=True, state="closed")),
        ]
        await pilot.press("M")
        await confirm(app, pilot)
        await press_ok(app, pilot)
        assert merged.called
