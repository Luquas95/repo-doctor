"""Závislosti do hloubky: rozjetý lockfile, nepřipnuté verze, instalační skripty a balíčky,
které autor opustil nebo označil jako zastaralé (to jediné používá data registrů ze skeneru).

Manifesty a lockfily jsou cizí vstup: čtou se jen jako text/JSON/TOML, hodnoty se typově
ověřují a nepovedený parser znamená „tento soubor přeskočit“, nikdy pád kontroly.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.checks.deps import _require_network
from repo_doctor.czech import count
from repo_doctor.deps import (
    _norm_py,
    cargo_direct,
    parse_pnpm_lock,
    parse_yarn_lock,
    pyproject_direct,
)
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity

ABANDONED_YEARS = 3  # PyPI: poslední vydání starší než tohle = opuštěný balíček
MAX_NAMES = 8  # kolik jmen se vypíše ve zprávě (celý seznam je v `data`)
MAX_DEPTH = 3
_SKIP_DIRS = frozenset({"fixtures", "testdata", "__fixtures__", "node_modules", "vendor"})

_NPM_LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml")
_PY_LOCKS = ("uv.lock", "poetry.lock", "pdm.lock")


def _dir(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent + "/"


def _files(repo: RepoContext, *names: str) -> list[str]:
    """Sledované soubory daných názvů do hloubky 3, mimo fixtury, `node_modules` a `vendor`."""
    return [
        f
        for f in repo.tracked_files
        if f.count("/") <= MAX_DEPTH
        and PurePosixPath(f).name in names
        and not _SKIP_DIRS & set(PurePosixPath(f).parts[:-1])
    ]


def _json(text: str | None) -> dict[str, Any]:
    try:
        data = json.loads(text) if text else None
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _toml(text: str | None) -> dict[str, Any]:
    try:
        return tomllib.loads(text) if text else {}
    except (tomllib.TOMLDecodeError, RecursionError, ValueError):
        return {}


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _names(names: list[str] | set[str]) -> str:
    shown = sorted(names)[:MAX_NAMES]
    more = len(names) - len(shown)
    return ", ".join(shown) + (f" (+{more})" if more > 0 else "")


# --------------------------------------------------------------------------- rozjetý lock


def _npm_lock_names(name: str, text: str) -> set[str] | None:
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        data = _json(text)
        packages = _section(data, "packages")
        if packages:
            return {k.rsplit("node_modules/", 1)[1] for k in packages if "node_modules/" in k}
        legacy = _section(data, "dependencies")
        return set(legacy) if legacy else None
    parser = parse_yarn_lock if name == "yarn.lock" else parse_pnpm_lock
    found = {d.name for d in parser(text, name)}
    return found or None


def _declared_npm(data: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for dep, spec in _section(data, key).items():
            if isinstance(dep, str) and not (
                isinstance(spec, str) and spec.startswith(("workspace:", "file:", "link:"))
            ):
                names.add(dep)
    return names


@register
class DepsLockDrift(Check):
    id = "deps-lock-drift"
    title = N_("Lockfile nesedí s manifestem")
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        for manifest in _files(repo, "package.json", "pyproject.toml", "Cargo.toml"):
            missing = self._missing(repo, manifest)
            if missing is None or not missing[1]:
                continue
            lock, names = missing
            findings.append(
                self.finding(
                    _(
                        "{manifest} deklaruje {names}, ale v {lock} nejsou: lockfile je zastaralý "
                        "a instalace z něj tyto balíčky nezíská."
                    ).format(
                        manifest=manifest,
                        names=_names(names),
                        lock=lock,
                    ),
                    path=manifest,
                    key=manifest,
                    lockfile=lock,
                    missing=sorted(names),
                )
            )
        return findings

    def _missing(self, repo: RepoContext, manifest: str) -> tuple[str, set[str]] | None:
        """(lockfile, deklarované závislosti, které v něm chybí); None, když nelze porovnat."""
        name, folder = PurePosixPath(manifest).name, _dir(manifest)
        text = repo.read_text(manifest)
        if text is None:
            return None
        if name == "package.json":
            data = _json(text)
            if "workspaces" in data or f"{folder}pnpm-workspace.yaml" in repo.tracked_set:
                return None  # členové workspace mají lock v kořeni a vlastní jména
            declared = _declared_npm(data)
            for lock in _NPM_LOCKS:
                if f"{folder}{lock}" in repo.tracked_set:
                    locked = _npm_lock_names(lock, repo.read_text(f"{folder}{lock}") or "")
                    return (f"{folder}{lock}", declared - locked) if locked is not None else None
            return None
        if name == "pyproject.toml":
            data = _toml(text)
            if _section(_section(_section(data, "tool"), "uv"), "workspace"):
                return None
            for lock in _PY_LOCKS:
                if f"{folder}{lock}" in repo.tracked_set:
                    packages = _toml(repo.read_text(f"{folder}{lock}")).get("package")
                    if not isinstance(packages, list):
                        return None
                    locked = {
                        _norm_py(p["name"])
                        for p in packages
                        if isinstance(p, dict) and isinstance(p.get("name"), str)
                    }
                    declared, _pinned, _has = pyproject_direct(text)
                    return f"{folder}{lock}", declared - locked
            return None
        if "[workspace]" in text or f"{folder}Cargo.lock" not in repo.tracked_set:
            return None
        packages = _toml(repo.read_text(f"{folder}Cargo.lock")).get("package")
        if not isinstance(packages, list):
            return None
        locked = {
            p["name"] for p in packages if isinstance(p, dict) and isinstance(p.get("name"), str)
        }
        return f"{folder}Cargo.lock", cargo_direct(text) - locked


# --------------------------------------------------------------------------- nepřipnuté verze

_FLOATING = frozenset({"", "*", "x", "X", "latest"})
_GIT_PREFIX = ("git+", "git:", "github:", "gitlab:", "bitbucket:")
_NPM_SHORTHAND = re.compile(r"^[\w.-]{1,100}/[\w.-]{1,100}$")
_REQ_BARE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}(\[[^\]]{0,200}\])?\s*(;.*)?$")


def _git_without_ref(url: str) -> bool:
    """Git URL bez `@ref` v cestě (uživatel v `git@host` se nepočítá, `#egg=` také ne)."""
    path = url.split("#", 1)[0].split("://", 1)[-1].split("/", 1)[-1]
    return "@" not in path


def _unpinned_npm(text: str) -> set[str]:
    out: set[str] = set()
    data = _json(text)
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        for dep, spec in _section(data, key).items():
            if not isinstance(dep, str) or not isinstance(spec, str):
                continue
            spec = spec.strip()
            git = spec.startswith(_GIT_PREFIX) or bool(_NPM_SHORTHAND.match(spec))
            if spec in _FLOATING or (git and "#" not in spec):
                out.add(dep)
    return out


def _unpinned_requirements(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.splitlines()[:5000]:
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("-") or len(line) > 500:
            continue
        if line.startswith("git+"):
            if _git_without_ref(line):
                out.add(line.split("#egg=")[-1] if "#egg=" in line else line[:80])
        elif _REQ_BARE.match(line):
            out.add(re.split(r"[\[;\s]", line, maxsplit=1)[0])
    return out


def _unpinned_pyproject(text: str) -> set[str]:
    data = _toml(text)
    specs: list[Any] = list(_section(data, "project").get("dependencies") or [])
    out: set[str] = set()
    for spec in specs:
        if not isinstance(spec, str):
            continue
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            continue
        if req.url and req.url.startswith("git+") and _git_without_ref(req.url):
            out.add(req.name)
    return out


def _unpinned_cargo(text: str) -> set[str]:
    out: set[str] = set()
    data = _toml(text)
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        for dep, spec in _section(data, key).items():
            if spec == "*" or (
                isinstance(spec, dict)
                and (
                    spec.get("version") == "*"
                    or ("git" in spec and not ({"rev", "tag"} & set(spec)))
                )
            ):
                out.add(str(dep))
    return out


@register
class DepsUnpinned(Check):
    id = "deps-unpinned"
    title = N_("Nepřipnuté verze závislostí")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        names = ("package.json", "pyproject.toml", "Cargo.toml")
        paths = _files(repo, *names) + [
            f
            for f in repo.tracked_files
            if f.count("/") <= MAX_DEPTH
            and re.fullmatch(r"requirements[\w.-]*\.txt", PurePosixPath(f).name)
            and not _SKIP_DIRS & set(PurePosixPath(f).parts[:-1])
        ]
        for path in sorted(paths):
            text = repo.read_text(path)
            if text is None:
                continue
            name = PurePosixPath(path).name
            if name == "package.json":
                loose = _unpinned_npm(text)
            elif name == "pyproject.toml":
                loose = _unpinned_pyproject(text)
            elif name == "Cargo.toml":
                loose = _unpinned_cargo(text)
            else:
                loose = _unpinned_requirements(text)
            if not loose:
                continue
            findings.append(
                self.finding(
                    _(
                        "{count} bez pevné verze ({names}): při každé instalaci se může stáhnout "
                        "jiný kód."
                    ).format(
                        count=count(len(loose), _("závislost"), _("závislosti"), _("závislostí")),
                        names=_names(loose),
                    ),
                    path=path,
                    key=path,
                    packages=sorted(loose),
                )
            )
        return findings


# --------------------------------------------------------------------------- instalační skripty

_IGNORE_SCRIPTS = re.compile(r"^\s*ignore-scripts\s*=\s*true\b", re.MULTILINE | re.IGNORECASE)


@register
class DepsInstallScripts(Check):
    id = "deps-install-scripts"
    title = N_("Závislosti spouštějící skripty při instalaci")
    severity = Severity.LOW
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        for lock in _files(repo, "package-lock.json", "npm-shrinkwrap.json"):
            folder = _dir(lock)
            if any(
                _IGNORE_SCRIPTS.search(repo.read_text(rc) or "")
                for rc in (f"{folder}.npmrc", ".npmrc")
                if rc in repo.tracked_set
            ):
                continue
            packages = _section(_json(repo.read_text(lock)), "packages")
            scripted = {
                key.rsplit("node_modules/", 1)[1]
                for key, info in packages.items()
                if key
                and "node_modules/" in key
                and isinstance(info, dict)
                and info.get("hasInstallScript") is True
            }
            if not scripted:
                continue
            findings.append(
                self.finding(
                    _(
                        "{count} spouští při instalaci vlastní skripty ({names}). "
                        "Zkompromitovaný balíček tak získá kód na tvém stroji už při npm install."
                    ).format(
                        count=count(
                            len(scripted), _("závislost"), _("závislosti"), _("závislostí")
                        ),
                        names=_names(scripted),
                    ),
                    path=lock,
                    key=lock,
                    packages=sorted(scripted),
                )
            )
        return findings


# --------------------------------------------------------------------------- opuštěné balíčky


@register
class DepsUnmaintained(Check):
    id = "deps-unmaintained"
    title = N_("Opuštěné nebo zastaralé balíčky")
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE
    network = True

    def run(self, repo: RepoContext) -> list[Finding]:
        deps = _require_network(repo)
        findings: list[Finding] = []
        ordered = sorted(deps.registry.items(), key=lambda kv: (kv[0].ecosystem, kv[0].name))
        for dep, info in ordered:
            dev = (dep.ecosystem, dep.name) in deps.dev_only
            label = f"{dep.name} {dep.version} ({dep.ecosystem})"
            if info.deprecated:
                text = (
                    _("projekt je na PyPI označený jako neaktivní (Development Status: Inactive).")
                    if dep.ecosystem == "PyPI"
                    else _("balíček je označený jako deprecated: {note}").format(
                        note=info.deprecated
                    )
                )
                findings.append(
                    self.finding(
                        f"{label}: {text}",
                        severity=Severity.LOW if dev else Severity.MEDIUM,
                        path=dep.source,
                        key=f"{dep.ecosystem}:{dep.name}:deprecated",
                    )
                )
            elif info.last_release and not dev:
                years = (repo.now - info.last_release).days // 365
                if years >= ABANDONED_YEARS:
                    findings.append(
                        self.finding(
                            _("{label}: poslední vydání je {date}, tedy před {years} lety.").format(
                                label=label, date=f"{info.last_release:%Y-%m-%d}", years=years
                            ),
                            severity=Severity.LOW,
                            path=dep.source,
                            key=f"{dep.ecosystem}:{dep.name}:abandoned",
                        )
                    )
        return findings
