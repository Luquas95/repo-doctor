"""Licence přímých závislostí vs. licence projektu (`license-compat`) – informativní."""

from __future__ import annotations

from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.licenses import classify, project_license
from repo_doctor.models import Category, Finding, Severity

DISCLAIMER = "nejde o právní radu"


@register
class LicenseCompat(Check):
    id = "license-compat"
    title = "Licence závislosti nemusí být slučitelná"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    network = True  # licence z registrů (PyPI, npm, crates.io), cachované

    def run(self, repo: RepoContext) -> list[Finding]:
        data = repo.deps
        if data is None or not data.network_done:
            raise SkipCheck(repo.deps_status or "licence závislostí nejsou zjištěné (offline)")
        project = project_license(repo.tracked_files, repo.read_text)
        kind, shown = classify(project)
        if kind != "permissive":
            return []  # copyleft/neznámý projekt: GPL závislost nevadí, chybějící LICENSE řeší jiná kontrola
        findings: list[Finding] = []
        for dep, lic in sorted(data.licenses.items(), key=lambda kv: (kv[0].ecosystem, kv[0].name)):
            dep_kind, dep_shown = classify(lic)
            where = f"{dep.ecosystem} {dep.name} {dep.version}"
            if dep_kind == "strong":
                findings.append(
                    self.finding(
                        f"{where} má silně copyleftovou licenci {dep_shown} – projekt je {shown}; "
                        f"ověř, jestli ji smíš takto použít ({DISCLAIMER})",
                        severity=Severity.MEDIUM,
                        path=dep.source,
                        key=f"{dep.ecosystem}:{dep.name}",
                        kind="copyleft",
                        license=dep_shown or "",
                    )
                )
            elif dep_kind == "unknown":
                findings.append(
                    self.finding(
                        f"{where}: licence {'chybí' if not lic else f'je neznámá ({lic[:60]})'} "
                        f"– bez licence nemáš právo kód použít ({DISCLAIMER})",
                        path=dep.source,
                        key=f"{dep.ecosystem}:{dep.name}",
                        kind="unknown",
                        license=lic or "",
                    )
                )
        return findings[:50]
