"""Chybí ochrana proti pushnutí tajemství (`prepush-guard`)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.guard import HOOK_SCRIPT
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, FileChange, Finding, LocalAction, Patch, Severity

SECRET_TOOLS = ("gitleaks", "repo-doctor", "detect-secrets", "trufflehog", "ggshield", "secretlint")
PRECOMMIT_BLOCK = """\
  - repo: local
    hooks:
      - id: repo-doctor-guard
        name: repo-doctor guard ({name})
        entry: repo-doctor guard
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-push]
"""


def _precommit_block() -> str:
    return PRECOMMIT_BLOCK.format(name=_("tajemství před pushem"))


def precommit_protects(text: str) -> bool:
    """Má `.pre-commit-config.yaml` hlídač tajemství, který běží i při `pre-push`?"""
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    if not isinstance(data, dict):
        return False
    default_stages = data.get("default_stages") or []
    for repo in data.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        source = str(repo.get("repo", ""))
        for hook in repo.get("hooks") or []:
            if not isinstance(hook, dict):
                continue
            ident = " ".join(str(hook.get(k, "")) for k in ("id", "entry", "name")) + " " + source
            if not any(tool in ident for tool in SECRET_TOOLS):
                continue
            stages = hook.get("stages") or default_stages
            if any(s in ("pre-push", "push") for s in stages):
                return True
    return False


def _hook_ok(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


@register
class PrepushGuard(Check):
    id = "prepush-guard"
    title = N_("Chybí ochrana proti pushnutí tajemství")
    severity = Severity.LOW
    category = Category.SECURITY
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        if not repo.git.remotes():
            return []  # bez remote není kam pushnout
        hooks_path = repo.git.user_hooks_path()
        hook_dir = (
            (repo.path / os.path.expanduser(hooks_path)) if hooks_path else repo.git.hooks_dir()
        )
        if _hook_ok(hook_dir / "pre-push"):
            return []
        for name in (".pre-commit-config.yaml", ".pre-commit-config.yml"):
            if name in repo.all_files:
                text = repo.read_text(name) or ""
                if precommit_protects(text):
                    return []
        return [
            self.finding(
                _(
                    "repo nemá hook pre-push, který by zastavil push s tajemstvím "
                    "(ani gitleaks / repo-doctor guard v pre-commitu pro stage pre-push)"
                ),
                key="prepush",
            )
        ]

    def fixes(self, repo: RepoContext, findings: list[Finding]) -> list[Patch]:
        patches: list[Patch] = []
        name = next(
            (
                n
                for n in (".pre-commit-config.yaml", ".pre-commit-config.yml")
                if n in repo.all_files
            ),
            None,
        )
        text = repo.read_text(name) if name else None
        new: str | None = None
        if text is None and name is None:
            new = "repos:\n" + _precommit_block()
            change = FileChange(path=".pre-commit-config.yaml", action="create", content=new)
        elif text is not None and _repos_is_last_top_level(text):
            new = text + ("" if text.endswith("\n") else "\n") + _precommit_block()
            change = FileChange(path=str(name), action="replace", content=new, old=text)
        if new is not None:
            patches.append(
                Patch(
                    check_id=self.id,
                    variant="precommit",
                    title=_("do repa přes pre-commit"),
                    summary=_(
                        "hook repo-doctor guard pro stage pre-push v .pre-commit-config.yaml "
                        "(sdílené s ostatními, commit do větve oprav)"
                    ),
                    changes=[change],
                    notes=[
                        _(
                            "Aktivace u každého: pre-commit install --hook-type pre-push "
                            "(hook potřebuje repo-doctor v PATH)."
                        ),
                    ],
                )
            )
        if not repo.git.user_hooks_path():
            patches.append(
                Patch(
                    check_id=self.id,
                    variant="local",
                    title=_("jen lokálně (.git/hooks)"),
                    summary=_(
                        "nainstaluje .git/hooks/pre-push, který spustí repo-doctor guard "
                        "(jen tvůj klon, nic se necommituje)"
                    ),
                    local=[
                        LocalAction(
                            kind="hook",
                            key="pre-push",
                            value=HOOK_SCRIPT,
                            description="hook .git/hooks/pre-push → repo-doctor guard",
                        )
                    ],
                    notes=[_("Jednorázové obejití: git push --no-verify. Odinstalace: smaž hook.")],
                )
            )
        return patches


def _repos_is_last_top_level(text: str) -> bool:
    """Lze blok bezpečně připojit na konec? (`repos:` je poslední klíč nejvyšší úrovně)."""
    top = [
        line.split(":", 1)[0]
        for line in text.splitlines()
        if line and not line[0].isspace() and not line.startswith(("#", "-"))
    ]
    return bool(top) and top[-1] == "repos"
