from __future__ import annotations

import os
from pathlib import Path

from repo_doctor.config import RootConfig
from repo_doctor.discovery import DiscoveryResult, discover, matches_any, suggest_depth
from tests.factory import RepoBuilder, git


def _names(result: DiscoveryResult) -> list[str]:
    return sorted(r.name for r in result.repos)


def test_multiple_roots_and_depth(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    RepoBuilder.create(a / "one")
    RepoBuilder.create(a / "group" / "two")
    RepoBuilder.create(a / "group" / "deep" / "deeper" / "three")
    RepoBuilder.create(b / "four")
    res = discover([RootConfig(path=str(a), depth=2), RootConfig(path=str(b), depth=1)])
    assert _names(res) == ["four", "one", "two"]
    assert res.per_root[str(a)] == 2


def test_overlapping_roots_counted_once(tmp_path: Path) -> None:
    RepoBuilder.create(tmp_path / "x" / "r1")
    res = discover([RootConfig(path=str(tmp_path)), RootConfig(path=str(tmp_path / "x"))])
    assert _names(res) == ["r1"]


def test_symlinks_not_followed_by_default(tmp_path: Path) -> None:
    real = tmp_path / "real"
    RepoBuilder.create(real / "r1")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(real, root / "link")
    assert _names(discover([RootConfig(path=str(root))])) == []
    res = discover([RootConfig(path=str(root), follow_symlinks=True)])
    assert _names(res) == ["r1"]
    # stejné repo dvěma cestami → jednou
    res = discover([RootConfig(path=str(root), follow_symlinks=True), RootConfig(path=str(real))])
    assert _names(res) == ["r1"]


def test_nested_and_submodules(tmp_path: Path) -> None:
    sub = RepoBuilder.create(tmp_path / "subsrc")
    sub.write("s.txt", "s").commit()
    parent = RepoBuilder.create(tmp_path / "root" / "parent")
    parent.write("p.txt", "p").commit()
    git(
        parent.path,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(sub.path),
        "vendor/sub",
    )
    RepoBuilder.create(parent.path / "nested")
    res = discover([RootConfig(path=str(tmp_path / "root"), depth=5)])
    assert _names(res) == ["parent"]


def test_disabled_and_missing(tmp_path: Path) -> None:
    RepoBuilder.create(tmp_path / "r")
    res = discover(
        [
            RootConfig(path=str(tmp_path), enabled=False),
            RootConfig(path=str(tmp_path / "missing")),
            RootConfig(path=str(tmp_path / "r" / ".git" / "HEAD")),
        ]
    )
    assert res.repos == []
    assert any("neexistuje" in w for w in res.warnings)
    assert any("není složka" in w for w in res.warnings)


def test_skip_dirs_and_excludes(tmp_path: Path) -> None:
    RepoBuilder.create(tmp_path / "node_modules" / "pkg")
    RepoBuilder.create(tmp_path / "archiv" / "old")
    RepoBuilder.create(tmp_path / "keep")
    res = discover([RootConfig(path=str(tmp_path), exclude=["**/archiv/**"])])
    assert _names(res) == ["keep"]
    res = discover([RootConfig(path=str(tmp_path))], ignore_repos=["keep"])
    assert _names(res) == ["old"]


def test_root_is_repo_and_worktree_file(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    rb.git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt")
    res = discover([RootConfig(path=str(tmp_path / "r"))])
    assert _names(res) == ["r"]
    res = discover([RootConfig(path=str(tmp_path), depth=1)])
    assert _names(res) == ["r", "wt"]


def test_permission_denied(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        res = discover([RootConfig(path=str(tmp_path))])
        if os.geteuid() != 0:
            assert any("oprávnění" in w for w in res.warnings)
    finally:
        locked.chmod(0o755)


def test_glob_matching() -> None:
    assert matches_any("a/archiv/b", ["**/archiv/**"])
    assert matches_any("archiv", ["**/archiv/**"])
    assert matches_any("x/tmp", ["tmp"])
    assert matches_any("x/y.bak", ["*.bak"])
    assert not matches_any("x/y", ["z", ""])
    assert matches_any("a/b", ["a/[bc]"])
    assert matches_any("a/b", ["a/?"])
    assert matches_any("a[", ["a["])


def test_suggest_depth(tmp_path: Path) -> None:
    RepoBuilder.create(tmp_path / "x" / "y" / "r")
    RepoBuilder.create(tmp_path / "z")
    assert suggest_depth(tmp_path) == (3, 2)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert suggest_depth(empty) == (3, 0)
