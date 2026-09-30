from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx

from repo_doctor import deps as D
from repo_doctor.checks import SkipCheck
from repo_doctor.httpclient import HttpClient
from repo_doctor.models import Severity
from tests.factory import RepoBuilder
from tests.helpers import run

UV_LOCK = """\
version = 1
[[package]]
name = "myproj"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Requests"
version = "2.19.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "urllib3"
version = "1.26.0"
"""

PKG_LOCK_V3 = json.dumps(
    {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app"},
            "node_modules/lodash": {"version": "4.17.20"},
            "node_modules/a/node_modules/@scope/b": {"version": "1.0.0"},
            "node_modules/linked": {"link": True},
        },
    }
)
PKG_LOCK_V1 = json.dumps(
    {"dependencies": {"x": {"version": "1.0.0", "dependencies": {"y": {"version": "2.0.0"}}}}}
)
PNPM = """\
lockfileVersion: '9.0'
importers:
  .:
    dependencies: {}
packages:
  '@babel/core@7.24.0':
    resolution: {}
  lodash@4.17.21:
    resolution: {}
  /old-style@1.2.3:
    resolution: {}
snapshots:
  lodash@4.17.21: {}
"""
YARN_V1 = """\
# yarn lockfile v1

"@types/node@^20", "@types/node@^20.1":
  version "20.1.0"
  resolved "https://x"

lodash@^4.17.0:
  version "4.17.15"
"""
YARN_BERRY = """\
__metadata:
  version: 6

"react@npm:^18.0.0":
  version: 18.2.0
"""
GO_SUM = """\
github.com/gin-gonic/gin v1.7.0 h1:abc=
github.com/gin-gonic/gin v1.7.0/go.mod h1:def=
golang.org/x/text v0.3.0+incompatible h1:x=
"""
CARGO_LOCK = """\
[[package]]
name = "app"
version = "0.1.0"

[[package]]
name = "serde"
version = "1.0.100"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""


def test_parsers() -> None:
    uv = D.parse_toml_packages(UV_LOCK, "uv.lock", "PyPI")
    assert {(d.name, d.version) for d in uv} == {("requests", "2.19.0"), ("urllib3", "1.26.0")}
    assert {(d.name, d.version) for d in D.parse_package_lock(PKG_LOCK_V3, "p")} == {
        ("lodash", "4.17.20"),
        ("@scope/b", "1.0.0"),
    }
    assert {(d.name, d.version) for d in D.parse_package_lock(PKG_LOCK_V1, "p")} == {
        ("x", "1.0.0"),
        ("y", "2.0.0"),
    }
    assert D.parse_package_lock("{bad", "p") == []
    assert {(d.name, d.version) for d in D.parse_pnpm_lock(PNPM, "p")} == {
        ("@babel/core", "7.24.0"),
        ("lodash", "4.17.21"),
        ("old-style", "1.2.3"),
    }
    assert {(d.name, d.version) for d in D.parse_yarn_lock(YARN_V1, "y")} == {
        ("@types/node", "20.1.0"),
        ("lodash", "4.17.15"),
    }
    assert {(d.name, d.version) for d in D.parse_yarn_lock(YARN_BERRY, "y")} == {
        ("react", "18.2.0")
    }
    assert {(d.name, d.version) for d in D.parse_go_sum(GO_SUM, "go.sum")} == {
        ("github.com/gin-gonic/gin", "1.7.0"),
        ("golang.org/x/text", "0.3.0"),
    }
    assert [
        (d.name, d.ecosystem) for d in D.parse_toml_packages(CARGO_LOCK, "Cargo.lock", "crates.io")
    ] == [("serde", "crates.io")]
    assert D.parse_toml_packages("not = [toml", "x", "PyPI") == []
    reqs = D.parse_requirements(
        "# c\nDjango[bcrypt]==3.2.0 ; python_version>'3'\nflask>=2\n-r other.txt\nx==1.*\n", "r.txt"
    )
    assert [(d.name, d.version) for d in reqs] == [("django", "3.2.0")]
    names, pinned, has = D.pyproject_direct(
        '[project]\ndependencies=["httpx==0.27.0", "rich>=13", "bad spec!!"]\n'
        '[project.optional-dependencies]\ndev=["pytest"]\n[dependency-groups]\nlint=["ruff"]\n'
        '[tool.poetry.dependencies]\npython="^3.12"\nclick="^8"\n'
    )
    assert names == {"httpx", "rich", "pytest", "ruff", "click"} and has
    assert [(d.name, d.version) for d in pinned] == [("httpx", "0.27.0")]
    assert D.pyproject_direct("[[") == (set(), [], False)
    assert D.package_json_direct('{"dependencies": {"a": "1"}}') == ({"a"}, True)
    assert D.package_json_direct("nope") == (set(), False)


def test_collect_and_missing_locks(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname="x"\ndependencies=["requests"]\n',
        "uv.lock": UV_LOCK,
        "web/package.json": '{"dependencies": {"lodash": "^4"}}',
        "tool/package.json": '{"dependencies": {"left-pad": "1"}}',
        "web/package-lock.json": PKG_LOCK_V3,
        "svc/go.mod": "module x\nrequire github.com/a/b v1.0.0\n",
        "rs/Cargo.toml": "[package]\n[dependencies]\nserde='1'\n",
        "rs/src/main.rs": "fn main(){}",
        "tests/fixtures/package-lock.json": PKG_LOCK_V1,
        "lib/pyproject.toml": '[project]\nname="lib"\ndependencies=["click==8.0.0"]\n',
    }
    data = D.collect(list(files), files.get)
    assert sorted(data.missing_locks) == [
        ("lib/pyproject.toml", "uv.lock"),
        ("rs/Cargo.toml", "Cargo.lock"),
        ("svc/go.mod", "go.sum"),
        ("tool/package.json", "package-lock.json"),
    ]
    by_name = {d.name: d for d in data.dependencies}
    assert by_name["requests"].direct and not by_name["urllib3"].direct
    assert by_name["lodash"].direct
    assert "x" not in by_name  # z fixtury
    assert by_name["click"].version == "8.0.0"


def test_compare_versions() -> None:
    assert D.compare_versions("1.2.3", "2.0.0") == "major"
    assert D.compare_versions("1.2.3", "1.3.0") == "minor"
    assert D.compare_versions("1.2.3", "1.2.4") == "patch"
    assert D.compare_versions("1.2.3", "1.2.3") is None
    assert D.compare_versions("1.2.3", "2.0.0rc1") is None
    assert D.compare_versions("weird", "1") is None


def _deps() -> list[D.Dependency]:
    return [
        D.Dependency("PyPI", "requests", "2.19.0", "uv.lock", direct=True),
        D.Dependency("npm", "@scope/pkg", "1.0.0", "package-lock.json", direct=True),
        D.Dependency("PyPI", "safe", "1.0.0", "uv.lock", direct=False),
    ]


@respx.mock
async def test_enrich() -> None:
    respx.post(D.OSV_BATCH_URL).respond(
        json={"results": [{"vulns": [{"id": "GHSA-1"}, {"id": "PYSEC-2"}]}, {}, {"vulns": []}]}
    )
    respx.get("https://api.osv.dev/v1/vulns/GHSA-1").respond(
        json={"database_specific": {"severity": "CRITICAL"}, "summary": "bad"}
    )
    respx.get("https://api.osv.dev/v1/vulns/PYSEC-2").respond(404)
    respx.get("https://pypi.org/pypi/requests/json").respond(json={"info": {"version": "2.32.3"}})
    respx.get("https://registry.npmjs.org/@scope%2Fpkg/latest").respond(json={"version": "3.0.0"})
    data = D.DepsData(dependencies=_deps())
    async with HttpClient() as c:
        await D.enrich(c, data, ttl=0)
    (dep,) = data.vulns
    assert dep.name == "requests"
    sev = {v.id: v.severity for v in data.vulns[dep]}
    assert sev == {"GHSA-1": Severity.HIGH, "PYSEC-2": Severity.MEDIUM}
    assert {(o.dep.name, o.level) for o in data.outdated} == {
        ("requests", "minor"),
        ("@scope/pkg", "major"),
    }
    assert data.network_done


@respx.mock
async def test_enrich_errors_recorded() -> None:
    respx.post(D.OSV_BATCH_URL).respond(503)
    respx.get("https://pypi.org/pypi/requests/json").respond(404)
    respx.get("https://registry.npmjs.org/@scope%2Fpkg/latest").respond(json={})
    data = D.DepsData(dependencies=_deps())
    async with HttpClient() as c:
        await D.enrich(c, data, ttl=0)
    assert any(e.startswith("OSV") for e in data.errors)
    assert any("requests" in e for e in data.errors)
    assert data.vulns == {} and data.outdated == []


def test_dep_checks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("package.json", '{"dependencies": {"a": "1"}}').commit()
    (f,) = run("deps-lockfile-missing", rb.path)
    assert "package-lock.json" in f.message
    with pytest.raises(SkipCheck, match="offline"):
        run("deps-vulnerable", rb.path, offline=True)
    with pytest.raises(SkipCheck):
        run("deps-outdated", rb.path)
    dep = D.Dependency("npm", "a", "1.0.0", "package-lock.json", True)
    data = D.DepsData(
        dependencies=[dep],
        vulns={
            dep: [D.Vuln(f"GHSA-{i}", Severity.LOW) for i in range(7)]
            + [D.Vuln("X", Severity.HIGH)]
        },
        outdated=[D.Outdated(dep, "2.0.0", "major")]
        + [
            D.Outdated(D.Dependency("npm", f"p{i}", "1.0.0", "x"), "1.0.1", "patch")
            for i in range(9)
        ],
        network_done=True,
    )
    (v,) = run("deps-vulnerable", rb.path, deps=data)
    assert v.severity is Severity.HIGH and "(+2)" in v.message
    out = {f.key: f for f in run("deps-outdated", rb.path, deps=data)}
    assert out["major"].severity is Severity.MEDIUM
    assert "a 1 další" in out["patch"].message
    assert run("deps-lockfile-missing", rb.path, deps=D.DepsData()) == []
