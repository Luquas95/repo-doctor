from __future__ import annotations

import os
from pathlib import Path

import pytest

from repo_doctor.models import Severity
from tests.factory import RepoBuilder, healthy_python_repo
from tests.helpers import run

TREE = [
    "conflict-markers",
    "committed-artifacts",
    "broken-symlinks",
    "case-collisions",
    "line-endings",
    "submodule-state",
    "lfs-not-applied",
]

# Značky se skládají za běhu, aby je v tomto zdrojáku nenašel žádný skener konfliktů.
START, MID, END = "<" * 7, "=" * 7, ">" * 7


def test_healthy_repo_has_no_tree_findings(tmp_path: Path) -> None:
    rb = healthy_python_repo(tmp_path / "ok")
    for check in TREE:
        assert run(check, rb.path) == [], check


def test_conflict_markers(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    body = f"a\n{START} HEAD\nx\n{MID}\ny\n{END} feature\nb\n"
    rb.write("src/app.py", body).write("notes.md", f"Title\n{MID}\ntext\n")
    rb.write("half.txt", f"{START} HEAD\nonly one side\n").commit()
    (f,) = run("conflict-markers", rb.path)
    assert f.location.path == "src/app.py" and f.location.line == 2
    assert f.key == "conflict:src/app.py"


def test_committed_artifacts_are_grouped(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("web/node_modules/a/index.js", "x").write("web/node_modules/b/index.js", "x")
    rb.write("pkg/__pycache__/m.cpython-312.pyc", "x").write("old.pyc", "x")
    rb.write("assets/.DS_Store", "x").write("target/debug/app", "x").write("src/main.py", "x")
    rb.commit()
    found = {f.location.path: f.data["files"] for f in run("committed-artifacts", rb.path)}
    assert found == {
        "web/node_modules": 2,
        "pkg/__pycache__": 1,
        "old.pyc": 1,
        "assets/.DS_Store": 1,
    }  # `target/` bez Cargo.toml není artefakt
    rb.write("Cargo.toml", "[package]\n").commit()
    paths = {f.location.path for f in run("committed-artifacts", rb.path)}
    assert "target" in paths


@pytest.mark.skipif(os.name == "nt", reason="symlinky")
def test_broken_symlinks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("real.txt", "x").write("sub/keep.txt", "x")
    (rb.path / "good").symlink_to("real.txt")
    (rb.path / "sub" / "up").symlink_to("../real.txt")
    (rb.path / "bad").symlink_to("missing/file")
    (rb.path / "dirlink").symlink_to("sub")
    (rb.path / "generated").symlink_to("build.out")
    rb.write(".gitignore", "build.out\n").write("build.out", "x")
    rb.commit()
    found = {f.location.path: f for f in run("broken-symlinks", rb.path)}
    # symlink na ignorovaný soubor je pro každého, kdo repo naklonuje, rozbitý
    assert set(found) == {"bad", "generated"}
    assert "missing/file" in found["bad"].message
    assert found["bad"].severity is Severity.LOW


def test_case_collisions(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x").write("readme.md", "y")
    rb.write("Docs/a.md", "x").write("docs/b.md", "y").write("other/a.md", "x")
    rb.commit()
    msgs = sorted(f.key for f in run("case-collisions", rb.path))
    assert msgs == ["case:docs", "case:readme.md"]


def test_line_endings_mixed_and_policy(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.git("config", "core.autocrlf", "false")
    rb.write("mixed.txt", b"a\r\nb\n").write("unix.txt", b"a\nb\n").write("win.txt", b"a\r\nb\r\n")
    rb.write("run.bat", b"echo\r\n").commit()
    keys = sorted(f.key for f in run("line-endings", rb.path))
    assert keys == ["mixed:mixed.txt", "policy"]
    rb.write(".gitattributes", "* text=auto\n").commit()
    # win.txt zůstává v indexu CRLF, ale pravidlo už existuje → žádná „policy“ výjimka
    assert "policy" not in [f.key for f in run("line-endings", rb.path)]


def test_line_endings_uniform_crlf_is_fine(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.git("config", "core.autocrlf", "false")
    rb.write("a.txt", b"a\r\n").write("b.txt", b"b\r\n").commit()
    assert run("line-endings", rb.path) == []


def _add_submodule(rb: RepoBuilder, sub: Path, path: str, url: str) -> None:
    rb.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), path)
    rb.write(".gitmodules", f'[submodule "{path}"]\n\tpath = {path}\n\turl = {url}\n')


def test_submodule_states(tmp_path: Path) -> None:
    sub = RepoBuilder.create(tmp_path / "sub")
    sub.write("a", "x").commit()
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x").commit()
    _add_submodule(rb, sub.path, "libs/sub", "https://example.invalid/sub.git")
    rb.commit()
    assert run("submodule-state", rb.path) == []

    rb.write(
        ".gitmodules",
        '[submodule "libs/sub"]\n\tpath = libs/sub\n\turl = http://x.invalid/s\n'
        '[submodule "gone"]\n\tpath = gone\n\turl = ../gone\n',
    ).commit()
    keys = sorted(f.key for f in run("submodule-state", rb.path))
    assert keys == ["insecure:libs/sub", "stale:gone"]

    rb.git("rm", "-q", "--cached", ".gitmodules")
    rb.commit(all_files=False)
    assert [f.key for f in run("submodule-state", rb.path)] == ["unmapped:libs/sub"]


def test_submodule_not_initialised(tmp_path: Path) -> None:
    sub = RepoBuilder.create(tmp_path / "sub")
    sub.write("a", "x").commit()
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x").commit()
    _add_submodule(rb, sub.path, "lib", "../sub")
    rb.commit()
    rb.git("submodule", "deinit", "-q", "-f", "lib")
    (rb.path / "lib" / ".git").unlink(missing_ok=True)
    (f,) = run("submodule-state", rb.path)
    assert f.key == "uninit:lib" and f.severity is Severity.LOW


def test_lfs_not_applied(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("data/model.bin", b"x" * 4096).write("small.bin", b"x" * 10)
    rb.write("tool.bin", b"y" * 4096).commit()
    assert run("lfs-not-applied", rb.path) == []  # bez LFS pravidel nic
    rb.write(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n").commit()
    paths = sorted(f.location.path or "" for f in run("lfs-not-applied", rb.path))
    assert paths == ["data/model.bin", "tool.bin"]  # small.bin se vejde do pointeru


@pytest.mark.skipif(os.name == "nt", reason="symlinky")
def test_symlinks_pointing_outside_are_not_touched(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x")
    (rb.path / "abs").symlink_to("/etc/passwd")
    (rb.path / "up").symlink_to("../../outside")
    (rb.path / "unc").symlink_to("\\\\host\\share\\f")
    (rb.path / "win").symlink_to("sub\\..\\..\\x")
    (rb.path / "dir").mkdir()
    (rb.path / "dir" / "ok").symlink_to("../README.md")
    (rb.path / "root").symlink_to(".")
    rb.commit()
    found = {f.key for f in run("broken-symlinks", rb.path)}
    assert found == {
        "symlink-outside:abs",
        "symlink-outside:up",
        "symlink-outside:unc",
        "symlink-outside:win",
    }
