"""Cesty podle XDG Base Directory (s fallbacky na ~/.config, ~/.cache, ~/.local/share)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "repo-doctor"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    # Specifikace XDG: relativní cesty se ignorují.
    if value and os.path.isabs(value):
        return Path(value) / APP_NAME
    return Path.home() / fallback / APP_NAME


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def config_file() -> Path:
    return config_dir() / "config.toml"


def last_scan_file() -> Path:
    return cache_dir() / "last-scan.json"


def http_cache_dir() -> Path:
    return cache_dir() / "http"


def history_dir() -> Path:
    return data_dir() / "history"


def expand_path(raw: str) -> Path:
    """Rozbalí `~` a proměnné prostředí; výsledek není resolvovaný (symlinky zůstávají)."""
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
