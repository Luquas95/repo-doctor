"""Dokumentace kontrol (`docs/checks/<id>.md`) – stejný text pro `explain` i detail v TUI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class CheckDoc:
    check_id: str
    text: str

    def section(self, heading: str) -> str:
        m = re.search(
            rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", self.text, re.MULTILINE | re.DOTALL
        )
        return m.group(1).strip() if m else ""

    @property
    def what(self) -> str:
        return self.section("Co kontrola hledá")

    @property
    def why(self) -> str:
        return self.section("Proč to vadí")

    @property
    def steps(self) -> list[str]:
        return [
            re.sub(r"^\d+\.\s*", "", line).strip()
            for line in self.section("Postup").splitlines()
            if line.strip()
        ]

    @property
    def note(self) -> str:
        return self.section("Poznámka")


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [here / "_checkdocs", here.parent.parent / "docs" / "checks"]


@lru_cache(maxsize=64)
def load(check_id: str) -> CheckDoc | None:
    if not re.fullmatch(r"[a-z0-9-]+", check_id):
        return None
    for base in _candidates():
        file = base / f"{check_id}.md"
        if file.is_file():
            return CheckDoc(check_id, file.read_text("utf-8"))
    return None
