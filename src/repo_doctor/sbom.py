"""SBOM ve formátu CycloneDX 1.5 (JSON) z lockfilů, které už parsuje `deps-vulnerable`.

Bez síťových dotazů – licence se doplní jen tehdy, když jsou v cache odpovědí registrů.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from repo_doctor import __version__, paths
from repo_doctor.deps import Dependency, DepsData, collect
from repo_doctor.gitwrap import Git
from repo_doctor.httpclient import ResponseCache
from repo_doctor.licenses import cached_license, normalize, project_license

FORMATS = ("cyclonedx-json",)

_PURL_TYPE = {"PyPI": "pypi", "npm": "npm", "crates.io": "cargo", "Go": "golang"}


def purl(dep: Dependency) -> str:
    kind = _PURL_TYPE[dep.ecosystem]
    name = dep.name
    if dep.ecosystem == "npm" and name.startswith("@") and "/" in name:
        scope, _, pkg = name.partition("/")
        return f"pkg:npm/{quote(scope)}/{quote(pkg)}@{quote(dep.version)}"
    if dep.ecosystem == "Go":
        return f"pkg:golang/{quote(name, safe='/')}@{quote(dep.version)}"
    if dep.ecosystem == "PyPI":
        name = name.lower().replace("_", "-")
    return f"pkg:{kind}/{quote(name)}@{quote(dep.version)}"


def _license_entry(expression: str | None) -> list[dict[str, Any]]:
    if not expression:
        return []
    spdx = normalize(expression)
    if spdx:
        return [{"license": {"id": spdx}}]
    if " OR " in expression or " AND " in expression:
        return [{"expression": expression}]
    return [{"license": {"name": expression[:200]}}]


def build(
    name: str,
    data: DepsData,
    *,
    project_licence: str | None = None,
    cache: ResponseCache | None = None,
    now: datetime | None = None,
    serial: str | None = None,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dep in sorted(data.dependencies, key=lambda d: (d.ecosystem, d.name, d.version)):
        ref = purl(dep)
        if ref in seen:
            continue
        seen.add(ref)
        lic = data.licenses.get(dep) if dep in data.licenses else None
        if lic is None and cache is not None:
            lic = cached_license(cache, dep)
        comp: dict[str, Any] = {
            "type": "library",
            "bom-ref": ref,
            "name": dep.name,
            "version": dep.version,
            "purl": ref,
            "scope": "required" if dep.direct else "optional",
            "properties": [
                {"name": "repo-doctor:source", "value": dep.source},
                {"name": "repo-doctor:direct", "value": "true" if dep.direct else "false"},
            ],
        }
        if licences := _license_entry(lic):
            comp["licenses"] = licences
        components.append(comp)
    metadata: dict[str, Any] = {
        "timestamp": (now or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        "tools": {
            "components": [{"type": "application", "name": "repo-doctor", "version": __version__}]
        },
        "component": {"type": "application", "bom-ref": f"repo:{name}", "name": name},
    }
    if licences := _license_entry(project_licence):
        metadata["component"]["licenses"] = licences
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": serial or f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": metadata,
        "components": components,
        "dependencies": [
            {
                "ref": f"repo:{name}",
                "dependsOn": [c["bom-ref"] for c in components if c["scope"] == "required"],
            }
        ],
    }


def sbom_for_repo(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """SBOM repa z pracovního stromu (sledované soubory). Nic nemění, nepoužívá síť."""
    git = Git(path)
    if git.dubious_ownership():
        raise ValueError("repo patří jinému uživateli (safe.directory) – nelze číst")
    files = git.ls_files()

    def read(rel: str) -> str | None:
        target = path / rel
        try:
            if target.is_symlink() or not target.is_file() or target.stat().st_size > 20_000_000:
                return None
            return target.read_text("utf-8", "replace")
        except OSError:
            return None

    data = collect(files, read)
    cache = ResponseCache(paths.http_cache_dir())
    return build(
        path.name, data, project_licence=project_license(files, read), cache=cache, now=now
    )


def write_sbom(path: Path, output: Path) -> Path:
    """Zapíše SBOM do nového souboru – existující soubor nikdy nepřepíše."""
    doc = sbom_for_repo(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return output
