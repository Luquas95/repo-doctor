"""license-compat (licence přímých závislostí) a SBOM CycloneDX 1.5."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx

from repo_doctor import cli
from repo_doctor.checks import get_check
from repo_doctor.checks.base import RepoContext, SkipCheck
from repo_doctor.config import Config, RootConfig
from repo_doctor.deps import Dependency, DepsData
from repo_doctor.forges.urls import SshConfig
from repo_doctor.licenses import classify, license_from_body, normalize, project_license
from repo_doctor.sbom import build, purl, sbom_for_repo
from repo_doctor.scanner import Scanner, ScanOptions
from tests.factory import RepoBuilder
from tests.helpers import ctx


@pytest.mark.parametrize(
    ("raw", "spdx"),
    [
        ("MIT", "MIT"),
        ("MIT License", "MIT"),
        ("Apache Software License", "Apache-2.0"),
        ("apache-2.0", "Apache-2.0"),
        ("GPL-3.0", "GPL-3.0-only"),
        ("GPLv3+", "GPL-3.0-or-later"),
        ("GNU Affero General Public License v3", "AGPL-3.0-only"),
        ("License :: OSI Approved :: BSD License", "BSD-3-Clause"),
        ("ISC License (ISCL)", "ISC"),
        ("GNU General Public License v2 (GPLv2)", "GPL-2.0-only"),
        ("Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0"),
        ("(MIT)", "MIT"),
        ("Proprietary", None),
        ("", None),
    ],
)
def test_normalize(raw: str, spdx: str | None) -> None:
    assert normalize(raw) == spdx


@pytest.mark.parametrize(
    ("expr", "kind"),
    [
        ("MIT", "permissive"),
        ("MIT OR Apache-2.0", "permissive"),
        ("GPL-3.0-only OR MIT", "permissive"),  # lze si vybrat MIT
        ("MIT AND GPL-2.0-only", "strong"),  # musí platit obě
        ("LGPL-3.0-or-later", "weak"),
        ("MIT/Apache-2.0", "permissive"),
        ("Apache-2.0 WITH LLVM-exception", "permissive"),
        ("AGPL-3.0", "strong"),
        ("(MIT OR Apache-2.0) AND GPL-3.0-only", "strong"),  # AND váže silněji než OR
        ("GPL-3.0-only AND (MIT OR Apache-2.0)", "strong"),
        ("MIT OR (Apache-2.0 AND GPL-3.0-only)", "permissive"),
        ("MIT AND", "unknown"),
        (None, "unknown"),
        ("Neznámá licence", "unknown"),
    ],
)
def test_classify(expr: str | None, kind: str) -> None:
    assert classify(expr)[0] == kind


def _dep(eco: str, name: str = "pkg", version: str = "1.0") -> Dependency:
    return Dependency(eco, name, version, "src", direct=True)  # type: ignore[arg-type]


def test_license_from_registry_bodies() -> None:
    assert license_from_body(_dep("PyPI"), {"info": {"license_expression": "MIT"}}) == "MIT"
    assert license_from_body(_dep("PyPI"), {"info": {"license": "BSD"}}) == "BSD"
    body = {"info": {"license": "", "classifiers": ["License :: OSI Approved :: MIT License"]}}
    assert license_from_body(_dep("PyPI"), body) == "MIT License"
    assert license_from_body(_dep("PyPI"), {"info": {"license": "x" * 500}}) is None
    assert license_from_body(_dep("npm"), {"license": "ISC"}) == "ISC"
    assert license_from_body(_dep("npm"), {"license": {"type": "MIT"}}) == "MIT"
    assert license_from_body(_dep("npm"), {"licenses": [{"type": "GPL-2.0"}]}) == "GPL-2.0"
    assert license_from_body(_dep("crates.io"), {"version": {"license": "MIT OR Apache-2.0"}}) == (
        "MIT OR Apache-2.0"
    )


def test_project_license_detection(tmp_path: Path) -> None:
    files = {
        "pyproject.toml": '[project]\nname = "x"\nlicense = "MIT"\n',
        "package.json": '{"license": "Apache-2.0"}',
        "LICENSE": "GNU GENERAL PUBLIC LICENSE\n  Version 3, 29 June 2007\n",
    }

    def read(name: str) -> str | None:
        return files.get(name)

    assert project_license(["pyproject.toml", "LICENSE"], read) == "MIT"
    assert project_license(["package.json"], read) == "Apache-2.0"
    assert project_license(["LICENSE"], read) == "GPL-3.0-only"
    assert project_license([], read) is None


def _check_ctx(
    tmp_path: Path, licence_file: str, licenses: dict[Dependency, str | None]
) -> RepoContext:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("LICENSE", licence_file).commit()
    data = DepsData(licenses=licenses, network_done=True)
    return ctx(rb.path, deps=data)


MIT_TEXT = "MIT License\n\nPermission is hereby granted, free of charge, to any person\n"


def test_check_reports_copyleft_and_unknown_for_permissive_project(tmp_path: Path) -> None:
    check = get_check("license-compat")
    assert check is not None
    deps = {
        _dep("PyPI", "gplka"): "GPL-3.0-or-later",
        _dep("npm", "ok"): "MIT",
        _dep("npm", "lgpl"): "LGPL-3.0-only",
        _dep("crates.io", "bez"): None,
        _dep("PyPI", "divna"): "Moje vlastní licence",
    }
    findings = check.run(_check_ctx(tmp_path, MIT_TEXT, deps))
    by = {f.key: f for f in findings}
    assert set(by) == {"PyPI:gplka", "crates.io:bez", "PyPI:divna"}
    assert by["PyPI:gplka"].severity.value == "medium"
    assert "nejde o právní radu" in by["PyPI:gplka"].message
    assert by["crates.io:bez"].severity.value == "low"


def test_check_quiet_for_copyleft_project_and_skips_offline(tmp_path: Path) -> None:
    check = get_check("license-compat")
    assert check is not None
    gpl = "GNU GENERAL PUBLIC LICENSE\nVersion 3\n"
    assert check.run(_check_ctx(tmp_path, gpl, {_dep("PyPI", "x"): "GPL-3.0-only"})) == []
    rb = RepoBuilder.create(tmp_path / "offline")
    with pytest.raises(SkipCheck):
        check.run(ctx(rb.path))


def test_project_license_file_header_only() -> None:
    gpl3 = (
        "GNU GENERAL PUBLIC LICENSE\nVersion 3\n"
        + "x\n" * 300
        + "GNU Affero General Public License"
    )
    assert project_license(["COPYING.md"], lambda f: gpl3) == "GPL-3.0-only"


@respx.mock
async def test_dev_deps_and_registry_errors_not_reported(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "projekt")
    rb.write("pyproject.toml", '[project]\nname = "p"\nlicense = "MIT"\n')
    rb.write("requirements.txt", "soukroma==1.0\n")
    rb.write("requirements-dev.txt", "gpllinter==1.0\n")
    rb.commit("deps")
    respx.get("https://pypi.org/pypi/soukroma/1.0/json").respond(404)
    linter = respx.get("https://pypi.org/pypi/gpllinter/1.0/json").respond(
        json={"info": {"license_expression": "GPL-3.0-only"}}
    )
    cfg = Config(roots=[RootConfig(path=str(rb.path))])
    result = await Scanner(
        cfg, ScanOptions(only=["license-compat"], use_forges=False), ssh_config=SshConfig()
    ).run()
    assert result.repos[0].findings == []  # 404 není „licence chybí“, linter je jen pro vývoj
    assert linter.call_count == 0


def _python_repo(tmp_path: Path) -> RepoBuilder:
    rb = RepoBuilder.create(tmp_path / "projekt")
    rb.write("pyproject.toml", '[project]\nname = "projekt"\nlicense = "MIT"\n')
    rb.write("requirements.txt", "gplka==1.0\nhezka==2.0\n")
    rb.write("package-lock.json", json.dumps({
        "lockfileVersion": 3,
        "packages": {"": {"name": "p"}, "node_modules/@scope/lib": {"version": "3.1.0"}},
    }))  # fmt: skip
    rb.commit("deps")
    return rb


@respx.mock
async def test_scan_fetches_licences_and_sbom_uses_cache_offline(tmp_path: Path) -> None:
    rb = _python_repo(tmp_path)
    gpl = respx.get("https://pypi.org/pypi/gplka/1.0/json").respond(
        json={"info": {"license_expression": "GPL-3.0-only"}}
    )
    respx.get("https://pypi.org/pypi/hezka/2.0/json").respond(json={"info": {"license": "MIT"}})
    cfg = Config(roots=[RootConfig(path=str(rb.path))])
    result = await Scanner(
        cfg, ScanOptions(only=["license-compat"], use_forges=False), ssh_config=SshConfig()
    ).run()
    findings = result.repos[0].findings
    assert [f.key for f in findings] == ["PyPI:gplka"]
    assert gpl.call_count == 1
    # SBOM bez sítě: licence jen z cache odpovědí registrů
    respx.reset()
    before = rb.snapshot()
    doc = sbom_for_repo(rb.path, now=datetime(2026, 10, 13, tzinfo=UTC))
    assert not respx.calls  # žádný síťový dotaz
    assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.5"
    assert doc["serialNumber"].startswith("urn:uuid:")
    comps = {c["purl"]: c for c in doc["components"]}
    assert comps["pkg:pypi/gplka@1.0"]["licenses"] == [{"license": {"id": "GPL-3.0-only"}}]
    assert comps["pkg:pypi/hezka@2.0"]["licenses"] == [{"license": {"id": "MIT"}}]
    assert comps["pkg:npm/%40scope/lib@3.1.0"]["scope"] == "optional"
    assert "licenses" not in comps["pkg:npm/%40scope/lib@3.1.0"]
    assert doc["metadata"]["component"]["licenses"] == [{"license": {"id": "MIT"}}]
    assert doc["metadata"]["tools"]["components"][0]["name"] == "repo-doctor"
    assert rb.snapshot() == before


def test_purl() -> None:
    assert purl(_dep("PyPI", "Foo_Bar", "1.0")) == "pkg:pypi/foo-bar@1.0"
    assert purl(_dep("npm", "@types/node", "20.0.0")) == "pkg:npm/%40types/node@20.0.0"
    assert purl(_dep("crates.io", "serde", "1.0.200")) == "pkg:cargo/serde@1.0.200"
    assert purl(_dep("Go", "github.com/x/y", "v1.2.3")) == "pkg:golang/github.com/x/y@v1.2.3"


def test_build_dedupes_and_expressions() -> None:
    a = _dep("crates.io", "dual", "1.0")
    data = DepsData(dependencies=[a, a], licenses={a: "MIT OR Apache-2.0"})
    doc = build("x", data, serial="urn:uuid:1")
    assert len(doc["components"]) == 1
    assert doc["components"][0]["licenses"] == [{"expression": "MIT OR Apache-2.0"}]
    assert doc["dependencies"][0]["dependsOn"] == ["pkg:cargo/dual@1.0"]


def test_cli_sbom_stdout_and_no_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rb = _python_repo(tmp_path)
    assert cli.main(["sbom", str(rb.path)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {c["name"] for c in doc["components"]} == {"gplka", "hezka", "@scope/lib"}
    out = tmp_path / "sbom.json"
    assert cli.main(["sbom", str(rb.path), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["specVersion"] == "1.5"
    out.write_text("moje")
    assert cli.main(["sbom", str(rb.path), "-o", str(out)]) == 2
    assert out.read_text() == "moje"
    assert cli.main(["sbom", str(rb.path), "--format", "spdx"]) == 2
    assert cli.main(["sbom", str(tmp_path / "neni")]) == 2
    capsys.readouterr()


async def test_tui_export_sbom(tmp_path: Path) -> None:
    from repo_doctor.models import RepoResult, ScanResult
    from repo_doctor.tui.screens.dialogs import InputDialog
    from tests.tui_helpers import make_app

    rb = _python_repo(tmp_path)
    result = ScanResult(repos=[RepoResult(path=str(rb.path), name="projekt", root="~")])
    app = make_app(tmp_path, result=result)
    target = tmp_path / "vystup" / "p.cdx.json"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, InputDialog)
        dialog.query_one("#value").value = str(target)  # type: ignore[attr-defined]
        await pilot.press("enter")
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
    assert json.loads(target.read_text())["metadata"]["component"]["name"] == "projekt"
