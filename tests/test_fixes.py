from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from repo_doctor import fixes
from repo_doctor.checks import all_checks
from repo_doctor.config import Config
from repo_doctor.fixes import FixRefused, apply, plan, render_diff
from repo_doctor.gitwrap import Git
from repo_doctor.models import FileChange, Finding, Patch
from tests.factory import RepoBuilder, git
from tests.helpers import ctx

TODAY = date(2026, 9, 30)


def _findings(path: Path, config: Config | None = None) -> list[Finding]:
    c = ctx(path, config)
    out: list[Finding] = []
    for check in all_checks():
        if check.network or check.needs_forge or check.id == "public-sensitive":
            continue
        out.extend(check.run(c))
    return out


def messy_repo(tmp: Path) -> RepoBuilder:
    rb = RepoBuilder.create(tmp / "messy")
    rb.write("main.py", "print(1)\n").write("util.py", "x=1\n").write(
        "pyproject.toml", "[project]\nname='m'\n"
    )
    rb.write(".env", "SECRET=1\n").write("Dockerfile", "FROM python:3.12\nUSER app\n")
    rb.write(".gitignore", "node_modules/\n")
    rb.commit("init")
    return rb


def test_plan_does_not_change_repo(tmp_path: Path) -> None:
    rb = messy_repo(tmp_path)
    before = rb.snapshot()
    findings = _findings(rb.path)
    patches = plan(ctx(rb.path), findings)
    ids = sorted(p.check_id for p in patches)
    assert ids == [
        "ci-missing",
        "docker-hygiene",
        "env-committed",
        "gitignore-incomplete",
        "license-missing",
        "precommit-missing",
        "readme-missing",
    ]
    for p in patches:
        assert p.diff()
    assert rb.snapshot() == before


def test_apply_creates_branch_and_commits(tmp_path: Path) -> None:
    rb = messy_repo(tmp_path)
    before = rb.snapshot()
    patches = plan(ctx(rb.path), _findings(rb.path))
    result = apply(Git(rb.path), patches, today=TODAY)
    assert result.branch == "repo-doctor/fixes-2026-09-30"
    assert len(result.commits) == len(patches)
    after = rb.snapshot()
    # pracovní strom, HEAD, index i aktuální branch beze změny; přibyla jen nová branch
    for key in ("head", "symbolic", "status", "index", "files", "stash"):
        assert after[key] == before[key], key
    assert "refs/heads/repo-doctor/fixes-2026-09-30" in after["refs"]
    log = git(rb.path, "log", "--format=%s", "repo-doctor/fixes-2026-09-30")
    assert "chore(repo-doctor): gitignore-incomplete" in log
    assert "chore(repo-doctor): env-committed" in log
    branch = "repo-doctor/fixes-2026-09-30"
    gi = git(rb.path, "show", f"{branch}:.gitignore")
    assert gi.startswith("node_modules/\n")
    assert "# repo-doctor: doplněno 2026-09-30\n.env\n" in gi
    assert "/.env" in gi
    assert gi.count("\n.env\n") == 1  # bez duplicit
    files = git(rb.path, "ls-tree", "-r", "--name-only", branch).split()
    assert ".env" not in files
    assert {
        "LICENSE",
        "README.md",
        ".pre-commit-config.yaml",
        ".github/workflows/ci.yml",
        ".dockerignore",
    } <= set(files)
    assert (rb.path / ".env").exists()  # soubor na disku zůstal
    lic = git(rb.path, "show", f"{branch}:LICENSE")
    assert "Test Tester" in lic and "2026" in lic
    assert "ruff" in git(rb.path, "show", f"{branch}:.pre-commit-config.yaml")
    assert any("rotuj" in n for n in result.notes)
    # druhé spuštění ve stejný den → nová branch s příponou, stará zůstane
    result2 = apply(Git(rb.path), patches[:1], today=TODAY)
    assert result2.branch == "repo-doctor/fixes-2026-09-30-2"


def test_dirty_repo_refused(tmp_path: Path) -> None:
    rb = messy_repo(tmp_path)
    rb.write("main.py", "changed\n")
    before = rb.snapshot()
    patches = plan(ctx(rb.path), _findings(rb.path))
    with pytest.raises(FixRefused, match="necommitnuté"):
        apply(Git(rb.path), patches, today=TODAY)
    assert rb.snapshot() == before


def test_refusals(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "empty")
    with pytest.raises(FixRefused, match="žádná"):
        apply(Git(rb.path), [], today=TODAY)
    p = Patch(
        check_id="readme-missing",
        title="t",
        summary="s",
        changes=[FileChange(path="README.md", action="create", content="x")],
    )
    with pytest.raises(FixRefused, match="commit"):
        apply(Git(rb.path), [p], today=TODAY)
    rb.write("README.md", "x").commit()
    with pytest.raises(FixRefused, match="nic nemění"):
        apply(Git(rb.path), [p], today=TODAY)


def test_healthy_repo_has_nothing_to_fix(tmp_path: Path) -> None:
    from tests.factory import healthy_python_repo

    rb = healthy_python_repo(tmp_path / "ok")
    assert plan(ctx(rb.path), _findings(rb.path)) == []


def test_filechange_semantics() -> None:
    create = FileChange(path="a", action="create", content="new\n")
    assert create.result(None) == "new\n"
    assert create.result("existing") == "existing"
    app = FileChange(path=".gitignore", action="append", content=".env\n.venv/\n", header="# h")
    assert app.result(None) == "# h\n.env\n.venv/\n"
    assert app.result("x") == "x\n\n# h\n.env\n.venv/\n"
    assert app.result(".env\n.venv/\n") == ".env\n.venv/\n"
    assert FileChange(path="x", action="append", content="").result(None) == ""
    assert FileChange(path="a", action="untrack").result("x") is None


def test_render_diff() -> None:
    p = Patch(
        check_id="x",
        title="t",
        summary="s",
        changes=[
            FileChange(
                path=".gitignore", action="append", content=".env", header="# h", old="dist/"
            ),
            FileChange(path=".env", action="untrack"),
            FileChange(path="NEW", action="create", content="hello"),
        ],
    )
    d = render_diff(p)
    assert "+.env\n" in d and "+++ /dev/null" in d and "--- /dev/null" in d
    assert p.commit_message.startswith("chore(repo-doctor): x")


def test_templates_override(tmp_path: Path) -> None:
    tdir = tmp_path / "tpl"
    tdir.mkdir()
    (tdir / "README.md").write_text("# $name vlastní\n")
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    c = ctx(rb.path, Config(templates_dir=str(tdir), license="ISC"))
    findings = [
        f
        for f in _findings(rb.path)
        if f.check_id in {"readme-missing", "license-missing", "ci-missing"}
    ]
    patches = {p.check_id: p for p in plan(c, findings)}
    assert patches["readme-missing"].changes[0].content == "# r vlastní\n"
    assert "ISC License" in patches["license-missing"].changes[0].content
    assert "Doplň lint" in patches["ci-missing"].changes[0].content


def test_plan_ignores_unknown_and_nonfixable(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()
    bogus = Finding(
        check_id="nope", severity="low", category="git", title="t", message="m", fixable=True
    )
    other = Finding(
        check_id="uncommitted",
        severity="low",
        category="git",
        title="t",
        message="m",
        fixable=False,
    )
    assert plan(ctx(rb.path), [bogus, other]) == []
    assert fixes.branch_name(Git(rb.path), TODAY) == "repo-doctor/fixes-2026-09-30"
