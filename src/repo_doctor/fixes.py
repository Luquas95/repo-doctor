"""Opravy: plánování (bez jakékoli změny) a aplikace do nové branche.

Aplikace nikdy nesahá na pracovní strom, index ani aktuální branch: commity se staví
v dočasném indexu (`GIT_INDEX_FILE`) přes `hash-object`/`write-tree`/`commit-tree`
a nakonec se vytvoří nová branch `repo-doctor/fixes-<datum>`. Nic se nepushuje.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from repo_doctor.checks.base import Check, RepoContext, get_check
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.models import Finding, LocalAction, Patch

BRANCH_PREFIX = "repo-doctor/fixes-"


class FixRefused(Exception):
    """Opravu nelze bezpečně provést; zpráva vysvětluje proč."""


@dataclass
class ApplyResult:
    branch: str | None  # None, pokud se nic necommitovalo (jen lokální akce)
    commits: list[tuple[str, str]] = field(default_factory=list)  # (check_id, sha)
    notes: list[str] = field(default_factory=list)
    local: list[str] = field(default_factory=list)  # popisy provedených lokálních akcí


def render_diff(patch: Patch) -> str:
    out: list[str] = []
    for action in patch.local:
        if action.kind == "git_config":
            out.append("--- .git/config (jen lokálně, nic se necommituje)\n+++ .git/config\n")
            out.append(f"@@ [{action.key.split('.', 1)[0]}] @@\n")
            if action.display_old is not None:
                out.append(f"-{action.key} = {action.display_old}\n")
            out.append(f"+{action.key} = {action.display_new or action.value}\n")
        else:
            out.append(f"--- /dev/null\n+++ .git/hooks/{action.key} (jen lokálně, spustitelný)\n")
            lines = action.value.splitlines()
            out.append(f"@@ -0,0 +1,{len(lines)} @@\n")
            out.extend(f"+{line}\n" for line in lines)
    for change in patch.changes:
        new = change.result(change.old)
        if new is None:
            out.append(
                f"--- a/{change.path}\n+++ /dev/null\n@@ odstraněno z gitu (soubor na disku zůstává) @@\n"
            )
            continue
        old_lines = (change.old or "").splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        from_name = f"a/{change.path}" if change.old is not None else "/dev/null"
        out.extend(difflib.unified_diff(old_lines, new_lines, from_name, f"b/{change.path}"))
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
    return "".join(out)


def plan(repo: RepoContext, findings: list[Finding]) -> list[Patch]:
    """Vygeneruje patche pro opravitelné nálezy. Nic nezapisuje."""
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.fixable:
            grouped[f.check_id].append(f)
    patches: list[Patch] = []
    for check_id, items in grouped.items():
        check: Check | None = get_check(check_id)
        if check is None:
            continue
        for patch in check.fixes(repo, items):
            if patch.changes or patch.local:
                patches.append(patch)
    return patches


def branch_name(git: Git, today: date) -> str:
    base = f"{BRANCH_PREFIX}{today:%Y-%m-%d}"
    name, n = base, 1
    while git.ref_exists(f"refs/heads/{name}"):
        n += 1
        name = f"{base}-{n}"
    return name


def preflight(git: Git) -> str:
    """Ověří, že opravu lze provést. Vrací SHA HEAD."""
    status = git.status()
    if status.dirty:
        raise FixRefused(
            f"Repo má necommitnuté změny ({status.dirty} souborů). repo-doctor na ně nesahá – "
            "commitni je nebo ulož do stashe a zkus to znovu."
        )
    head = git.head_sha()
    if head is None:
        raise FixRefused("Repo zatím nemá žádný commit, není z čeho vytvořit větev.")
    return head


# Lokální změny, které léčba smí provést (nic jiného v `.git/config` nemění).
LOCAL_CONFIG_KEYS = frozenset({"user.email"})
LOCAL_HOOKS = frozenset({"pre-push"})
HOOK_MARKER = "# repo-doctor guard"


def apply(git: Git, patches: list[Patch], *, today: date | None = None) -> ApplyResult:
    """Soubory: větev s jedním commitem na kontrolu (pracovní strom ani HEAD se nemění).
    Lokální akce (`user.email`, hook pre-push) se zapíší jen do `.git/` repa."""
    if not patches:
        raise FixRefused("Nebyla vybrána žádná oprava.")
    if git.dubious_ownership():
        raise FixRefused("Repo patří jinému uživateli – repo-doctor ho nikdy nemění.")
    if len({p.check_id for p in patches}) != len(patches):
        raise FixRefused("Od každé kontroly jde vybrat jen jednu variantu opravy.")
    result = ApplyResult(branch=None)
    file_patches = [p for p in patches if p.changes]
    if file_patches:
        _apply_files(git, file_patches, result, today or date.today())
    for patch in patches:
        for action in patch.local:
            _apply_local(git, action)
            result.local.append(action.description)
        if patch.local and not patch.changes:
            result.notes.extend(patch.notes)
    if not result.commits and not result.local:
        raise FixRefused("Vybrané opravy nic nemění (už jsou nejspíš aplikované).")
    return result


def _apply_local(git: Git, action: LocalAction) -> None:
    if action.kind == "git_config":
        if action.key not in LOCAL_CONFIG_KEYS:
            raise FixRefused(f"Lokální nastavení {action.key} léčba neumí.")
        git.run("config", "--local", "--end-of-options", action.key, action.value)
        return
    if action.key not in LOCAL_HOOKS:
        raise FixRefused(f"Hook {action.key} léčba neinstaluje.")
    target = git.hooks_dir() / action.key
    if target.exists() and HOOK_MARKER not in target.read_text("utf-8", "replace"):
        raise FixRefused(
            f"{target} už existuje (vlastní hook) – repo-doctor ho nepřepíše. "
            "Doplň do něj ručně: repo-doctor guard"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(action.value, "utf-8")
    target.chmod(0o755)


def _apply_files(git: Git, patches: list[Patch], result: ApplyResult, today: date) -> None:
    head = preflight(git)
    name = branch_name(git, today)
    result.branch = name
    overlay: dict[str, str | None] = {}
    parent = head
    with git.temp_index() as idx:
        idx.read_tree(head)
        tree = idx.write_tree()
        for patch in patches:
            for change in patch.changes:
                if change.path in overlay:
                    current = overlay[change.path]
                else:
                    blob = git.show_file(head, change.path)
                    current = blob.decode("utf-8", "replace") if blob is not None else None
                new = change.result(current)
                if new is None:
                    idx.remove(change.path)
                elif new != current:
                    idx.add_blob(change.path, git.hash_object(new.encode()))
                overlay[change.path] = new
            new_tree = idx.write_tree()
            if new_tree == tree:
                continue
            tree = new_tree
            parent = idx.commit_tree(tree, parent, patch.commit_message)
            result.commits.append((patch.check_id, parent))
            result.notes.extend(patch.notes)
    if not result.commits:
        result.branch = None
        return
    try:
        git.create_branch(name, parent)
    except GitError as err:  # pragma: no cover - závod s jiným procesem
        raise FixRefused(f"Branch {name} nelze vytvořit: {err.stderr}") from err
