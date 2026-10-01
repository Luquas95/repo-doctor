"""Vyhledání git repozitářů ve sledovaných složkách."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from repo_doctor.config import RootConfig

SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".env",
        "target",
        "dist",
        "build",
        "__pycache__",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        ".gradle",
        ".idea",
        ".vscode",
        "vendor",
        ".terraform",
        ".next",
        ".nuxt",
        "site-packages",
        ".cargo",
        ".rustup",
        ".npm",
        ".pnpm-store",
        ".local",
        ".Trash",
        "lost+found",
    }
)


@dataclass(frozen=True)
class DiscoveredRepo:
    path: Path  # realpath
    root: str  # cesta sledované složky, jak je v konfiguraci
    display: str  # cesta, jak ji uživatel zná (pod rootem)

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class DiscoveryResult:
    repos: list[DiscoveredRepo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    per_root: dict[str, int] = field(default_factory=dict)


@lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Převede glob s `**` na regex (porovnává se s relativní cestou s `/`)."""
    i, out = 0, []
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append(pattern[i : j + 1].replace("\\", "\\\\"))
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + "/?")


def matches_any(rel_path: str, patterns: Iterable[str]) -> bool:
    rel = rel_path.strip("/")
    for pattern in patterns:
        p = pattern.strip()
        if not p:
            continue
        regex = _glob_regex(p.rstrip("/"))
        # vzor bez lomítka se porovná i jen s názvem (jako .gitignore)
        if regex.fullmatch(rel) or regex.fullmatch(rel + "/"):
            return True
        if "/" not in p.rstrip("/") and regex.fullmatch(rel.rsplit("/", 1)[-1]):
            return True
        # adresář odpovídající vzoru s koncovým `/**`
        if p.endswith("/**") and _glob_regex(p[:-3]).fullmatch(rel):
            return True
    return False


def _is_repo_dir(path: Path) -> bool:
    git = path / ".git"
    try:
        if git.is_dir():
            return (git / "HEAD").exists()
        if git.is_file():  # worktree / submodul s gitdir souborem
            return git.read_text("utf-8", "replace").startswith("gitdir:")
    except OSError:
        return False
    return False


def discover(
    roots: Iterable[RootConfig],
    ignore_repos: Iterable[str] = (),
) -> DiscoveryResult:
    result = DiscoveryResult()
    seen: set[str] = set()
    ignore = list(ignore_repos)
    for root in roots:
        if not root.enabled:
            continue
        base = root.expanded
        count = 0
        if not base.exists():
            result.warnings.append(f"Složka {root.path} neexistuje – přeskočena.")
            result.per_root[root.path] = 0
            continue
        if not base.is_dir():
            result.warnings.append(f"{root.path} není složka – přeskočena.")
            result.per_root[root.path] = 0
            continue
        visited_dirs: set[str] = set()
        stack: list[tuple[Path, int]] = [(base, 0)]
        while stack:
            current, depth = stack.pop()
            try:
                real = os.path.realpath(current)
            except OSError:
                continue
            if real in visited_dirs:
                continue
            visited_dirs.add(real)
            rel = os.path.relpath(current, base)
            rel = "" if rel == "." else rel.replace(os.sep, "/")
            if rel and matches_any(rel, root.exclude):
                continue
            if _is_repo_dir(current):
                if real in seen:
                    continue
                if matches_any(rel or current.name, ignore) or str(current) in ignore:
                    continue
                seen.add(real)
                count += 1
                result.repos.append(
                    DiscoveredRepo(path=Path(real), root=root.path, display=str(current))
                )
                continue  # do repa nevstupujeme (submoduly a vnořená repa patří rodiči)
            if depth >= root.depth:
                continue
            try:
                entries = sorted(os.scandir(current), key=lambda e: e.name, reverse=True)
            except PermissionError:
                result.warnings.append(f"Nedostatečná oprávnění: {current}")
                continue
            except OSError as err:
                result.warnings.append(f"Nelze číst {current}: {err.strerror}")
                continue
            for entry in entries:
                if entry.name == ".git":
                    continue
                # build/, env/, vendor/… přeskakujeme, ledaže jsou samy git repem
                if entry.name in SKIP_DIRS and not _is_repo_dir(Path(entry.path)):
                    continue
                try:
                    if entry.is_symlink():
                        if not root.follow_symlinks or not entry.is_dir(follow_symlinks=True):
                            continue
                    elif not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                stack.append((Path(entry.path), depth + 1))
        result.per_root[root.path] = count
    result.repos.sort(key=lambda r: (r.root, r.display))
    return result


def suggest_depth(base: Path, max_depth: int = 5) -> tuple[int, int]:
    """Návrh hloubky pro průvodce: (nejmenší hloubka pokrývající nalezená repa, počet repozitářů)."""
    found = discover([RootConfig(path=str(base), depth=max_depth)])
    if not found.repos:
        return (3, 0)
    depths = []
    for repo in found.repos:
        rel = os.path.relpath(repo.display, base)
        depths.append(0 if rel == "." else rel.count(os.sep) + 1)
    return (max(depths), len(found.repos))
