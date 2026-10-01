"""Formulářové prvky: našeptávání cest a validátory."""

from __future__ import annotations

import os
from pathlib import Path

from textual.suggester import Suggester
from textual.validation import ValidationResult, Validator

from repo_doctor.paths import expand_path


class PathSuggester(Suggester):
    """Doplňuje adresáře podle toho, co existuje na disku (zachová `~`)."""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=True)

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        expanded = str(expand_path(value))
        if value.endswith("/"):
            base, prefix = Path(expanded), ""
        else:
            base, prefix = Path(expanded).parent, Path(expanded).name
        try:
            names = sorted(
                e.name
                for e in os.scandir(base)
                if e.is_dir()
                and e.name.startswith(prefix)
                and (prefix or not e.name.startswith("."))
            )
        except OSError:
            return None
        if not names:
            return None
        head = value if value.endswith("/") else value[: len(value) - len(prefix)]
        return head + names[0] + "/"


class ExistingDir(Validator):
    def validate(self, value: str) -> ValidationResult:
        if not value.strip():
            return self.failure("zadej cestu")
        path = expand_path(value.strip())
        if not path.exists():
            return self.failure(f"{path} neexistuje")
        if not path.is_dir():
            return self.failure(f"{path} není složka")
        return self.success()


class IntRange(Validator):
    def __init__(self, low: int, high: int) -> None:
        super().__init__()
        self.low, self.high = low, high

    def validate(self, value: str) -> ValidationResult:
        try:
            n = int(value)
        except ValueError:
            return self.failure("musí být celé číslo")
        if not self.low <= n <= self.high:
            return self.failure(f"rozsah {self.low}–{self.high}")
        return self.success()


class PositiveNumber(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            n = float(value)
        except ValueError:
            return self.failure("musí být číslo")
        return self.success() if n > 0 else self.failure("musí být větší než 0")


def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]
