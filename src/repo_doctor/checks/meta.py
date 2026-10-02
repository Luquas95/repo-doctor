"""Pseudo-kontroly, které nálezy negenerují samy (existují kvůli dokumentaci a `explain`)."""

from __future__ import annotations

import shlex

from repo_doctor.checks.base import INCOMPLETE_ID, UNSAFE_OWNERSHIP_ID, Check, RepoContext, register
from repo_doctor.models import Category, Finding, Severity


@register
class ScanIncomplete(Check):
    id = INCOMPLETE_ID
    title = "Nekompletní sken"
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        return []


@register
class UnsafeOwnership(Check):
    """Nález vytváří scanner, když git repo odmítne kvůli `safe.directory`."""

    id = UNSAFE_OWNERSHIP_ID
    title = "Nedůvěryhodný vlastník"
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        return []

    def for_path(self, path: str) -> Finding:
        return self.finding(
            "Git repo odmítl, protože patří jinému uživateli (safe.directory). "
            "Pokud mu věříš, povol ho: "
            f"git config --global --add safe.directory {shlex.quote(path)} "
            "– repo-doctor to sám nikdy nedělá. Do té doby repo nejde zkontrolovat.",
            key="safe.directory",
        )
