"""Závislosti: parsery manifestů a lockfilů, dotazy na OSV.dev a registry (PyPI, npm)."""

from __future__ import annotations

import asyncio
import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from repo_doctor.httpclient import HttpClient, HttpError
from repo_doctor.models import Severity

OsvEcosystem = Literal["PyPI", "npm", "crates.io", "Go"]

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{id}"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
NPM_URL = "https://registry.npmjs.org/{name}/latest"
OSV_BATCH_SIZE = 1000


@dataclass(frozen=True)
class Dependency:
    ecosystem: OsvEcosystem
    name: str
    version: str
    source: str  # soubor, ze kterého pochází
    direct: bool = False


@dataclass
class Vuln:
    id: str
    severity: Severity
    summary: str = ""


@dataclass
class Outdated:
    dep: Dependency
    latest: str
    level: Literal["major", "minor", "patch"]


@dataclass
class DepsData:
    dependencies: list[Dependency] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    missing_locks: list[tuple[str, str]] = field(
        default_factory=list
    )  # (manifest, doporučený lock)
    vulns: dict[Dependency, list[Vuln]] = field(default_factory=dict)
    outdated: list[Outdated] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    network_done: bool = False


ReadText = Callable[[str], "str | None"]

LOCK_NAMES = {
    "uv.lock",
    "poetry.lock",
    "pdm.lock",
    "Pipfile.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "bun.lock",
    "Cargo.lock",
    "go.sum",
}


# ---------------------------------------------------------------------- parsery
def _norm_py(name: str) -> str:
    return str(canonicalize_name(name))


def parse_toml_packages(text: str, source: str, ecosystem: OsvEcosystem) -> list[Dependency]:
    """uv.lock, poetry.lock, Cargo.lock – pole [[package]] s name a version."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    deps = []
    for pkg in data.get("package", []):
        name, version = pkg.get("name"), pkg.get("version")
        if not name or not version:
            continue
        src = pkg.get("source")
        if ecosystem == "crates.io" and src is None:
            continue  # lokální crate (workspace)
        if isinstance(src, dict) and ({"editable", "virtual", "path", "directory"} & set(src)):
            continue  # samotný projekt
        deps.append(
            Dependency(
                ecosystem, _norm_py(name) if ecosystem == "PyPI" else name, str(version), source
            )
        )
    return deps


_REQ_LINE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9.*+!_-]+)"
)


def parse_requirements(text: str, source: str) -> list[Dependency]:
    deps = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = _REQ_LINE.match(line)
        if m and "*" not in m.group(2):
            deps.append(Dependency("PyPI", _norm_py(m.group(1)), m.group(2), source, direct=True))
    return deps


def pyproject_direct(text: str) -> tuple[set[str], list[Dependency], bool]:
    """(názvy přímých závislostí, připnuté závislosti, má závislosti)."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set(), [], False
    specs: list[str] = list(data.get("project", {}).get("dependencies", []) or [])
    for group in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
        specs.extend(group)
    for group in (data.get("dependency-groups", {}) or {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    names: set[str] = set()
    pinned: list[Dependency] = []
    for spec in specs:
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            continue
        names.add(_norm_py(req.name))
        pins = [
            s.version for s in req.specifier if s.operator in ("==", "===") and "*" not in s.version
        ]
        if pins:
            pinned.append(
                Dependency("PyPI", _norm_py(req.name), pins[0], "pyproject.toml", direct=True)
            )
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
    names.update(_norm_py(n) for n in poetry if n.lower() != "python")
    return names, pinned, bool(names)


def parse_package_lock(text: str, source: str) -> list[Dependency]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    deps: dict[tuple[str, str], Dependency] = {}
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, info in packages.items():
            if not key or "node_modules/" not in key or not isinstance(info, dict):
                continue
            if info.get("link"):
                continue
            name = info.get("name") or key.rsplit("node_modules/", 1)[1]
            version = info.get("version")
            if version:
                deps[(name, version)] = Dependency("npm", name, version, source)
    else:

        def walk(tree: dict[str, Any]) -> None:
            for name, info in tree.items():
                if isinstance(info, dict) and info.get("version"):
                    deps[(name, info["version"])] = Dependency("npm", name, info["version"], source)
                    walk(info.get("dependencies", {}) or {})

        walk(data.get("dependencies", {}) or {})
    return list(deps.values())


_PNPM_KEY = re.compile(r"""^\s{2}['"]?/?((?:@[^/@\s'"]+/)?[^@\s'"/(][^@\s'"(]*)@(\d[^:'"(\s]*)""")
_PNPM_V5 = re.compile(r"""^\s{2}/((?:@[^/\s]+/)?[^/\s]+)/(\d[^:_\s(]*)""")


def parse_pnpm_lock(text: str, source: str) -> list[Dependency]:
    deps: dict[tuple[str, str], Dependency] = {}
    section = ""
    for line in text.splitlines():
        if line and not line.startswith(" "):
            section = line.rstrip(":").strip()
            continue
        if section not in ("packages", "snapshots"):
            continue
        m = _PNPM_KEY.match(line) or _PNPM_V5.match(line)
        if m:
            deps[(m.group(1), m.group(2))] = Dependency("npm", m.group(1), m.group(2), source)
    return list(deps.values())


LOCAL_PROTOCOLS = ("@workspace:", "@portal:", "@link:", "@file:", "@patch:")


def _yarn_name(spec: str) -> str | None:
    spec = spec.strip().strip('"')
    if any(p in spec for p in LOCAL_PROTOCOLS):
        return None  # lokální balíček workspace – nepatří do dotazu na OSV
    at = spec.find("@", 1)
    return spec[:at] if at > 0 else None


def parse_yarn_lock(text: str, source: str) -> list[Dependency]:
    deps: dict[tuple[str, str], Dependency] = {}
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            first = line.rstrip()[:-1].split(",")[0]
            current = _yarn_name(first)
            if current == "__metadata":
                current = None
            continue
        stripped = line.strip()
        if current and (stripped.startswith("version ") or stripped.startswith("version:")):
            version = stripped.split(None, 1)[1].strip().strip('"') if " " in stripped else ""
            if version and version[0].isdigit():
                deps[(current, version)] = Dependency("npm", current, version, source)
            current = None
    return list(deps.values())


def parse_go_sum(text: str, source: str) -> list[Dependency]:
    deps: dict[tuple[str, str], Dependency] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1].endswith("/go.mod"):
            continue
        version = parts[1].removeprefix("v").removesuffix("+incompatible")
        deps[(parts[0], version)] = Dependency("Go", parts[0], version, source)
    return list(deps.values())


def package_json_direct(text: str) -> tuple[set[str], bool]:
    try:
        data = json.loads(text)
    except ValueError:
        return set(), False
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.update(section)
    return names, bool(names)


def _dir(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent + "/"


def collect(files: list[str], read_text: ReadText) -> DepsData:
    """Najde manifesty a lockfily (do hloubky 3, mimo fixtury) a vytáhne závislosti."""
    from repo_doctor.secrets_scan import is_excluded_path

    data = DepsData()
    present = {f for f in files if f.count("/") <= 3 and "node_modules/" not in f}
    by_dir: dict[str, set[str]] = {}
    for f in present:
        by_dir.setdefault(_dir(f), set()).add(PurePosixPath(f).name)
    direct_py: set[str] = set()
    direct_npm: set[str] = set()
    for f in sorted(present):
        name = PurePosixPath(f).name
        if (
            name not in LOCK_NAMES
            and name not in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod"}
            and not (name.startswith("requirements") and name.endswith(".txt"))
        ):
            continue
        if is_excluded_path(f) and name not in LOCK_NAMES:
            continue
        if any(part in {"fixtures", "testdata", "__fixtures__"} for part in PurePosixPath(f).parts):
            continue
        text = read_text(f)
        if text is None:
            continue
        siblings = by_dir.get(_dir(f), set())
        # workspace: lockfile bývá v nadřazené složce (npm/uv/cargo workspaces, monorepa)
        ancestors: set[str] = set(siblings)
        parent = PurePosixPath(_dir(f) or ".")
        while str(parent) not in (".", ""):
            parent = parent.parent
            ancestors |= by_dir.get("" if str(parent) == "." else str(parent) + "/", set())
        data.manifests.append(f)
        if name in ("uv.lock", "poetry.lock", "pdm.lock"):
            data.dependencies.extend(parse_toml_packages(text, f, "PyPI"))
        elif name == "Cargo.lock":
            data.dependencies.extend(parse_toml_packages(text, f, "crates.io"))
        elif name in ("package-lock.json", "npm-shrinkwrap.json"):
            data.dependencies.extend(parse_package_lock(text, f))
        elif name == "pnpm-lock.yaml":
            data.dependencies.extend(parse_pnpm_lock(text, f))
        elif name == "yarn.lock":
            data.dependencies.extend(parse_yarn_lock(text, f))
        elif name == "go.sum":
            data.dependencies.extend(parse_go_sum(text, f))
        elif name.startswith("requirements") and name.endswith(".txt"):
            reqs = parse_requirements(text, f)
            data.dependencies.extend(reqs)
            direct_py.update(d.name for d in reqs)
        elif name == "pyproject.toml":
            names, pinned, has = pyproject_direct(text)
            direct_py.update(names)
            if (
                has
                and not ancestors & {"uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock"}
                and not any(s.startswith("requirements") for s in siblings)
            ):
                data.missing_locks.append((f, "uv.lock"))
                data.dependencies.extend(pinned)
        elif name == "package.json":
            names_npm, has = package_json_direct(text)
            direct_npm.update(names_npm)
            if has and not ancestors & {
                "package-lock.json",
                "npm-shrinkwrap.json",
                "yarn.lock",
                "pnpm-lock.yaml",
                "bun.lockb",
                "bun.lock",
            }:
                data.missing_locks.append((f, "package-lock.json"))
        elif name == "Cargo.toml":
            is_app = f"{_dir(f)}src/main.rs" in present
            if is_app and "[dependencies]" in text and "Cargo.lock" not in ancestors:
                data.missing_locks.append((f, "Cargo.lock"))
        elif name == "go.mod" and "require" in text and "go.sum" not in ancestors:
            data.missing_locks.append((f, "go.sum"))
    unique: dict[tuple[str, str, str], Dependency] = {}
    for d in data.dependencies:
        direct = (d.ecosystem == "PyPI" and d.name in direct_py) or (
            d.ecosystem == "npm" and d.name in direct_npm
        )
        unique.setdefault(
            (d.ecosystem, d.name, d.version),
            Dependency(d.ecosystem, d.name, d.version, d.source, direct or d.direct),
        )
    data.dependencies = list(unique.values())
    return data


# ---------------------------------------------------------------------- síť
SEVERITY_MAP = {
    "CRITICAL": Severity.HIGH,
    "HIGH": Severity.HIGH,
    "MODERATE": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}


async def osv_vulns(
    client: HttpClient, deps: list[Dependency], *, ttl: float
) -> dict[Dependency, list[str]]:
    result: dict[Dependency, list[str]] = {}
    for start in range(0, len(deps), OSV_BATCH_SIZE):
        chunk = deps[start : start + OSV_BATCH_SIZE]
        payload = {
            "queries": [
                {"package": {"name": d.name, "ecosystem": d.ecosystem}, "version": d.version}
                for d in chunk
            ]
        }
        body = await client.post_json(OSV_BATCH_URL, payload, ttl=ttl)
        results = body.get("results", []) if isinstance(body, dict) else []
        for dep, res in zip(chunk, results, strict=False):
            ids = [v["id"] for v in (res or {}).get("vulns", []) or [] if "id" in v]
            if ids:
                result[dep] = ids
    return result


async def osv_details(client: HttpClient, vuln_id: str, *, ttl: float) -> Vuln:
    try:
        body = await client.get_json(OSV_VULN_URL.format(id=vuln_id), ttl=ttl)
    except HttpError:
        return Vuln(vuln_id, Severity.MEDIUM)
    sev_raw = str((body.get("database_specific") or {}).get("severity", "")).upper()
    severity = SEVERITY_MAP.get(sev_raw, Severity.MEDIUM)
    return Vuln(vuln_id, severity, str(body.get("summary", ""))[:200])


def compare_versions(current: str, latest: str) -> Literal["major", "minor", "patch"] | None:
    try:
        cur, new = Version(current), Version(latest)
    except InvalidVersion:
        return None
    if new <= cur or new.is_prerelease:
        return None
    c = [*cur.release, 0, 0, 0][:3]
    n = [*new.release, 0, 0, 0][:3]
    if n[0] != c[0]:
        return "major"
    if n[1] != c[1]:
        return "minor"
    return "patch"


async def latest_version(client: HttpClient, dep: Dependency, *, ttl: float) -> str | None:
    if dep.ecosystem == "PyPI":
        body = await client.get_json(PYPI_URL.format(name=dep.name), ttl=ttl)
        return str(body.get("info", {}).get("version") or "") or None
    if dep.ecosystem == "npm":
        name = dep.name.replace("/", "%2F")
        body = await client.get_json(NPM_URL.format(name=name), ttl=ttl)
        return str(body.get("version") or "") or None
    return None


async def enrich(
    client: HttpClient,
    data: DepsData,
    *,
    ttl: float,
    want_vulns: bool = True,
    want_outdated: bool = True,
    max_details: int = 50,
) -> None:
    """Doplní zranitelnosti (OSV batch) a zastaralé přímé závislosti. Chyby jen zaznamená."""
    if want_vulns and data.dependencies:
        try:
            found = await osv_vulns(client, data.dependencies, ttl=ttl)
            ids = sorted({i for v in found.values() for i in v})[:max_details]
            details = dict(
                zip(
                    ids,
                    await asyncio.gather(*(osv_details(client, i, ttl=ttl) for i in ids)),
                    strict=True,
                )
            )
            for dep, vids in found.items():
                data.vulns[dep] = [details.get(i) or Vuln(i, Severity.MEDIUM) for i in vids]
        except HttpError as err:
            data.errors.append(f"OSV: {err}")
    if want_outdated:
        direct = [d for d in data.dependencies if d.direct and d.ecosystem in ("PyPI", "npm")]

        async def one(dep: Dependency) -> None:
            try:
                latest = await latest_version(client, dep, ttl=ttl)
            except HttpError as err:
                data.errors.append(f"{dep.ecosystem} {dep.name}: {err}")
                return
            level = compare_versions(dep.version, latest) if latest else None
            if latest and level:
                data.outdated.append(Outdated(dep, latest, level))

        await asyncio.gather(*(one(d) for d in direct[:200]))
        data.outdated.sort(key=lambda o: (o.dep.ecosystem, o.dep.name))
    data.network_done = True
