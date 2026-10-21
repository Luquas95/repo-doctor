"""Dokumentace kontrol (`docs/checks/<id>.md`, anglicky `docs/checks/en/<id>.md`) – stejný
text pro `explain` i detail v TUI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from repo_doctor.i18n import _, language


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
        return self.section(_("Co kontrola hledá"))

    @property
    def why(self) -> str:
        return self.section(_("Proč to vadí"))

    @property
    def steps(self) -> list[str]:
        return [
            re.sub(r"^\d+\.\s*", "", line).strip()
            for line in self.section(_("Postup")).splitlines()
            if line.strip()
        ]

    @property
    def note(self) -> str:
        return self.section(_("Poznámka"))


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [here / "_checkdocs", here.parent.parent / "docs" / "checks"]


def load(check_id: str) -> CheckDoc | None:
    """Dokumentace v jazyce rozhraní (`en/<id>.md`), jinak česká."""
    return _load(check_id, language())


@lru_cache(maxsize=128)
def _load(check_id: str, lang: str) -> CheckDoc | None:
    if not re.fullmatch(r"[a-z0-9-]+", check_id):
        return None
    for base in _candidates():
        names = [f"{lang}/{check_id}.md"] if lang != "cs" else []
        for name in [*names, f"{check_id}.md"]:
            file = base / name
            if file.is_file():
                return CheckDoc(check_id, file.read_text("utf-8"))
    return None
