"""Duplicitní klony stejného repa napříč sledovanými složkami (`duplicate-clone`).

Kontrola potřebuje výsledky všech rep najednou, proto ji počítá scanner po skončení skenu
(`add_duplicate_findings`); třída v registru existuje kvůli dokumentaci, `explain`
a vypínání. repo-doctor duplikáty nikdy sám nemaže – úklid (přes koš) nabízí jen u klonu
bez necommitnutých a nepushnutých změn, a jen po potvrzení.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, RepoResult, ScanResult, Severity

DUPLICATE_ID = "duplicate-clone"
# SSH přes port 443 má u hostingů vlastní hostname, repo je ale stejné
HOST_ALIASES = {"ssh.github.com": "github.com", "altssh.gitlab.com": "gitlab.com"}


def remote_key(repo: RepoResult) -> str | None:
    """Normalizovaná identita remotu: `host/owner/repo` malými písmeny (SSH i HTTPS stejně).

    Bere `origin`, jinak první remote. Aliasy z `~/.ssh/config` už rozložil scanner
    (`parse_remote` vrací skutečný HostName), `.git` na konci cesty je odstraněné.
    """
    remotes = sorted(repo.remotes, key=lambda r: (r.name != "origin", r.name))
    for remote in remotes:
        if remote.host and remote.owner_path:
            path = remote.owner_path.strip("/").removesuffix(".git")
            host = remote.host.lower().rstrip(".")
            return f"{HOST_ALIASES.get(host, host)}/{path.lower()}"
    return None


def group_key(repo: RepoResult) -> str | None:
    key = remote_key(repo)
    if key:
        return f"remote:{key}"
    if not repo.remotes and repo.state.root_commit:
        return f"root:{repo.state.root_commit}"
    return None


def _activity(repo: RepoResult) -> datetime:
    return repo.state.last_commit or datetime.min.replace(tzinfo=UTC)


def describe(repo: RepoResult) -> str:
    s = repo.state
    last = s.last_commit.strftime("%Y-%m-%d") if s.last_commit else _("bez commitu")
    return _(
        "{path} · větev {branch} · poslední commit {last} · necommitnuté {uncommitted} · nepushnuté {unpushed}"
    ).format(
        path=repo.path,
        branch=s.branch or "—",
        last=last,
        uncommitted=s.uncommitted,
        unpushed=s.unpushed,
    )


def is_safe_to_remove(repo: RepoResult) -> bool:
    # Bez remotu nejde nepushnuté commity spočítat → kopie bez remotu se ke smazání nenabízí.
    return (
        bool(repo.remotes)
        and repo.state.uncommitted == 0
        and repo.state.unpushed == 0
        and not repo.untrusted_owner
    )


def is_linked_worktree(repo: RepoResult) -> bool:
    """Pracovní strom z `git worktree add` (`.git` je soubor) – není to samostatný klon."""
    return (Path(repo.path).expanduser() / ".git").is_file()


def duplicate_groups(result: ScanResult) -> list[list[RepoResult]]:
    groups: dict[str, list[RepoResult]] = defaultdict(list)
    for repo in result.repos:
        if repo.untrusted_owner or is_linked_worktree(repo):
            continue
        key = group_key(repo)
        if key:
            groups[key].append(repo)
    out = [sorted(g, key=_activity, reverse=True) for g in groups.values() if len(g) > 1]
    return sorted(out, key=lambda g: g[0].path)


def add_duplicate_findings(result: ScanResult) -> set[str]:
    """Doplní nálezy k duplikátům. Vrací cesty rep, kterým přibyl nález."""
    check = DuplicateClone()
    touched: set[str] = set()
    for group in duplicate_groups(result):
        main = group[0]
        key = remote_key(main)
        what = (
            _("stejný remote {key}").format(key=key)
            if key
            else _("stejný kořenový commit (bez remote)")
        )
        for repo in group:
            others = [r for r in group if r is not repo]
            if repo is main:
                advice = _("hlavní klon (nejnovější aktivita)")
            elif is_safe_to_remove(repo):
                advice = _("po kontrole ho lze smazat (hlavní je {path})").format(path=main.path)
            elif not repo.remotes:
                advice = _("bez remote – porovnej historii s {path}, než ho smažeš ručně").format(
                    path=main.path
                )
            else:
                advice = _(
                    "má necommitnuté nebo nepushnuté změny – nejdřív je přenes do {path}"
                ).format(path=main.path)
            repo.findings.append(
                check.finding(
                    _("duplicitní klon: {what} má i {join} · {advice}").format(
                        what=what, join=", ".join(o.path for o in others), advice=advice
                    ),
                    key=f"{key or main.state.root_commit}",
                    role="main" if repo is main else "duplicate",
                    main=main.path,
                    others=[o.path for o in others],
                    compare=[describe(r) for r in group],
                    removable="yes" if repo is not main and is_safe_to_remove(repo) else "no",
                )
            )
            touched.add(repo.path)
    return touched


@register
class DuplicateClone(Check):
    id = DUPLICATE_ID
    title = N_("Duplicitní klon")
    severity = Severity.LOW
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        return []  # počítá se napříč repy v add_duplicate_findings
