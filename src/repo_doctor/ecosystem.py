"""Detekce ekosystému repozitáře podle souborů v kořeni (a jedné úrovni pod ním)."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Ecosystem(StrEnum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"
    GO = "go"


_MARKERS: dict[Ecosystem, tuple[str, ...]] = {
    Ecosystem.PYTHON: (
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "uv.lock",
        "poetry.lock",
    ),
    Ecosystem.NODE: ("package.json",),
    Ecosystem.RUST: ("Cargo.toml",),
    Ecosystem.GO: ("go.mod",),
}


def detect(files: Iterable[str]) -> set[Ecosystem]:
    found: set[Ecosystem] = set()
    top_py = 0
    for path in files:
        parts = path.split("/")
        name = parts[-1]
        if len(parts) <= 2:
            for eco, markers in _MARKERS.items():
                if name in markers or (
                    eco is Ecosystem.PYTHON
                    and name.startswith("requirements")
                    and name.endswith(".txt")
                ):
                    found.add(eco)
        if name.endswith(".py") and len(parts) <= 3:
            top_py += 1
    if top_py >= 2:
        found.add(Ecosystem.PYTHON)
    return found
