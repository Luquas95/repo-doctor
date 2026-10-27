"""Hygiena stromu: konflikt-značky, commitnuté artefakty, rozbité symlinky, kolize názvů,
konce řádků, submoduly a soubory, které měly jít přes Git LFS."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.checks.hygiene import _human
from repo_doctor.czech import count
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity

MAX_FILES = 25  # víc nálezů téhož druhu v jednom repu nemá smysl vypisovat po souborech
_SYMLINK = "120000"
_GITLINK = "160000"

_MARK_START = re.compile(r"^<{7}(?: |$)", re.MULTILINE)
_MARK_MID = re.compile(r"^={7}$", re.MULTILINE)
_MARK_END = re.compile(r"^>{7}(?: |$)", re.MULTILINE)


@register
class ConflictMarkers(Check):
    id = "conflict-markers"
    title = N_("Zbytky po konfliktu při mergi")
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        for path in repo.tracked_files:
            text = repo.read_text(path)
            if text is None or "<<<<<<<" not in text:
                continue
            start = _MARK_START.search(text)
            if start is None:
                continue
            mid = _MARK_MID.search(text, start.end())
            if mid is None or _MARK_END.search(text, mid.end()) is None:
                continue
            line = text.count("\n", 0, start.start()) + 1
            findings.append(
                self.finding(
                    _("Soubor obsahuje nevyřešené značky konfliktu (<<<<<<<, =======, >>>>>>>)."),
                    path=path,
                    line=line,
                    key=f"conflict:{path}",
                )
            )
            if len(findings) >= MAX_FILES:
                break
        return findings


ARTIFACT_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        ".gradle",
    }
)
ARTIFACT_FILES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
ARTIFACT_SUFFIXES = (".pyc", ".pyo")


def _artifact_group(path: str, rust: bool) -> str | None:
    """Co sledovaná cesta je za artefakt: adresář (např. `node_modules`) nebo samotný soubor."""
    parts = path.split("/")
    for i, part in enumerate(parts[:-1]):
        if part in ARTIFACT_DIRS or (rust and i == 0 and part == "target"):
            return "/".join(parts[: i + 1])
    name = parts[-1]
    if name.lower() in ARTIFACT_FILES or name.endswith(ARTIFACT_SUFFIXES):
        return "/".join(parts[:-1]) + "/" + name if len(parts) > 1 else name
    return None


@register
class CommittedArtifacts(Check):
    id = "committed-artifacts"
    title = N_("Commitnuté build artefakty a cache")
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        groups: dict[str, int] = defaultdict(int)
        rust = "Cargo.toml" in repo.tracked_set
        for path in repo.tracked_files:
            group = _artifact_group(path, rust)
            if group is not None:
                groups[group] += 1
        findings = []
        for group, n in sorted(groups.items()):
            findings.append(
                self.finding(
                    _("{files} v gitu, ale patří do .gitignore (vygenerované nebo lokální)").format(
                        files=count(n, _("soubor"), _("soubory"), _("souborů"))
                    ),
                    path=group,
                    key=f"artifact:{group}",
                    files=n,
                )
            )
        return findings


@register
class BrokenSymlinks(Check):
    id = "broken-symlinks"
    title = N_("Rozbité symlinky")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.git.is_bare():
            return []
        findings: list[Finding] = []
        for entry in repo.git.ls_files_stage():
            if entry.mode != _SYMLINK or entry.path not in repo.tracked_set:
                continue
            raw = repo.git.run_bytes("cat-file", "blob", entry.sha, check=False).stdout
            target = raw.decode("utf-8", "replace").strip()
            if not target or "\0" in target:
                continue
            link = repo.path / entry.path
            if Path(os.path.normpath(link.parent / target)).exists():
                continue
            findings.append(
                self.finding(
                    _("Symlink ukazuje na „{target}“, což neexistuje.").format(target=target[:200]),
                    path=entry.path,
                    key=f"symlink:{entry.path}",
                )
            )
            if len(findings) >= MAX_FILES:
                break
        return findings


@register
class CaseCollisions(Check):
    id = "case-collisions"
    title = N_("Cesty lišící se jen velikostí písmen")
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        spellings: dict[str, set[str]] = defaultdict(set)
        for path in repo.tracked_files:
            pure = PurePosixPath(path)
            for i in range(1, len(pure.parts) + 1):
                prefix = "/".join(pure.parts[:i])
                spellings[prefix.casefold()].add(prefix)
        reported: list[str] = []
        findings: list[Finding] = []
        for folded in sorted(spellings, key=lambda p: (p.count("/"), p)):
            variants = spellings[folded]
            if len(variants) < 2 or any(folded.startswith(r + "/") for r in reported):
                continue
            reported.append(folded)
            findings.append(
                self.finding(
                    _("Na macOS a Windows se tyto cesty srazí do jedné: {names}.").format(
                        names=", ".join(sorted(variants))
                    ),
                    path=sorted(variants)[0],
                    key=f"case:{folded}",
                )
            )
            if len(findings) >= MAX_FILES:
                break
        return findings


_CRLF_NATIVE = (".bat", ".cmd", ".ps1", ".sln", ".vbs", ".reg")


@register
class LineEndings(Check):
    id = "line-endings"
    title = N_("Nejednotné konce řádků")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        infos = repo.git.ls_files_eol()
        tracked = repo.tracked_set
        findings: list[Finding] = []
        lf = 0
        crlf: list[str] = []
        for info in infos:
            if info.path not in tracked:
                continue
            if info.index == "mixed" and len(findings) < MAX_FILES:
                findings.append(
                    self.finding(
                        _("Soubor má v gitu smíšené konce řádků (LF i CRLF)."),
                        path=info.path,
                        key=f"mixed:{info.path}",
                    )
                )
            elif info.index == "lf":
                lf += 1
            elif (
                info.index == "crlf"
                and not info.attr.startswith(("text", "eol"))
                and not info.path.lower().endswith(_CRLF_NATIVE)
            ):
                crlf.append(info.path)
        if crlf and lf:
            findings.append(
                self.finding(
                    _(
                        "{files} má v gitu CRLF, ostatní LF, a žádné pravidlo "
                        "v .gitattributes to nesjednocuje (např. {example})."
                    ).format(
                        files=count(len(crlf), _("soubor"), _("soubory"), _("souborů")),
                        example=crlf[0],
                    ),
                    path=crlf[0],
                    key="policy",
                    files=len(crlf),
                )
            )
        return findings


@register
class SubmoduleState(Check):
    id = "submodule-state"
    title = N_("Rozbité nebo nezabezpečené submoduly")
    severity = Severity.MEDIUM
    category = Category.GIT

    def run(self, repo: RepoContext) -> list[Finding]:
        gitlinks = {e.path for e in repo.git.ls_files_stage() if e.mode == _GITLINK}
        mapped, urls = self._gitmodules(repo)
        findings: list[Finding] = []
        for path in sorted(gitlinks - set(mapped.values())):
            findings.append(
                self.finding(
                    _(
                        "Submodul není v .gitmodules, klon repa proto hlásí chybu "
                        "(no submodule mapping)."
                    ),
                    path=path,
                    key=f"unmapped:{path}",
                )
            )
        for name, path in sorted(mapped.items()):
            if path not in gitlinks:
                findings.append(
                    self.finding(
                        _("Záznam v .gitmodules už nemá odpovídající submodul."),
                        severity=Severity.LOW,
                        path=path,
                        key=f"stale:{path}",
                    )
                )
                continue
            if not repo.exists(f"{path}/.git") and not repo.git.is_bare():
                findings.append(
                    self.finding(
                        _("Submodul není stažený (git submodule update --init)."),
                        severity=Severity.LOW,
                        path=path,
                        key=f"uninit:{path}",
                    )
                )
            if urls.get(name, "").lower().startswith(("http://", "git://")):
                findings.append(
                    self.finding(
                        _(
                            "Submodul se stahuje nešifrovaně ({scheme}), obsah jde podvrhnout."
                        ).format(scheme=urls[name].split(":", 1)[0]),
                        path=path,
                        key=f"insecure:{path}",
                    )
                )
        return findings

    @staticmethod
    def _gitmodules(repo: RepoContext) -> tuple[dict[str, str], dict[str, str]]:
        """({jméno: cesta}, {jméno: url}) z .gitmodules; prázdné, když soubor není sledovaný."""
        if ".gitmodules" not in repo.tracked_set:
            return {}, {}
        out = repo.git.run(
            "config",
            "--file",
            str(repo.path / ".gitmodules"),
            "--null",
            "--get-regexp",
            r"^submodule\..*\.(path|url)$",
            check=False,
        )
        paths: dict[str, str] = {}
        urls: dict[str, str] = {}
        for item in out.split("\0"):
            key, _sep, value = item.partition("\n")
            match = re.fullmatch(r"submodule\.(.+)\.(path|url)", key)
            if match:
                (paths if match.group(2) == "path" else urls)[match.group(1)] = value
        return paths, urls


@register
class LfsNotApplied(Check):
    id = "lfs-not-applied"
    title = N_("Soubory určené pro Git LFS uložené přímo v gitu")
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE

    POINTER_MAX = 1024  # LFS pointer má pár set bajtů; větší blob pointerem být nemůže

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.head is None or not self._uses_lfs(repo):
            return []
        candidates = [e for e in repo.git.ls_tree_sizes("HEAD") if e.size > self.POINTER_MAX]
        attrs = repo.git.check_attr("filter", [e.path for e in candidates])
        findings: list[Finding] = []
        for e in sorted(candidates, key=lambda e: -e.size):
            if attrs.get(e.path) != "lfs":
                continue
            findings.append(
                self.finding(
                    _(
                        "Podle .gitattributes patří do Git LFS, ale v gitu je celý ({human})."
                    ).format(human=_human(e.size)),
                    path=e.path,
                    key=f"lfs:{e.path}",
                    size=e.size,
                )
            )
            if len(findings) >= MAX_FILES:
                break
        return findings

    @staticmethod
    def _uses_lfs(repo: RepoContext) -> bool:
        for path in repo.tracked_files:
            if path.rsplit("/", 1)[-1] == ".gitattributes":
                text = repo.read_text(path)
                if text and "filter=lfs" in text:
                    return True
        return False
