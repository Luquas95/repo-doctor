"""Kontroly stavu gitu. Jen čtou lokální data, nikdy nic nemažou ani nefetchují."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.models import Category, Finding, Severity


def _age_days(ts: int, now: datetime) -> int:
    return int((now - datetime.fromtimestamp(ts, UTC)) / timedelta(days=1))


@register
class Uncommitted(Check):
    id = "uncommitted"
    title = "Necommitnuté změny"
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        st = repo.status
        if st.dirty == 0:
            return []
        parts = []
        if st.modified or st.staged:
            parts.append(f"{st.modified + st.staged} změněných")
        if st.untracked:
            parts.append(f"{st.untracked} nesledovaných")
        if st.conflicted:
            parts.append(f"{st.conflicted} v konfliktu")
        return [
            self.finding(
                f"{', '.join(parts)} souborů",
                key="uncommitted",
                count=st.dirty,
                files=list(st.paths[:20]),
            )
        ]


@register
class NoRemote(Check):
    id = "no-remote"
    title = "Repo bez remote (bez zálohy)"
    severity = Severity.MEDIUM
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.remotes or repo.git.remotes():
            return []
        if repo.head is None:
            return []  # prázdné repo nemá co zálohovat
        return [self.finding("Repozitář nemá žádný remote – commity existují jen na tomto disku.")]


@register
class Unpushed(Check):
    id = "unpushed"
    title = "Nepushnuté commity"
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
                    else "na žádném remote"
                )
                findings.append(
                    self.finding(
                        f"branch {b.name}: {count} commitů {where}",
                        key=b.name,
                        branch=b.name,
                        count=count,
                    )
                )
        return findings


@register
class StaleBranches(Check):
    id = "stale-branches"
    title = "Zastaralé lokální branche"
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        default = repo.default_branch
        current = repo.git.current_branch()
        limit = repo.config.limits.stale_branch_days
        merged = set(repo.git.merged_branches(default)) if default else set()
        findings = []
        for b in repo.git.branches():
            if b.name in {default, current}:
                continue
            age = _age_days(b.committer_ts, repo.now)
            reasons = []
            if b.name in merged:
                reasons.append(f"mergnutá do {default}")
            if age > limit:
                reasons.append(f"bez commitu {age} dní")
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
    title = "Zapomenuté stashe"
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
                        f"{s.ref} ({age} dní): {s.message[:80]}", key=s.message, age_days=age
                    )
                )
        return findings


@register
class DetachedHead(Check):
    id = "detached-head"
    title = "Detached HEAD"
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.git.is_detached():
            head = repo.head or ""
            return [
                self.finding(
                    f"HEAD ukazuje přímo na commit {head[:7]}, ne na branch.", key="detached"
                )
            ]
        return []


@register
class DefaultBranchBehind(Check):
    id = "default-branch-behind"
    title = "Výchozí branche je pozadu za remote"
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
                    f"{default} je {branch.behind} commitů za {branch.upstream} "
                    "(podle posledního fetch; pro aktuální stav spusť sken s --fetch).",
                    key=default,
                    count=branch.behind,
                )
            ]
        return []
