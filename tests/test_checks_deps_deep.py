from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from repo_doctor import deps as D
from repo_doctor.checks import SkipCheck
from repo_doctor.httpclient import HttpClient
from repo_doctor.models import Finding, Severity
from tests.factory import RepoBuilder, healthy_python_repo
from tests.helpers import run

DEEP = ["deps-lock-drift", "deps-unpinned", "deps-install-scripts"]


def test_healthy_repo_has_no_deep_dependency_findings(tmp_path: Path) -> None:
    rb = healthy_python_repo(tmp_path / "ok")
    for check in DEEP:
        assert run(check, rb.path) == [], check


def _packages(finding: Finding) -> list[str]:
    value = finding.data["packages"]
    assert isinstance(value, list)
    return value


def _npm_lock(*names: str, **extra: dict[str, object]) -> str:
    packages: dict[str, object] = {"": {"name": "app"}}
    for name in names:
        packages[f"node_modules/{name}"] = {"version": "1.0.0", **extra.get(name, {})}
    return json.dumps({"lockfileVersion": 3, "packages": packages})


def test_lock_drift_npm(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write(
        "package.json",
        json.dumps({"dependencies": {"a": "1", "b": "1"}, "devDependencies": {"c": "1"}}),
    )
    rb.write("package-lock.json", _npm_lock("a")).commit()
    (f,) = run("deps-lock-drift", rb.path)
    assert f.location.path == "package.json" and f.data["missing"] == ["b", "c"]
    assert f.data["lockfile"] == "package-lock.json" and f.severity is Severity.MEDIUM
    rb.write("package-lock.json", _npm_lock("a", "b", "c")).commit()
    assert run("deps-lock-drift", rb.path) == []


def test_lock_drift_skips_workspaces_and_broken_files(tmp_path: Path) -> None:
    ws = RepoBuilder.create(tmp_path / "ws")
    ws.write("package.json", json.dumps({"workspaces": ["p/*"], "dependencies": {"a": "1"}}))
    ws.write("package-lock.json", _npm_lock()).commit()
    assert run("deps-lock-drift", ws.path) == []
    bad = RepoBuilder.create(tmp_path / "bad")
    bad.write("package.json", "{not json")
    bad.write("pyproject.toml", "[project\nbroken").write("uv.lock", "[[package]\nx")
    bad.write("Cargo.toml", "[dependencies]\nserde = '1'\n").write("Cargo.lock", "garbage = [")
    bad.write("sub/package.json", json.dumps({"dependencies": {"a": 1, "b": ["x"], 5: 6}}))
    bad.write("sub/package-lock.json", '{"packages": 5}').commit()
    assert run("deps-lock-drift", bad.path) == []


def test_lock_drift_python_and_rust(tmp_path: Path) -> None:
    py = RepoBuilder.create(tmp_path / "py")
    py.write(
        "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["requests>=2", "Flask_Cors"]\n',
    )
    py.write("uv.lock", '[[package]]\nname = "x"\n\n[[package]]\nname = "requests"\n').commit()
    (f,) = run("deps-lock-drift", py.path)
    assert f.data["missing"] == ["flask-cors"] and f.data["lockfile"] == "uv.lock"
    uv_ws = RepoBuilder.create(tmp_path / "uvws")
    uv_ws.write(
        "pyproject.toml", '[project]\ndependencies = ["a"]\n[tool.uv.workspace]\nmembers=[]\n'
    )
    uv_ws.write("uv.lock", "version = 1\n").commit()
    assert run("deps-lock-drift", uv_ws.path) == []
    rs = RepoBuilder.create(tmp_path / "rs")
    rs.write("Cargo.toml", '[package]\nname = "x"\n[dependencies]\nserde = "1"\nanyhow = "1"\n')
    rs.write("Cargo.lock", '[[package]]\nname = "serde"\nversion = "1.0.0"\n').commit()
    (f,) = run("deps-lock-drift", rs.path)
    assert f.data["missing"] == ["anyhow"]
    rs.write("Cargo.toml", '[workspace]\nmembers = ["a"]\n[dependencies]\nanyhow = "1"\n').commit()
    assert run("deps-lock-drift", rs.path) == []


def test_unpinned_dependencies(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write(
        "package.json",
        json.dumps(
            {
                "dependencies": {
                    "star": "*",
                    "tag": "latest",
                    "gh": "user/repo",
                    "gitpin": "github:user/repo#v1.2.0",
                    "gitfloat": "git+https://github.com/u/r.git",
                    "ok": "^1.2.0",
                    "num": 5,
                }
            }
        ),
    )
    rb.write(
        "requirements.txt",
        "requests\nflask[async]>=2 ; python_version>'3'\nrequests==2.0\n-r other.txt\n"
        "git+https://github.com/u/r.git#egg=pkg\n"
        "git+https://github.com/u/r.git@v1#egg=pinned\n"
        "git+ssh://git@github.com/u/ssh.git@abc123\n"
        "numpy>=1.0\n",
    )
    rb.write(
        "pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["a @ git+https://h/a.git", '
        '"b @ git+https://h/b.git@v1", "c>=1"]\n',
    )
    rb.write(
        "Cargo.toml",
        '[dependencies]\na = "*"\nb = { version = "*" }\nc = { git = "https://h/c" }\n'
        'd = { git = "https://h/d", rev = "abc" }\ne = "1"\n',
    )
    rb.commit()
    found = {f.location.path: set(_packages(f)) for f in run("deps-unpinned", rb.path)}
    assert found == {
        "package.json": {"star", "tag", "gh", "gitfloat"},
        "requirements.txt": {"requests", "pkg"},
        "pyproject.toml": {"a"},
        "Cargo.toml": {"a", "b", "c"},
    }


def test_unpinned_survives_hostile_manifests(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("package.json", '{"dependencies": [1, 2], "devDependencies": "x"}')
    rb.write("pyproject.toml", "[project]\ndependencies = [1, {a = 2}, 'bad req !!']\n")
    rb.write("Cargo.toml", "[dependencies]\n1 = 2\nx = [1]\n")
    rb.write("requirements.txt", "A" * 100_000 + "\n" + "-" * 10 + "\n" + "[" * 5000 + "\n")
    rb.commit()
    assert [f.location.path for f in run("deps-unpinned", rb.path)] == []


def test_install_scripts(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    lock = _npm_lock(
        "esbuild",
        "sharp",
        "plain",
        esbuild={"hasInstallScript": True},
        sharp={"hasInstallScript": True},
    )
    rb.write("package-lock.json", lock).commit()
    (f,) = run("deps-install-scripts", rb.path)
    assert f.severity is Severity.LOW and "esbuild" in f.message
    assert _packages(f) == ["esbuild", "sharp"]
    rb.write(".npmrc", "# x\nignore-scripts=true\n").commit()
    assert run("deps-install-scripts", rb.path) == []


# ------------------------------------------------------------------ síťová data z registrů

UTC_NOW = datetime(2026, 9, 30, tzinfo=UTC)


def _registry_data() -> D.DepsData:
    npm_old = D.Dependency("npm", "request", "2.0.0", "package-lock.json", True)
    py_inactive = D.Dependency("PyPI", "legacy", "1.0", "uv.lock", True)
    py_old = D.Dependency("PyPI", "old", "1.0", "uv.lock", True)
    py_dev = D.Dependency("PyPI", "devold", "1.0", "uv.lock", True)
    py_fresh = D.Dependency("PyPI", "fresh", "1.0", "uv.lock", True)
    return D.DepsData(
        dependencies=[npm_old, py_inactive, py_old, py_dev, py_fresh],
        registry={
            npm_old: D.RegistryInfo(latest="2.88.2", deprecated="request has been deprecated"),
            py_inactive: D.RegistryInfo(deprecated="Inactive", last_release=UTC_NOW),
            py_old: D.RegistryInfo(last_release=datetime(2021, 5, 1, tzinfo=UTC)),
            py_dev: D.RegistryInfo(last_release=datetime(2019, 1, 1, tzinfo=UTC)),
            py_fresh: D.RegistryInfo(last_release=datetime(2026, 8, 1, tzinfo=UTC)),
        },
        dev_only={("PyPI", "devold")},
        network_done=True,
    )


def test_unmaintained_packages(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("README.md", "x").commit()
    with pytest.raises(SkipCheck, match="offline"):
        run("deps-unmaintained", rb.path, offline=True)
    with pytest.raises(SkipCheck):
        run("deps-unmaintained", rb.path)
    findings = {f.key: f for f in run("deps-unmaintained", rb.path, deps=_registry_data())}
    assert set(findings) == {
        "npm:request:deprecated",
        "PyPI:legacy:deprecated",
        "PyPI:old:abandoned",
    }
    assert findings["npm:request:deprecated"].severity is Severity.MEDIUM
    assert "has been deprecated" in findings["npm:request:deprecated"].message
    assert "Inactive" in findings["PyPI:legacy:deprecated"].message
    abandoned = findings["PyPI:old:abandoned"]
    assert abandoned.severity is Severity.LOW and "2021-05-01" in abandoned.message
    assert "před 5 lety" in abandoned.message


@respx.mock
async def test_enrich_collects_registry_info() -> None:
    respx.post(D.OSV_BATCH_URL).respond(json={"results": []})
    respx.get("https://pypi.org/pypi/legacy/json").respond(
        json={
            "info": {
                "version": "2.0",
                "classifiers": ["Development Status :: 7 - Inactive", "License :: OSI Approved"],
            },
            "urls": [
                {"upload_time_iso_8601": "2020-01-02T03:04:05.000000Z"},
                {"upload_time_iso_8601": "2020-01-02T03:04:06Z"},
                {"upload_time_iso_8601": "garbage"},
            ],
        }
    )
    respx.get("https://registry.npmjs.org/request/latest").respond(
        json={"version": "2.88.2", "deprecated": "x" * 1000}
    )
    deps = [
        D.Dependency("PyPI", "legacy", "1.0", "uv.lock", True),
        D.Dependency("npm", "request", "2.0.0", "package-lock.json", True),
    ]
    data = D.DepsData(dependencies=deps)
    async with HttpClient() as c:
        await D.enrich(c, data, ttl=0, want_vulns=False, want_outdated=False, want_registry=True)
    py, npm = (data.registry[d] for d in deps)
    assert py.deprecated == "Inactive" and py.latest == "2.0"
    assert py.last_release == datetime(2020, 1, 2, 3, 4, 6, tzinfo=UTC)
    assert npm.deprecated is not None and len(npm.deprecated) == 300
    assert data.outdated == []  # outdated se bez want_outdated nenaplňuje
