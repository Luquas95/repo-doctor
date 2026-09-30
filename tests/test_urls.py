from __future__ import annotations

from pathlib import Path

import pytest

from repo_doctor.config import ForgeConfig
from repo_doctor.forges.urls import (
    RemoteURL,
    SshConfig,
    forge_web_host,
    match_forge,
    parse_remote,
    web_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "git@github.com:nekdo/infra-notes.git",
            RemoteURL("ssh", "github.com", None, "nekdo/infra-notes", "git"),
        ),
        (
            "git@github.com:nekdo/infra-notes",
            RemoteURL("ssh", "github.com", None, "nekdo/infra-notes", "git"),
        ),
        ("github.com:nekdo/x.git", RemoteURL("ssh", "github.com", None, "nekdo/x", None)),
        (
            "ssh://git@git.example.ts.net:2222/owner/repo.git",
            RemoteURL("ssh", "git.example.ts.net", 2222, "owner/repo", "git"),
        ),
        (
            "ssh://git@100.101.1.2/owner/repo",
            RemoteURL("ssh", "100.101.1.2", None, "owner/repo", "git"),
        ),
        ("git+ssh://git@host/o/r.git", RemoteURL("ssh", "host", None, "o/r", "git")),
        ("ssh://git@host/~/o/r.git", RemoteURL("ssh", "host", None, "o/r", "git")),
        ("https://github.com/nekdo/repo.git", RemoteURL("https", "github.com", None, "nekdo/repo")),
        ("https://GitHub.com/nekdo/repo/", RemoteURL("https", "github.com", None, "nekdo/repo")),
        (
            "https://git.example.ts.net:3000/owner/repo.git",
            RemoteURL("https", "git.example.ts.net", 3000, "owner/repo"),
        ),
        (
            "https://user:tok@gitlab.com/g/sub/proj.git",
            RemoteURL("https", "gitlab.com", None, "g/sub/proj", "user"),
        ),
        ("http://100.64.0.5:8080/o/r", RemoteURL("http", "100.64.0.5", 8080, "o/r")),
        ("git://example.org/o/r.git", RemoteURL("git", "example.org", None, "o/r")),
        ("git@[::1]:o/r.git", RemoteURL("ssh", "::1", None, "o/r", "git")),
        ("https://host/o/my%20repo.git", RemoteURL("https", "host", None, "o/my repo")),
    ],
)
def test_parse(url: str, expected: RemoteURL) -> None:
    assert parse_remote(url) == expected


@pytest.mark.parametrize("url", ["", "ftp://x/y", "https:///nohost", "not a url"])
def test_parse_invalid(url: str) -> None:
    assert parse_remote(url) is None


def test_parse_local() -> None:
    r = parse_remote("/srv/git/repo.git")
    assert r is not None and r.scheme == "file" and r.host is None
    r = parse_remote("file:///srv/git/repo.git")
    assert r is not None and r.path == "srv/git/repo"
    assert web_url(r) is None


def test_bad_port() -> None:
    r = parse_remote("https://host:99999/o/r")
    assert r is not None and r.port is None


SSH_CONFIG = """\
# komentář
Host forgejo homelab-git
    HostName git.tailnet-name.ts.net
    Port 2222
    User git

Host gh-work
  HostName=github.com

Host *.internal !bad.internal
  HostName %h.example.org

Match host x
  HostName ignored

Host *
  Port 22
"""


def test_ssh_aliases(tmp_path: Path) -> None:
    cfg = SshConfig.parse(SSH_CONFIG)
    assert cfg.resolve("forgejo") == ("git.tailnet-name.ts.net", 2222)
    assert cfg.resolve("gh-work") == ("github.com", 22)
    assert cfg.resolve("srv.internal") == ("srv.internal.example.org", 22)
    assert cfg.resolve("bad.internal") == ("bad.internal", 22)
    r = parse_remote("forgejo:owner/repo.git", cfg)
    assert r == RemoteURL("ssh", "git.tailnet-name.ts.net", 2222, "owner/repo", None, "forgejo")
    r = parse_remote("ssh://git@homelab-git/o/r.git", cfg)
    assert (
        r is not None
        and r.host == "git.tailnet-name.ts.net"
        and r.port == 2222
        and r.alias == "homelab-git"
    )
    r = parse_remote("git@gh-work:firma/app.git", cfg)
    assert r is not None and r.host == "github.com" and r.owner == "firma" and r.name == "app"


def test_ssh_include_and_load(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    (ssh / "conf.d").mkdir(parents=True)
    (ssh / "conf.d" / "a.conf").write_text("Host inc\n  HostName included.example\n")
    (ssh / "config").write_text("HostName global.example\nInclude conf.d/*.conf\n")
    cfg = SshConfig.load(ssh / "config")
    assert cfg.resolve("inc")[0] == "global.example"  # globální volba bez Host platí pro vše
    assert SshConfig.load(tmp_path / "missing").resolve("x") == ("x", None)
    cfg2 = SshConfig.parse("Include conf.d/*.conf\n", base=ssh)
    assert cfg2.resolve("inc") == ("included.example", None)


def test_match_forge() -> None:
    gh = ForgeConfig(name="github", type="github", user="nekdo")
    gh_work = ForgeConfig(name="gh-work", type="github", org="firma")
    fj = ForgeConfig(name="domaci", type="forgejo", url="https://git.example.ts.net:3000")
    gl = ForgeConfig(name="gl", type="gitlab")
    ghe = ForgeConfig(name="ghe", type="github", url="https://ghe.corp.example/api/v3")
    off = ForgeConfig(name="off", type="gitea", url="https://off.example", enabled=False)
    forges = [gh, gh_work, fj, gl, ghe, off]
    assert forge_web_host(gh) == "github.com"
    assert forge_web_host(fj) == "git.example.ts.net"
    assert match_forge(parse_remote("git@github.com:firma/x.git"), forges) is gh_work  # type: ignore[arg-type]
    assert match_forge(parse_remote("git@github.com:nekdo/x.git"), forges) is gh  # type: ignore[arg-type]
    assert match_forge(parse_remote("git@github.com:cizi/x.git"), forges) is gh  # type: ignore[arg-type]
    # SSH port (2222) se liší od webového (3000) – rozhoduje jen hostname
    assert match_forge(parse_remote("ssh://git@git.example.ts.net:2222/o/r"), forges) is fj  # type: ignore[arg-type]
    assert match_forge(parse_remote("https://gitlab.com/g/s/p"), forges) is gl  # type: ignore[arg-type]
    assert match_forge(parse_remote("git@ghe.corp.example:t/r"), forges) is ghe  # type: ignore[arg-type]
    assert match_forge(parse_remote("https://off.example/o/r"), forges) is None  # type: ignore[arg-type]
    assert match_forge(parse_remote("/local/path"), forges) is None  # type: ignore[arg-type]
    assert match_forge(parse_remote("https://unknown.example/o/r"), forges) is None  # type: ignore[arg-type]
    assert web_url(parse_remote("git@github.com:a/b.git")) == "https://github.com/a/b"  # type: ignore[arg-type]
