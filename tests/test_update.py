from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
import respx
from packaging.version import Version

from repo_doctor import __version__, cli, schedule, update
from repo_doctor.config import Config
from repo_doctor.update import InstallKind, Release, UpdateError
from tests.tui_helpers import make_app

NEWER = Version(__version__).major + 1
NEWER_TAG = f"v{NEWER}.0.0"


def release(version: str = f"{NEWER}.0.0") -> Release:
    return Release(Version(version), f"v{version}")


# ---------------------------------------------------------------------- způsob instalace
def test_install_kind_from_marker(tmp_path: Path) -> None:
    assert update.install_kind(tmp_path) is InstallKind.SOURCE  # bez značky
    (tmp_path / "install-kind").write_text("deb\n")
    assert update.install_kind(tmp_path) is InstallKind.DEB
    (tmp_path / "install-kind").write_text("nesmysl")
    assert update.install_kind(tmp_path) is InstallKind.SOURCE


def test_install_kind_not_frozen_is_source() -> None:
    assert update.install_kind() is InstallKind.SOURCE


def test_install_kind_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "repo-doctor").write_text("")
    (tmp_path / "install-kind").write_text("rpm")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "repo-doctor"))
    assert update.install_kind() is InstallKind.RPM
    assert update.app_dir() == tmp_path.resolve()


def test_instructions_cover_every_kind() -> None:
    texts = {k: update.instructions(k) for k in InstallKind}
    assert "apt" in texts[InstallKind.DEB]
    assert "dnf" in texts[InstallKind.RPM]
    assert "repo-doctor update" in texts[InstallKind.TARBALL]
    assert all("uv" not in t.split() and "pipx" not in t for t in texts.values())


# ---------------------------------------------------------------------- GitHub Releases
@respx.mock
def test_fetch_latest() -> None:
    respx.get(update.LATEST_API).respond(json={"tag_name": "v1.2.3"})
    rel = update.fetch_latest()
    assert rel.version == Version("1.2.3") and rel.tag == "v1.2.3"


@respx.mock
@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(404), "Zatím není"),
        (httpx.Response(500), "nejsou dostupné"),
        (httpx.Response(200, json={"tag_name": "latest"}), "nečekanou"),
        (httpx.Response(200, json=[1, 2]), "nečekanou"),
    ],
)
def test_fetch_latest_errors(response: httpx.Response, message: str) -> None:
    respx.get(update.LATEST_API).mock(return_value=response)
    with pytest.raises(UpdateError, match=message):
        update.fetch_latest()


@respx.mock
def test_fetch_latest_network_error() -> None:
    respx.get(update.LATEST_API).mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(UpdateError, match="ConnectError"):
        update.fetch_latest()


def test_latest_cached_fetches_once_a_day(tmp_path: Path) -> None:
    cache = tmp_path / "c" / "update-check.json"
    calls: list[int] = []

    def fetch() -> Release:
        calls.append(1)
        return release("9.9.9")

    assert update.latest_cached(fetch, now=lambda: 1000.0, cache=cache) == Version("9.9.9")
    assert update.latest_cached(fetch, now=lambda: 2000.0, cache=cache) == Version("9.9.9")
    assert len(calls) == 1
    later = 1000.0 + update.CHECK_INTERVAL_S + 1
    update.latest_cached(fetch, now=lambda: later, cache=cache)
    assert len(calls) == 2


def test_latest_cached_survives_errors(tmp_path: Path) -> None:
    cache = tmp_path / "update-check.json"
    cache.write_text("{rozbité")

    def fail() -> Release:
        raise UpdateError("offline")

    assert update.latest_cached(fail, cache=cache) is None


def test_notice(tmp_path: Path) -> None:
    msg = update.notice(lambda: release(), kind=InstallKind.DEB, cache=tmp_path / "a.json")
    assert msg is not None and f"{NEWER}.0.0" in msg and "apt" in msg
    same = update.notice(lambda: release(__version__), cache=tmp_path / "b.json")
    assert same is None


# ---------------------------------------------------------------------- podpis
needs_gpg = pytest.mark.skipif(shutil.which("gpg") is None, reason="chybí gpg")


@pytest.fixture(scope="module")
def signer(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, bytes, str]:
    home = tmp_path_factory.mktemp("gnupg")
    home.chmod(0o700)
    env = {**os.environ, "GNUPGHOME": str(home)}
    run = {"env": env, "check": True, "capture_output": True}
    subprocess.run(
        [
            *["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", ""],
            *["--quick-gen-key", "test <t@example.invalid>", "ed25519", "sign", "never"],
        ],
        **run,  # type: ignore[call-overload]
    )
    out = subprocess.run(["gpg", "--list-keys", "--with-colons"], text=True, **run)  # type: ignore[call-overload]
    fpr = next(line.split(":")[9] for line in out.stdout.splitlines() if line.startswith("fpr"))
    key = subprocess.run(["gpg", "--armor", "--export", fpr], **run).stdout  # type: ignore[call-overload]
    return home, key, fpr


def _sign(home: Path, data: Path) -> Path:
    sig = data.with_name(data.name + ".asc")
    subprocess.run(
        ["gpg", "--batch", "--yes", "--armor", "--detach-sign", "-o", str(sig), str(data)],
        env={**os.environ, "GNUPGHOME": str(home)},
        check=True,
        capture_output=True,
    )
    return sig


@needs_gpg
@pytest.mark.parametrize("use_gpgv", [True, False])
def test_verify_signature(
    signer: tuple[Path, bytes, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_gpgv: bool,
) -> None:
    home, key, fpr = signer
    if not use_gpgv:
        real = shutil.which
        monkeypatch.setattr(shutil, "which", lambda n: None if n == "gpgv" else real(n))
    data = tmp_path / "SHA256SUMS"
    data.write_text("abc  soubor\n")
    sig = _sign(home, data)
    update.verify_signature(data, sig, key=key, fingerprint=fpr)
    with pytest.raises(UpdateError, match="neplatí"):
        update.verify_signature(data, sig, key=key, fingerprint="0" * 40)
    data.write_text("podvržený obsah\n")
    with pytest.raises(UpdateError, match="neplatí"):
        update.verify_signature(data, sig, key=key, fingerprint=fpr)


@needs_gpg
def test_verify_rejects_other_key(signer: tuple[Path, bytes, str], tmp_path: Path) -> None:
    """Podpis cizím klíčem neprojde – ověřuje se jen proti zabudovanému klíči vydání."""
    home, _key, _fpr = signer
    data = tmp_path / "SHA256SUMS"
    data.write_text("x\n")
    with pytest.raises(UpdateError, match="neplatí"):
        update.verify_signature(data, _sign(home, data))


def test_embedded_key_is_packaged() -> None:
    key = Path(update.__file__).parent / "data" / "signing-key.asc"
    assert key.read_text().startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----")


def test_verify_without_gpg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    with pytest.raises(UpdateError, match="GnuPG"):
        update.verify_signature(tmp_path / "a", tmp_path / "b")


# ---------------------------------------------------------------------- samoaktualizace
def _tarball(content: str, *, kind: str = "tarball", extra: tarfile.TarInfo | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (
            ("repo-doctor/repo-doctor", content),
            ("repo-doctor/install-kind", kind),
        ):
            raw = data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(raw))
        if extra is not None:
            tar.addfile(extra, io.BytesIO(b"x" * extra.size))
    return buf.getvalue()


def _installed(tmp_path: Path) -> Path:
    target = tmp_path / "lib" / "repo-doctor"
    target.mkdir(parents=True)
    (target / "repo-doctor").write_text("stará")
    (target / "install-kind").write_text("tarball")
    return target


def _mock_release(blob: bytes, *, sha: str | None = None) -> None:
    base = f"{update.DOWNLOAD_BASE}/{NEWER_TAG}"
    digest = sha or hashlib.sha256(blob).hexdigest()
    respx.get(f"{base}/SHA256SUMS").respond(text=f"{digest}  {update.TARBALL}\n")
    respx.get(f"{base}/SHA256SUMS.asc").respond(text="podpis")
    respx.get(f"{base}/{update.TARBALL}").respond(content=blob)


def _ok(_data: Path, _sig: Path) -> None:
    return None


@respx.mock
def test_self_update_replaces_app(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    _mock_release(_tarball("nová"))
    steps: list[str] = []
    update.self_update(release(), target=target, verify=_ok, progress=steps.append)
    assert (target / "repo-doctor").read_text() == "nová"
    assert os.access(target / "repo-doctor", os.X_OK)
    assert (target.parent / update.OLD_DIR / "repo-doctor").read_text() == "stará"
    assert any("podpis" in s for s in steps)
    # další aktualizace starou kopii uklidí
    update.self_update(release(), target=target, verify=_ok)
    assert (target.parent / update.OLD_DIR / "repo-doctor").read_text() == "nová"
    assert not [p for p in target.parent.iterdir() if p.name.startswith(".repo-doctor-update")]


@respx.mock
def test_self_update_bad_signature_keeps_app(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    _mock_release(_tarball("nová"))

    def bad(_d: Path, _s: Path) -> None:
        raise UpdateError("Podpis aktualizace neplatí")

    with pytest.raises(UpdateError, match="neplatí"):
        update.self_update(release(), target=target, verify=bad)
    assert (target / "repo-doctor").read_text() == "stará"


@respx.mock
def test_self_update_checksum_mismatch(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    _mock_release(_tarball("nová"), sha="0" * 64)
    with pytest.raises(UpdateError, match="Kontrolní součet"):
        update.self_update(release(), target=target, verify=_ok)
    assert (target / "repo-doctor").read_text() == "stará"


@respx.mock
def test_self_update_rejects_path_traversal(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    evil = tarfile.TarInfo("../../venku")
    evil.size = 1
    _mock_release(_tarball("nová", extra=evil))
    with pytest.raises(UpdateError, match="rozbalit"):
        update.self_update(release(), target=target, verify=_ok)
    assert not (tmp_path / "venku").exists()
    assert (target / "repo-doctor").read_text() == "stará"


@respx.mock
def test_self_update_rejects_wrong_content(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    _mock_release(_tarball("nová", kind="deb"))
    with pytest.raises(UpdateError, match="obsah"):
        update.self_update(release(), target=target, verify=_ok)


@respx.mock
def test_self_update_missing_asset(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    respx.get(url__startswith=update.DOWNLOAD_BASE).respond(404)
    with pytest.raises(UpdateError, match="HTTP 404"):
        update.self_update(release(), target=target, verify=_ok)


@respx.mock
def test_self_update_sums_without_tarball(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    base = f"{update.DOWNLOAD_BASE}/{NEWER_TAG}"
    respx.get(f"{base}/SHA256SUMS").respond(text="abc  jiny-soubor\n")
    respx.get(f"{base}/SHA256SUMS.asc").respond(text="podpis")
    with pytest.raises(UpdateError, match="chybí"):
        update.self_update(release(), target=target, verify=_ok)


def test_self_update_only_for_tarball(tmp_path: Path) -> None:
    target = _installed(tmp_path)
    (target / "install-kind").write_text("deb")
    with pytest.raises(UpdateError, match="tarballu"):
        update.self_update(release(), target=target, verify=_ok)


# ---------------------------------------------------------------------- CLI, TUI, konfigurace
def test_cli_update_up_to_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(update, "fetch_latest", lambda: release(__version__))
    assert cli.main(["update"]) == 0
    assert "nejnovější" in capsys.readouterr().out


def test_cli_update_package_prints_instructions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    monkeypatch.setattr(update, "install_kind", lambda: InstallKind.DEB)
    called: list[int] = []
    monkeypatch.setattr(update, "self_update", lambda *_a, **_k: called.append(1))
    assert cli.main(["update"]) == 0
    out = capsys.readouterr().out
    assert f"{NEWER}.0.0" in out and "apt" in out and not called


def test_cli_update_tarball(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    monkeypatch.setattr(update, "install_kind", lambda: InstallKind.TARBALL)
    called: list[Release] = []
    monkeypatch.setattr(update, "self_update", lambda rel, **_k: called.append(rel))
    assert cli.main(["update", "--check"]) == 0
    assert not called
    assert cli.main(["update"]) == 0
    assert called and "Aktualizováno" in capsys.readouterr().out


def test_cli_update_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def offline() -> Release:
        raise UpdateError("GitHub Releases nejsou dostupné")

    monkeypatch.setattr(update, "fetch_latest", offline)
    assert cli.main(["update"]) == 2
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    monkeypatch.setattr(update, "install_kind", lambda: InstallKind.TARBALL)

    def broken(*_a: object, **_k: object) -> None:
        raise UpdateError("Podpis aktualizace neplatí")

    monkeypatch.setattr(update, "self_update", broken)
    assert cli.main(["update"]) == 1
    assert "neplatí" in capsys.readouterr().err


async def test_tui_shows_update_notice(tmp_path: Path) -> None:
    app = make_app(tmp_path, update_checker=lambda: "Je dostupná verze 9.0.0")
    async with app.run_test(size=(100, 31)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert any("9.0.0" in str(n.message) for n in app._notifications)


async def test_tui_update_check_respects_config_and_offline(tmp_path: Path) -> None:
    calls: list[int] = []

    def checker() -> str | None:
        calls.append(1)
        return None

    off = make_app(tmp_path, config="[updates]\ncheck = false\n", update_checker=checker)
    async with off.run_test(size=(100, 31)) as pilot:
        await pilot.pause()
    offline = make_app(tmp_path, offline=True, update_checker=checker)
    async with offline.run_test(size=(100, 31)) as pilot:
        await pilot.pause()
    assert calls == []


def test_config_updates_default() -> None:
    assert Config().updates.check is True


def test_schedule_executable_frozen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "repo-doctor"))
    assert schedule.executable() == str(tmp_path / "repo-doctor")
