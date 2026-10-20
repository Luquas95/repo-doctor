from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import respx

from repo_doctor import cli, paths, secrets_scan, tools
from repo_doctor.tools import Download, InstallPlan, PackageManager, ToolsError
from tests.tui_helpers import FakeTools, make_app, screen_text

APT_HAS = "repo:\n  Installed: (none)\n  Candidate: 8.16.0-1\n"
APT_NONE = "repo:\n  Installed: (none)\n  Candidate: (none)\n"


def runner(code: int = 0, out: str = "") -> tools.Runner:
    return lambda _cmd: subprocess.CompletedProcess([], code, out, "")


def tool(tool_id: str) -> tools.Tool:
    return next(t for t in tools.TOOLS if t.id == tool_id)


# ---------------------------------------------------------------------- stav
def test_find_prefers_path_then_tools_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _b: None)
    assert tools.find("gitleaks") is None
    local = tools.tools_dir() / "gitleaks"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n")
    assert tools.find("gitleaks") is None  # bez práva spuštění se nepočítá
    local.chmod(0o755)
    assert tools.find("gitleaks") == str(local)
    assert tools.tools_dir() == paths.data_dir() / "tools"
    monkeypatch.setattr(shutil, "which", lambda b: f"/usr/bin/{b}")
    assert tools.find("gitleaks") == "/usr/bin/gitleaks"


def test_status_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda b: None if b in {"gitleaks", "wl-copy"} else f"/bin/{b}"
    )
    assert [t.id for t in tools.missing()] == ["gitleaks", "wl-clipboard"]
    by_id = {s.tool.id: s for s in tools.status()}
    assert by_id["xdg-utils"].installed and not by_id["gitleaks"].installed


def _downloaded_gitleaks(version: str | None) -> Path:
    local = tools.tools_dir() / "gitleaks"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("#!/bin/sh\n")
    local.chmod(0o755)
    if version is not None:
        (local.parent / "gitleaks.version").write_text(version + "\n")
    return local


def test_status_source_version_and_outdated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda b: None if b == "gitleaks" else f"/bin/{b}")
    assert tools.status()[0].source == "chybí"
    _downloaded_gitleaks("8.0.0")
    st = tools.tool_status(tool("gitleaks"))
    assert st.downloaded and st.version == "8.0.0" and st.outdated
    assert st.source == "stažený 8.0.0"
    assert [t.id for t in tools.outdated()] == ["gitleaks"]
    (tools.tools_dir() / "gitleaks.version").write_text(tools.GITLEAKS_VERSION)
    assert not tools.tool_status(tool("gitleaks")).outdated and not tools.outdated()
    (tools.tools_dir() / "gitleaks.version").unlink()  # stažený dřív, než se verze zapisovala
    st = tools.tool_status(tool("gitleaks"))
    assert st.outdated and st.source == "stažený (neznámá verze)"
    xdg = tools.tool_status(tool("xdg-utils"))
    assert xdg.source == "systém" and not xdg.downloaded and not xdg.outdated


def test_update_plan_only_downloads() -> None:
    p = tools.update_plan([tool("gitleaks"), tool("xdg-utils")])
    assert p.downloads == [tools.GITLEAKS] and p.command is None and not p.manual


def test_remove_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda b: None if b == "gitleaks" else f"/bin/{b}")
    local = _downloaded_gitleaks("8.0.0")
    assert tools.remove_download(tool("gitleaks")) == local
    assert not local.exists() and not (local.parent / "gitleaks.version").exists()
    with pytest.raises(ToolsError, match="správcem balíčků"):
        tools.remove_download(tool("xdg-utils"))  # ze systému se nemaže
    with pytest.raises(ToolsError):
        tools.remove_download(tool("gitleaks"))  # už není


def test_gitleaks_download_is_pinned() -> None:
    d = tools.GITLEAKS
    assert d.version in d.url and d.url.startswith("https://github.com/gitleaks/gitleaks/")
    assert len(d.sha256) == 64 and int(d.sha256, 16) >= 0
    assert tool("gitleaks").download is d


def test_secrets_scan_uses_downloaded_gitleaks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _b: None)
    assert not secrets_scan.gitleaks_available()
    local = tools.tools_dir() / "gitleaks"
    local.parent.mkdir(parents=True)
    local.write_text("")
    local.chmod(0o755)
    assert secrets_scan.gitleaks_path() == str(local)


def test_keyring_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring
    from keyring.backends import fail

    monkeypatch.setattr(keyring, "get_keyring", lambda: fail.Keyring())
    ok, detail = tools.keyring_status()
    assert not ok and "env" in detail

    class Good:
        name = "SecretService Keyring"

    monkeypatch.setattr(keyring, "get_keyring", lambda: Good())
    assert tools.keyring_status() == (True, "SecretService Keyring")

    def broken() -> object:
        raise RuntimeError("dbus")

    monkeypatch.setattr(keyring, "get_keyring", broken)
    assert tools.keyring_status()[0] is False


# ---------------------------------------------------------------------- distribuce
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('ID=debian\nVERSION_ID="12"\n', "apt"),
        ("ID=ubuntu\nID_LIKE=debian\n", "apt"),
        ("ID=linuxmint\nID_LIKE='ubuntu debian'\n", "apt"),
        ("ID=fedora\n", "dnf"),
        ('ID="rocky"\nID_LIKE="rhel centos fedora"\n', "dnf"),
        ("ID=arch\n", "pacman"),
        ("ID=endeavouros\nID_LIKE=arch\n", "pacman"),
        ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "zypper"),
        ("ID=nixos\n", None),
    ],
)
def test_detect_manager(tmp_path: Path, content: str, expected: str | None) -> None:
    f = tmp_path / "os-release"
    f.write_text(content)
    manager = tools.detect_manager(f, which=lambda b: f"/usr/bin/{b}")
    assert (manager.name if manager else None) == expected


def test_detect_manager_requires_binary(tmp_path: Path) -> None:
    f = tmp_path / "os-release"
    f.write_text("ID=debian\n")
    assert tools.detect_manager(f, which=lambda _b: None) is None
    assert tools.detect_manager(tmp_path / "chybi") is None


def test_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert PackageManager("apt").install_command(["gitleaks"]) == [
        *["sudo", "apt-get", "install", "gitleaks"]
    ]
    assert PackageManager("pacman").install_command(["x"]) == [
        *["sudo", "pacman", "-S", "--needed", "x"]
    ]
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    assert PackageManager("dnf").install_command(["x"]) == ["dnf", "install", "x"]
    assert PackageManager("zypper").install_command(["x"]) == ["zypper", "install", "x"]
    yes = {n: PackageManager(n).install_command(["x"], assume_yes=True) for n in ("apt", "dnf")}
    assert yes == {"apt": ["apt-get", "install", "-y", "x"], "dnf": ["dnf", "install", "-y", "x"]}
    assert "--noconfirm" in PackageManager("pacman").install_command(["x"], assume_yes=True)
    assert PackageManager("zypper").install_command(["x"], assume_yes=True)[:2] == [
        *["zypper", "--non-interactive"]
    ]


@pytest.mark.parametrize(
    ("name", "result", "expected"),
    [
        ("apt", (0, APT_HAS), True),
        ("apt", (0, APT_NONE), False),
        ("dnf", (0, "8.29.0\n"), True),
        ("dnf", (0, ""), False),
        ("pacman", (0, "Name: gitleaks"), True),
        ("pacman", (1, ""), False),
        ("zypper", (104, ""), False),
    ],
)
def test_has_package(name: str, result: tuple[int, str], expected: bool) -> None:
    pm = PackageManager(name, runner=runner(*result))  # type: ignore[arg-type]
    assert pm.has_package("gitleaks") is expected


def test_has_package_query_failure() -> None:
    def boom(_cmd: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    assert PackageManager("apt", runner=boom).has_package("x") is False


# ---------------------------------------------------------------------- plán
def test_plan_downloads_gitleaks_when_distro_lacks_it() -> None:
    apt = PackageManager("apt", runner=runner(0, APT_NONE))
    p = tools.plan([tool("gitleaks"), tool("libnotify")], apt)
    assert p.packages == ["libnotify-bin"] and p.downloads == [tools.GITLEAKS]
    lines = tools.describe(p)
    assert any("apt-get install libnotify-bin" in line for line in lines)
    assert any("SHA-256" in line for line in lines)


def test_plan_uses_distro_package_when_available() -> None:
    dnf = PackageManager("dnf", runner=runner(0, "8.29.0"))
    p = tools.plan([tool("gitleaks"), tool("wl-clipboard")], dnf)
    assert p.packages == ["gitleaks", "wl-clipboard"] and not p.downloads


def test_plan_unknown_distro() -> None:
    p = tools.plan([tool("gitleaks"), tool("xdg-utils")], None)
    assert p.command is None and p.downloads == [tools.GITLEAKS]
    assert [t.id for t in p.manual] == ["xdg-utils"]
    assert any("ručně" in line for line in tools.describe(p))
    assert tools.plan([], None).empty


def test_run_command(monkeypatch: pytest.MonkeyPatch) -> None:
    assert tools.run_command(InstallPlan(None)) == 0
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    p = InstallPlan(PackageManager("apt"), packages=["xdg-utils"])
    seen: list[list[str]] = []
    monkeypatch.setattr(shutil, "which", lambda b: f"/usr/bin/{b}")

    def record(cmd: list[str]) -> int:
        seen.append(cmd)
        return 7

    assert tools.run_command(p, runner=record) == 7
    assert seen == [["sudo", "apt-get", "install", "xdg-utils"]]
    monkeypatch.setattr(shutil, "which", lambda _b: None)
    with pytest.raises(ToolsError, match="sudo"):
        tools.run_command(p)


def test_run_command_real_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    p = InstallPlan(PackageManager("apt"), packages=["x"])
    monkeypatch.setattr(PackageManager, "install_command", lambda _s, _p, **_k: ["true"])
    assert tools.run_command(p) == 0
    monkeypatch.setattr(PackageManager, "install_command", lambda _s, _p, **_k: ["/neexistuje/x"])
    with pytest.raises(ToolsError, match="nejde spustit"):
        tools.run_command(p)


# ---------------------------------------------------------------------- stažení
def _archive(*, member: str = "gitleaks", symlink: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        readme = tarfile.TarInfo("README.md")
        readme.size = 2
        tar.addfile(readme, io.BytesIO(b"hi"))
        info = tarfile.TarInfo(member)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        else:
            info.size = 9
            tar.addfile(info, io.BytesIO(b"#!binary\n"))
    return buf.getvalue()


def _dl(blob: bytes, sha: str | None = None) -> Download:
    return Download(
        "gitleaks", "1.0", "https://example.invalid/gl.tar.gz",
        sha or hashlib.sha256(blob).hexdigest(), "gitleaks",
    )  # fmt: skip


@respx.mock
def test_install_download(tmp_path: Path) -> None:
    blob = _archive()
    respx.get("https://example.invalid/gl.tar.gz").respond(content=blob)
    path = tools.install_download(_dl(blob), target=tmp_path / "tools")
    assert path.read_bytes() == b"#!binary\n" and os.access(path, os.X_OK)
    # jen binárka a značka verze (archiv ani dočasné soubory nezůstanou)
    assert sorted(p.name for p in path.parent.iterdir()) == ["gitleaks", "gitleaks.version"]
    assert (path.parent / "gitleaks.version").read_text() == "1.0\n"


@respx.mock
def test_install_download_bad_checksum(tmp_path: Path) -> None:
    respx.get("https://example.invalid/gl.tar.gz").respond(content=_archive())
    with pytest.raises(ToolsError, match="součet"):
        tools.install_download(_dl(_archive(), sha="0" * 64), target=tmp_path)
    assert not (tmp_path / "gitleaks").exists()


@respx.mock
@pytest.mark.parametrize("kwargs", [{"member": "jiny"}, {"symlink": True}])
def test_install_download_unexpected_archive(tmp_path: Path, kwargs: dict[str, object]) -> None:
    blob = _archive(**kwargs)  # type: ignore[arg-type]
    respx.get("https://example.invalid/gl.tar.gz").respond(content=blob)
    with pytest.raises(ToolsError, match=r"obsah|rozbalit"):
        tools.install_download(_dl(blob), target=tmp_path)
    assert not (tmp_path / "gitleaks").exists()


@respx.mock
def test_install_download_http_error(tmp_path: Path) -> None:
    respx.get("https://example.invalid/gl.tar.gz").respond(404)
    with pytest.raises(ToolsError, match="404"):
        tools.install_download(_dl(b""), target=tmp_path)


# ---------------------------------------------------------------------- CLI
def _fake_module(monkeypatch: pytest.MonkeyPatch, fake: FakeTools) -> None:
    for name in (
        "status",
        "missing",
        "keyring_status",
        "detect_manager",
        "install_download",
        "remove_download",
    ):
        monkeypatch.setattr(tools, name, getattr(fake, name))
    monkeypatch.setattr(tools, "run_command", fake.run_command)


def test_cli_tools_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_module(monkeypatch, FakeTools(missing=("gitleaks",)))
    assert cli.main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "✗ gitleaks" in out and "✓ xdg-utils" in out and "klíčenka" in out
    assert "tools --install" in out


def test_cli_tools_all_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_module(monkeypatch, FakeTools())
    assert cli.main(["tools", "--install"]) == 0
    assert "--install" not in capsys.readouterr().out


def test_cli_tools_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTools(missing=("gitleaks", "libnotify"))
    _fake_module(monkeypatch, fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cli.main(["tools", "--install"]) == 2  # bez terminálu jen s --yes
    assert not fake.commands and not fake.downloads
    assert cli.main(["tools", "--install", "--yes"]) == 0
    assert fake.downloads == ["gitleaks"]
    assert fake.commands and fake.commands[0][-2:] == ["-y", "libnotify-bin"]
    fake.code = 100
    fake.missing_ids.add("libnotify")
    assert cli.main(["tools", "--install", "-y"]) == 1
    assert "kódem 100" in capsys.readouterr().err


def test_cli_tools_install_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTools(missing=("libnotify",))
    _fake_module(monkeypatch, fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("typer.confirm", lambda *_a, **_k: False)
    assert cli.main(["tools", "--install"]) == 1
    assert not fake.commands


def test_cli_tools_install_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTools(missing=("gitleaks",))
    _fake_module(monkeypatch, fake)

    def fail(_d: Download) -> Path:
        raise ToolsError("Kontrolní součet gitleaks nesedí")

    monkeypatch.setattr(tools, "install_download", fail)
    assert cli.main(["tools", "--install", "--yes"]) == 1
    assert "nesedí" in capsys.readouterr().err


def test_cli_tools_unknown_distro(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_module(monkeypatch, FakeTools(missing=("xdg-utils",), manager=None))
    assert cli.main(["tools", "--install", "--yes"]) == 0
    assert "ručně" in capsys.readouterr().out


def test_cli_tools_update(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTools(downloaded={"gitleaks": "8.0.0"})
    _fake_module(monkeypatch, fake)
    assert cli.main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "↑ gitleaks" in out and "[stažený 8.0.0]" in out and "tools --update" in out
    assert cli.main(["tools", "--update", "--yes"]) == 0
    assert fake.downloads == ["gitleaks"]
    assert cli.main(["tools", "--update"]) == 0
    assert "aktuální" in capsys.readouterr().out


def test_cli_tools_remove(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeTools(downloaded={"gitleaks": "8.0.0"})
    _fake_module(monkeypatch, fake)
    assert cli.main(["tools", "--remove", "nic"]) == 2
    assert cli.main(["tools", "--remove", "xdg-utils"]) == 1
    assert "správcem balíčků" in capsys.readouterr().err
    assert cli.main(["tools", "--remove", "gitleaks"]) == 0
    assert fake.removed == ["gitleaks"]


# ---------------------------------------------------------------------- TUI
async def _open_tools(app: object, pilot: object) -> None:
    await pilot.press("8")  # type: ignore[attr-defined]
    await app.workers.wait_for_complete()  # type: ignore[attr-defined]
    await pilot.pause()  # type: ignore[attr-defined]


async def test_tui_tools_screen_shows_status(tmp_path: Path) -> None:
    from repo_doctor.tui.screens.tools import ToolsScreen

    fake = FakeTools(missing=("wl-clipboard",), downloaded={"gitleaks": "8.0.0"})
    app = make_app(tmp_path, tools_backend=fake)
    async with app.run_test(size=(140, 40)) as pilot:
        await _open_tools(app, pilot)
        assert isinstance(app.screen, ToolsScreen)
        text = screen_text(app)
        assert "nástroje" in text and "klíčenka" in text
        assert f"stažený 8.0.0 → {tools.GITLEAKS_VERSION}" in text
        assert "systém" in text and "chybí" in text


async def test_tui_settings_points_to_tools_screen(tmp_path: Path) -> None:
    from textual.widgets import Static

    app = make_app(tmp_path)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("4")
        await pilot.pause()
        hint = app.screen.query_one("#tools-hint", Static)
        assert "obrazovce Nástroje (klávesa 8)" in str(hint.render())


async def test_tui_install_tools(tmp_path: Path) -> None:
    from repo_doctor.tui.screens.dialogs import ConfirmDialog

    fake = FakeTools(missing=("gitleaks", "wl-clipboard"))
    app = make_app(tmp_path, tools_backend=fake)
    async with app.run_test(size=(120, 40)) as pilot:
        await _open_tools(app, pilot)
        await pilot.press("i")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        assert "wl-clipboard" in str(app.screen.body) and "gitleaks" in str(app.screen.body)
        app.screen.dismiss(True)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert fake.downloads == ["gitleaks"]
        # headless terminál pozastavit nejde → příkaz se jen ukáže k ručnímu spuštění
        assert any("apt-get install wl-clipboard" in str(n.message) for n in app._notifications)


async def test_tui_install_nothing_missing(tmp_path: Path) -> None:
    app = make_app(tmp_path, tools_backend=FakeTools())
    async with app.run_test(size=(120, 40)) as pilot:
        await _open_tools(app, pilot)
        await pilot.press("i")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert any("Všechny" in str(n.message) for n in app._notifications)


async def test_tui_install_unknown_distro_only_advises(tmp_path: Path) -> None:
    from repo_doctor.tui.screens.dialogs import ConfirmDialog

    app = make_app(tmp_path, tools_backend=FakeTools(missing=("xdg-utils",), manager=None))
    async with app.run_test(size=(120, 40)) as pilot:
        await _open_tools(app, pilot)
        await pilot.press("i")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmDialog)
        assert any("ručně" in str(n.message) for n in app._notifications)


async def test_tui_update_downloaded_tool(tmp_path: Path) -> None:
    from repo_doctor.tui.screens.dialogs import ConfirmDialog

    fake = FakeTools(downloaded={"gitleaks": "8.0.0"})
    app = make_app(tmp_path, tools_backend=fake)
    async with app.run_test(size=(140, 40)) as pilot:
        await _open_tools(app, pilot)
        await pilot.press("u")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        app.screen.dismiss(True)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert fake.downloads == ["gitleaks"]
        assert fake.downloaded["gitleaks"] == tools.GITLEAKS_VERSION
        await pilot.press("u")  # už aktuální
        await pilot.pause()
        assert any("aktuální" in str(n.message) for n in app._notifications)


async def test_tui_remove_only_downloaded(tmp_path: Path) -> None:
    from repo_doctor.tui.screens.dialogs import ConfirmDialog

    fake = FakeTools(downloaded={"gitleaks": tools.GITLEAKS_VERSION})
    app = make_app(tmp_path, tools_backend=fake)
    async with app.run_test(size=(140, 40)) as pilot:
        await _open_tools(app, pilot)
        await pilot.press("j", "d")  # wl-clipboard je ze systému
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmDialog)
        assert any("správcem balíčků" in str(n.message) for n in app._notifications)
        await pilot.press("k", "d")  # gitleaks je stažený
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("enter")  # výchozí je Zrušit
        await pilot.pause()
        assert fake.removed == []
        await pilot.press("d")
        await pilot.pause()
        app.screen.dismiss(True)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert fake.removed == ["gitleaks"]
        assert "chybí" in screen_text(app)


async def test_tui_gitleaks_hint_once(tmp_path: Path) -> None:
    def hints(app: object) -> int:
        return sum("gitleaks" in str(n.message) for n in app._notifications)  # type: ignore[attr-defined]

    for expected in (1, 0):
        app = make_app(tmp_path, tools_backend=FakeTools(missing=("gitleaks",)), tools_hint=True)
        async with app.run_test(size=(100, 31)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert hints(app) == expected
    present = make_app(tmp_path, tools_backend=FakeTools(), tools_hint=True)
    (paths.cache_dir() / "tools-hint").unlink()
    async with present.run_test(size=(100, 31)) as pilot:
        await present.workers.wait_for_complete()
        await pilot.pause()
        assert hints(present) == 0
