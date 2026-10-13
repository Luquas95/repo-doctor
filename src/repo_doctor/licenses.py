"""Licence závislostí: SPDX identifikátory, kategorie a zjištění z registrů.

Mapování je vlastní tabulka běžných licencí (ne úplný SPDX seznam). Výsledek je
informativní – nejde o právní radu.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Callable
from typing import Literal

from repo_doctor.deps import Dependency
from repo_doctor.httpclient import HttpClient, HttpError, ResponseCache

Kind = Literal["permissive", "weak", "strong", "unknown"]

PERMISSIVE = {
    "MIT", "MIT-0", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "BSD-3-Clause-Clear",
    "0BSD", "ISC", "Unlicense", "Zlib", "PSF-2.0", "Python-2.0", "BSL-1.0", "CC0-1.0",
    "WTFPL", "X11", "Artistic-2.0", "Unicode-3.0", "Unicode-DFS-2016", "BlueOak-1.0.0",
    "CC-BY-4.0", "PostgreSQL", "NCSA", "HPND", "curl",
}  # fmt: skip
WEAK = {
    "LGPL-2.0-only", "LGPL-2.0-or-later", "LGPL-2.1-only", "LGPL-2.1-or-later",
    "LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-1.1", "MPL-2.0", "EPL-1.0", "EPL-2.0",
    "CDDL-1.0", "CDDL-1.1", "CPL-1.0",
}  # fmt: skip
STRONG = {
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "AGPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0", "OSL-3.0", "EUPL-1.1", "EUPL-1.2",
}  # fmt: skip

# Volné názvy z metadat (PyPI `license`, klasifikátory, staré npm) → SPDX.
_ALIASES: dict[str, str] = {
    "mit": "MIT", "mit license": "MIT", "the mit license": "MIT", "expat": "MIT",
    "apache": "Apache-2.0", "apache 2": "Apache-2.0", "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0", "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "asl 2.0": "Apache-2.0",
    "bsd": "BSD-3-Clause", "bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "bsd-3": "BSD-3-Clause", "3-clause bsd": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause",
    "isc license": "ISC", "isc license (iscl)": "ISC", "public domain": "Unlicense",
    "the unlicense (unlicense)": "Unlicense", "psf": "PSF-2.0",
    "python software foundation license": "PSF-2.0", "zlib/libpng": "Zlib",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0", "mpl 2.0": "MPL-2.0",
    "gpl": "GPL-3.0-or-later", "gplv2": "GPL-2.0-only", "gplv2+": "GPL-2.0-or-later",
    "gplv3": "GPL-3.0-only", "gplv3+": "GPL-3.0-or-later",
    "gnu general public license v2 (gplv2)": "GPL-2.0-only",
    "gnu general public license v2 or later (gplv2+)": "GPL-2.0-or-later",
    "gnu general public license v3 (gplv3)": "GPL-3.0-only",
    "gnu general public license v3 or later (gplv3+)": "GPL-3.0-or-later",
    "gnu general public license (gpl)": "GPL-3.0-or-later",
    "gnu affero general public license v3": "AGPL-3.0-only",
    "gnu affero general public license v3 or later (agplv3+)": "AGPL-3.0-or-later",
    "agpl": "AGPL-3.0-only", "agplv3": "AGPL-3.0-only",
    "lgpl": "LGPL-3.0-or-later", "lgplv2+": "LGPL-2.1-or-later", "lgplv3": "LGPL-3.0-only",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-or-later",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
    "gnu library or lesser general public license (lgpl)": "LGPL-2.1-or-later",
    "eclipse public license 2.0 (epl-2.0)": "EPL-2.0",
}  # fmt: skip
# Staré krátké SPDX tvary
_LEGACY = {
    "GPL-2.0": "GPL-2.0-only", "GPL-2.0+": "GPL-2.0-or-later", "GPL-3.0": "GPL-3.0-only",
    "GPL-3.0+": "GPL-3.0-or-later", "AGPL-3.0": "AGPL-3.0-only", "LGPL-2.1": "LGPL-2.1-only",
    "LGPL-2.1+": "LGPL-2.1-or-later", "LGPL-3.0": "LGPL-3.0-only", "LGPL-3.0+": "LGPL-3.0-or-later",
    "LGPL-2.0": "LGPL-2.0-only",
}  # fmt: skip
_KNOWN = {s.lower(): s for s in PERMISSIVE | WEAK | STRONG}
_RANK: dict[Kind, int] = {"permissive": 0, "weak": 1, "unknown": 2, "strong": 3}


def normalize(name: str | None) -> str | None:
    """Volný název licence → SPDX identifikátor (nebo None, když ho neznáme)."""
    if not name:
        return None
    text = name.strip().strip("()").strip()
    text = text.removeprefix("License :: ").removeprefix("OSI Approved :: ").strip()
    if not text or len(text) > 120 or "\n" in text:
        return None
    if text in _LEGACY:
        return _LEGACY[text]
    if text.lower() in _KNOWN:
        return _KNOWN[text.lower()]
    return _ALIASES.get(text.lower().removesuffix(" license") or text.lower()) or _ALIASES.get(
        text.lower()
    )


def kind_of(spdx: str | None) -> Kind:
    if spdx in PERMISSIVE:
        return "permissive"
    if spdx in WEAK:
        return "weak"
    if spdx in STRONG:
        return "strong"
    return "unknown"


def classify(expression: str | None) -> tuple[Kind, str | None]:
    """Kategorie licenčního výrazu. `A OR B` → nejvolnější možnost, `A AND B` → nejpřísnější.

    Vrací (kategorie, normalizovaný výraz pro zobrazení).
    """
    if not expression or not expression.strip():
        return "unknown", None
    expr = expression.strip()
    if re.search(r"\s(OR|AND|WITH)\s|/", expr):
        expr = expr.replace("/", " OR ")
        ors = re.split(r"\s+OR\s+", expr.strip("() "))
        best: Kind = "strong"
        names: list[str] = []
        for alt in ors:
            parts = re.split(r"\s+AND\s+", alt.strip("() "))
            worst: Kind = "permissive"
            for part in parts:
                spdx = normalize(part.split(" WITH ", 1)[0])
                names.append(spdx or part.strip())
                k = kind_of(spdx)
                worst = k if _RANK[k] > _RANK[worst] else worst
            best = worst if _RANK[worst] < _RANK[best] else best
        return best, " OR ".join(dict.fromkeys(names)) if " OR " in expr else " AND ".join(names)
    spdx = normalize(expr)
    return kind_of(spdx), spdx or expr


# ---------------------------------------------------------------------- registry
PYPI_URL = "https://pypi.org/pypi/{name}/{version}/json"
NPM_URL = "https://registry.npmjs.org/{name}/{version}"
CRATES_URL = "https://crates.io/api/v1/crates/{name}/{version}"


def license_url(dep: Dependency) -> str | None:
    if dep.ecosystem == "PyPI":
        return PYPI_URL.format(name=dep.name, version=dep.version)
    if dep.ecosystem == "npm":
        return NPM_URL.format(name=dep.name.replace("/", "%2F"), version=dep.version)
    if dep.ecosystem == "crates.io":
        return CRATES_URL.format(name=dep.name, version=dep.version)
    return None  # Go: pkg.go.dev nemá stabilní API – licence se nezjišťuje


def license_from_body(dep: Dependency, body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    if dep.ecosystem == "PyPI":
        info = body.get("info") or {}
        expr = info.get("license_expression")
        if expr:
            return str(expr)
        text = str(info.get("license") or "").strip()
        if text and len(text) <= 80 and "\n" not in text and text.upper() != "UNKNOWN":
            return text
        for c in info.get("classifiers") or []:
            if str(c).startswith("License :: "):
                name = str(c).rsplit(" :: ", 1)[-1]
                if name != "OSI Approved":
                    return name
        return None
    if dep.ecosystem == "npm":
        lic = body.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        if not lic and isinstance(body.get("licenses"), list) and body["licenses"]:
            first = body["licenses"][0]
            lic = first.get("type") if isinstance(first, dict) else first
        return str(lic) if lic else None
    if dep.ecosystem == "crates.io":
        version = body.get("version") or {}
        return (
            str(version.get("license"))
            if isinstance(version, dict) and version.get("license")
            else None
        )
    return None


async def fetch_license(client: HttpClient, dep: Dependency, *, ttl: float) -> str | None:
    url = license_url(dep)
    if url is None:
        return None
    try:
        body = await client.get_json(url, ttl=ttl)
    except HttpError:
        return None
    return license_from_body(dep, body)


def cached_license(cache: ResponseCache, dep: Dependency, namespace: str = "public") -> str | None:
    """Licence jen z cache odpovědí (bez sítě) – pro SBOM."""
    url = license_url(dep)
    if url is None:
        return None
    entry = cache.get(ResponseCache.key(namespace, "GET", url))
    return license_from_body(dep, entry.body) if entry else None


# ---------------------------------------------------------------------- licence projektu
_FILE_HINTS: list[tuple[str, str]] = [
    (r"GNU AFFERO GENERAL PUBLIC LICENSE", "AGPL-3.0-only"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE", "LGPL-3.0-only"),
    (r"GNU GENERAL PUBLIC LICENSE\s+Version 3", "GPL-3.0-only"),
    (r"GNU GENERAL PUBLIC LICENSE\s+Version 2", "GPL-2.0-only"),
    (r"Mozilla Public License,? (v\. |Version )2\.0", "MPL-2.0"),
    (r"Apache License\s+Version 2\.0", "Apache-2.0"),
    (r"Permission is hereby granted, free of charge", "MIT"),
    (r"Permission to use, copy, modify, and/or distribute this software", "ISC"),
    (r"This is free and unencumbered software released into the public domain", "Unlicense"),
    (r"Redistribution and use in source and binary forms", "BSD-3-Clause"),
]


def project_license(files: list[str], read_text: Callable[[str], str | None]) -> str | None:
    """Licence projektu z manifestu (pyproject, package.json, Cargo.toml), jinak z LICENSE."""
    lower = {f.lower(): f for f in files}
    if "pyproject.toml" in lower and (text := read_text(lower["pyproject.toml"])):
        try:
            project = tomllib.loads(text).get("project", {})
        except tomllib.TOMLDecodeError:
            project = {}
        lic = project.get("license")
        if isinstance(lic, dict):
            lic = lic.get("text") or lic.get("file")
        if isinstance(lic, str) and normalize(lic.split(" OR ")[0]):
            return lic
    if "package.json" in lower and (text := read_text(lower["package.json"])):
        try:
            lic = json.loads(text).get("license")
        except (ValueError, AttributeError):
            lic = None
        if isinstance(lic, str) and lic:
            return lic
    if "cargo.toml" in lower and (text := read_text(lower["cargo.toml"])):
        try:
            lic = tomllib.loads(text).get("package", {}).get("license")
        except tomllib.TOMLDecodeError:
            lic = None
        if isinstance(lic, str) and lic:
            return lic
    for name in ("license", "license.md", "license.txt", "licence", "copying", "unlicense"):
        if name in lower and (text := read_text(lower[name])):
            for pattern, spdx in _FILE_HINTS:
                if re.search(pattern, text, re.IGNORECASE):
                    return spdx
    return None
