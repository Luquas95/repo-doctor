"""Bezpečnost CI workflow (GitHub Actions, Forgejo/Gitea Actions) – `ci-security`.

Workflow se jen čtou (`yaml.safe_load`), nic z nich se nespouští. Nálezy:
nepřipnuté akce, `pull_request_target` s checkoutem kódu z PR, injekce výrazů do `run:`,
široká oprávnění tokenu, tajemství vypisovaná do logu a self-hosted runner ve veřejném repu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.models import Category, FileChange, Finding, Patch, Severity

WORKFLOW_DIRS = (".github/workflows/", ".forgejo/workflows/", ".gitea/workflows/")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Akce vlastněné samotným GitHubem – nepřipnutí je méně rizikové (medium i s tajemstvími).
FIRST_PARTY_OWNERS = frozenset({"actions", "github"})
# Pole událostí, která ovládá autor PR / issue / komentáře (nedůvěryhodný vstup).
UNTRUSTED_EXPR = re.compile(
    r"\$\{\{[^}]*\bgithub\.(?:"
    r"head_ref|"
    r"event\.(?:"
    r"issue\.(?:title|body)|"
    r"pull_request\.(?:title|body|head\.ref|head\.label|head\.repo\.default_branch)|"
    r"comment\.body|review\.body|review_comment\.body|discussion\.(?:title|body)|"
    r"pages\.[^}]*\.page_name|"
    r"commits\.[^}]*\.(?:message|author\.(?:email|name))|"
    r"head_commit\.(?:message|author\.(?:email|name))|"
    r"workflow_run\.(?:head_branch|head_commit\.message|display_title)"
    r"))[^}]*\}\}"
)
PR_HEAD_REF = re.compile(r"github\.(?:event\.pull_request\.head\.(?:sha|ref)|head_ref)")
SECRET_EXPR = re.compile(r"\$\{\{\s*secrets\.(?!GITHUB_TOKEN\b)[A-Za-z0-9_]+")
ECHO_SECRET = re.compile(r"(?:echo|printf|cat)\b[^\n]*\$\{\{\s*secrets\.", re.IGNORECASE)
XTRACE = re.compile(r"(?m)^\s*set\s+-[a-zA-Z]*x|set\s+-o\s+xtrace|\bbash\s+-[a-zA-Z]*x")
FOREIGN_PR_EVENTS = frozenset({"pull_request_target", "workflow_run", "issue_comment"})


@dataclass(frozen=True)
class ActionRef:
    """`uses: owner/repo[/path]@ref` v souboru workflow."""

    file: str
    line: int
    uses: str  # celý text za `uses:` (bez uvozovek)
    repo: str  # owner/repo (bez cesty uvnitř repa)
    ref: str

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0].lower()

    @property
    def key(self) -> str:
        return f"{self.repo}@{self.ref}"


@dataclass
class Workflow:
    path: str
    text: str
    data: dict[Any, Any]
    events: set[str] = field(default_factory=set)

    @property
    def github(self) -> bool:
        return self.path.startswith(".github/")

    def line_of(self, needle: str, start: int = 0) -> int:
        for i, line in enumerate(self.text.splitlines()[start:], start=start + 1):
            if needle in line:
                return i
        return 0

    def jobs(self) -> list[tuple[str, dict[str, Any]]]:
        jobs = self.data.get("jobs")
        if not isinstance(jobs, dict):
            return []
        return [(str(k), v) for k, v in jobs.items() if isinstance(v, dict)]

    def steps(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        for name, job in self.jobs():
            for step in job.get("steps") or []:
                if isinstance(step, dict):
                    out.append((name, step))
        return out


def _events(data: dict[Any, Any]) -> set[str]:
    # YAML 1.1 (pyyaml) čte klíč `on` jako True
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(e) for e in on}
    if isinstance(on, dict):
        return {str(e) for e in on}
    return set()


def load_workflows(repo: RepoContext) -> list[Workflow]:
    out: list[Workflow] = []
    for path in repo.tracked_files:
        if not path.startswith(WORKFLOW_DIRS) or PurePosixPath(path).suffix not in (
            ".yml",
            ".yaml",
        ):
            continue
        text = repo.read_text(path, limit_kb=512)
        if not text:
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            out.append(Workflow(path, text, data, _events(data)))
    return out


def parse_uses(uses: str) -> tuple[str, str] | None:
    """`owner/repo/sub@ref` → (owner/repo, ref). Lokální (`./`) a `docker://` akce → None."""
    uses = uses.strip().strip("'\"")
    if uses.startswith(("./", "docker://")) or "@" not in uses:
        return None
    target, _, ref = uses.rpartition("@")
    if "://" in target:  # Forgejo: https://code.forgejo.org/actions/checkout@v4
        target = (
            target.split("://", 1)[1].split("/", 1)[1] if "/" in target.split("://", 1)[1] else ""
        )
    parts = [p for p in target.split("/") if p]
    if len(parts) < 2 or not ref:
        return None
    return "/".join(parts[:2]), ref


def action_refs(wf: Workflow) -> list[ActionRef]:
    refs: list[ActionRef] = []
    last = 0
    for _, step in wf.steps():
        uses = step.get("uses")
        if not isinstance(uses, str):
            continue
        parsed = parse_uses(uses)
        if parsed is None:
            continue
        line = wf.line_of(uses.strip(), last) or wf.line_of(uses.strip())
        last = max(last, line)
        refs.append(ActionRef(wf.path, line, uses.strip(), parsed[0], parsed[1]))
    # akce použité přímo jako job (reusable workflow) – `jobs.<id>.uses`
    for _, job in wf.jobs():
        uses = job.get("uses")
        if isinstance(uses, str) and (parsed := parse_uses(uses)):
            refs.append(ActionRef(wf.path, wf.line_of(uses.strip()), uses.strip(), *parsed))
    return refs


def unpinned_refs(workflows: list[Workflow], trusted: set[str]) -> list[ActionRef]:
    return [
        r
        for wf in workflows
        for r in action_refs(wf)
        if not SHA_RE.match(r.ref) and r.owner not in trusted
    ]


def trusted_owners(repo: RepoContext) -> set[str]:
    return {o.lower() for o in repo.config.ci.trusted_action_owners}


@register
class CISecurity(Check):
    id = "ci-security"
    title = "Rizikové nastavení CI workflow"
    severity = Severity.MEDIUM
    category = Category.SECURITY
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        workflows = load_workflows(repo)
        findings: list[Finding] = []
        trusted = trusted_owners(repo)
        for wf in workflows:
            findings += self._workflow(repo, wf, trusted)
        return findings[:50]

    def _workflow(self, repo: RepoContext, wf: Workflow, trusted: set[str]) -> list[Finding]:
        out: list[Finding] = []
        uses_secrets = bool(SECRET_EXPR.search(wf.text))
        # 1) nepřipnuté akce
        for ref in unpinned_refs([wf], trusted):
            third_party = ref.owner not in FIRST_PARTY_OWNERS
            high = third_party and uses_secrets
            sha = repo.action_shas.get(ref.key, "")
            out.append(
                self.finding(
                    f"akce {ref.uses} není připnutá na commit SHA"
                    + (" (workflow pracuje s tajemstvími)" if high else ""),
                    title="Akce nepřipnutá na commit",
                    severity=Severity.HIGH if high else Severity.MEDIUM,
                    path=wf.path,
                    line=ref.line,
                    key=f"unpinned:{wf.path}:{ref.key}",
                    kind="unpinned",
                    fixable=bool(sha),
                    action=ref.uses,
                    sha=sha,
                )
            )
        # 2) pull_request_target + checkout kódu z PR
        if "pull_request_target" in wf.events:
            for job, step in wf.steps():
                with_ = step.get("with") if isinstance(step.get("with"), dict) else {}
                ref_value = str((with_ or {}).get("ref", ""))
                uses = str(step.get("uses", ""))
                if "checkout" in uses and PR_HEAD_REF.search(ref_value):
                    out.append(
                        self.finding(
                            f"pull_request_target spouští kód z PR (checkout {ref_value.strip()}) "
                            f"s právy repa · job {job}",
                            title="pull_request_target s kódem z PR",
                            severity=Severity.HIGH,
                            path=wf.path,
                            line=wf.line_of("ref:", wf.line_of(uses) - 1 if uses else 0)
                            or wf.line_of("pull_request_target"),
                            key=f"prt:{wf.path}:{job}",
                            kind="pull_request_target",
                            fixable=False,
                        )
                    )
        # 3) injekce výrazů do run:, 5) tajemství v logu
        for job, step in wf.steps():
            run = step.get("run")
            if not isinstance(run, str):
                continue
            first = run.strip().splitlines()[0] if run.strip() else ""
            line = wf.line_of(first) if first else 0
            m = UNTRUSTED_EXPR.search(run)
            if m:
                out.append(
                    self.finding(
                        f"run: vkládá nedůvěryhodný vstup {m.group(0)} přímo do shellu · job {job}",
                        title="Injekce výrazu do run:",
                        severity=Severity.HIGH,
                        path=wf.path,
                        line=line,
                        key=f"inject:{wf.path}:{job}:{m.group(0)}",
                        kind="injection",
                        fixable=False,
                    )
                )
            env = step.get("env") if isinstance(step.get("env"), dict) else {}
            step_secrets = bool(SECRET_EXPR.search(run)) or any(
                SECRET_EXPR.search(str(v)) for v in (env or {}).values()
            )
            if ECHO_SECRET.search(run) or (step_secrets and XTRACE.search(run)):
                out.append(
                    self.finding(
                        f"krok vypisuje tajemství do logu (echo nebo set -x) · job {job}",
                        title="Tajemství v logu CI",
                        severity=Severity.MEDIUM,
                        path=wf.path,
                        line=line,
                        key=f"log:{wf.path}:{job}:{line}",
                        kind="secret-log",
                        fixable=False,
                    )
                )
        # 4) oprávnění tokenu
        perms = [wf.data.get("permissions")] + [j.get("permissions") for _, j in wf.jobs()]
        if any(p == "write-all" for p in perms):
            out.append(
                self.finding(
                    "permissions: write-all – token workflow smí zapisovat úplně všude",
                    title="Široká oprávnění tokenu",
                    path=wf.path,
                    line=wf.line_of("write-all"),
                    key=f"perms:{wf.path}:write-all",
                    kind="permissions",
                    fixable=False,
                )
            )
        elif wf.events & FOREIGN_PR_EVENTS and all(p is None for p in perms):
            out.append(
                self.finding(
                    f"workflow spouštěný cizími PR ({', '.join(sorted(wf.events & FOREIGN_PR_EVENTS))}) "
                    "nemá omezená oprávnění tokenu (permissions)",
                    title="Chybí omezení oprávnění tokenu",
                    path=wf.path,
                    line=1,
                    key=f"perms:{wf.path}:missing",
                    kind="permissions",
                    fixable=False,
                )
            )
        # 6) self-hosted runner ve veřejném repu
        if wf.github and repo.visibility == "public":
            for job, data in wf.jobs():
                runs_on = data.get("runs-on")
                labels = (
                    [runs_on]
                    if isinstance(runs_on, str)
                    else runs_on
                    if isinstance(runs_on, list)
                    else (runs_on or {}).get("labels", [])
                    if isinstance(runs_on, dict)
                    else []
                )
                if any(str(lbl) == "self-hosted" for lbl in labels or []):
                    out.append(
                        self.finding(
                            f"veřejné repo používá self-hosted runner · job {job} – cizí PR "
                            "může spustit kód na tvém stroji",
                            title="Self-hosted runner ve veřejném repu",
                            severity=Severity.HIGH,
                            path=wf.path,
                            line=wf.line_of("self-hosted"),
                            key=f"selfhosted:{wf.path}:{job}",
                            kind="self-hosted",
                            fixable=False,
                        )
                    )
        return out

    def fix(self, repo: RepoContext, findings: list[Finding]) -> Patch | None:
        """Připne akce na SHA zjištěné přes API: `@v4` → `@<sha> # v4`. Nic jiného nemění."""
        by_file: dict[str, dict[str, str]] = {}
        for f in findings:
            sha, uses, path = (
                str(f.data.get("sha") or ""),
                str(f.data.get("action") or ""),
                f.location.path,
            )
            if f.kind == "unpinned" and SHA_RE.match(sha) and uses and path:
                by_file.setdefault(path, {})[uses] = sha
        changes: list[FileChange] = []
        for path, pins in sorted(by_file.items()):
            text = repo.read_text(path, limit_kb=512)
            if text is None:
                continue
            new = pin_actions(text, pins)
            if new != text:
                changes.append(FileChange(path=path, action="replace", content=new, old=text))
        if not changes:
            return None
        n = sum(len(p) for p in by_file.values())
        return Patch(
            check_id=self.id,
            title="připnutí akcí na commit SHA",
            summary=f"připne {n} {'akci' if n == 1 else 'akce' if n < 5 else 'akcí'} na SHA "
            "(původní tag zůstane v komentáři)",
            changes=changes,
            notes=[
                "Ostatní nálezy ci-security je potřeba opravit ručně – viz explain ci-security."
            ],
        )


def pin_actions(text: str, pins: dict[str, str]) -> str:
    """Nahradí `uses: X@ref` za `uses: X@<sha> # ref` jen na řádcích s přesně touto akcí."""
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = re.match(
            r"^([ \t]*-?[ \t]*uses:[ \t]*)(['\"]?)([^'\"\s#]+)(['\"]?)([ \t]*)(#.*)?(\r?\n)?$", line
        )
        if not m or m.group(3) not in pins:
            continue
        target, _, ref = m.group(3).rpartition("@")
        nl = m.group(7) or ""
        lines[i] = f"{m.group(1)}{m.group(2)}{target}@{pins[m.group(3)]}{m.group(4)} # {ref}{nl}"
    return "".join(lines)
