"""Úklid místa: regenerovatelné složky v repech (node_modules, .venv, target…) a koš.

Pravidla bezpečnosti:
- jen složky ignorované gitem (`git check-ignore`) a bez jediného sledovaného souboru,
- nikdy nic mimo repozitář, symlinky se nenásledují ani nemažou,
- složky, ve kterých běží proces (Linux `/proc`), se přeskočí,
- mazání přes koš (freedesktop Trash), trvalé smazání jen na výslovnou žádost,
- repo cizího vlastníka se nikdy nemění.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from repo_doctor.gitwrap import Git, GitError
from repo_doctor.i18n import _
from repo_doctor.models import ScanResult

DEFAULT_DIRS = (
    "node_modules",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".gradle",
    ".terraform",
)
MAX_DEPTH = 6
MB = 1024 * 1024


@dataclass
class Candidate:
    repo: Path
    path: Path  # absolutní cesta složky
    size: int
    kind: str = "dir"  # "dir" (regenerovatelná složka) | "clone" (celý duplicitní klon)
    busy: bool = False  # běží v ní proces

    @property
    def rel(self) -> str:
        return "." if self.path == self.repo else str(self.path.relative_to(self.repo))


@dataclass
class RepoCleanup:
    repo: Path
    candidates: list[Candidate] = field(default_factory=list)
    dirty: int = 0
    last_commit: datetime | None = None
    error: str | None = None

    @property
    def size(self) -> int:
        return sum(c.size for c in self.candidates if not c.busy)


def human(size: int) -> str:
    for unit, div in (("GB", 1024**3), ("MB", MB), ("kB", 1024)):
        if size >= div:
            return f"{size / div:.1f} {unit}"
    return f"{size} B"


def dir_size(path: Path) -> int:
    """Velikost složky bez následování symlinků (symlink se počítá jen jako odkaz)."""
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files + [d for d in dirs if Path(root, d).is_symlink()]:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def _busy_paths() -> list[str]:
    """Cesty, které mají otevřené běžící procesy (cwd a soubory), jen Linux /proc."""
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    out: list[str] = []
    me = os.getpid()
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) == me:
            continue
        with contextlib.suppress(OSError):
            out.append(str((pid_dir / "cwd").readlink()))
        try:
            for fd in (pid_dir / "fd").iterdir():
                try:
                    target = str(fd.readlink())
                except OSError:
                    continue
                if target.startswith("/"):
                    out.append(target)
        except OSError:
            continue
    return out


def mark_busy(candidates: Iterable[Candidate], busy: list[str] | None = None) -> None:
    paths = _busy_paths() if busy is None else busy
    for c in candidates:
        prefix = str(c.path) + os.sep
        c.busy = any(p == str(c.path) or p.startswith(prefix) for p in paths)


def find_candidates(
    repo: Path, names: Iterable[str] = DEFAULT_DIRS, git: Git | None = None
) -> list[Candidate]:
    """Regenerovatelné složky v repu: ignorované gitem, bez sledovaných souborů, bez symlinků."""
    repo = repo.resolve()
    wanted = set(names)
    git = git or Git(repo)
    found: list[Path] = []
    for root, dirs, _files in os.walk(repo, followlinks=False):
        depth = Path(root).relative_to(repo).parts
        keep: list[str] = []
        for d in dirs:
            full = Path(root) / d
            if d == ".git" or full.is_symlink():
                continue
            if d in wanted:
                found.append(full)
            elif len(depth) < MAX_DEPTH:
                keep.append(d)
        dirs[:] = keep
    out: list[Candidate] = []
    for path in found:
        rel = str(path.relative_to(repo))
        try:
            ignored = git.ok("check-ignore", "-q", "--", rel + "/")
            tracked = git.run("ls-files", "-z", "--", rel, check=False)
        except GitError:
            continue
        if ignored and not tracked:
            out.append(Candidate(repo, path, dir_size(path)))
    return out


def inspect_repo(path: Path, names: Iterable[str] = DEFAULT_DIRS) -> RepoCleanup:
    repo = path.resolve()
    git = Git(repo)
    info = RepoCleanup(repo)
    if git.dubious_ownership():
        info.error = _("repo patří jinému uživateli – nic se nemění")
        return info
    try:
        info.dirty = git.status().dirty
        ts = git.last_commit_ts()
        info.last_commit = datetime.fromtimestamp(ts, UTC) if ts else None
        info.candidates = find_candidates(repo, names, git)
    except (GitError, OSError) as err:
        info.error = str(err)
    return info


# ---------------------------------------------------------------------- koš
def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _mount_point(path: Path) -> Path:
    path = path.resolve()
    while not os.path.ismount(path) and path.parent != path:
        path = path.parent
    return path


def trash_dir_for(path: Path) -> Path:
    """Koš podle specifikace freedesktop: domovský, nebo `$topdir/.Trash-$uid` na jiném svazku."""
    home_trash = _xdg_data_home() / "Trash"
    anchor = home_trash
    while not anchor.exists() and anchor.parent != anchor:
        anchor = anchor.parent  # koš ani ~/.local/share ještě nemusí existovat
    home_dev = anchor.stat().st_dev
    if path.lstat().st_dev == home_dev:
        return home_trash
    top = _mount_point(path)
    shared = top / ".Trash"
    uid = os.getuid()
    st = shared.lstat() if shared.exists() else None
    if (
        st
        and stat.S_ISDIR(st.st_mode)
        and not stat.S_ISLNK(st.st_mode)
        and st.st_mode & stat.S_ISVTX
    ):
        return shared / str(uid)
    return top / f".Trash-{uid}"


def _check_own_dir(d: Path) -> None:
    """Koš na sdíleném svazku si mohl připravit někdo jiný (symlink, cizí vlastník)."""
    st = d.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise OSError(_("koš {d} není obyčejná složka – nepoužiju ho").format(d=d))
    if st.st_uid != os.getuid():
        raise OSError(_("koš {d} patří jinému uživateli – nepoužiju ho").format(d=d))
    if d.name.startswith(".Trash-") and st.st_mode & 0o077:
        raise OSError(_("koš {d} je přístupný ostatním – nepoužiju ho").format(d=d))


def move_to_trash(path: Path) -> Path:
    """Přesune složku do koše (rename na stejném svazku) a zapíše `.trashinfo`."""
    if path.is_symlink():
        raise OSError(_("{path} je symlink – nemažu").format(path=path))
    trash = trash_dir_for(path)
    files, info = trash / "files", trash / "info"
    if not trash.is_symlink():
        trash.parent.mkdir(parents=True, exist_ok=True)
        trash.mkdir(exist_ok=True, mode=0o700)
    _check_own_dir(trash)  # dřív, než se v něm cokoli vytvoří
    for d in (files, info):
        d.mkdir(exist_ok=True, mode=0o700)
        _check_own_dir(d)
    base = path.name
    for n in range(1, 10_000):
        name = base if n == 1 else f"{base}.{n}"
        info_file = info / f"{name}.trashinfo"
        try:
            fd = os.open(info_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            stamp = datetime.now().replace(microsecond=0).isoformat()
            fh.write(f"[Trash Info]\nPath={quote(str(path.resolve()))}\nDeletionDate={stamp}\n")
        target = files / name
        if target.exists():
            info_file.unlink()
            continue
        try:
            path.rename(target)
        except OSError:
            info_file.unlink(missing_ok=True)
            raise
        return target
    raise OSError(_("v koši už je příliš mnoho stejně pojmenovaných položek"))


def delete_permanently(path: Path) -> None:
    if path.is_symlink():
        raise OSError(_("{path} je symlink – nemažu").format(path=path))
    shutil.rmtree(path)


@dataclass
class CleanResult:
    removed: list[tuple[Path, int]] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def freed(self) -> int:
        return sum(size for _, size in self.removed)


def apply_cleanup(
    candidates: Iterable[Candidate],
    *,
    permanent: bool = False,
    remover: Callable[[Path], object] | None = None,
) -> CleanResult:
    """Smaže vybrané kandidáty (výchozí přes koš). Těsně před smazáním vše znovu ověří."""
    result = CleanResult()
    items = list(candidates)
    mark_busy(items)
    for c in items:
        reason = _verify(c)
        if reason:
            result.skipped.append((c.path, reason))
            continue
        try:
            if remover is not None:
                remover(c.path)
            elif permanent:
                delete_permanently(c.path)
            else:
                move_to_trash(c.path)
        except OSError as err:
            result.skipped.append((c.path, str(err)))
            continue
        result.removed.append((c.path, c.size))
    return result


def _verify(c: Candidate) -> str | None:
    if c.busy:
        return _("běží v ní proces")
    if c.path.is_symlink() or not c.path.is_dir():
        return _("už neexistuje nebo je to symlink")
    repo = c.repo.resolve()
    real = c.path.resolve()
    if c.kind == "clone":
        if real != repo:
            return _("neplatná cesta klonu")
        if (repo / ".git").is_file():
            return _("je to pracovní strom (git worktree), ne samostatný klon")
        git = Git(repo)
        if git.dubious_ownership():
            return _("repo patří jinému uživateli")
        if not git.worktree_is_path():
            return _("pracovní strom repa je jinde (core.worktree)")
        if not git.remotes():
            return _("klon nemá remote – nepushnuté commity nejde ověřit")
        if git.run("worktree", "list", "--porcelain", check=False).count("worktree ") > 1:
            return _("klon má další pracovní stromy (git worktree)")
        if git.status().dirty:
            return _("klon má necommitnuté změny")
        for b in git.branches():
            pending = (
                b.ahead if b.upstream and not b.upstream_gone else git.count_not_on_remotes(b.name)
            )
            if pending:
                return _("klon má nepushnuté commity")
        if git.run("stash", "list", check=False).strip():
            return _("klon má uložené stashe")
        skip = [f":(exclude,glob)**/{d}/**" for d in DEFAULT_DIRS]
        ignored = git.run(
            "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--", ".", *skip,
            check=False,
        ).split("\0")  # fmt: skip
        regenerable = set(DEFAULT_DIRS)
        own = [
            p for p in ignored
            if p and not regenerable & set(PurePosixPath(p).parts)
        ]  # fmt: skip
        if own:
            return _("klon má ignorované soubory, které jinde nejsou: {files}").format(
                files=", ".join(own[:3])
            )
        return None
    if real == repo or repo not in real.parents:
        return _("mimo repozitář")
    git = Git(repo)
    if git.dubious_ownership():
        return _("repo patří jinému uživateli")
    if not git.worktree_is_path():
        return _("pracovní strom repa je jinde (core.worktree)")
    rel = str(real.relative_to(repo))
    if not git.ok("check-ignore", "-q", "--", rel + "/") or git.run(
        "ls-files", "-z", "--", rel, check=False
    ):
        return _("obsahuje sledované soubory")
    return None


def is_inactive(info: RepoCleanup, days: int, now: datetime | None = None) -> bool:
    if info.last_commit is None:
        return True
    return (now or datetime.now(UTC)) - info.last_commit >= timedelta(days=days)


def duplicate_candidates(result: ScanResult | None) -> list[Candidate]:
    """Celé duplicitní klony z posledního skenu, které jdou bezpečně smazat (ověří se znovu)."""
    if result is None:
        return []
    out: list[Candidate] = []
    for repo in result.repos:
        if repo.untrusted_owner:
            continue
        for f in repo.findings:
            if f.check_id == "duplicate-clone" and f.data.get("removable") == "yes":
                path = Path(repo.path).expanduser()
                if path.is_dir() and not path.is_symlink():
                    out.append(Candidate(path.resolve(), path.resolve(), dir_size(path), "clone"))
    return out
