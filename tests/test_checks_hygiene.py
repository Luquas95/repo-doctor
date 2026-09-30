from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from repo_doctor.config import Config, LimitsConfig
from repo_doctor.gitwrap import Git, GitTimeout
from repo_doctor.models import Severity
from tests.factory import RepoBuilder, healthy_python_repo
from tests.helpers import run

HYGIENE = [
    "readme-missing",
    "license-missing",
    "ci-missing",
    "precommit-missing",
    "gitignore-missing",
    "gitignore-incomplete",
    "large-files",
]


def test_healthy_repo_has_no_hygiene_findings(tmp_path: Path) -> None:
    rb = healthy_python_repo(tmp_path / "ok")
    for check in HYGIENE:
        assert run(check, rb.path) == [], check


def test_bare_repo_findings(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("main.py", "print(1)\n").write("util.py", "x = 1\n").commit()
    for check in [
        "readme-missing",
        "license-missing",
        "ci-missing",
        "precommit-missing",
        "gitignore-missing",
    ]:
        findings = run(check, rb.path)
        assert len(findings) == 1, check
        assert findings[0].fixable
    assert run("gitignore-incomplete", rb.path) == []


def test_alternative_names(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("readme.rst", "x").write("COPYING", "gpl").write(".gitlab-ci.yml", "x").commit()
    assert run("readme-missing", rb.path) == []
    assert run("license-missing", rb.path) == []
    assert run("ci-missing", rb.path) == []
    rb2 = RepoBuilder.create(tmp_path / "r2")
    rb2.write(".forgejo/workflows/ci.yml", "x").commit()
    assert run("ci-missing", rb2.path) == []


def test_gitignore_incomplete_by_ecosystem(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("package.json", "{}").write("pyproject.toml", "[project]\nname='x'\n")
    rb.write(".gitignore", "node_modules\n# komentář\n").commit()
    (f,) = run("gitignore-incomplete", rb.path)
    missing = f.data["missing"]
    assert isinstance(missing, list)
    assert ".env" in missing and "__pycache__/" in missing and ".venv/" in missing
    assert "node_modules/" not in missing
    assert f.severity is Severity.MEDIUM


def test_gitignore_incomplete_low_when_env_present(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("Cargo.toml", "[package]\n").write(".gitignore", ".env*\n").commit()
    (f,) = run("gitignore-incomplete", rb.path)
    assert f.data["missing"] == ["target/"]
    assert f.severity is Severity.LOW


def test_gitignore_negative_rust_go(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("Cargo.toml", "").write("go.mod", "module x\n")
    rb.write(".gitignore", ".env\n.env.*\n/target\n*.test\n").commit()
    assert run("gitignore-incomplete", rb.path) == []


def test_large_files_tree_and_history(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("small.txt", "x")
    rb.write("big.dat", b"a" * (2 * 1024 * 1024))
    rb.write("app.zip", b"PK" + b"\0" * 300_000)
    rb.write("lfs.bin", b"\0" * (3 * 1024 * 1024)).write(".gitattributes", "lfs.bin filter=lfs\n")
    rb.commit()
    rb.write("old.iso", b"\1" * (2 * 1024 * 1024)).commit("add iso")
    rb.remove("old.iso").commit("rm iso")
    cfg = Config(limits=LimitsConfig(large_file_mb=1, binary_file_kb=100))
    findings = {f.location.path: f for f in run("large-files", rb.path, cfg)}
    assert findings["big.dat"].severity is Severity.MEDIUM
    assert findings["app.zip"].severity is Severity.LOW
    assert "lfs.bin" not in findings
    assert "v historii" in findings["old.iso"].message
    assert run("large-files", rb.path) == []  # výchozí limit 5 MB, 1 MB binárky


def test_large_files_empty_repo(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    assert run("large-files", rb.path) == []


def test_large_files_history_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit()

    def slow(self: Git, *args: str, timeout: float | None = None) -> Iterator[str]:
        raise GitTimeout(args, timeout or 0)
        yield ""

    monkeypatch.setattr(Git, "stream_lines", slow)
    (f,) = run("large-files", rb.path)
    assert f.check_id == "scan-incomplete"
    assert "large-files" in f.message
