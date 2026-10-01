"""Závislosti: zranitelnosti (OSV.dev), zastaralé verze (PyPI, npm), chybějící lockfile."""

from __future__ import annotations

from typing import TYPE_CHECKING

from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.models import Category, Finding, Severity

if TYPE_CHECKING:
    from repo_doctor.deps import DepsData


def _require_network(repo: RepoContext) -> DepsData:
    if repo.offline:
        raise SkipCheck("offline režim")
    if repo.deps is None or not repo.deps.network_done:
        raise SkipCheck(repo.deps_status or "síťová data nejsou k dispozici")
    return repo.deps


@register
class DepsVulnerable(Check):
    id = "deps-vulnerable"
    title = "Zranitelné závislosti"
    severity = Severity.HIGH
    category = Category.SECURITY
    network = True

    def run(self, repo: RepoContext) -> list[Finding]:
        deps = _require_network(repo)
        findings = []
        for dep, vulns in sorted(deps.vulns.items(), key=lambda kv: (kv[0].ecosystem, kv[0].name)):
            worst = max((v.severity for v in vulns), key=lambda s: s.rank)
            ids = ", ".join(v.id for v in vulns[:6]) + (
                f" (+{len(vulns) - 6})" if len(vulns) > 6 else ""
            )
            findings.append(
                self.finding(
                    f"{dep.name} {dep.version} ({dep.ecosystem}): {ids}",
                    severity=worst,
                    path=dep.source,
                    key=f"{dep.ecosystem}:{dep.name}:{dep.version}",
                    vulns=[v.id for v in vulns],
                )
            )
        return findings


@register
class DepsOutdated(Check):
    id = "deps-outdated"
    title = "Zastaralé závislosti"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    network = True

    def run(self, repo: RepoContext) -> list[Finding]:
        deps = _require_network(repo)
        findings = []
        for level, sev in (
            ("major", Severity.MEDIUM),
            ("minor", Severity.LOW),
            ("patch", Severity.LOW),
        ):
            items = [o for o in deps.outdated if o.level == level]
            if not items:
                continue
            listing = ", ".join(f"{o.dep.name} {o.dep.version}→{o.latest}" for o in items[:8])
            more = f" a {len(items) - 8} další" if len(items) > 8 else ""
            findings.append(
                self.finding(
                    f"{len(items)}× {level}: {listing}{more}",
                    title=f"Zastaralé závislosti ({level})",
                    severity=sev,
                    key=level,
                    packages=[f"{o.dep.name}=={o.dep.version}->{o.latest}" for o in items],
                )
            )
        return findings


@register
class DepsLockfileMissing(Check):
    id = "deps-lockfile-missing"
    title = "Chybí lockfile"
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        from repo_doctor.deps import collect

        data = repo.deps or collect(repo.tracked_files, repo.read_text)
        return [
            self.finding(
                f"{manifest} deklaruje závislosti, ale chybí {lock} – verze nejsou připnuté a zranitelnosti nejde ověřit",
                path=manifest,
                key=manifest,
            )
            for manifest, lock in data.missing_locks
        ]
