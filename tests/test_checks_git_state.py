from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from repo_doctor.checks import RepoContext, all_checks, get_check, select_checks
from repo_doctor.config import Config, LimitsConfig
from repo_doctor.gitwrap import Git
from repo_doctor.models import Finding
from tests.factory import RepoBuilder, git, with_remote

NOW = datetime(2026, 9, 30, tzinfo=UTC)


def ctx(path: Path, config: Config | None = None) -> RepoContext:
    return RepoContext(
        path=path,
        name=path.name,
        root=str(path.parent),
        config=config or Config(),
        git=Git(path),
        now=NOW,
    )


def run(check_id: str, path: Path, config: Config | None = None) -> list[Finding]:
    check = get_check(check_id)
    assert check is not None
    return check.run(ctx(path, config))


def test_registry() -> None:
    ids = [c.id for c in all_checks()]
    assert len(ids) == len(set(ids))
    assert "uncommitted" in ids
    assert [c.id for c in select_checks(only=["stashes"])] == ["stashes"]
    assert "stashes" not in [c.id for c in select_checks(skip=["stashes"])]
    assert "stashes" not in [c.id for c in select_checks(disabled=["stashes"])]


def test_uncommitted(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    assert run("uncommitted", rb.path) == []
    rb.write("a", "b").write("n", "n")
    (f,) = run("uncommitted", rb.path)
    assert f.data["count"] == 2
    assert "1 změněných" in f.message and "1 nesledovaných" in f.message


def test_no_remote(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    assert run("no-remote", rb.path) == []  # prázdné
    rb.write("a", "a").commit()
    assert len(run("no-remote", rb.path)) == 1
    rb2, _ = with_remote(tmp_path)
    assert run("no-remote", rb2.path) == []


def test_unpushed(tmp_path: Path) -> None:
    rb, _ = with_remote(tmp_path, ahead=2)
    rb.git("checkout", "-q", "-b", "local-only")
    rb.write("x", "x").commit()
    findings = {f.key: f for f in run("unpushed", rb.path)}
    assert findings["main"].data["count"] == 2
    assert findings["local-only"].data["count"] == 3
    assert "na žádném remote" in findings["local-only"].message
    clean, _ = with_remote(tmp_path, name="clean")
    assert run("unpushed", clean.path) == []
    solo = RepoBuilder.create(tmp_path / "solo")
    solo.write("a", "a").commit()
    assert run("unpushed", solo.path) == []


def test_stale_branches(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit(ts=int(NOW.timestamp()) - 86400)
    rb.branch("merged")
    rb.git("checkout", "-q", "-b", "old")
    rb.write("b", "b").commit(ts=int(NOW.timestamp()) - 200 * 86400)
    rb.checkout("main")
    rb.write("c", "c").commit(ts=int(NOW.timestamp()))
    findings = {f.key: f for f in run("stale-branches", rb.path)}
    assert "mergnutá" in findings["merged"].message
    assert "bez commitu" in findings["old"].message
    assert "main" not in findings
    cfg = Config(limits=LimitsConfig(stale_branch_days=1000))
    assert "old" not in {f.key for f in run("stale-branches", rb.path, cfg)}


def test_stashes(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    rb.write("a", "old")
    old = str(int(NOW.timestamp()) - 60 * 86400)
    rb.git("stash", "push", "-m", "old one", env={"GIT_COMMITTER_DATE": f"{old} +0000"})
    rb.write("a", "new")
    rb.git(
        "stash", "push", "-m", "fresh", env={"GIT_COMMITTER_DATE": f"{int(NOW.timestamp())} +0000"}
    )
    findings = run("stashes", rb.path)
    assert len(findings) == 1
    assert "old one" in findings[0].message


def test_detached(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    first = rb.write("a", "a").commit()
    rb.write("a", "b").commit()
    assert run("detached-head", rb.path) == []
    rb.checkout(first)
    assert len(run("detached-head", rb.path)) == 1


def test_default_branch_behind(tmp_path: Path) -> None:
    rb, bare = with_remote(tmp_path)
    assert run("default-branch-behind", rb.path) == []
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(bare), str(other))
    RepoBuilder(other).write("z", "z").commit()
    git(other, "push", "-q", "origin", "main")
    rb.git("fetch", "-q")
    (f,) = run("default-branch-behind", rb.path)
    assert f.data["count"] == 1
    solo = RepoBuilder.create(tmp_path / "solo")
    assert run("default-branch-behind", solo.path) == []
