"""Kontrola ci-security: workflow se jen čtou; připnutí akcí přes SHA z API."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import respx

from repo_doctor.checks import get_check
from repo_doctor.checks.ci_security import parse_uses, pin_actions
from repo_doctor.config import CIConfig, Config, RootConfig
from repo_doctor.fixes import apply, plan
from repo_doctor.forges.urls import SshConfig
from repo_doctor.gitwrap import Git
from repo_doctor.models import Finding
from repo_doctor.scanner import NetServices, Scanner, ScanOptions
from tests.factory import RepoBuilder, git
from tests.helpers import ctx

SHA = "08eba0b27e820071cde6df949e0beb9ba4906955"

SAFE = f"""\
name: ci
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v4
      - uses: ./.github/actions/local
      - env:
          TITLE: ${{{{ github.event.pull_request.title }}}}
        run: echo "$TITLE"
"""

RISKY = """\
name: risky
on:
  pull_request_target:
    types: [opened]
jobs:
  build:
    runs-on: [self-hosted, linux]
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - uses: "tj-actions/changed-files@v45"
      - run: |
          echo "PR: ${{ github.event.pull_request.title }}"
      - run: echo ${{ secrets.DEPLOY_KEY }}
      - env:
          TOKEN: ${{ secrets.NPM_TOKEN }}
        run: |
          set -x
          npm publish
"""

WRITE_ALL = """\
on: push
permissions: write-all
jobs:
  x:
    runs-on: ubuntu-latest
    steps:
      - uses: ja/moje-akce@main
      - uses: https://code.forgejo.org/actions/setup-node@v4
"""


def _repo(tmp_path: Path, files: dict[str, str]) -> RepoBuilder:
    rb = RepoBuilder.create(tmp_path / "r")
    for path, text in files.items():
        rb.write(path, text)
    rb.commit("ci")
    return rb


def _run(path: Path, **kw: object) -> list[Finding]:
    check = get_check("ci-security")
    assert check is not None
    return check.run(ctx(path, **kw))  # type: ignore[arg-type]


def test_safe_workflow_has_no_findings(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".github/workflows/ci.yml": SAFE})
    assert _run(rb.path, visibility="public") == []


def test_risky_workflow(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".github/workflows/risky.yml": RISKY})
    before = rb.snapshot()
    findings = _run(rb.path, visibility="public")
    kinds = {(f.kind, f.severity.value) for f in findings}
    assert ("unpinned", "medium") in kinds  # actions/checkout – první strana
    assert ("unpinned", "high") in kinds  # tj-actions s tajemstvími ve workflow
    assert ("pull_request_target", "high") in kinds
    assert ("injection", "high") in kinds
    assert ("secret-log", "medium") in kinds
    assert ("permissions", "medium") in kinds  # cizí PR bez permissions
    assert ("self-hosted", "high") in kinds
    secret_logs = [f for f in findings if f.kind == "secret-log"]
    assert len(secret_logs) == 2  # echo i set -x
    inj = next(f for f in findings if f.kind == "injection")
    assert inj.location.line == 14
    assert all(not f.fixable for f in findings)  # bez SHA z API se nic nepřipíná
    assert rb.snapshot() == before


def test_private_repo_self_hosted_not_reported(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".github/workflows/risky.yml": RISKY})
    assert "self-hosted" not in {f.kind for f in _run(rb.path, visibility="private")}


def test_write_all_trusted_owner_and_forgejo_url(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".forgejo/workflows/x.yaml": WRITE_ALL})
    cfg = Config(ci=CIConfig(trusted_action_owners=["ja"]))
    findings = _run(rb.path, config=cfg)
    assert {f.kind for f in findings} == {"permissions", "unpinned"}
    unpinned = [f for f in findings if f.kind == "unpinned"]
    assert [f.data["action"] for f in unpinned] == [
        "https://code.forgejo.org/actions/setup-node@v4"
    ]
    without_trust = _run(rb.path)
    assert len([f for f in without_trust if f.kind == "unpinned"]) == 2


def test_invalid_yaml_is_ignored(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".github/workflows/bad.yml": "on: [push\n  : ::"})
    assert _run(rb.path) == []


@pytest.mark.parametrize(
    ("uses", "expected"),
    [
        ("actions/checkout@v4", ("actions/checkout", "v4")),
        ("github/codeql-action/init@v3", ("github/codeql-action", "v3")),
        ("'docker/build-push-action@v6'", ("docker/build-push-action", "v6")),
        ("https://code.forgejo.org/actions/checkout@v4", ("actions/checkout", "v4")),
        ("./local", None),
        ("docker://alpine:3", None),
        ("nobranch", None),
    ],
)
def test_parse_uses(uses: str, expected: tuple[str, str] | None) -> None:
    assert parse_uses(uses) == expected


def test_pin_actions_keeps_format() -> None:
    text = (
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: 'tj-actions/changed-files@v45'  # komentář\n"
        "        with: {fetch-depth: 0}\n"
        "      - uses: actions/checkout@v4.1.0\n"
    )
    new = pin_actions(text, {"actions/checkout@v4": SHA, "tj-actions/changed-files@v45": "a" * 40})
    assert f"      - uses: actions/checkout@{SHA} # v4\n" in new
    assert f"      - uses: 'tj-actions/changed-files@{'a' * 40}' # v45\n" in new
    assert "      - uses: actions/checkout@v4.1.0\n" in new  # jiný tag se nemění


@respx.mock
async def test_scan_resolves_sha_and_fix_pins_in_fix_branch(tmp_path: Path) -> None:
    rb = _repo(tmp_path, {".github/workflows/risky.yml": RISKY})
    rb.remote("origin", "https://github.com/ja/projekt.git")
    respx.get("https://api.github.com/repos/actions/checkout/commits/v4").respond(json={"sha": SHA})
    respx.get("https://api.github.com/repos/tj-actions/changed-files/commits/v45").respond(404)
    respx.get("https://api.github.com/repos/ja/projekt").respond(
        json={"full_name": "ja/projekt", "private": False, "default_branch": "main"}
    )
    cfg = Config(roots=[RootConfig(path=str(rb.path))])
    net = NetServices.create(cfg)
    try:
        result = await Scanner(
            cfg,
            ScanOptions(only=["ci-security"], use_forges=False),
            net=net,
            ssh_config=SshConfig(),
        ).run()
    finally:
        await net.aclose()
    findings = result.repos[0].findings
    pinned = [f for f in findings if f.kind == "unpinned" and f.fixable]
    assert [f.data["action"] for f in pinned] == ["actions/checkout@v4"]
    before = rb.snapshot()
    c = ctx(rb.path)
    patches = plan(c, findings)
    assert len(patches) == 1
    diff = patches[0].diff()
    assert f"+      - uses: actions/checkout@{SHA} # v4" in diff
    assert '"tj-actions/changed-files@v45"' in diff  # nezjištěné SHA zůstává (jen kontext)
    assert rb.snapshot() == before  # plán nic nezměnil
    res = apply(Git(rb.path), patches, today=date(2026, 10, 13))
    assert res.branch == "repo-doctor/fixes-2026-10-13"
    pinned_text = git(rb.path, "show", f"{res.branch}:.github/workflows/risky.yml")
    assert f"actions/checkout@{SHA} # v4" in pinned_text
    assert (
        rb.path / ".github/workflows/risky.yml"
    ).read_text() == RISKY  # pracovní strom beze změny
