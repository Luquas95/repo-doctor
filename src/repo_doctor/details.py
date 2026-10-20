"""Detaily repa pro kartu a reporty: jazyky, velikost, závislosti, historie (#36).

Všechno offline z gitu a souborů v HEAD. Data z hostingu doplní scanner ze snapshotu API.
Selhání jednotlivého dotazu nic nezastaví – položka zůstane prázdná.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from repo_doctor.deps import DepsData, OsvEcosystem
from repo_doctor.gitwrap import Git, GitError, TreeEntry
from repo_doctor.models import AuthorCount, EcosystemInfo, LanguageShare, RepoDetails

# Jen programovací a značkovací jazyky (jako lišta jazyků na GitHubu) – data (JSON, YAML)
# a prostý text (Markdown) by podíl zkreslily.
EXTENSIONS: dict[str, str] = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++",
    ".hh": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".m": "Objective-C", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".ps1": "PowerShell", ".lua": "Lua", ".dart": "Dart", ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".ml": "OCaml",
    ".clj": "Clojure", ".r": "R", ".jl": "Julia", ".pl": "Perl", ".pm": "Perl",
    ".zig": "Zig", ".nim": "Nim", ".html": "HTML", ".htm": "HTML", ".css": "CSS",
    ".scss": "SCSS", ".sass": "SCSS", ".less": "Less", ".vue": "Vue", ".svelte": "Svelte",
    ".tf": "HCL", ".hcl": "HCL", ".nix": "Nix", ".sql": "SQL", ".tex": "TeX",
    ".tcss": "CSS", ".astro": "Astro", ".elm": "Elm", ".groovy": "Groovy", ".v": "V",
}  # fmt: skip
FILENAMES: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Makefile",
    "gnumakefile": "Makefile",
    "justfile": "Just",
}
# cizí, generovaný nebo stažený kód do jazyků nepatří
VENDORED = {
    "node_modules", "vendor", "third_party", "thirdparty", "dist", "build", "target",
    ".venv", "venv", "__pycache__", "site-packages", ".git",
}  # fmt: skip

ECOSYSTEM_NAMES: dict[OsvEcosystem, str] = {
    "PyPI": "python",
    "npm": "node",
    "crates.io": "rust",
    "Go": "go",
}
# podle souboru v repu: (ekosystém, správce balíčků)
MANAGERS: dict[str, tuple[str, str]] = {
    "uv.lock": ("python", "uv"),
    "poetry.lock": ("python", "poetry"),
    "pdm.lock": ("python", "pdm"),
    "Pipfile.lock": ("python", "pipenv"),
    "Pipfile": ("python", "pipenv"),
    "requirements.txt": ("python", "pip"),
    "package-lock.json": ("node", "npm"),
    "npm-shrinkwrap.json": ("node", "npm"),
    "yarn.lock": ("node", "yarn"),
    "pnpm-lock.yaml": ("node", "pnpm"),
    "bun.lock": ("node", "bun"),
    "bun.lockb": ("node", "bun"),
    "Cargo.toml": ("rust", "cargo"),
    "go.mod": ("go", "go"),
}
TOP_AUTHORS = 3
TOP_LANGUAGES = 6


def language_of(path: str) -> str | None:
    p = PurePosixPath(path)
    if any(part in VENDORED for part in p.parts[:-1]) or p.name.endswith((".min.js", ".min.css")):
        return None
    if p.name.lower() in FILENAMES:
        return FILENAMES[p.name.lower()]
    return EXTENSIONS.get(p.suffix.lower())


def languages(entries: list[TreeEntry]) -> list[LanguageShare]:
    sizes: dict[str, int] = {}
    for e in entries:
        if (lang := language_of(e.path)) is not None:
            sizes[lang] = sizes.get(lang, 0) + e.size
    ordered = sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))
    return [LanguageShare(name=n, bytes=b) for n, b in ordered if b > 0]


def ecosystems(files: list[str], deps: DepsData | None) -> list[EcosystemInfo]:
    """Ekosystémy se správci balíčků a počty závislostí (přímé / všechny z lockfilů)."""
    infos: dict[str, EcosystemInfo] = {}
    for f in files:
        p = PurePosixPath(f)
        if len(p.parts) > 3 or any(part in VENDORED for part in p.parts):
            continue
        name = (
            "requirements.txt"
            if p.name.startswith("requirements") and p.suffix == ".txt"
            else p.name
        )
        if name in MANAGERS:
            eco, manager = MANAGERS[name]
            info = infos.setdefault(eco, EcosystemInfo(name=eco))
            if manager not in info.managers:
                info.managers.append(manager)
    if deps is not None:
        direct: dict[str, set[str]] = {}
        total: dict[str, set[str]] = {}
        for d in deps.dependencies:
            eco = ECOSYSTEM_NAMES[d.ecosystem]
            infos.setdefault(eco, EcosystemInfo(name=eco))
            total.setdefault(eco, set()).add(d.name)
            if d.direct:
                direct.setdefault(eco, set()).add(d.name)
        for eco, info in infos.items():
            info.direct = len(direct.get(eco, set()))
            info.total = len(total.get(eco, set()))
    return sorted(infos.values(), key=lambda i: (-i.total, i.name))


def _safe[T](fn: Callable[[], T]) -> T | None:
    try:
        return fn()
    except (GitError, OSError, ValueError):
        return None


def collect(
    git: Git,
    *,
    files: list[str],
    deps: DepsData | None,
    license: str | None,
    now: datetime,
) -> RepoDetails:
    """Detaily z gitu a souborů. Bez HEAD (prázdné repo) zůstane většina prázdná."""
    entries = _safe(lambda: git.ls_tree_sizes("HEAD")) or []
    details = RepoDetails(
        languages=languages(entries)[:TOP_LANGUAGES],
        files=len(entries) if entries else len(files),
        worktree_bytes=sum(e.size for e in entries) if entries else None,
        git_bytes=_safe(git.objects_bytes),
        ecosystems=ecosystems(files, deps),
        license=license,
    )
    if first := _safe(git.first_commit_ts):
        details.first_commit = datetime.fromtimestamp(first, UTC)
    month = int((now - timedelta(days=30)).timestamp())
    year = int((now - timedelta(days=365)).timestamp())
    details.commits_30d = _safe(lambda: git.commit_count_since(month))
    details.commits_year = _safe(lambda: git.commit_count_since(year))
    if (authors := _safe(git.authors)) is not None:
        details.authors = len(authors)
        details.top_authors = [AuthorCount(name=n, commits=c) for n, c in authors[:TOP_AUTHORS]]
    if (branches := _safe(git.branches)) is not None:
        details.branches = len(branches)
    if tag := _safe(git.last_tag):
        details.last_tag = tag[0]
        details.last_tag_date = datetime.fromtimestamp(tag[1], UTC) if tag[1] else None
    return details
