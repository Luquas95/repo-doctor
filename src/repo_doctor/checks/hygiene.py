"""Hygiena repozitáře: README, licence, CI, pre-commit, .gitignore, velké soubory."""

from __future__ import annotations

import re

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.ecosystem import Ecosystem
from repo_doctor.gitwrap import GitTimeout
from repo_doctor.models import Category, Finding, Severity


def _top_level_names(repo: RepoContext) -> set[str]:
    return {f.split("/", 1)[0].lower() for f in repo.all_files}


@register
class ReadmeMissing(Check):
    id = "readme-missing"
    title = "Chybí README"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        names = _top_level_names(repo)
        if any(n.startswith("readme") for n in names):
            return []
        return [self.finding("V kořeni repozitáře není README.", key="readme")]


@register
class LicenseMissing(Check):
    id = "license-missing"
    title = "Chybí licence"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        names = _top_level_names(repo)
        if any(n.startswith(("license", "licence", "copying", "unlicense")) for n in names):
            return []
        return [self.finding("V kořeni repozitáře není LICENSE (ani COPYING).", key="license")]


@register
class CiMissing(Check):
    id = "ci-missing"
    title = "Chybí CI"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        ci_prefixes = (
            ".github/workflows/",
            ".forgejo/workflows/",
            ".gitea/workflows/",
            ".woodpecker",
            ".circleci/",
            ".buildkite/",
        )
        ci_files = {
            ".gitlab-ci.yml",
            ".travis.yml",
            "jenkinsfile",
            ".drone.yml",
            "azure-pipelines.yml",
            ".woodpecker.yml",
        }
        for f in repo.all_files:
            if f.startswith(ci_prefixes) or f.lower() in ci_files:
                return []
        return [
            self.finding(
                "Nenalezena konfigurace CI (.github/workflows, .gitlab-ci.yml, .forgejo/workflows…).",
                key="ci",
            )
        ]


@register
class PrecommitMissing(Check):
    id = "precommit-missing"
    title = "Chybí pre-commit"
    severity = Severity.LOW
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        if (
            ".pre-commit-config.yaml" in repo.all_files
            or ".pre-commit-config.yml" in repo.all_files
        ):
            return []
        return [
            self.finding(
                "Chybí .pre-commit-config.yaml (kontrola tajemství a formátu před commitem).",
                key="precommit",
            )
        ]


# Položky .gitignore podle ekosystému: (řádek do .gitignore, reprezentativní cesta pro check-ignore)
COMMON_IGNORES: list[tuple[str, str]] = [(".env", ".env"), (".env.*", ".env.local")]
ECOSYSTEM_IGNORES: dict[Ecosystem, list[tuple[str, str]]] = {
    Ecosystem.PYTHON: [
        ("__pycache__/", "pkg/__pycache__/mod.cpython-312.pyc"),
        (".venv/", ".venv/bin/python"),
        ("dist/", "dist/pkg.whl"),
    ],
    Ecosystem.NODE: [("node_modules/", "node_modules/pkg/index.js"), ("dist/", "dist/bundle.js")],
    Ecosystem.RUST: [("target/", "target/debug/app")],
    Ecosystem.GO: [("*.test", "pkg.test")],
}


def required_ignores(repo: RepoContext) -> list[tuple[str, str]]:
    result = list(COMMON_IGNORES)
    for eco in sorted(repo.ecosystems):
        for item in ECOSYSTEM_IGNORES.get(eco, []):
            if item[0] not in {r[0] for r in result}:
                result.append(item)
    return result


def missing_ignores(repo: RepoContext) -> list[str]:
    required = required_ignores(repo)
    ignored = repo.git.check_ignore([probe for _, probe in required])
    return [entry for entry, probe in required if probe not in ignored]


@register
class GitignoreMissing(Check):
    id = "gitignore-missing"
    title = "Chybí .gitignore"
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.exists(".gitignore"):
            return []
        eco = ", ".join(sorted(repo.ecosystems)) or "obecný"
        return [self.finding(f"Repozitář nemá .gitignore (ekosystém: {eco}).", key="gitignore")]


@register
class GitignoreIncomplete(Check):
    id = "gitignore-incomplete"
    title = "Neúplný .gitignore"
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        if not repo.exists(".gitignore"):
            return []  # řeší gitignore-missing
        missing = missing_ignores(repo)
        if not missing:
            return []
        severity = Severity.MEDIUM if any(m.startswith(".env") for m in missing) else Severity.LOW
        return [
            self.finding(
                f"chybí {', '.join(missing)}",
                severity=severity,
                path=".gitignore",
                key="gitignore-incomplete",
                missing=missing,
            )
        ]


BINARY_EXT = re.compile(
    r"\.(zip|tar|gz|tgz|bz2|xz|7z|rar|exe|dll|so|dylib|jar|war|bin|iso|img|dmg|apk|msi|deb|rpm|"
    r"mp4|mov|avi|mkv|mp3|wav|flac|psd|ai|sqlite|db|pdf|parquet|onnx|pt|pth|h5|ckpt|safetensors)$",
    re.IGNORECASE,
)


@register
class LargeFiles(Check):
    id = "large-files"
    title = "Velké soubory mimo Git LFS"
    severity = Severity.MEDIUM
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.head is None:
            return []
        limit = int(repo.config.limits.large_file_mb * 1024 * 1024)
        bin_limit = repo.config.limits.binary_file_kb * 1024
        entries = repo.git.ls_tree_sizes("HEAD")
        candidates = [
            e
            for e in entries
            if e.size > limit or (e.size > bin_limit and BINARY_EXT.search(e.path))
        ]
        lfs = repo.git.check_attr("filter", [e.path for e in candidates])
        findings: list[Finding] = []
        current_blobs = {e.sha for e in entries}
        for e in sorted(candidates, key=lambda e: -e.size):
            if lfs.get(e.path) == "lfs":
                continue
            kind = "binárka" if BINARY_EXT.search(e.path) else "soubor"
            sev = Severity.MEDIUM if e.size > limit else Severity.LOW
            findings.append(
                self.finding(
                    f"{kind} {_human(e.size)} v aktuálním stromu",
                    severity=sev,
                    path=e.path,
                    key=f"tree:{e.path}",
                    size=e.size,
                )
            )
        findings.extend(self._history(repo, limit, current_blobs))
        return findings

    def _history(self, repo: RepoContext, limit: int, current: set[str]) -> list[Finding]:
        """Bloby nad limitem, které už v aktuálním stromu nejsou (stále ale zvětšují klon)."""
        omitted: list[str] = []
        try:
            for line in repo.git.stream_lines(
                "rev-list",
                "--objects",
                "--all",
                f"--filter=blob:limit={limit + 1}",
                "--filter-print-omitted",
                timeout=repo.config.limits.history_timeout_s,
            ):
                if line.startswith("~"):
                    sha = line[1:].strip()
                    if sha not in current:
                        omitted.append(sha)
        except GitTimeout:
            return [
                self.incomplete(
                    "historie je příliš velká, velké soubory v ní nebyly prověřeny celé"
                )
            ]
        if not omitted:
            return []
        sizes = repo.git.run(
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
            input="\n".join(omitted) + "\n",
            check=False,
        )
        findings = []
        names = self._names_for(repo, set(omitted))
        for line in sizes.splitlines():
            parts = line.split()
            if len(parts) != 3 or parts[1] != "blob" or int(parts[2]) <= limit:
                continue
            sha, size = parts[0], int(parts[2])
            path = names.get(sha) or f"blob {sha[:7]}"
            findings.append(
                self.finding(
                    f"{_human(size)} v historii (už není v aktuálním stromu, ale zvětšuje každý klon)",
                    path=path,
                    key=f"history:{sha}",
                    size=size,
                )
            )
        return findings

    @staticmethod
    def _names_for(repo: RepoContext, shas: set[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        try:
            for line in repo.git.stream_lines(
                "rev-list", "--objects", "--all", timeout=repo.config.limits.history_timeout_s
            ):
                sha, _, path = line.partition(" ")
                if sha in shas and path:
                    names.setdefault(sha, path)
                    if len(names) == len(shas):
                        break
        except GitTimeout:
            pass
        return names


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"  # pragma: no cover
