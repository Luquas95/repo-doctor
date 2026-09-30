"""Továrna na testovací git repozitáře (vše v tmp_path, bez sítě).

Falešná tajemství se skládají až za běhu, aby je v tomto zdrojáku nenašel žádný skener.
"""

from __future__ import annotations

import os
import random
import string
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Tester",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test Tester",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _rand(chars: str, n: int, seed: int) -> str:
    rng = random.Random(seed)
    return "".join(rng.choice(chars) for _ in range(n))


def fake_aws_key(seed: int = 1) -> str:
    return "AK" + "IA" + _rand(string.ascii_uppercase + string.digits, 16, seed)


def fake_github_token(seed: int = 2) -> str:
    return "gh" + "p_" + _rand(string.ascii_letters + string.digits, 36, seed)


def fake_gitlab_token(seed: int = 3) -> str:
    return "gl" + "pat-" + _rand(string.ascii_letters + string.digits, 20, seed)


def fake_slack_token(seed: int = 4) -> str:
    return (
        "xo" + "xb-" + _rand(string.digits, 12, seed) + "-" + _rand(string.ascii_letters, 24, seed)
    )


def fake_openai_key(seed: int = 5) -> str:
    return "s" + "k-proj-" + _rand(string.ascii_letters + string.digits, 48, seed)


def fake_anthropic_key(seed: int = 6) -> str:
    return "s" + "k-ant-api03-" + _rand(string.ascii_letters + string.digits + "-_", 90, seed)


def fake_private_key() -> str:
    body = _rand(string.ascii_letters + string.digits + "+/", 64, 7)
    kind = "OPEN" + "SSH PRIVATE KEY"
    return f"-----BEGIN {kind}-----\n{body}\n-----END {kind}-----\n"


def fake_generic_secret(seed: int = 8) -> str:
    return _rand(string.ascii_letters + string.digits, 32, seed)


def fake_jwt(seed: int = 9) -> str:
    part = _rand(string.ascii_letters + string.digits, 24, seed)
    return (
        "ey" + "J" + part + ".ey" + "J" + part[::-1] + "." + _rand(string.ascii_letters, 30, seed)
    )


def fake_db_url(seed: int = 10) -> str:
    return (
        "postgres"
        + "://admin:"
        + _rand(string.ascii_letters + string.digits, 16, seed)
        + "@db.internal:5432/app"
    )


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = dict(os.environ) | GIT_ENV | (env or {})
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=full_env, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout


@dataclass
class RepoBuilder:
    path: Path
    _time: int = 1_750_000_000

    @classmethod
    def create(cls, path: Path, *, branch: str = "main", bare: bool = False) -> RepoBuilder:
        path.mkdir(parents=True, exist_ok=True)
        args = ["init", "-q", "-b", branch]
        if bare:
            args.append("--bare")
        git(path, *args)
        git(path, "config", "user.name", "Test Tester")
        git(path, "config", "user.email", "test@example.invalid")
        git(path, "config", "commit.gpgsign", "false")
        return cls(path)

    def write(self, rel: str, content: str | bytes) -> RepoBuilder:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, "utf-8")
        return self

    def remove(self, rel: str) -> RepoBuilder:
        (self.path / rel).unlink()
        return self

    def commit(
        self, message: str = "commit", *, ts: int | None = None, all_files: bool = True
    ) -> str:
        if ts is None:
            self._time += 3600
            ts = self._time
        date = f"{ts} +0000"
        if all_files:
            git(self.path, "add", "-A")
        git(
            self.path,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
            env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        )
        return git(self.path, "rev-parse", "HEAD").strip()

    def branch(self, name: str, start: str = "HEAD") -> RepoBuilder:
        git(self.path, "branch", name, start)
        return self

    def checkout(self, ref: str) -> RepoBuilder:
        git(self.path, "checkout", "-q", ref)
        return self

    def remote(self, name: str, url: str) -> RepoBuilder:
        git(self.path, "remote", "add", name, url)
        return self

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        return git(self.path, *args, env=env)

    def head(self) -> str:
        return git(self.path, "rev-parse", "HEAD").strip()

    def snapshot(self) -> dict[str, str]:
        """Stav repa pro porovnání před/po (HEAD, branche, status, index, soubory)."""
        files = {}
        for p in sorted(self.path.rglob("*")):
            if ".git" in p.relative_to(self.path).parts or not p.is_file():
                continue
            files[str(p.relative_to(self.path))] = p.read_bytes().hex()[:64] + str(p.stat().st_size)
        return {
            "head": git(self.path, "rev-parse", "HEAD").strip(),
            "symbolic": git(self.path, "symbolic-ref", "-q", "HEAD").strip(),
            "refs": git(self.path, "for-each-ref", "--format=%(refname) %(objectname)"),
            "status": git(self.path, "status", "--porcelain", env={"GIT_OPTIONAL_LOCKS": "0"}),
            "index": git(self.path, "ls-files", "-s"),
            "stash": git(self.path, "stash", "list"),
            "files": repr(files),
        }


def with_remote(tmp: Path, name: str = "proj", *, ahead: int = 0) -> tuple[RepoBuilder, Path]:
    """Repo naklonované z lokálního bare remote (plně offline)."""
    bare = tmp / f"{name}-remote.git"
    seed = RepoBuilder.create(tmp / f"{name}-seed")
    seed.write("README.md", "# seed\n").commit("init")
    git(tmp, "clone", "-q", "--bare", str(seed.path), str(bare))
    work = tmp / name
    git(tmp, "clone", "-q", str(bare), str(work))
    rb = RepoBuilder(work)
    git(work, "config", "user.name", "Test Tester")
    git(work, "config", "user.email", "test@example.invalid")
    for i in range(ahead):
        rb.write(f"f{i}.txt", str(i)).commit(f"local {i}")
    return rb, bare


def healthy_python_repo(path: Path) -> RepoBuilder:
    rb = RepoBuilder.create(path)
    rb.write("README.md", "# healthy\n")
    rb.write("LICENSE", "MIT License\n")
    rb.write(".gitignore", ".env\n.env.*\n__pycache__/\n.venv/\ndist/\n*.pyc\nbuild/\n")
    rb.write(".pre-commit-config.yaml", "repos: []\n")
    rb.write(".github/workflows/ci.yml", "name: ci\n")
    rb.write(
        "pyproject.toml", '[project]\nname = "healthy"\nversion = "0.1.0"\ndependencies = []\n'
    )
    rb.write("uv.lock", "version = 1\n")
    rb.write("src/healthy/__init__.py", "")
    rb.commit("init")
    return rb
