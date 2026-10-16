"""Volitelné systémové nástroje: stav, plán instalace a stažení gitleaks.

Systémové balíčky instaluje správce balíčků distribuce (`sudo apt-get install …` apod.)
spuštěný viditelně v terminálu – repo-doctor sám root nikdy nezíská. Kde distribuce gitleaks
nemá (Debian 12, Ubuntu 22.04), stáhne se oficiální binárka do `~/.local/share/repo-doctor/tools`
a ověří proti SHA-256 zapsanému tady v kódu (ne proti součtu staženému ze stejného místa).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx

from repo_doctor import paths

ManagerName = Literal["apt", "dnf", "pacman", "zypper"]
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class ToolsError(Exception):
    """Instalace nástroje selhala; zpráva je pro uživatele."""


@dataclass(frozen=True)
class Download:
    """Binárka stahovaná mimo správce balíčků – verze a součet jsou připnuté v kódu."""

    name: str
    version: str
    url: str
    sha256: str
    member: str  # cesta binárky uvnitř tar.gz


GITLEAKS_VERSION = "8.30.1"
GITLEAKS = Download(
    name="gitleaks",
    version=GITLEAKS_VERSION,
    url=(
        f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}/"
        f"gitleaks_{GITLEAKS_VERSION}_linux_x64.tar.gz"
    ),
    sha256="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    member="gitleaks",
)


@dataclass(frozen=True)
class Tool:
    id: str
    binary: str
    purpose: str
    packages: dict[ManagerName, str]
    download: Download | None = None


def _same(pkg: str) -> dict[ManagerName, str]:
    return {"apt": pkg, "dnf": pkg, "pacman": pkg, "zypper": pkg}


TOOLS: tuple[Tool, ...] = (
    Tool(
        "gitleaks", "gitleaks", "rychlejší a přesnější sken tajemství", _same("gitleaks"), GITLEAKS
    ),
    Tool(
        "wl-clipboard", "wl-copy", "kopírování cesty do schránky (Wayland)", _same("wl-clipboard")
    ),
    Tool("xdg-utils", "xdg-open", "otevření repa na webu", _same("xdg-utils")),
    Tool(
        "libnotify",
        "notify-send",
        "upozornění plánovaného skenu na ploše",
        {
            "apt": "libnotify-bin",
            "dnf": "libnotify",
            "pacman": "libnotify",
            "zypper": "libnotify-tools",
        },
    ),
)


def tools_dir() -> Path:
    return paths.data_dir() / "tools"


def find(binary: str) -> str | None:
    """Cesta k nástroji: z PATH, jinak ze složky stažených nástrojů repo-doctoru."""
    found = shutil.which(binary)
    if found:
        return found
    local = tools_dir() / binary
    return str(local) if local.is_file() and os.access(local, os.X_OK) else None


@dataclass(frozen=True)
class ToolStatus:
    tool: Tool
    path: str | None

    @property
    def installed(self) -> bool:
        return self.path is not None


def status() -> list[ToolStatus]:
    return [ToolStatus(t, find(t.binary)) for t in TOOLS]


def missing() -> list[Tool]:
    return [s.tool for s in status() if not s.installed]


def keyring_status() -> tuple[bool, str]:
    """Je k dispozici klíčenka pro tokeny? Klíčenka se neinstaluje – musí běžet v relaci."""
    try:
        import keyring
        from keyring.backends import chainer, fail

        backend = keyring.get_keyring()
    except Exception as err:  # backendy keyringu hází různé výjimky
        return False, f"klíčenka není dostupná ({type(err).__name__})"
    if isinstance(backend, fail.Keyring) or (
        isinstance(backend, chainer.ChainerBackend) and not backend.backends
    ):
        return False, "žádná klíčenka (Secret Service) neběží – tokeny jdou přes env nebo cmd"
    return True, getattr(backend, "name", type(backend).__name__)


# ---------------------------------------------------------------------- správce balíčků
_FAMILIES: dict[str, ManagerName] = {
    "debian": "apt",
    "ubuntu": "apt",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "arch": "pacman",
    "suse": "zypper",
    "opensuse": "zypper",
}


def _os_ids(os_release: Path) -> list[str]:
    try:
        text = os_release.read_text("utf-8")
    except OSError:
        return []
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip("\"'")
    return [values.get("ID", ""), *values.get("ID_LIKE", "").split()]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, check=False, stdin=subprocess.DEVNULL
    )


@dataclass(frozen=True)
class PackageManager:
    name: ManagerName
    runner: Runner = field(default=_run, compare=False, repr=False)

    def install_command(self, packages: list[str], *, assume_yes: bool = False) -> list[str]:
        """Bez `assume_yes` se správce balíčků sám zeptá (a ukáže i závislosti)."""
        cmd: list[str] = {
            "apt": ["apt-get", "install", *(["-y"] if assume_yes else [])],
            "dnf": ["dnf", "install", *(["-y"] if assume_yes else [])],
            "pacman": ["pacman", "-S", "--needed", *(["--noconfirm"] if assume_yes else [])],
            "zypper": [*(["zypper", "--non-interactive"] if assume_yes else ["zypper"]), "install"],
        }[self.name]
        prefix = [] if os.geteuid() == 0 else ["sudo"]
        return [*prefix, *cmd, *packages]

    def has_package(self, package: str) -> bool:
        """Má distribuce balíček v repozitářích? (bez roota, jen dotaz)"""
        query: list[str] = {
            "apt": ["apt-cache", "policy", package],
            "dnf": ["dnf", "-q", "repoquery", "--latest-limit", "1", package],
            "pacman": ["pacman", "-Si", package],
            "zypper": [
                "zypper",
                "--non-interactive",
                "--quiet",
                "search",
                "--match-exact",
                package,
            ],
        }[self.name]
        try:
            proc = self.runner(query)
        except (OSError, subprocess.SubprocessError):
            return False
        if self.name == "apt":
            return any(
                line.strip().startswith("Candidate:") and "(none)" not in line
                for line in proc.stdout.splitlines()
            )
        if self.name == "dnf":
            return proc.returncode == 0 and bool(proc.stdout.strip())
        return proc.returncode == 0


def detect_manager(
    os_release: Path = Path("/etc/os-release"), which: Callable[[str], str | None] = shutil.which
) -> PackageManager | None:
    for os_id in _os_ids(os_release):
        name = _FAMILIES.get(os_id)
        if name is not None and which(name if name != "apt" else "apt-get"):
            return PackageManager(name)
    return None


# ---------------------------------------------------------------------- plán a instalace
@dataclass
class InstallPlan:
    manager: PackageManager | None
    packages: list[str] = field(default_factory=list)
    downloads: list[Download] = field(default_factory=list)
    manual: list[Tool] = field(default_factory=list)  # neznámá distribuce – jen poradit
    assume_yes: bool = False  # `--yes` v CLI: správce balíčků se už neptá

    @property
    def command(self) -> list[str] | None:
        if self.manager is None or not self.packages:
            return None
        return self.manager.install_command(self.packages, assume_yes=self.assume_yes)

    @property
    def empty(self) -> bool:
        return not (self.packages or self.downloads or self.manual)


def plan(tools: list[Tool], manager: PackageManager | None) -> InstallPlan:
    result = InstallPlan(manager)
    for tool in tools:
        if manager is not None:
            package = tool.packages[manager.name]
            if tool.download is None or manager.has_package(package):
                result.packages.append(package)
                continue
        if tool.download is not None:
            result.downloads.append(tool.download)
        else:
            result.manual.append(tool)
    return result


def describe(p: InstallPlan) -> list[str]:
    """Řádky pro náhled před potvrzením (TUI i CLI)."""
    lines: list[str] = []
    if p.command:
        lines.append(f"Spustí v terminálu: {' '.join(p.command)}")
    for d in p.downloads:
        lines.append(
            f"Stáhne {d.name} {d.version} z GitHubu do {tools_dir()} "
            f"(ověří SHA-256 zapsaný v repo-doctoru)"
        )
    for tool in p.manual:
        lines.append(f"Nainstaluj ručně: {tool.id} ({tool.purpose})")
    return lines


def run_command(p: InstallPlan, runner: Callable[[list[str]], int] | None = None) -> int:
    """Spustí instalaci systémových balíčků v aktuálním terminálu (interaktivně, kvůli sudo)."""
    if p.command is None:
        return 0
    if p.command[0] == "sudo" and shutil.which("sudo") is None:
        raise ToolsError("Chybí sudo – spusť příkaz jako root: " + " ".join(p.command[1:]))
    if runner is not None:
        return runner(p.command)
    try:
        return subprocess.run(p.command, check=False).returncode
    except OSError as err:
        raise ToolsError(f"Příkaz nejde spustit: {type(err).__name__}") from None


def install_download(
    d: Download, *, client: httpx.Client | None = None, target: Path | None = None
) -> Path:
    """Stáhne binárku, ověří připnutý SHA-256 a z archivu vybalí jen ji."""
    from repo_doctor.update import UpdateError, _client, _download, _sha256

    target = target or tools_dir()
    paths.ensure_private_dir(target)
    own = client is None
    http = client or _client()
    try:
        with tempfile.TemporaryDirectory(prefix=".download-", dir=target) as tmp:
            archive = Path(tmp) / "archive.tar.gz"
            _download(http, d.url, archive)
            if _sha256(archive) != d.sha256:
                raise ToolsError(f"Kontrolní součet {d.name} nesedí – soubor nepoužiju.")
            staged = Path(tmp) / d.name
            try:
                with tarfile.open(archive, "r:gz") as tar:
                    member = tar.getmember(d.member)
                    source = tar.extractfile(member) if member.isfile() else None
                    if source is None:
                        raise ToolsError(f"Archiv {d.name} nemá očekávaný obsah.")
                    with source, staged.open("wb") as out:
                        shutil.copyfileobj(source, out)
            except (tarfile.TarError, KeyError):
                raise ToolsError(f"Archiv {d.name} nejde rozbalit.") from None
            staged.chmod(0o755)
            final = target / d.name
            staged.replace(final)
    except httpx.HTTPError as err:
        raise ToolsError(f"Stažení {d.name} selhalo: {type(err).__name__}") from None
    except UpdateError as err:  # HTTP chyba nebo překročená velikost z _download
        raise ToolsError(str(err)) from None
    finally:
        if own:
            http.close()
    return final
