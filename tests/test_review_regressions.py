"""Regresní testy pro nálezy z revize detekce (docs/REVIEW.md)."""

from __future__ import annotations

import os
from pathlib import Path

from repo_doctor.checks.public_sensitive import scan_infra
from repo_doctor.checks.secrets import is_sensitive_file
from repo_doctor.config import RootConfig
from repo_doctor.deps import collect, parse_yarn_lock
from repo_doctor.discovery import discover
from repo_doctor.forges.urls import parse_remote
from repo_doctor.secrets_scan import parse_log_patch, scan_text
from tests import factory as fx
from tests.factory import RepoBuilder
from tests.helpers import run


def test_generic_secret_prefixed_and_unquoted() -> None:
    val = fx.fake_generic_secret(11)
    assert scan_text(f'DB_PASSWORD="{val}"', "app.py")
    assert scan_text(f'GITHUB_TOKEN: "{val}"', "ci.py")
    assert scan_text(f"PASSWORD={val}", ".env.production")
    assert scan_text(f"api_key: {val}", "config.yaml")
    assert not scan_text(f"token = get_token_from_environment({val})", "app.py")
    assert not scan_text(f'password_hash = "{val}"', "app.py")


def test_aws_secret_with_trailing_symbol() -> None:
    key = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5hJk/"
    assert scan_text(f'AWS_SECRET_ACCESS_KEY="{key}"', "x.env")


def test_placeholder_only_whole_words() -> None:
    assert scan_text('password: "reallyStrongPass123replacement"', "c.yaml")
    assert scan_text(f"{fx.fake_github_token()[:-4]}Todo", "c.txt")


def test_default_db_password_ignored() -> None:
    assert not scan_text("postgres://postgres:postgres@db:5432/app", "compose.yml")


def test_history_parser_headers() -> None:
    key = fx.fake_aws_key()
    lines = [
        "\0commit abc 1700000000",
        "diff --git a/my config.py b/my config.py",
        "--- /dev/null",
        "+++ b/my config.py\t",
        "@@ -0,0 +1,3 @@",
        "+x",
        "+++ heading",
        f"+k={key}",
    ]
    (m,) = list(parse_log_patch(lines))
    assert m.path == "my config.py" and m.line == 3


def test_workspace_lockfiles() -> None:
    files = {
        "package.json": '{"workspaces": ["packages/*"], "devDependencies": {"x": "1"}}',
        "package-lock.json": "{}",
        "packages/a/package.json": '{"dependencies": {"y": "1"}}',
        "pyproject.toml": '[tool.uv.workspace]\nmembers=["py/*"]\n',
        "uv.lock": "version = 1\n",
        "py/b/pyproject.toml": '[project]\nname="b"\ndependencies=["z"]\n',
    }
    assert collect(list(files), files.get).missing_locks == []


def test_yarn_workspace_entries_skipped() -> None:
    text = '"my-app@workspace:.":\n  version: 0.0.0-use.local\n\n"lodash@npm:^4":\n  version: 4.17.21\n'
    assert [(d.name, d.version) for d in parse_yarn_lock(text, "yarn.lock")] == [
        ("lodash", "4.17.21")
    ]


def test_sensitive_pem_names() -> None:
    for name in ("localhost.pem", "application.pem", "cache-key.pem"):
        assert is_sensitive_file(name), name
    for name in ("ca.pem", "server-cert.pem", "fullchain.pem", "ca_bundle.pem"):
        assert not is_sensitive_file(name), name


def test_public_ip_ranges() -> None:
    assert scan_infra("netmask: 255.255.255.0\ndoc: 192.0.2.10\nbench: 198.18.0.1\n") == set()
    assert scan_infra("db: 172.20.0.5") == {"privátní IP adresy"}
    assert "adresy fd7a:115c:a1e0:: (Tailscale)" in scan_infra("node: fd7a:115c:a1e0:ab12::1")


def test_docker_env_non_secrets(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write(
        "Dockerfile",
        "FROM python:3.12\nENV POSTGRES_PASSWORD_FILE=/run/secrets/db_password\nARG API_KEY=changeme\n"
        "ENV TOKEN_URL=https://auth.example.com/token\nUSER root:root\n",
    ).write(".dockerignore", ".git\n").commit()
    msgs = [f.message for f in run("docker-hygiene", rb.path)]
    assert msgs == ["kontejner běží pod rootem (ve finální fázi chybí USER)"]


def test_discovery_finds_repo_named_build(tmp_path: Path) -> None:
    for name in ("build", "env", "tools"):
        RepoBuilder.create(tmp_path / name)
    RepoBuilder.create(tmp_path / "node_modules" / "x")
    found = sorted(r.name for r in discover([RootConfig(path=str(tmp_path))]).repos)
    assert found == ["build", "env", "tools"]


def test_fresh_branch_not_stale(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a", "a").commit(ts=1_790_000_000)
    rb.branch("new-feature")
    assert run("stale-branches", rb.path) == []


def test_windows_path_is_not_ssh() -> None:
    r = parse_remote("C:\\Users\\me\\repo")
    assert r is not None and r.scheme == "file"
    assert os.sep  # jen pro mypy/ruff
