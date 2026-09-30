"""Pseudo-kontroly, které nálezy negenerují samy (existují kvůli dokumentaci a `explain`)."""

from __future__ import annotations

from repo_doctor.checks.base import INCOMPLETE_ID, Check, RepoContext, register
from repo_doctor.models import Category, Finding, Severity


@register
class ScanIncomplete(Check):
    id = INCOMPLETE_ID
    title = "Nekompletní sken"
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        return []
