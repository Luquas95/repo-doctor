"""Synchronizace s remotem – jediná funkce, která mění pracovní strom, a jen fast-forwardem.

„Rychle dohnat“ = `git merge --ff-only @{u}` u repa, které je čisté, je na sledované větvi
a není rozdělené. Nikdy merge commit, rebase, reset ani push. Hooky zůstávají vypnuté
(`core.hooksPath=/dev/null`). Před provedením se stav ověří znovu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from repo_doctor.gitwrap import Git, GitError
from repo_doctor.i18n import N_, _

State = Literal[
    "clean", "behind", "ahead", "diverged", "no-upstream", "detached", "untrusted", "error"
]  # fmt: skip
STATE_LABELS: dict[str, str] = {
    "clean": N_("aktuální"),
    "behind": N_("pozadu"),
    "ahead": N_("napřed"),
    "diverged": N_("rozdělené"),
    "no-upstream": N_("bez sledované větve"),
    "detached": N_("detached HEAD"),
    "untrusted": N_("cizí vlastník"),
    "error": N_("chyba"),
}


@dataclass
class SyncStatus:
    path: Path
    name: str
    state: State
    branch: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    dirty: int = 0  # změny ve sledovaných souborech (staged, modified, conflicted)
    files: list[str] = field(default_factory=list)  # soubory, které fast-forward změní
    reason: str | None = None  # proč nejde rychle dohnat (None = jde)
    fetch_error: str | None = None

    @property
    def can_fast_forward(self) -> bool:
        return self.state == "behind" and self.reason is None


def overwrite_clash(git: Git, files: list[str]) -> list[str]:
    """Soubory z `files`, které leží na nesledovaných či ignorovaných cestách pracovního stromu."""
    changed = set(git.status().paths)  # status vrací i nesledované (soubory i „dir/“)
    # ignorované soubory (např. lokální .env) by fast-forward přepsal bez varování
    ignored = git.run(
        "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory", check=False
    )
    changed.update(p for p in ignored.split("\0") if p)
    return sorted(
        f for f in files for u in changed if f == u or (u.endswith("/") and f.startswith(u))
    )


def _plan_reason(git: Git, st: SyncStatus) -> str | None:
    if st.state != "behind":
        return {
            "clean": _("už je aktuální"),
            "ahead": _("má jen nepushnuté commity – nic k dohnání"),
            "diverged": _(
                "rozdělená historie – vyřeš ručně (merge/rebase), repo-doctor jen fast-forward"
            ),
            "no-upstream": _("větev nesleduje žádnou vzdálenou větev"),
            "detached": _("není na větvi (detached HEAD)"),
            "untrusted": _("repo patří jinému uživateli – nic se nemění"),
        }.get(st.state, "stav repa nejde zjistit")
    if st.dirty:
        return _("necommitnuté změny ve sledovaných souborech ({dirty})").format(dirty=st.dirty)
    if not git.worktree_is_path():
        return _("pracovní strom repa je jinde než repo (core.worktree) – nic se nemění")
    if any(k.startswith(("filter.", "merge.")) for k, _ in git.hardening_pairs()):
        return _("repo má vlastní filtry/drivery v .git/config – dohnat ručně (git pull --ff-only)")
    clash = overwrite_clash(git, st.files)
    if clash:
        return _("nesledované nebo ignorované soubory by se přepsaly: {files}").format(
            files=", ".join(clash[:3])
        )
    return None


def status(path: Path, *, fetch: bool = False) -> SyncStatus:
    """Stav repa vůči sledované větvi (volitelně po `git fetch`, pravidla sítě z 0.1.4/0.2.0)."""
    git = Git(path)
    st = SyncStatus(path=path, name=path.name, state="error")
    try:
        if git.dubious_ownership():
            st.state, st.reason = "untrusted", _("repo patří jinému uživateli – nic se nemění")
            return st
        if fetch:
            try:
                git.fetch()
            except GitError as err:
                from repo_doctor.sshhelp import friendly_git_error

                st.fetch_error = friendly_git_error(err.stderr, None)[:300]
        st.branch = git.current_branch()
        if st.branch is None:
            st.state = "detached"
        else:
            up = git.run(
                "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False
            ).strip()  # fmt: skip
            if not up or not git.ok("rev-parse", "--verify", "--quiet", "@{u}^{commit}"):
                st.state = "no-upstream"
            else:
                st.upstream = up
                counts = git.run("rev-list", "--left-right", "--count", "HEAD...@{u}").split()
                st.ahead, st.behind = int(counts[0]), int(counts[1])
                st.state = (
                    "diverged" if st.ahead and st.behind
                    else "behind" if st.behind
                    else "ahead" if st.ahead
                    else "clean"
                )  # fmt: skip
                if st.behind:
                    st.files = [
                        f
                        for f in git.run("diff", "--name-only", "-z", "HEAD", "@{u}", "--").split(
                            "\0"
                        )
                        if f
                    ]
        s = git.status()
        st.dirty = s.staged + s.modified + s.conflicted
        st.reason = _plan_reason(git, st)
    except (GitError, OSError, ValueError) as err:
        st.state, st.reason = "error", str(err)[:300]
    return st


@dataclass
class SyncResult:
    updated: list[tuple[Path, int]] = field(default_factory=list)  # (repo, počet commitů)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def fast_forward(paths: list[Path]) -> SyncResult:
    """Dohnání fast-forwardem. Stav každého repa se těsně předtím ověří znovu (bez fetch)."""
    result = SyncResult()
    for path in paths:
        st = status(path)
        if not st.can_fast_forward:
            result.skipped.append((path, st.reason or "nejde dohnat"))
            continue
        try:
            Git(path).run("merge", "--ff-only", "--no-edit", "--quiet", "@{u}")
        except GitError as err:
            result.skipped.append((path, err.stderr[:200] or "git merge --ff-only selhal"))
            continue
        result.updated.append((path, st.behind))
    return result
