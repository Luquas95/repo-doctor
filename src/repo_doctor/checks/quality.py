"""Kvalita a zdraví projektu: testy, lint, verze runtime, projektové dokumenty, aktualizační
bot a funkčnost odkazů v README. Vše se zjišťuje ze souborů, nic se nespouští."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator
from urllib.parse import unquote

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.czech import count
from repo_doctor.ecosystem import Ecosystem
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity

SOURCE_MIN = 5  # pod tímto počtem zdrojáků je repo skript/hračka a kontroly kódu mlčí
MAX_LINKS = 25

_SOURCE_EXT: dict[Ecosystem, tuple[str, ...]] = {
    Ecosystem.PYTHON: (".py",),
    Ecosystem.NODE: (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"),
    Ecosystem.RUST: (".rs",),
    Ecosystem.GO: (".go",),
}
_TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e", "testing"})
_TEST_FILE = re.compile(
    r"(^test_.+\.py$|_test\.(py|go)$|^conftest\.py$|\.(test|spec)\.(js|jsx|mjs|cjs|ts|tsx)$"
    r"|_spec\.rb$|Test\.java$)"
)
_VENDORED = frozenset({"node_modules", "vendor", "third_party", ".venv", "venv", "site-packages"})


def _is_test(path: str) -> bool:
    parts = path.split("/")
    return any(p.lower() in _TEST_DIRS for p in parts[:-1]) or bool(_TEST_FILE.search(parts[-1]))


def _is_vendored(path: str) -> bool:
    return any(p in _VENDORED for p in path.split("/")[:-1])


def _sources(repo: RepoContext, eco: Ecosystem) -> list[str]:
    exts = _SOURCE_EXT[eco]
    return [
        f
        for f in repo.tracked_files
        if f.endswith(exts) and not _is_vendored(f) and not _is_test(f)
    ]


def _has_tests(repo: RepoContext) -> bool:
    if any(_is_test(f) and not _is_vendored(f) for f in repo.tracked_files):
        return True
    # Rust má testy často přímo ve zdrojácích
    for f in repo.tracked_files:
        if f.endswith(".rs"):
            text = repo.read_text(f)
            if text and ("#[test]" in text or "#[cfg(test)]" in text):
                return True
    return False


def _code_ecosystems(repo: RepoContext) -> list[Ecosystem]:
    """Ekosystémy s dost zdrojáky na to, aby se kontroly kódu vyplatily."""
    return [e for e in _SOURCE_EXT if e in repo.ecosystems and len(_sources(repo, e)) >= SOURCE_MIN]


def _text(repo: RepoContext, *names: str) -> str:
    return "\n".join(repo.read_text(n) or "" for n in names if n in repo.tracked_set)


@register
class TestsMissing(Check):
    id = "tests-missing"
    title = N_("Projekt bez testů")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        ecos = _code_ecosystems(repo)
        if not ecos or _has_tests(repo):
            return []
        total = sum(len(_sources(repo, e)) for e in ecos)
        return [
            self.finding(
                _("Je tu {files}, ale žádné testy (adresář tests/, test_*.py, *.test.ts…).").format(
                    files=count(
                        total, _("zdrojový soubor"), _("zdrojové soubory"), _("zdrojových souborů")
                    )
                ),
                key="tests",
                files=total,
            )
        ]


_CI_FILES = (
    ".github/workflows/",
    ".forgejo/workflows/",
    ".gitea/workflows/",
    ".circleci/",
    ".buildkite/",
)
_CI_NAMES = frozenset(
    {".gitlab-ci.yml", ".travis.yml", ".drone.yml", "azure-pipelines.yml", "jenkinsfile"}
)
_TEST_CMD = re.compile(
    r"\b(pytest|py\.test|tox|nox|unittest|vitest|jest|mocha|ava|playwright test|ctest|rspec|"
    r"phpunit|mvn|gradle|gradlew|npm (run )?test|npm t|yarn (run )?test|pnpm (run )?test|"
    r"bun test|deno test|cargo (test|nextest)|go test|make (test|check)|dotnet test)\b",
    re.IGNORECASE,
)
_REUSED = re.compile(r"^\s*(uses:\s*\./|include:|extends:|workflow_call)", re.MULTILINE)


@register
class TestsNotInCi(Check):
    id = "tests-not-in-ci"
    title = N_("Testy existují, ale CI je nespouští")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        ci = [
            f
            for f in repo.tracked_files
            if f.lower().startswith(_CI_FILES)
            or f.lower().split("/")[-1] in _CI_NAMES
            or f.lower().startswith(".woodpecker")
        ]
        if not ci or not _has_tests(repo):
            return []
        for path in ci:
            text = repo.read_text(path)
            if text is None or _TEST_CMD.search(text) or _REUSED.search(text):
                return []  # nečitelné nebo složené z jiných souborů → nehádáme
        return [
            self.finding(
                _("Repo má testy, ale v CI konfiguraci není žádný příkaz, který je spouští."),
                path=ci[0],
                key="ci-tests",
            )
        ]


_PY_LINT = (
    "ruff.toml",
    ".ruff.toml",
    ".flake8",
    ".pylintrc",
    "pylintrc",
    ".style.yapf",
    ".isort.cfg",
)
_PY_LINT_TEXT = re.compile(
    r"\[tool\.(ruff|black|flake8|pylint|isort|autopep8|yapf)|\[(flake8|pylint)"
)
_NODE_LINT = re.compile(
    r"^(eslint\.config\.(js|mjs|cjs|ts)|\.eslintrc(\..+)?|biome\.jsonc?|\.prettierrc(\..+)?|"
    r"prettier\.config\.(js|mjs|cjs|ts)|deno\.jsonc?|\.oxlintrc\.json)$"
)
_LINT_HOOKS = re.compile(r"\b(ruff|black|flake8|pylint|eslint|prettier|biome)\b")


@register
class LintConfigMissing(Check):
    id = "lint-config-missing"
    title = N_("Chybí konfigurace linteru nebo formátovače")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        ecos = _code_ecosystems(repo)
        names = {f.split("/")[-1] for f in repo.tracked_files if f.count("/") <= 1}
        hooks = bool(_LINT_HOOKS.search(_text(repo, ".pre-commit-config.yaml")))
        if Ecosystem.PYTHON in ecos and not (
            hooks
            or names.intersection(_PY_LINT)
            or _PY_LINT_TEXT.search(_text(repo, "pyproject.toml", "setup.cfg", "tox.ini"))
        ):
            findings.append(
                self.finding(
                    _(
                        "Python projekt bez konfigurace linteru či formátovače (ruff, flake8, black…)."
                    ),
                    key="python",
                )
            )
        if Ecosystem.NODE in ecos and not (
            hooks
            or any(_NODE_LINT.match(n) for n in names)
            or re.search(r'"(eslintConfig|prettier|biome)"', _text(repo, "package.json"))
        ):
            findings.append(
                self.finding(
                    _(
                        "Node projekt bez konfigurace linteru či formátovače (eslint, prettier, biome)."
                    ),
                    key="node",
                )
            )
        return findings


_PY_PIN_FILES = frozenset({".python-version", "runtime.txt", ".tool-versions", "mise.toml"})
_NODE_PIN_FILES = frozenset({".nvmrc", ".node-version", ".tool-versions", "mise.toml"})


@register
class RuntimeUnpinned(Check):
    id = "runtime-unpinned"
    title = N_("Nepřipnutá verze jazyka")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        ecos = _code_ecosystems(repo)
        top = {f for f in repo.tracked_files if "/" not in f}
        if Ecosystem.PYTHON in ecos and not (
            top & _PY_PIN_FILES
            or re.search(
                r"requires-python|python_requires|python_version",
                _text(repo, "pyproject.toml", "setup.cfg", "setup.py", "Pipfile"),
            )
        ):
            findings.append(
                self.finding(
                    _(
                        "Není určená podporovaná verze Pythonu "
                        "(requires-python, .python-version nebo .tool-versions)."
                    ),
                    key="python",
                )
            )
        if Ecosystem.NODE in ecos and not (
            top & _NODE_PIN_FILES or re.search(r'"(engines|volta)"', _text(repo, "package.json"))
        ):
            findings.append(
                self.finding(
                    _(
                        "Není určená verze Node.js (engines v package.json, .nvmrc nebo .tool-versions)."
                    ),
                    key="node",
                )
            )
        return findings


def _has_file(repo: RepoContext, prefixes: tuple[str, ...], dirs: tuple[str, ...]) -> bool:
    for f in repo.tracked_files:
        parts = f.split("/")
        if len(parts) == 1 and parts[0].lower().startswith(prefixes):
            return True
        if len(parts) == 2 and parts[0] in dirs and parts[1].lower().startswith(prefixes):
            return True
    return False


@register
class ProjectDocsMissing(Check):
    id = "project-docs-missing"
    title = N_("Chybí projektové dokumenty")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        dirs = (".github", "docs", ".gitlab")
        tag = repo.git.last_tag() if repo.head else None
        if tag and not _has_file(
            repo, ("changelog", "changes", "history", "news", "releases"), dirs
        ):
            findings.append(
                self.finding(
                    _(
                        "Repo má tagy (poslední {tag}), ale žádný CHANGELOG ani poznámky k vydání."
                    ).format(tag=tag[0]),
                    key="changelog",
                )
            )
        if repo.visibility == "public" and not _has_file(repo, ("security",), dirs):
            findings.append(
                self.finding(
                    _(
                        "Veřejné repo bez SECURITY.md: nahlašovatelé zranitelností nevědí, kam psát."
                    ),
                    key="security",
                )
            )
        authors = repo.git.authors() if repo.head else []
        if len(authors) >= 3 and not _has_file(repo, ("contributing",), dirs):
            findings.append(
                self.finding(
                    _("Do repa přispívá {people}, ale chybí CONTRIBUTING.").format(
                        people=count(len(authors), _("člověk"), _("lidé"), _("lidí"))
                    ),
                    key="contributing",
                )
            )
        return findings


_BOT_FILES = frozenset(
    {
        ".github/dependabot.yml",
        ".github/dependabot.yaml",
        "renovate.json",
        "renovate.json5",
        ".renovaterc",
        ".renovaterc.json",
        ".github/renovate.json",
        ".github/renovate.json5",
        ".gitlab/renovate.json",
    }
)
_MANIFESTS = re.compile(
    r"(^|/)(pyproject\.toml|requirements[^/]*\.txt|Pipfile|package\.json|Cargo\.toml|go\.mod|"
    r"Dockerfile)$"
)


@register
class DependencyBotMissing(Check):
    id = "dependency-bot-missing"
    title = N_("Bez automatických aktualizací závislostí")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        if not repo.git.remotes():
            return []
        tracked = repo.tracked_set
        if tracked & _BOT_FILES or not any(_MANIFESTS.search(f) for f in tracked):
            return []
        if re.search(r'"renovate"', _text(repo, "package.json")):
            return []
        return [
            self.finding(
                _(
                    "Repo má závislosti, ale žádný Dependabot ani Renovate, "
                    "takže aktualizace a bezpečnostní opravy hlídá jen člověk."
                ),
                key="bot",
            )
        ]


# README je cizí vstup: všechno je omezené (délka štítku, cíle, řádku, souboru, počtu odkazů),
# aby žádný vzor nemohl projít celý soubor znovu pro každou závorku.
README_MAX_KB = 256
README_MAX_LINE = 1000
README_MAX_CANDIDATES = 500
_MD_LINK = re.compile(r'!?\[[^\]\n]{0,500}\]\(\s*<?([^)\s>]{1,2048})>?(?:\s+"[^"\n]{0,500}")?\s*\)')
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|//|#)")


@register
class ReadmeLinksBroken(Check):
    id = "readme-links-broken"
    title = N_("Rozbité odkazy v README")
    severity = Severity.LOW
    category = Category.MAINTENANCE

    def run(self, repo: RepoContext) -> list[Finding]:
        readmes = [
            f
            for f in repo.tracked_files
            if "/" not in f
            and f.lower().startswith("readme")
            and f.lower().endswith((".md", ".markdown"))
        ]
        findings: list[Finding] = []
        for readme in readmes:
            text = repo.read_text(readme, limit_kb=README_MAX_KB)
            if not text:
                continue
            seen: set[str] = set()
            for raw in self._links(text):
                if len(seen) >= README_MAX_CANDIDATES:
                    break
                target = self._local_target(raw)
                if target is None or target in seen:
                    continue
                seen.add(target)
                if not self._exists(repo, target):
                    findings.append(
                        self.finding(
                            _("Odkaz na „{target}“ vede na soubor, který v repu není.").format(
                                target=target[:200]
                            ),
                            path=readme,
                            key=f"link:{readme}:{target}",
                        )
                    )
                    if len(findings) >= MAX_LINKS:
                        return findings
        return findings

    @staticmethod
    def _links(text: str) -> Iterator[str]:
        """Cíle odkazů po řádcích, mimo bloky kódu (``` a ~~~); řádky jsou zpracované jen jednou."""
        fence: str | None = None
        for line in text.splitlines():
            marker = line.lstrip()[:3]
            if marker in ("```", "~~~"):
                fence = marker if fence is None else (None if marker == fence else fence)
                continue
            if fence is None and len(line) <= README_MAX_LINE:
                yield from _MD_LINK.findall(line)

    @staticmethod
    def _local_target(raw: str) -> str | None:
        """Cesta uvnitř repa z odkazu; `None` pro URL, kotvy, absolutní a ven mířící cesty."""
        if _SCHEME.match(raw) or "\\" in raw:
            return None
        path = unquote(raw.split("#", 1)[0].split("?", 1)[0])
        if not path or "\0" in path:
            return None
        target = (
            posixpath.normpath(path.lstrip("/"))
            if path.startswith("/")
            else posixpath.normpath(path)
        )
        if target == ".." or target.startswith("../") or target == ".":
            return None
        return target

    @staticmethod
    def _exists(repo: RepoContext, target: str) -> bool:
        """Existence podle seznamu souborů (sledované i nesledované neignorované), bez disku:
        cíl odkazu je text z cizího README a čtenáři na hostingu uvidí jen to, co je v gitu."""
        files = repo.all_files
        if target in repo.all_files_set:
            return True
        prefix = target.rstrip("/") + "/"
        return any(f.startswith(prefix) for f in files)
