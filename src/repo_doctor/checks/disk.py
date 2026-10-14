"""Místo na disku: velké regenerovatelné složky v neaktivních repech (`disk-usage`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.cleanup import MB, find_candidates, human
from repo_doctor.models import Category, Finding, Severity


@register
class DiskUsage(Check):
    id = "disk-usage"
    title = "Velké regenerovatelné složky v neaktivním repu"
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        cfg = repo.config.cleanup
        ts = repo.git.last_commit_ts()
        last = datetime.fromtimestamp(ts, UTC) if ts else None
        if last is not None and repo.now - last < timedelta(days=cfg.inactive_days):
            return []  # aktivní repo – složky se nejspíš používají
        candidates = find_candidates(repo.path, cfg.dirs, repo.git)
        total = sum(c.size for c in candidates)
        if total < cfg.min_mb * MB:
            return []
        biggest = sorted(candidates, key=lambda c: -c.size)[:5]
        return [
            self.finding(
                f"{human(total)} v regenerovatelných složkách "
                f"({', '.join(f'{c.rel} {human(c.size)}' for c in biggest)}); "
                f"repo je neaktivní {cfg.inactive_days}+ dní – uvolníš na obrazovce Úklid",
                key="disk-usage",
                bytes=total,
                dirs=[c.rel for c in candidates],
            )
        ]
