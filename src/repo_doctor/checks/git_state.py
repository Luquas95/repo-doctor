"""Kontroly stavu gitu. Jen čtou lokální data, nikdy nic nemažou ani nefetchují."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_doctor import czech
from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity


def _age_days(ts: int, now: datetime) -> int:
    return int((now - datetime.fromtimestamp(ts, UTC)) / timedelta(days=1))


@register
class Uncommitted(Check):
    id = "uncommitted"
    title = N_("Necommitnuté změny")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        st = repo.status
        if st.dirty == 0:
            return []
        parts = []
        if st.modified or st.staged:
            parts.append(_("{modified} změněných").format(modified=st.modified + st.staged))
        if st.untracked:
            parts.append(_("{untracked} nesledovaných").format(untracked=st.untracked))
        if st.conflicted:
            parts.append(_("{n} v konfliktu").format(n=st.conflicted))
        return [
            self.finding(
                _("{join} souborů").format(join=", ".join(parts)),
                key="uncommitted",
                count=st.dirty,
                files=list(st.paths[:20]),
            )
        ]


# Otisk nálezu (allowlist) dřív vznikal z české zprávy – klíč ji drží, aby se nezměnil
# s jazykem ani pro už povolené nálezy.
NO_REMOTE_KEY = "Repozitář nemá žádný remote – commity existují jen na tomto disku."


@register
class NoRemote(Check):
    id = "no-remote"
    title = N_("Repo bez remote (bez zálohy)")
    severity = Severity.MEDIUM
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.remotes or repo.git.remotes():
            return []
        if repo.head is None:
            return []  # prázdné repo nemá co zálohovat
        return [
            self.finding(
                _("Repozitář nemá žádný remote – commity existují jen na tomto disku."),
                key=NO_REMOTE_KEY,
            )
        ]


@register
class Unpushed(Check):
    id = "unpushed"
    title = N_("Nepushnuté commity")
    severity = Severity.MEDIUM
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        if not repo.git.remotes():
            return []  # řeší no-remote
        findings = []
        for b in repo.git.branches():
            if b.upstream and not b.upstream_gone:
                count = b.ahead
            else:
                count = repo.git.count_not_on_remotes(b.name)
            if count:
                where = (
                    f"oproti {b.upstream}"
                    if b.upstream and not b.upstream_gone
                    else _("na žádném remote")
                )
                findings.append(
                    self.finding(
                        _("branch {name}: {commits} {where}").format(
                            name=b.name, commits=czech.commits(count), where=where
                        ),
                        key=b.name,
                        branch=b.name,
                        count=count,
                    )
                )
        return findings


@register
class StaleBranches(Check):
    id = "stale-branches"
    title = N_("Zastaralé lokální branche")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        default = repo.default_branch
        current = repo.git.current_branch()
        limit = repo.config.limits.stale_branch_days
        target = default
        if default and not repo.git.ref_exists(f"refs/heads/{default}"):
            remote_ref = next(
                (
                    f"{r}/{default}"
                    for r in repo.git.remotes()
                    if repo.git.ref_exists(f"refs/remotes/{r}/{default}")
                ),
                None,
            )
            target = remote_ref
        merged = set(repo.git.merged_branches(target)) if target else set()
        default_sha = (
            repo.git.run(
                "rev-parse", "--verify", "--quiet", "--end-of-options", target, check=False
            ).strip()
            if target
            else ""
        )
        findings = []
        for b in repo.git.branches():
            if b.name in {default, current}:
                continue
            age = _age_days(b.committer_ts, repo.now)
            reasons = []
            if (
                b.name in merged and b.sha != default_sha
            ):  # čerstvá větev bez vlastních commitů není „stará“
                reasons.append(_("mergnutá do {default}").format(default=default))
            if age > limit:
                reasons.append(_("bez commitu {age} dní").format(age=age))
            if reasons:
                findings.append(
                    self.finding(
                        f"{b.name}: {', '.join(reasons)}", key=b.name, branch=b.name, age_days=age
                    )
                )
        return findings


@register
class Stashes(Check):
    id = "stashes"
    title = N_("Zapomenuté stashe")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        limit = repo.config.limits.stash_days
        findings = []
        for s in repo.git.stashes():
            age = _age_days(s.timestamp, repo.now)
            if age > limit:
                findings.append(
                    self.finding(
                        _("{ref} ({age} dní): {message}").format(
                            ref=s.ref, age=age, message=s.message[:80]
                        ),
                        key=s.message,
                        age_days=age,
                    )
                )
        return findings


@register
class DetachedHead(Check):
    id = "detached-head"
    title = N_("Detached HEAD")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.git.is_detached():
            head = repo.head or ""
            return [
                self.finding(
                    _("HEAD ukazuje přímo na commit {sha}, ne na branch.").format(sha=head[:7]),
                    key="detached",
                )
            ]
        return []


@register
class DefaultBranchBehind(Check):
    id = "default-branch-behind"
    title = N_("Výchozí branche je pozadu za remote")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        default = repo.default_branch
        if not default:
            return []
        branch = next((b for b in repo.git.branches() if b.name == default), None)
        if branch is None or not branch.upstream or branch.upstream_gone:
            return []
        if branch.behind:
            return [
                self.finding(
                    _(
                        "{default} je {commits} za {upstream} (podle posledního fetch; pro aktuální stav spusť sken s --fetch)."
                    ).format(
                        default=default,
                        commits=czech.commits(branch.behind),
                        upstream=branch.upstream,
                    ),
                    key=default,
                    count=branch.behind,
                )
            ]
        return []
