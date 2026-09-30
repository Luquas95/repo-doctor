"""Parser URL remote a přiřazení repozitáře k hostingu.

Podporuje `git@host:owner/repo.git`, `ssh://git@host:2222/owner/repo.git`, HTTPS s portem,
`git://`, lokální cesty a SSH aliasy z `~/.ssh/config` (HostName, Port).
"""

from __future__ import annotations

import fnmatch
import glob
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from repo_doctor.config import ForgeConfig


@dataclass(frozen=True)
class RemoteURL:
    scheme: str  # ssh | https | http | git | file
    host: str | None
    port: int | None
    path: str  # owner/repo (bez .git a lomítek), u GitLabu i group/sub/repo
    user: str | None = None
    alias: str | None = None  # původní název hostitele, pokud šlo o SSH alias

    @property
    def owner(self) -> str:
        return self.path.split("/", 1)[0] if "/" in self.path else ""

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


def _clean_path(path: str) -> str:
    path = unquote(path).strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path.rstrip("/")


_SCP = re.compile(r"^(?:(?P<user>[^@/:\s]+)@)?(?P<host>\[[^\]]+\]|[^:/\s]+):(?P<path>(?!//).*)$")


class SshConfig:
    """Minimální parser ~/.ssh/config: Host (vzory, negace), HostName, Port, Include."""

    def __init__(self, entries: list[tuple[list[str], dict[str, str]]] | None = None) -> None:
        self.entries = entries or []

    @classmethod
    def load(cls, path: Path | None = None) -> SshConfig:
        path = path or Path.home() / ".ssh" / "config"
        entries: list[tuple[list[str], dict[str, str]]] = []
        cls._parse_file(path, entries, depth=0)
        return cls(entries)

    @classmethod
    def parse(cls, text: str, base: Path | None = None) -> SshConfig:
        entries: list[tuple[list[str], dict[str, str]]] = []
        cls._parse_text(text, entries, base or Path.home() / ".ssh", depth=0)
        return cls(entries)

    @classmethod
    def _parse_file(
        cls, path: Path, entries: list[tuple[list[str], dict[str, str]]], depth: int
    ) -> None:
        try:
            text = path.read_text("utf-8", "replace")
        except OSError:
            return
        cls._parse_text(text, entries, path.parent, depth)

    @classmethod
    def _parse_text(
        cls, text: str, entries: list[tuple[list[str], dict[str, str]]], base: Path, depth: int
    ) -> None:
        current: dict[str, str] | None = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.replace("=", " ", 1).partition(" ")
            key, value = key.lower(), value.strip().strip('"')
            if key == "host":
                current = {}
                entries.append((value.split(), current))
            elif key == "match":
                current = None  # Match bloky nevyhodnocujeme
            elif key == "include" and depth < 8:
                for pattern in value.split():
                    full = Path(pattern).expanduser()
                    if not full.is_absolute():
                        full = base / full
                    for inc in sorted(glob.glob(str(full))):  # noqa: PTH207 - absolutní vzor
                        cls._parse_file(Path(inc), entries, depth + 1)
            elif key in ("hostname", "port") and (current is not None or not entries):
                target = current if current is not None else {}
                if current is None:
                    entries.append((["*"], target))
                    current = target
                target.setdefault(key, value)

    def resolve(self, alias: str) -> tuple[str, int | None]:
        hostname: str | None = None
        port: int | None = None
        for patterns, options in self.entries:
            if not self._matches(alias, patterns):
                continue
            if hostname is None and "hostname" in options:
                hostname = options["hostname"].replace("%h", alias)
            if port is None and options.get("port", "").isdigit():
                port = int(options["port"])
        return (hostname or alias), port

    @staticmethod
    def _matches(alias: str, patterns: Iterable[str]) -> bool:
        matched = False
        for p in patterns:
            if p.startswith("!"):
                if fnmatch.fnmatchcase(alias, p[1:]):
                    return False
            elif fnmatch.fnmatchcase(alias, p):
                matched = True
        return matched


def parse_remote(url: str, ssh_config: SshConfig | None = None) -> RemoteURL | None:
    url = url.strip()
    if not url:
        return None
    if url.startswith("file://") or url.startswith(("/", "./", "../", "~")):
        return RemoteURL(
            "file",
            None,
            None,
            _clean_path(urlsplit(url).path if url.startswith("file://") else url),
        )
    if "://" in url:
        parts = urlsplit(url)
        scheme = parts.scheme.lower().replace("git+ssh", "ssh").replace("ssh+git", "ssh")
        if scheme not in {"ssh", "https", "http", "git"}:
            return None
        host = (parts.hostname or "").lower() or None
        try:
            port = parts.port
        except ValueError:
            port = None
        path = parts.path
        if scheme == "ssh" and path.startswith("/~"):
            path = path[2:]
        user = parts.username
        alias = None
        if scheme == "ssh" and host and ssh_config:
            resolved, ssh_port = ssh_config.resolve(host)
            if resolved.lower() != host:
                alias, host = host, resolved.lower()
            port = port or ssh_port
        if host is None:
            return None
        return RemoteURL(scheme, host, port, _clean_path(path), user, alias)
    m = _SCP.match(url)
    if not m:
        return None
    host = m.group("host").strip("[]").lower()
    port = None
    alias = None
    if ssh_config:
        resolved, port = ssh_config.resolve(m.group("host"))
        if resolved.lower() != host:
            alias, host = host, resolved.lower()
    return RemoteURL("ssh", host, port, _clean_path(m.group("path")), m.group("user"), alias)


def forge_web_host(forge: ForgeConfig) -> str:
    """Hostname, pod kterým se hosting objevuje v URL remote."""
    base = forge.base_url
    host = (urlsplit(base).hostname or "").lower()
    if host == "api.github.com":
        return "github.com"
    return host


def match_forge(remote: RemoteURL, forges: Iterable[ForgeConfig]) -> ForgeConfig | None:
    if remote.host is None:
        return None
    candidates = [f for f in forges if f.enabled and forge_web_host(f) == remote.host]
    if not candidates:
        return None
    if len(candidates) > 1:
        owner = remote.owner.lower()
        for f in candidates:
            if owner and owner in {(f.user or "").lower(), (f.org or "").lower()}:
                return f
    return candidates[0]


def web_url(remote: RemoteURL) -> str | None:
    if remote.host is None:
        return None
    return f"https://{remote.host}/{remote.path}"
