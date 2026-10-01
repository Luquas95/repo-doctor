"""Kontroly nad daty připojeného hostingu. Síť nevolají – data připraví scanner předem."""

from __future__ import annotations

from datetime import UTC, datetime

from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.forges.base import ForgeSnapshot, is_stale
from repo_doctor.models import Category, Finding, Severity


def _snapshot(repo: RepoContext, *, need_repo: bool = True) -> ForgeSnapshot:
    snap = repo.forge_snapshot
    if snap is None:
        raise SkipCheck(repo.forge_status or "remote nepatří k připojenému hostingu")
    if need_repo and snap.repo is None:
        raise SkipCheck(snap.missing_reason or "repo na hostingu nenalezeno")
    return snap


class ForgeCheck(Check):
    category = Category.FORGE
    needs_forge = True


@register
class ForgeUnknownRemote(ForgeCheck):
    id = "forge-unknown-remote"
    title = "Remote ukazuje na neznámé repo"
    severity = Severity.MEDIUM

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo, need_repo=False)
        if snap.repo is not None:
            return []
        return [
            self.finding(
                f"{snap.forge}:{snap.owner_path} – {snap.missing_reason or 'repo nenalezeno'}",
                key=snap.owner_path,
            )
        ]


@register
class ForgeMirrorDrift(ForgeCheck):
    id = "forge-mirror-drift"
    title = "Lokální výchozí branche se liší od hostingu"
    severity = Severity.LOW

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        assert snap.repo is not None  # noqa: S101 - zaručeno _snapshot
        remote_default = snap.repo.default_branch
        local_default = repo.default_branch
        findings = []
        if remote_default and local_default and remote_default != local_default:
            findings.append(
                self.finding(
                    f"výchozí branche: lokálně {local_default}, na hostingu {remote_default}",
                    key="name",
                )
            )
        branch = remote_default or local_default
        if branch and snap.default_branch_sha and repo.git.ref_exists(f"refs/heads/{branch}"):
            local_sha = repo.git.run(
                "rev-parse", "--verify", "--end-of-options", f"refs/heads/{branch}"
            ).strip()
            if local_sha != snap.default_branch_sha:
                if repo.git.ref_exists(snap.default_branch_sha):
                    ahead, behind = repo.git.ahead_behind(local_sha, snap.default_branch_sha)
                    detail = f"lokálně +{ahead} / −{behind} commitů"
                    if ahead and not behind:
                        return findings  # jen nepushnuté commity – hlásí `unpushed`
                else:
                    detail = "hosting má commity, které lokálně nejsou (chybí fetch)"
                findings.append(
                    self.finding(
                        f"{branch}: lokálně {local_sha[:7]}, na hostingu {snap.default_branch_sha[:7]} – {detail}",
                        key="sha",
                    )
                )
        return findings


@register
class ForgeCiFailing(ForgeCheck):
    id = "forge-ci-failing"
    title = "CI na výchozí branchi selhává"
    severity = Severity.MEDIUM

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.ci is None or snap.ci.state == "unknown":
            raise SkipCheck("stav CI se nepodařilo zjistit")
        if snap.ci.state != "failure":
            return []
        number = f" (#{snap.ci.number})" if snap.ci.number else ""
        return [
            self.finding(
                f"poslední běh CI na {snap.ci.ref or 'výchozí branchi'} selhal{number}",
                key="ci",
                url=snap.ci.url,
            )
        ]


@register
class ForgeNoBranchProtection(ForgeCheck):
    id = "forge-no-branch-protection"
    title = "Výchozí branche bez ochrany"
    severity = Severity.LOW

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.protected is None:
            raise SkipCheck("API hostingu ochranu větve nezjistí")
        if snap.protected or (snap.repo and snap.repo.archived):
            return []
        branch = snap.repo.default_branch if snap.repo else "?"
        return [
            self.finding(
                f"výchozí branche {branch} nemá ochranu (force push, mazání)", key="protection"
            )
        ]


@register
class ForgeSecurityAlerts(ForgeCheck):
    id = "forge-security-alerts"
    title = "Otevřené bezpečnostní alerty"
    severity = Severity.HIGH

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.alerts is None:
            raise SkipCheck(
                "alerty nejsou dostupné (hosting je nepodporuje nebo token nemá oprávnění)"
            )
        labels = {
            "dependabot": "Dependabot",
            "secret_scanning": "secret scanning",
            "code_scanning": "code scanning",
        }
        findings = []
        for kind, count in sorted(snap.alerts.items()):
            if count:
                sev = Severity.HIGH if kind == "secret_scanning" else Severity.MEDIUM
                findings.append(
                    self.finding(
                        f"{count} otevřených alertů ({labels.get(kind, kind)})",
                        severity=sev,
                        key=kind,
                        count=count,
                    )
                )
        return findings


@register
class ForgeStalePrs(ForgeCheck):
    id = "forge-stale-prs"
    title = "Neaktivní pull requesty a issues"
    severity = Severity.LOW

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        days = repo.config.limits.stale_pr_days
        stale = [i for i in snap.open_items if is_stale(i, days, repo.now)]
        if not stale:
            return []
        prs = [i for i in stale if i.kind == "pr"]
        issues = [i for i in stale if i.kind == "issue"]
        parts = []
        if prs:
            parts.append(f"{len(prs)} otevřené PR")
        if issues:
            parts.append(f"{len(issues)} issues")
        return [
            self.finding(
                f"{' a '.join(parts)} bez aktivity {days}+ dní",
                key="stale",
                items=[f"#{i.number} {i.title[:60]}" for i in stale[:10]],
            )
        ]


@register
class ForgeArchivedActive(ForgeCheck):
    id = "forge-archived-active"
    title = "Archivované repo s lokální aktivitou"
    severity = Severity.MEDIUM

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        assert snap.repo is not None  # noqa: S101
        if not snap.repo.archived:
            return []
        last = repo.git.last_commit_ts()
        pushed = snap.repo.pushed_at
        unpushed = sum(b.ahead for b in repo.git.branches() if b.upstream)
        newer = (
            last is not None and pushed is not None and datetime.fromtimestamp(last, UTC) > pushed
        )
        if not (newer or unpushed):
            return []
        return [
            self.finding(
                "repo je na hostingu archivované (jen pro čtení), ale lokálně má nové commity",
                key="archived",
            )
        ]
