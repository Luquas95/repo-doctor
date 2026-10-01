"""Tenký, testovaný wrapper nad příkazem `git`.

Zásady:
- vždy seznam argumentů (žádný shell), vždy timeout,
- `GIT_OPTIONAL_LOCKS=0`, aby čtecí příkazy (např. `status`) nezapisovaly index,
- `core.fsmonitor=false` a vypnuté externí diffy/textconv, aby git v cizím repu nespouštěl
  programy z jeho konfigurace,
- cesty a názvy refů od uživatele jdou vždy za `--` / `--end-of-options`,
- chybové hlášky se před propagací redigují (tokeny v URL remote).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from repo_doctor.masking import redact, redact_url_credentials

DEFAULT_TIMEOUT = 30.0

_SAFE_CONFIG = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.pager=cat",
    "-c",
    "color.ui=false",
    "-c",
    "diff.external=",
    "-c",
    "log.showSignature=false",
    "-c",
    "core.quotePath=false",
)


def _clean(text: str) -> str:
    return redact_url_credentials(redact(text))


class GitError(RuntimeError):
    """Selhání příkazu git (zpráva je vždy redigovaná)."""

    def __init__(self, args: Sequence[str], returncode: int, stderr: str) -> None:
        self.git_args = [_clean(a) for a in args]
        self.returncode = returncode
        self.stderr = _clean(stderr.strip())
        super().__init__(
            f"git {' '.join(self.git_args[:3])} selhal ({returncode}): {self.stderr[:300]}"
        )


class GitTimeout(GitError):
    def __init__(self, args: Sequence[str], timeout: float) -> None:
        super().__init__(args, -1, f"překročen časový limit {timeout:g} s")
        self.timeout = timeout


class GitNotFound(GitError):
    def __init__(self) -> None:
        super().__init__(["git"], 127, "příkaz git nebyl nalezen v PATH")


def git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_EDITOR": "true",
            "GIT_SSH_COMMAND": env.get("GIT_SSH_COMMAND", "ssh") + " -o BatchMode=yes",
        }
    )
    # Proměnné, které by mohly přesměrovat git mimo zkoumané repo.
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CEILING_DIRECTORIES"):
        env.pop(var, None)
    if extra:
        env.update(extra)
    return env


@dataclass(frozen=True)
class StatusSummary:
    staged: int = 0
    modified: int = 0
    untracked: int = 0
    conflicted: int = 0
    paths: tuple[str, ...] = ()

    @property
    def dirty(self) -> int:
        return self.staged + self.modified + self.untracked + self.conflicted


@dataclass(frozen=True)
class BranchInfo:
    name: str
    sha: str
    committer_ts: int
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    upstream_gone: bool = False


@dataclass(frozen=True)
class StashInfo:
    ref: str
    timestamp: int
    message: str


@dataclass
class TreeEntry:
    path: str
    size: int
    sha: str


@dataclass
class CommitRef:
    sha: str
    timestamp: int
    extra: dict[str, str] = field(default_factory=dict)


class Git:
    """Operace nad jedním repozitářem."""

    def __init__(self, path: Path | str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._hardening: list[tuple[str, str]] | None = None

    # ------------------------------------------------------------------ nízká úroveň
    def _cmd(self, args: Sequence[str]) -> list[str]:
        return ["git", "--no-pager", *_SAFE_CONFIG, *self.hardening(), "-C", str(self.path), *args]

    def hardening_pairs(self) -> list[tuple[str, str]]:
        """Neutralizace programů, které by spustila konfigurace *repozitáře* (ne uživatele).

        Cizí `.git/config` (např. rozbalený archiv s .git) může definovat `filter.X.clean`,
        `diff.X.textconv/command` apod. – git by je spustil i při čtení (`status`, `log -p`).
        Proto je pro každé volání přebijeme prázdnou hodnotou. Globální konfiguraci uživatele
        (např. git-lfs) necháváme, ta je důvěryhodná.
        """
        if self._hardening is None:
            pairs: list[tuple[str, str]] = []
            try:
                proc = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.path),
                        "config",
                        "--local",
                        "--includes",
                        "--name-only",
                        "--get-regexp",
                        r"^(filter|diff|merge)\..*\.(clean|smudge|process|textconv|command|driver)$|^core\.(sshcommand|editor|pager|askpass)$",
                    ],
                    capture_output=True,
                    timeout=self.timeout,
                    env=git_env(),
                    check=False,
                    stdin=subprocess.DEVNULL,
                )
                names = proc.stdout.decode("utf-8", "replace").split()
            except (subprocess.TimeoutExpired, FileNotFoundError, NotADirectoryError):
                names = []
            safe = {
                "textconv": "cat",
                "command": "true",
                "driver": "false",
                "sshcommand": "ssh",
                "editor": "true",
                "pager": "cat",
            }
            for name in sorted(set(names)):
                if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                    continue
                pairs.append((name, safe.get(name.rsplit(".", 1)[-1].lower(), "")))
                if name.startswith("filter.") and name.endswith((".clean", ".smudge", ".process")):
                    pairs.append((name.rsplit(".", 1)[0] + ".required", "false"))
            self._hardening = pairs
        return self._hardening

    def hardening(self) -> list[str]:
        out: list[str] = []
        for key, value in self.hardening_pairs():
            out += ["-c", f"{key}={value}"]
        return out

    def hardening_env(self) -> dict[str, str]:
        """Totéž jako `hardening()`, ale přes GIT_CONFIG_* (pro externí nástroje, např. gitleaks)."""
        pairs = [
            *self.hardening_pairs(),
            ("core.fsmonitor", "false"),
            ("diff.external", ""),
            ("core.pager", "cat"),
        ]
        env = {"GIT_CONFIG_COUNT": str(len(pairs))}
        for i, (key, value) in enumerate(pairs):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        return env

    def run_bytes(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = True,
        input: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        limit = self.timeout if timeout is None else timeout
        try:
            proc = subprocess.run(
                self._cmd(args),
                input=input,
                capture_output=True,
                timeout=limit,
                env=git_env(env),
                check=False,
                stdin=None if input is not None else subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitTimeout(args, limit) from exc
        except FileNotFoundError as exc:
            raise GitNotFound() from exc
        if check and proc.returncode != 0:
            raise GitError(args, proc.returncode, proc.stderr.decode("utf-8", "replace"))
        return proc

    def run(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = True,
        input: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        proc = self.run_bytes(
            *args,
            timeout=timeout,
            check=check,
            input=input.encode() if input is not None else None,
            env=env,
        )
        return proc.stdout.decode("utf-8", "replace")

    def ok(self, *args: str, timeout: float | None = None) -> bool:
        try:
            return self.run_bytes(*args, timeout=timeout, check=False).returncode == 0
        except GitTimeout:
            return False

    def stream_lines(self, *args: str, timeout: float | None = None) -> Iterator[str]:
        """Streamuje stdout po řádcích. Po vypršení limitu proces ukončí a vyhodí GitTimeout.

        Volající může zachytit GitTimeout a pracovat s dosud přečtenými řádky.
        """
        limit = self.timeout if timeout is None else timeout
        try:
            proc = subprocess.Popen(
                self._cmd(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=git_env(),
            )
        except FileNotFoundError as exc:
            raise GitNotFound() from exc
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(limit, _kill)
        timer.daemon = True
        timer.start()
        if proc.stdout is None or proc.stderr is None:  # pragma: no cover - PIPE je vždy nastavený
            raise GitError(args, -1, "chybí výstupní roura")
        try:
            for raw in proc.stdout:
                if timed_out.is_set():
                    break
                yield raw.decode("utf-8", "replace").rstrip("\n")
            stderr = proc.stderr.read().decode("utf-8", "replace")
            proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()
        if timed_out.is_set():
            raise GitTimeout(args, limit)
        if proc.returncode != 0:
            raise GitError(args, proc.returncode, stderr)

    # ------------------------------------------------------------------ dotazy
    def is_repo(self) -> bool:
        return self.ok("rev-parse", "--git-dir")

    def toplevel(self) -> Path | None:
        out = self.run("rev-parse", "--show-toplevel", check=False).strip()
        return Path(out) if out else None

    def git_dir(self) -> Path:
        out = self.run("rev-parse", "--absolute-git-dir").strip()
        return Path(out)

    def is_bare(self) -> bool:
        return self.run("rev-parse", "--is-bare-repository", check=False).strip() == "true"

    def head_sha(self) -> str | None:
        proc = self.run_bytes("rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
        out = proc.stdout.decode().strip()
        return out or None

    def current_branch(self) -> str | None:
        """Název aktuální branche, `None` při detached HEAD."""
        proc = self.run_bytes("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode().strip() or None

    def is_detached(self) -> bool:
        return self.current_branch() is None and self.head_sha() is not None

    def remotes(self) -> dict[str, str]:
        out = self.run("config", "--get-regexp", r"^remote\..*\.url$", check=False)
        result: dict[str, str] = {}
        for line in out.splitlines():
            key, _, url = line.partition(" ")
            name = key[len("remote.") : -len(".url")]
            result.setdefault(name, url.strip())
        return result

    def config_get(self, key: str) -> str | None:
        out = self.run("config", "--get", "--end-of-options", key, check=False).strip()
        return out or None

    def status(self) -> StatusSummary:
        out = self.run_bytes("status", "--porcelain=v1", "-z", "--untracked-files=normal").stdout
        staged = modified = untracked = conflicted = 0
        paths: list[str] = []
        entries = out.decode("utf-8", "replace").split("\0")
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            x, y, path = entry[0], entry[1], entry[3:]
            paths.append(path)
            if x in "RC":  # přejmenování má za sebou původní cestu
                i += 1
            if x == "?" and y == "?":
                untracked += 1
            elif "U" in (x, y) or (x, y) in {("A", "A"), ("D", "D")}:
                conflicted += 1
            else:
                if x not in " ?!":
                    staged += 1
                if y not in " ?!":
                    modified += 1
        return StatusSummary(staged, modified, untracked, conflicted, tuple(paths))

    def branches(self) -> list[BranchInfo]:
        fmt = "%(refname:short)%00%(objectname)%00%(committerdate:unix)%00%(upstream:short)%00%(upstream:track,nobracket)"
        out = self.run("for-each-ref", f"--format={fmt}", "refs/heads", check=False)
        result: list[BranchInfo] = []
        for line in out.splitlines():
            parts = line.split("\0")
            if len(parts) < 5:
                continue
            name, sha, ts, upstream, track = parts[:5]
            ahead = behind = 0
            gone = track.strip() == "gone"
            for piece in track.split(","):
                piece = piece.strip()
                if piece.startswith("ahead "):
                    ahead = int(piece[6:])
                elif piece.startswith("behind "):
                    behind = int(piece[7:])
            result.append(
                BranchInfo(
                    name=name,
                    sha=sha,
                    committer_ts=int(ts or 0),
                    upstream=upstream or None,
                    ahead=ahead,
                    behind=behind,
                    upstream_gone=gone,
                )
            )
        return result

    def ref_exists(self, ref: str) -> bool:
        return self.ok("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")

    def remote_head(self, remote: str = "origin") -> str | None:
        """Výchozí branche remote podle `refs/remotes/<remote>/HEAD` (bez síťového dotazu)."""
        proc = self.run_bytes(
            "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD", check=False
        )
        out = proc.stdout.decode().strip()
        if proc.returncode != 0 or not out:
            return None
        return out.split("/", 1)[1] if "/" in out else out

    def default_branch(self) -> str | None:
        """Heuristika: origin/HEAD → main → master → aktuální branche."""
        names = {b.name for b in self.branches()}
        for remote in self.remotes():
            head = self.remote_head(remote)
            if head:
                return head
        for candidate in ("main", "master", "trunk", "develop"):
            if candidate in names:
                return candidate
        return self.current_branch()

    def count_not_on_remotes(self, ref: str) -> int:
        out = self.run(
            "rev-list",
            "--count",
            "--not",
            "--remotes",
            "--not",
            "--end-of-options",
            ref,
            check=False,
        )
        try:
            return int(out.strip() or 0)
        except ValueError:
            return 0

    def ahead_behind(self, left: str, right: str) -> tuple[int, int]:
        """(commity jen v left, commity jen v right)."""
        out = self.run(
            "rev-list",
            "--left-right",
            "--count",
            "--end-of-options",
            f"{left}...{right}",
            check=False,
        ).split()
        if len(out) != 2:
            return (0, 0)
        return int(out[0]), int(out[1])

    def merged_branches(self, target: str) -> list[str]:
        out = self.run(
            "for-each-ref",
            "--format=%(refname:short)",
            f"--merged={target}",
            "refs/heads",
            check=False,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]

    def stashes(self) -> list[StashInfo]:
        out = self.run("stash", "list", "--format=%gd%x00%ct%x00%gs", check=False)
        result = []
        for line in out.splitlines():
            parts = line.split("\0")
            if len(parts) == 3:
                result.append(StashInfo(parts[0], int(parts[1] or 0), parts[2]))
        return result

    def last_commit_ts(self) -> int | None:
        out = self.run("log", "-1", "--format=%ct", "--branches", check=False).strip()
        return int(out) if out.isdigit() else None

    def commit_timestamps(self, since_ts: int) -> list[int]:
        out = self.run("log", "--branches", f"--since={since_ts}", "--format=%ct", check=False)
        return [int(x) for x in out.split() if x.isdigit()]

    def commit_count(self) -> int:
        out = self.run("rev-list", "--count", "--all", check=False).strip()
        return int(out) if out.isdigit() else 0

    def ls_files(self, *, untracked: bool = False) -> list[str]:
        args = ["ls-files", "-z", "--cached"]
        if untracked:
            args += ["--others", "--exclude-standard"]
        out = self.run_bytes(*args, check=False).stdout.decode("utf-8", "replace")
        return sorted({p for p in out.split("\0") if p})

    def ls_tree_sizes(self, ref: str = "HEAD") -> list[TreeEntry]:
        proc = self.run_bytes("ls-tree", "-r", "-l", "-z", "--end-of-options", ref, check=False)
        if proc.returncode != 0:
            return []
        result = []
        for item in proc.stdout.decode("utf-8", "replace").split("\0"):
            if not item:
                continue
            meta, _, path = item.partition("\t")
            parts = meta.split()
            if len(parts) != 4 or parts[1] != "blob" or not parts[3].isdigit():
                continue
            result.append(TreeEntry(path=path, size=int(parts[3]), sha=parts[2]))
        return result

    def check_ignore(self, paths: Sequence[str], *, repo_rules_only: bool = True) -> set[str]:
        """Které z `paths` jsou ignorované (podle pravidel repa, bez ohledu na index)."""
        if not paths:
            return set()
        args = ["check-ignore", "--no-index", "--stdin", "-z"]
        env = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.excludesFile",
            "GIT_CONFIG_VALUE_0": "",
        }
        proc = self.run_bytes(
            *args,
            input="\0".join(paths).encode() + b"\0",
            check=False,
            env=env if repo_rules_only else None,
        )
        return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}

    def check_attr(self, attr: str, paths: Sequence[str]) -> dict[str, str]:
        if not paths:
            return {}
        proc = self.run_bytes(
            "check-attr",
            "-z",
            "--stdin",
            attr,
            input="\0".join(paths).encode() + b"\0",
            check=False,
        )
        parts = proc.stdout.decode("utf-8", "replace").split("\0")
        result: dict[str, str] = {}
        for i in range(0, len(parts) - 2, 3):
            result[parts[i]] = parts[i + 2]
        return result

    def show_file(self, ref: str, path: str) -> bytes | None:
        proc = self.run_bytes("cat-file", "blob", f"{ref}:{path}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    # ------------------------------------------------------------------ zápisové operace (jen opravy)
    def check_branch_name(self, name: str) -> bool:
        return self.ok("check-ref-format", "--branch", name) and not name.startswith("-")

    def hash_object(self, content: bytes) -> str:
        return self.run_bytes("hash-object", "-w", "--stdin", input=content).stdout.decode().strip()

    def create_branch(self, name: str, commit: str) -> None:
        if not self.check_branch_name(name):
            raise GitError(["branch", name], 1, "neplatný název branche")
        # `git branch` bez --force nikdy existující branch nepřepíše.
        self.run("branch", "--no-track", "--end-of-options", name, commit)

    def temp_index(self) -> TempIndex:
        return TempIndex(self)

    # ------------------------------------------------------------------ síť (jen na výslovný pokyn)
    def fetch(self, timeout: float = 120.0) -> None:
        self.run("fetch", "--quiet", "--no-write-fetch-head", "--no-prune", timeout=timeout)

    @staticmethod
    def clone(url: str, dest: Path, timeout: float = 600.0) -> None:
        """`git clone` do neexistující cesty. Existující cíl nikdy nepřepisuje."""
        if dest.exists():
            raise FileExistsError(f"cíl {dest} už existuje, klon by ho přepsal")
        if url.startswith("-"):
            raise GitError(["clone"], 1, "neplatná URL")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                ["git", "clone", "--quiet", "--", url, str(dest)],
                capture_output=True,
                timeout=timeout,
                env=git_env(),
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitTimeout(["clone"], timeout) from exc
        except FileNotFoundError as exc:
            raise GitNotFound() from exc
        if proc.returncode != 0:
            raise GitError(["clone", url], proc.returncode, proc.stderr.decode("utf-8", "replace"))


class TempIndex:
    """Dočasný index pro stavbu commitů bez dotyku pracovního stromu i aktuální branche."""

    def __init__(self, git: Git) -> None:
        self.git = git
        self._dir = tempfile.TemporaryDirectory(prefix="repo-doctor-idx-")
        self.env = {"GIT_INDEX_FILE": str(Path(self._dir.name) / "index")}

    def __enter__(self) -> TempIndex:
        return self

    def __exit__(self, *exc: object) -> None:
        self._dir.cleanup()

    def _run(self, *args: str, input: bytes | None = None) -> str:
        return self.git.run_bytes(*args, input=input, env=self.env).stdout.decode().strip()

    def read_tree(self, commit: str) -> None:
        self._run("read-tree", "--end-of-options", commit)

    def add_blob(self, path: str, sha: str, mode: str = "100644") -> None:
        self._run("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")

    def remove(self, path: str) -> None:
        self._run("update-index", "--force-remove", "--", path)

    def write_tree(self) -> str:
        return self._run("write-tree")

    def commit_tree(self, tree: str, parent: str, message: str) -> str:
        return self._run(
            "commit-tree", "--no-gpg-sign", tree, "-p", parent, "-F", "-", input=message.encode()
        )
