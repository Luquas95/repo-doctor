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
from repo_doctor.models import Finding, Patch

BRANCH_PREFIX = "repo-doctor/fixes-"


class FixRefused(Exception):
    """Opravu nelze bezpečně provést; zpráva vysvětluje proč."""


@dataclass
class ApplyResult:
    branch: str
    commits: list[tuple[str, str]] = field(default_factory=list)  # (check_id, sha)
    notes: list[str] = field(default_factory=list)


def render_diff(patch: Patch) -> str:
    out: list[str] = []
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
        patch = check.fix(repo, items)
        if patch is not None and patch.changes:
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


def apply(git: Git, patches: list[Patch], *, today: date | None = None) -> ApplyResult:
    """Vytvoří branch s jedním commitem na kontrolu. Pracovní strom ani HEAD se nemění."""
    if not patches:
        raise FixRefused("Nebyla vybrána žádná oprava.")
    head = preflight(git)
    name = branch_name(git, today or date.today())
    result = ApplyResult(branch=name)
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
        raise FixRefused("Vybrané opravy nic nemění (už jsou nejspíš aplikované).")
    try:
        git.create_branch(name, parent)
    except GitError as err:  # pragma: no cover - závod s jiným procesem
        raise FixRefused(f"Branch {name} nelze vytvořit: {err.stderr}") from err
    return result
