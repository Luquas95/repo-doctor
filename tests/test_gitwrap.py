from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_doctor.gitwrap import Git, GitError, GitNotFound, GitTimeout
from tests.factory import RepoBuilder, git, with_remote


def test_basic_queries(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    g = Git(rb.path)
    assert g.is_repo()
    assert g.head_sha() is None  # prázdné repo
    assert g.last_commit_ts() is None
    sha = rb.write("a.txt", "a").commit("one", ts=1_700_000_000)
    assert g.head_sha() == sha
    assert g.current_branch() == "main"
    assert not g.is_detached()
    assert g.toplevel() == rb.path.resolve()
    assert g.git_dir().name == ".git"
    assert not g.is_bare()
    assert g.last_commit_ts() == 1_700_000_000
    assert g.commit_timestamps(1_600_000_000) == [1_700_000_000]
    assert g.commit_count() == 1
    assert g.config_get("user.name") == "Test Tester"
    assert g.config_get("no.such") is None
    assert g.remotes() == {}
    assert g.default_branch() == "main"
    assert g.ls_files() == ["a.txt"]
    assert g.ref_exists("main")
    assert not g.ref_exists("nope")
    assert g.show_file("HEAD", "a.txt") == b"a"
    assert g.show_file("HEAD", "missing") is None


def test_not_a_repo(tmp_path: Path) -> None:
    g = Git(tmp_path)
    assert not g.is_repo()
    assert g.toplevel() is None


def test_status_counts(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a.txt", "a").write("b.txt", "b").commit()
    rb.write("a.txt", "changed").write("new.txt", "n").write("c.txt", "c")
    rb.git("add", "c.txt")
    rb.git("mv", "b.txt", "b2.txt")
    st = Git(rb.path).status()
    assert st.modified == 1
    assert st.untracked == 1
    assert st.staged == 2
    assert st.dirty == 4
    assert "new.txt" in st.paths


def test_status_does_not_write_index(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a.txt", "a").commit()
    index = rb.path / ".git" / "index"
    before = index.stat().st_mtime_ns
    (rb.path / "a.txt").touch()
    Git(rb.path).status()
    assert index.stat().st_mtime_ns == before


def test_branches_and_tracking(tmp_path: Path) -> None:
    rb, _bare = with_remote(tmp_path, ahead=2)
    g = Git(rb.path)
    branches = {b.name: b for b in g.branches()}
    assert branches["main"].upstream == "origin/main"
    assert branches["main"].ahead == 2
    assert g.remotes()["origin"].endswith("proj-remote.git")
    assert g.remote_head() == "main"
    assert g.default_branch() == "main"
    assert g.count_not_on_remotes("main") == 2
    assert g.ahead_behind("main", "origin/main") == (2, 0)
    assert g.ahead_behind("nope", "x") == (0, 0)
    rb.branch("feature")
    assert "feature" in g.merged_branches("main")


def test_detached_and_stash(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    first = rb.write("a.txt", "a").commit()
    rb.write("a.txt", "b").commit()
    rb.write("a.txt", "dirty")
    rb.git("stash", "push", "-m", "wip", env={"GIT_COMMITTER_DATE": "1600000000 +0000"})
    g = Git(rb.path)
    stashes = g.stashes()
    assert len(stashes) == 1
    assert stashes[0].timestamp == 1_600_000_000
    assert "wip" in stashes[0].message
    rb.checkout(first)
    assert g.is_detached()
    assert g.current_branch() is None


def test_ls_tree_sizes_ignore_attr(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("big.bin", b"\0" * 2048).write(".gitignore", "*.log\nnode_modules/\n")
    rb.write(".gitattributes", "*.bin filter=lfs\n").commit()
    g = Git(rb.path)
    sizes = {e.path: e.size for e in g.ls_tree_sizes()}
    assert sizes["big.bin"] == 2048
    assert g.ls_tree_sizes("nope") == []
    assert g.check_ignore(["x.log", "a.txt", "node_modules/x"]) == {"x.log", "node_modules/x"}
    assert g.check_ignore([]) == set()
    assert g.check_attr("filter", ["big.bin", "a.txt"]) == {
        "big.bin": "lfs",
        "a.txt": "unspecified",
    }
    assert g.check_attr("filter", []) == {}


def test_untracked_listing(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a.txt", "a").write(".gitignore", "*.log\n").commit()
    rb.write("n.txt", "n").write("x.log", "l")
    g = Git(rb.path)
    assert g.ls_files() == [".gitignore", "a.txt"]
    assert g.ls_files(untracked=True) == [".gitignore", "a.txt", "n.txt"]


def test_error_is_redacted(tmp_path: Path) -> None:
    g = Git(tmp_path)
    with pytest.raises(GitError) as exc:
        g.run("fetch", "https://user:hunter2secret@example.invalid/x.git", timeout=5)
    assert "hunter2secret" not in str(exc.value)


def test_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(GitTimeout):
        Git(tmp_path).run("status")
    assert not Git(tmp_path).ok("status")


def test_git_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(GitNotFound):
        Git(tmp_path).run("status")
    with pytest.raises(GitNotFound):
        list(Git(tmp_path).stream_lines("log"))


def test_stream_lines(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    for i in range(3):
        rb.write("a.txt", str(i)).commit(f"c{i}")
    lines = list(Git(rb.path).stream_lines("log", "--format=%s"))
    assert lines == ["c2", "c1", "c0"]
    with pytest.raises(GitError):
        list(Git(rb.path).stream_lines("log", "nope-ref"))


def test_stream_lines_timeout(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a.txt", "x").commit()
    g = Git(rb.path)
    # alias spouští `sleep`, takže proces běží déle než limit
    with pytest.raises(GitTimeout):
        for _ in g.stream_lines("-c", "alias.slp=!sleep 5", "slp", timeout=0.3):
            pass


def test_branch_name_validation(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    sha = rb.write("a", "a").commit()
    g = Git(rb.path)
    assert g.check_branch_name("repo-doctor/fixes-2026-01-01")
    assert not g.check_branch_name("-evil")
    assert not g.check_branch_name("bad..name")
    with pytest.raises(GitError):
        g.create_branch("--force", sha)
    g.create_branch("x/y", sha)
    with pytest.raises(GitError):  # existující branch nikdy nepřepíše
        g.create_branch("x/y", sha)


def test_temp_index_does_not_touch_worktree(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    base = rb.write("a.txt", "a").commit()
    before = rb.snapshot()
    g = Git(rb.path)
    with g.temp_index() as idx:
        idx.read_tree(base)
        blob = g.hash_object(b"hello\n")
        idx.add_blob("new.txt", blob)
        idx.remove("a.txt")
        tree = idx.write_tree()
        commit = idx.commit_tree(tree, base, "msg")
    after = rb.snapshot()
    assert before == after
    assert git(rb.path, "show", f"{commit}:new.txt") == "hello\n"


def test_clone_never_overwrites(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "src")
    rb.write("a", "a").commit()
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(FileExistsError):
        Git.clone(str(rb.path), dest)
    with pytest.raises(GitError):
        Git.clone("--upload-pack=evil", tmp_path / "x")
    Git.clone(str(rb.path), tmp_path / "ok" / "clone")
    assert (tmp_path / "ok" / "clone" / "a").exists()
    with pytest.raises(GitError):
        Git.clone(str(tmp_path / "missing"), tmp_path / "y")


def test_fetch(tmp_path: Path) -> None:
    rb, _ = with_remote(tmp_path)
    Git(rb.path).fetch()


def test_repo_config_cannot_run_programs(tmp_path: Path) -> None:
    """Cizí .git/config s filtrem/textconv nesmí při čtení nic spustit."""
    rb = RepoBuilder.create(tmp_path / "r")
    marker = tmp_path / "PWNED"
    rb.write("a.txt", "hi\n").write(".gitattributes", "* filter=x diff=x\n").commit()
    rb.git("config", "filter.x.clean", f"sh -c 'touch {marker}; cat'")
    rb.git("config", "filter.x.required", "true")
    rb.git("config", "diff.x.textconv", f"sh -c 'touch {marker}; cat'")
    import os
    import time

    time.sleep(1.1)
    os.utime(rb.path / "a.txt")
    g = Git(rb.path)
    g.status()
    list(g.stream_lines("log", "-p", "--format=%H"))
    g.run("diff", "HEAD~0")
    assert not marker.exists()
    env = g.hardening_env()
    assert "filter.x.clean" in env.values() and env["GIT_CONFIG_COUNT"].isdigit()
