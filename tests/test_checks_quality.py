from __future__ import annotations

from pathlib import Path

from repo_doctor.models import Severity
from tests.factory import RepoBuilder, git, healthy_python_repo
from tests.helpers import run

QUALITY = [
    "tests-missing",
    "tests-not-in-ci",
    "lint-config-missing",
    "runtime-unpinned",
    "project-docs-missing",
    "dependency-bot-missing",
    "readme-links-broken",
]


def _py_project(path: Path, files: int = 6) -> RepoBuilder:
    rb = RepoBuilder.create(path)
    rb.write("pyproject.toml", '[project]\nname = "x"\nversion = "1"\n')
    for i in range(files):
        rb.write(f"src/x/mod{i}.py", "x = 1\n")
    return rb


def test_healthy_repo_has_no_quality_findings(tmp_path: Path) -> None:
    rb = healthy_python_repo(tmp_path / "ok")
    for check in QUALITY:
        assert run(check, rb.path) == [], check


def test_tests_missing_needs_enough_sources(tmp_path: Path) -> None:
    small = _py_project(tmp_path / "small", files=2)
    small.commit()
    assert run("tests-missing", small.path) == []
    rb = _py_project(tmp_path / "r")
    rb.commit()
    (f,) = run("tests-missing", rb.path)
    assert f.severity is Severity.LOW and f.data["files"] == 6
    rb.write("tests/test_mod.py", "def test_x(): pass\n").commit()
    assert run("tests-missing", rb.path) == []


def test_tests_found_in_other_ecosystems(tmp_path: Path) -> None:
    node = RepoBuilder.create(tmp_path / "n")
    node.write("package.json", "{}")
    for i in range(5):
        node.write(f"src/m{i}.ts", "export {}")
    node.commit()
    assert len(run("tests-missing", node.path)) == 1
    node.write("src/m0.test.ts", "test()").commit()
    assert run("tests-missing", node.path) == []
    rust = RepoBuilder.create(tmp_path / "rs")
    rust.write("Cargo.toml", "[package]\n")
    for i in range(5):
        rust.write(f"src/m{i}.rs", "fn f() {}\n")
    rust.commit()
    assert len(run("tests-missing", rust.path)) == 1
    rust.write("src/m1.rs", "#[cfg(test)]\nmod t {}\n").commit()
    assert run("tests-missing", rust.path) == []


def test_vendored_code_is_not_counted(tmp_path: Path) -> None:
    rb = _py_project(tmp_path / "r", files=1)
    for i in range(8):
        rb.write(f"node_modules/p/m{i}.js", "x")
    rb.write("package.json", "{}").commit()
    assert run("tests-missing", rb.path) == []


def test_tests_not_in_ci(tmp_path: Path) -> None:
    rb = _py_project(tmp_path / "r")
    rb.write("tests/test_a.py", "def test_a(): pass\n")
    rb.commit()
    assert run("tests-not-in-ci", rb.path) == []  # bez CI není co hlásit
    rb.write(".github/workflows/ci.yml", "jobs:\n  lint:\n    steps:\n      - run: ruff check\n")
    rb.commit()
    (f,) = run("tests-not-in-ci", rb.path)
    assert f.location.path == ".github/workflows/ci.yml"
    rb.write(".github/workflows/ci.yml", "steps:\n  - run: uv run pytest -q\n").commit()
    assert run("tests-not-in-ci", rb.path) == []
    rb.write(".github/workflows/ci.yml", "jobs:\n  t:\n    uses: ./.github/workflows/t.yml\n")
    rb.commit()
    assert run("tests-not-in-ci", rb.path) == []  # znovupoužitelný workflow nehádáme


def test_lint_config_missing(tmp_path: Path) -> None:
    rb = _py_project(tmp_path / "r")
    rb.commit()
    assert [f.key for f in run("lint-config-missing", rb.path)] == ["python"]
    rb.write("pyproject.toml", '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n').commit()
    assert run("lint-config-missing", rb.path) == []
    node = RepoBuilder.create(tmp_path / "n")
    node.write("package.json", "{}")
    for i in range(5):
        node.write(f"src/m{i}.js", "x")
    node.commit()
    assert [f.key for f in run("lint-config-missing", node.path)] == ["node"]
    node.write("eslint.config.js", "export default []").commit()
    assert run("lint-config-missing", node.path) == []
    hooks = _py_project(tmp_path / "h")
    hooks.write(".pre-commit-config.yaml", "repos:\n  - repo: x\n    hooks:\n      - id: ruff\n")
    hooks.commit()
    assert run("lint-config-missing", hooks.path) == []


def test_runtime_unpinned(tmp_path: Path) -> None:
    rb = _py_project(tmp_path / "r")
    rb.commit()
    assert [f.key for f in run("runtime-unpinned", rb.path)] == ["python"]
    rb.write("pyproject.toml", '[project]\nname = "x"\nrequires-python = ">=3.12"\n').commit()
    assert run("runtime-unpinned", rb.path) == []
    node = RepoBuilder.create(tmp_path / "n")
    node.write("package.json", "{}")
    for i in range(5):
        node.write(f"src/m{i}.js", "x")
    node.commit()
    assert [f.key for f in run("runtime-unpinned", node.path)] == ["node"]
    node.write("package.json", '{"engines": {"node": ">=20"}}').commit()
    assert run("runtime-unpinned", node.path) == []


def test_project_docs(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x").commit("one")
    rb.git("tag", "v1.0.0")
    keys = [f.key for f in run("project-docs-missing", rb.path)]
    assert keys == ["changelog"]  # security jen u veřejného repa, contributing až od 3 autorů
    rb.write("docs/CHANGELOG.md", "x").commit()
    assert run("project-docs-missing", rb.path) == []
    assert [f.key for f in run("project-docs-missing", rb.path, visibility="public")] == [
        "security"
    ]
    rb.write(".github/SECURITY.md", "x").commit()
    assert run("project-docs-missing", rb.path, visibility="public") == []
    for i in range(2):
        rb.write(f"f{i}", "x")
        git(rb.path, "add", "-A")
        git(
            rb.path,
            "commit",
            "-q",
            "-m",
            f"c{i}",
            env={"GIT_AUTHOR_NAME": f"Dev {i}", "GIT_AUTHOR_EMAIL": f"d{i}@example.invalid"},
        )
    (f,) = run("project-docs-missing", rb.path)
    assert f.key == "contributing" and "3" in f.message
    rb.write("CONTRIBUTING.md", "x").commit()
    assert run("project-docs-missing", rb.path) == []


def test_dependency_bot(tmp_path: Path) -> None:
    rb = _py_project(tmp_path / "r", files=1)
    rb.commit()
    assert run("dependency-bot-missing", rb.path) == []  # bez remote nemá bot smysl
    rb.remote("origin", "https://example.invalid/x/y.git")
    (f,) = run("dependency-bot-missing", rb.path)
    assert f.key == "bot"
    rb.write(".github/dependabot.yml", "version: 2\n").commit()
    assert run("dependency-bot-missing", rb.path) == []
    plain = RepoBuilder.create(tmp_path / "p")
    plain.write("notes.txt", "x").commit()
    plain.remote("origin", "https://example.invalid/x/p.git")
    assert run("dependency-bot-missing", plain.path) == []


def test_readme_links_broken(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("docs/guide.md", "x").write("img/a.png", "x")
    rb.write(
        "README.md",
        "# t\n[ok](docs/guide.md) [anchor](#top) [url](https://example.invalid/a) "
        '[dir](docs/) ![img](img/a.png "title") [frag](docs/guide.md#x)\n'
        "[gone](docs/missing.md) [root](/docs/guide.md) [up](../outside) [mail](mailto:a@b.c)\n"
        "```\n[fenced](nope.md)\n```\n",
    )
    rb.commit()
    (f,) = run("readme-links-broken", rb.path)
    assert f.location.path == "README.md" and "docs/missing.md" in f.message
    assert f.key == "link:README.md:docs/missing.md"


def test_readme_links_survive_hostile_input(tmp_path: Path) -> None:
    import time

    rb = RepoBuilder.create(tmp_path / "r")
    hostile = "[" * 100_000 + "\n```\n" * 2000 + "[a](" * 30_000 + "\n" + "[x](" + "y" * 20_000
    assert len(hostile) < 250 * 1024  # pod limitem, ať se opravdu zpracuje
    rb.write("README.md", hostile).commit()
    started = time.monotonic()
    run("readme-links-broken", rb.path)
    assert time.monotonic() - started < 5
    big = RepoBuilder.create(tmp_path / "big")
    big.write("README.md", "[gone](missing.md)\n" + "x" * (300 * 1024)).commit()
    assert run("readme-links-broken", big.path) == []  # nad 256 KB se README nečte
