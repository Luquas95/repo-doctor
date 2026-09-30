from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pytest

from repo_doctor import paths
from repo_doctor.masking import (
    Token,
    install_log_redaction,
    mask,
    redact,
    redact_url_credentials,
    register_secret,
)
from tests.factory import fake_aws_key


def test_mask_format() -> None:
    key = fake_aws_key()
    assert mask(key) == f"{key[:4]}…(20 znaků)"
    assert key not in mask(key)


def test_mask_short_hides_prefix() -> None:
    assert mask("abc123") == "…(6 znaků)"


def test_token_never_printed() -> None:
    value = "tok_" + "x" * 30
    token = Token(value)
    assert value not in str(token)
    assert value not in repr(token)
    assert value not in f"{token}"
    assert token.reveal() == value
    assert bool(token)
    assert token == Token(value)
    assert hash(token) == hash(Token(value))
    with pytest.raises(TypeError):
        pickle.dumps(token)


def test_redact_registered() -> None:
    register_secret("supersecretvalue123")
    assert "supersecretvalue123" not in redact("x supersecretvalue123 y")
    register_secret("abc")  # příliš krátké, ignoruje se
    assert redact("abc") == "abc"


def test_redact_url_credentials() -> None:
    assert redact_url_credentials("https://user:pa55@host/x") == "https://user:…@host/x"
    assert redact_url_credentials("https://host/x") == "https://host/x"


def test_log_filter(caplog: pytest.LogCaptureFixture) -> None:
    secret = "token-" + "q" * 30
    Token(secret)
    install_log_redaction()
    install_log_redaction()  # idempotentní
    logger = logging.getLogger("repo_doctor.test")
    with caplog.at_level(logging.INFO):
        logger.info("using %s at https://u:%s@h/", secret, secret)
    assert secret not in caplog.text


def test_xdg_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    assert paths.config_file() == tmp_path / "c" / "repo-doctor" / "config.toml"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert paths.config_dir() == Path.home() / ".config" / "repo-doctor"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert paths.cache_dir() == Path.home() / ".cache" / "repo-doctor"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert paths.history_dir() == Path.home() / ".local/share" / "repo-doctor" / "history"
    assert paths.last_scan_file().name == "last-scan.json"
    assert paths.http_cache_dir().name == "http"
    monkeypatch.setenv("MYDIR", "/opt/x")
    assert paths.expand_path("$MYDIR/y") == Path("/opt/x/y")
    assert paths.expand_path("~/a") == Path.home() / "a"
    d = paths.ensure_private_dir(tmp_path / "p")
    assert d.is_dir()
