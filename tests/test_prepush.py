"""prepush-guard (ochrana proti pushnutí tajemství) a `repo-doctor guard`."""

from __future__ import annotations

import io
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

from repo_doctor import cli
from repo_doctor.checks import get_check
from repo_doctor.config import AllowEntry, Config
from repo_doctor.fixes import FixRefused, apply, plan
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.guard import push_ranges, render, run_guard
from tests import factory as fx
from tests.factory import RepoBuilder, git
from tests.helpers import ctx

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="shell hooky")
ZERO = "0" * 40


def _with_upstream(tmp_path: Path) -> RepoBuilder:
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    rb = RepoBuilder.create(tmp_path / "repo")
    rb.write("a.txt", "a").commit("init")
    rb.remote("origin", str(upstream))
    rb.git("push", "-q", "-u", "origin", "main")
    return rb


def test_check_without_and_with_protection(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    assert [f.check_id for f in check.run(ctx(rb.path))] == ["prepush-guard"]
    rb.write(
        ".pre-commit-config.yaml",
        "repos:\n  - repo: https://github.com/gitleaks/gitleaks\n    rev: v8\n"
        "    hooks:\n      - id: gitleaks\n",
    ).commit("pc")
    assert check.run(ctx(rb.path)) != []  # gitleaks jen pro commit, ne pre-push
    rb.write(
        ".pre-commit-config.yaml",
        "default_stages: [pre-push]\nrepos:\n  - repo: https://github.com/gitleaks/gitleaks\n"
        "    rev: v8\n    hooks:\n      - id: gitleaks\n",
    ).commit("pc2")
    assert check.run(ctx(rb.path)) == []
    hook = rb.path / ".git" / "hooks" / "pre-push"
    rb.write(".pre-commit-config.yaml", "repos: []\n").commit("pc3")
    hook.write_text("#!/bin/sh\nexit 0\n")
    assert check.run(ctx(rb.path)) != []  # nespustitelný hook nepočítáme
    hook.chmod(0o755)
    assert check.run(ctx(rb.path)) == []


def test_two_variants_one_at_a_time(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    c = ctx(rb.path)
    patches = plan(c, check.run(c))
    assert [p.variant for p in patches] == ["precommit", "local"]
    with pytest.raises(FixRefused, match="jen jednu variantu"):
        apply(Git(rb.path), patches)
    # varianta 1: commit do větve oprav
    before = rb.snapshot()
    res = apply(Git(rb.path), [patches[0]], today=date(2026, 10, 14))
    cfg = git(rb.path, "show", f"{res.branch}:.pre-commit-config.yaml")
    assert "entry: repo-doctor guard" in cfg and "stages: [pre-push]" in cfg
    assert rb.snapshot()["status"] == before["status"]
    assert not (rb.path / ".git" / "hooks" / "pre-push").exists()


def test_precommit_variant_appends_only_when_safe(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    rb.write(".pre-commit-config.yaml", "repos:\n  - repo: local\n    hooks: []\n").commit()
    patches = plan(ctx(rb.path), check.run(ctx(rb.path)))
    assert patches[0].variant == "precommit"
    assert patches[0].changes[0].content.endswith("stages: [pre-push]\n")
    rb.write(".pre-commit-config.yaml", "repos: []\nci:\n  skip: []\n").commit()
    variants = [p.variant for p in plan(ctx(rb.path), check.run(ctx(rb.path)))]
    assert variants == ["local"]  # repos není poslední klíč – soubor neupravujeme


def test_local_hook_install_and_real_push_is_blocked(tmp_path: Path) -> None:
    if shutil.which("repo-doctor") is None:
        pytest.skip("repo-doctor není v PATH")
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    local = [p for p in plan(ctx(rb.path), check.run(ctx(rb.path))) if p.variant == "local"]
    res = apply(Git(rb.path), local)
    assert res.branch is None and res.local
    hook = rb.path / ".git" / "hooks" / "pre-push"
    assert hook.stat().st_mode & 0o111 and "repo-doctor guard" in hook.read_text()
    secret = fx.fake_aws_key(3)
    rb.write("config.env", f"AWS={secret}\n").commit("omylem tajemství")
    proc = __import__("subprocess").run(
        ["git", "push", "origin", "main"], cwd=rb.path, capture_output=True, text=True,
        env={**__import__("os").environ, **fx.GIT_ENV},
    )  # fmt: skip
    assert proc.returncode != 0
    assert "push zastaven" in proc.stderr and secret not in proc.stderr
    assert secret[:4] in proc.stderr
    # čistý commit projde
    rb.git("reset", "-q", "--hard", "HEAD~1")
    rb.write("b.txt", "b").commit("ok")
    rb.git("push", "-q", "origin", "main")


def test_foreign_hook_is_never_overwritten(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    local = [p for p in plan(ctx(rb.path), check.run(ctx(rb.path))) if p.variant == "local"]
    hook = rb.path / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho moje\n")  # nespustitelný vlastní hook
    with pytest.raises(FixRefused, match="nepřepíše"):
        apply(Git(rb.path), local)
    assert hook.read_text() == "#!/bin/sh\necho moje\n"


def test_symlinked_hook_is_refused(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    local = [p for p in plan(ctx(rb.path), check.run(ctx(rb.path))) if p.variant == "local"]
    elsewhere = tmp_path / "bin" / "git"
    (rb.path / ".git" / "hooks" / "pre-push").symlink_to(elsewhere)  # visící symlink
    with pytest.raises(FixRefused, match="symlink"):
        apply(Git(rb.path), local)
    assert not elsewhere.exists()


def test_untrusted_owner_never_gets_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    local = [p for p in plan(ctx(rb.path), check.run(ctx(rb.path))) if p.variant == "local"]
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(FixRefused):
        apply(Git(rb.path), local)
    monkeypatch.delenv("GIT_TEST_ASSUME_DIFFERENT_OWNER")
    assert not (rb.path / ".git" / "hooks" / "pre-push").exists()


def test_user_hooks_path_disables_local_variant(tmp_path: Path) -> None:
    check = get_check("prepush-guard")
    assert check is not None
    rb = _with_upstream(tmp_path)
    rb.git("config", "core.hooksPath", ".githooks")
    assert [p.variant for p in plan(ctx(rb.path), check.run(ctx(rb.path)))] == ["precommit"]
    (rb.path / ".githooks").mkdir()
    (rb.path / ".githooks" / "pre-push").write_text("#!/bin/sh\n")
    (rb.path / ".githooks" / "pre-push").chmod(0o755)
    assert check.run(ctx(rb.path)) == []


# ------------------------------------------------------------------ guard
def test_push_ranges() -> None:
    lines = [
        f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}",
        f"refs/heads/nova {'c' * 40} refs/heads/nova {ZERO}",
        f"(delete) {ZERO} refs/heads/stara {'d' * 40}",
        "nesmysl",
    ]
    assert push_ranges(lines, env={}) == [
        [f"{'b' * 40}..{'a' * 40}"],
        ["c" * 40, "--not", "--remotes"],
    ]
    assert push_ranges([], env={"PRE_COMMIT_FROM_REF": "x", "PRE_COMMIT_TO_REF": "y"}) == [["x..y"]]


def test_guard_scans_only_new_commits_and_masks(tmp_path: Path) -> None:
    rb = _with_upstream(tmp_path)
    old_secret = fx.fake_aws_key(5)
    # tajemství už na remotu (není „nové“) se nehlásí
    rb.write("stare.env", f"AWS={old_secret}\n").commit("staré")
    rb.git("push", "-q", "origin", "main")
    remote_sha = rb.head()
    secret = fx.fake_aws_key(6)
    rb.write("nove.env", f"AWS={secret}\n").commit("nové")
    line = f"refs/heads/main {rb.head()} refs/heads/main {remote_sha}"
    result = run_guard(rb.path, [line], Config())
    assert result.blocked and len(result.matches) == 1
    text = render(result)
    assert secret not in text and old_secret not in text and "nove.env" in text
    # allowlist (stejný otisk jako v kartě repa) push pustí
    from repo_doctor.checks.secrets import _to_finding

    check = get_check("secrets-history")
    assert check is not None
    fp = _to_finding(check, result.matches[0], history=True).fingerprint(rb.path.name)
    cfg = Config(allowlist=[AllowEntry(hash=fp, reason="testovací")])
    allowed = run_guard(rb.path, [line], cfg)
    assert not allowed.blocked and allowed.allowlisted == 1


def test_guard_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rb = _with_upstream(tmp_path)
    remote_sha = rb.head()
    rb.write("b.txt", "b").commit("čisté")
    monkeypatch.chdir(rb.path)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(f"refs/heads/main {rb.head()} refs/heads/main {remote_sha}\n")
    )
    assert cli.main(["guard", "origin", "url"]) == 0
    secret = fx.fake_aws_key(8)
    rb.write("x.env", f"AWS={secret}\n").commit("špatně")
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(f"refs/heads/main {rb.head()} refs/heads/main {remote_sha}\n")
    )
    assert cli.main(["guard", "origin", "url"]) == 1
    err = capsys.readouterr().err
    assert "push zastaven" in err and secret not in err


def test_guard_unknown_remote_sha_and_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rb = _with_upstream(tmp_path)
    secret = fx.fake_aws_key(7)
    rb.write("nove.env", f"AWS={secret}\n").commit("nové")
    # force push / nefetchnutý remote: remote sha lokálně neexistuje
    line = f"refs/heads/main {rb.head()} refs/heads/main {'f' * 40}"
    result = run_guard(rb.path, [line], Config())
    assert result.blocked and len(result.matches) == 1

    def boom(self: Git, *args: str, **kw: object) -> str:
        raise GitError(["git", *args], 128, "fatal: timeout")

    monkeypatch.setattr(Git, "run", boom)
    failed = run_guard(
        rb.path, [f"refs/heads/main {rb.head()} refs/heads/main {'0' * 40}"], Config()
    )
    assert failed.blocked and failed.errors and "nešlo zkontrolovat" in render(failed)
