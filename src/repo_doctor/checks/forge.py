"""Kontroly nad daty připojeného hostingu. Síť nevolají – data připraví scanner předem."""

from __future__ import annotations

from datetime import UTC, datetime

from repo_doctor import czech
from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.forges.base import ForgeSnapshot, is_stale
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity


def _snapshot(repo: RepoContext, *, need_repo: bool = True) -> ForgeSnapshot:
    snap = repo.forge_snapshot
    if snap is None:
        raise SkipCheck(repo.forge_status or _("remote nepatří k připojenému hostingu"))
    if need_repo and snap.repo is None:
        raise SkipCheck(snap.missing_reason or _("repo na hostingu nenalezeno"))
    return snap


class ForgeCheck(Check):
    category = Category.FORGE
    needs_forge = True


@register
class ForgeUnknownRemote(ForgeCheck):
    id = "forge-unknown-remote"
    title = N_("Remote ukazuje na neznámé repo")
    severity = Severity.MEDIUM

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo, need_repo=False)
        if snap.repo is not None:
            return []
        return [
            self.finding(
                f"{snap.forge}:{snap.owner_path} – {snap.missing_reason or _('repo nenalezeno')}",
                key=snap.owner_path,
            )
        ]


@register
class ForgeMirrorDrift(ForgeCheck):
    id = "forge-mirror-drift"
    title = N_("Lokální výchozí branche se liší od hostingu")
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
                    _(
                        "výchozí branche: lokálně {local_default}, na hostingu {remote_default}"
                    ).format(local_default=local_default, remote_default=remote_default),
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
                    detail = _("lokálně +{ahead} / −{behind} commitů").format(
                        ahead=ahead, behind=behind
                    )
                    if ahead and not behind:
                        return findings  # jen nepushnuté commity – hlásí `unpushed`
                else:
                    detail = _("hosting má commity, které lokálně nejsou (chybí fetch)")
                findings.append(
                    self.finding(
                        _("{branch}: lokálně {local}, na hostingu {remote} – {detail}").format(
                            branch=branch,
                            local=local_sha[:7],
                            remote=snap.default_branch_sha[:7],
                            detail=detail,
                        ),
                        key="sha",
                    )
                )
        return findings


@register
class ForgeCiFailing(ForgeCheck):
    id = "forge-ci-failing"
    title = N_("CI na výchozí branchi selhává")
    severity = Severity.MEDIUM

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.ci is None or snap.ci.state == "unknown":
            raise SkipCheck(_("stav CI se nepodařilo zjistit"))
        if snap.ci.state != "failure":
            return []
        number = f" (#{snap.ci.number})" if snap.ci.number else ""
        return [
            self.finding(
                _("poslední běh CI na {ref} selhal{number}").format(
                    ref=snap.ci.ref or _("výchozí branchi"), number=number
                ),
                key="ci",
                url=snap.ci.url,
            )
        ]


@register
class ForgeNoBranchProtection(ForgeCheck):
    id = "forge-no-branch-protection"
    title = N_("Výchozí branche bez ochrany")
    severity = Severity.LOW

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.protected is None:
            raise SkipCheck(_("API hostingu ochranu větve nezjistí"))
        if snap.protected or (snap.repo and snap.repo.archived):
            return []
        branch = snap.repo.default_branch if snap.repo else "?"
        return [
            self.finding(
                _("výchozí branche {branch} nemá ochranu (force push, mazání)").format(
                    branch=branch
                ),
                key="protection",
            )
        ]


@register
class ForgeSecurityAlerts(ForgeCheck):
    id = "forge-security-alerts"
    title = N_("Otevřené bezpečnostní alerty")
    severity = Severity.HIGH

    def run(self, repo: RepoContext) -> list[Finding]:
        snap = _snapshot(repo)
        if snap.alerts is None:
            raise SkipCheck(
                _("alerty nejsou dostupné (hosting je nepodporuje nebo token nemá oprávnění)")
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
                        _("{count} ({kind})").format(
                            count=czech.count(
                                count,
                                _("otevřený alert"),
                                _("otevřené alerty"),
                                _("otevřených alertů"),
                            ),
                            kind=labels.get(kind, kind),
                        ),
                        severity=sev,
                        key=kind,
                        count=count,
                    )
                )
        return findings


@register
class ForgeStalePrs(ForgeCheck):
    id = "forge-stale-prs"
    title = N_("Neaktivní pull requesty a issues")
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
            parts.append(
                czech.count(len(prs), _("otevřený PR"), _("otevřené PR"), _("otevřených PR"))
            )
        if issues:
            parts.append(czech.count(len(issues), _("issue"), _("issues"), _("issues")))
        return [
            self.finding(
                _("{join} bez aktivity {days}+ dní").format(join=_(" a ").join(parts), days=days),
                key="stale",
                items=[f"#{i.number} {i.title[:60]}" for i in stale[:10]],
            )
        ]


@register
class ForgeArchivedActive(ForgeCheck):
    id = "forge-archived-active"
    title = N_("Archivované repo s lokální aktivitou")
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
                _("repo je na hostingu archivované (jen pro čtení), ale lokálně má nové commity"),
                key="archived",
            )
        ]
