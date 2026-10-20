"""Překlady rozhraní (#33): `_("český text")` vrátí text v jazyce uživatele.

Zdrojovým jazykem je čeština (msgid), překlady jsou v `locale/<jazyk>.po` – standardní
gettext formát (jde upravit v Poedit), načítá se přímo bez kompilace do .mo.

Jazyk se určí jednou při importu balíčku (texty v konstantách modulů se překládají při
importu), proto změna v Nastavení platí až po restartu. Pořadí:
`--lang` v argumentech → `REPO_DOCTOR_LANG` → `[ui] language` v config.toml →
`LC_ALL` / `LC_MESSAGES` / `LANG` (cs_* → čeština, jinak angličtina).
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from functools import cache
from pathlib import Path
from typing import Literal

Language = Literal["cs", "en"]
LANGUAGES: tuple[Language, ...] = ("cs", "en")
SOURCE: Language = "cs"
LOCALE_DIR = Path(__file__).parent / "locale"

_current: Language = SOURCE


def _(message: str) -> str:
    """Přeloží český text do aktuálního jazyka (chybí-li překlad, vrátí originál)."""
    if _current == SOURCE:
        return message
    return catalog(_current).get(message) or message


def N_(message: str) -> str:
    """Označí text k překladu bez překladu (překládá se až při použití přes `_`)."""
    return message


def language() -> Language:
    return _current


def set_language(lang: str) -> Language:
    global _current
    _current = normalize(lang) or SOURCE
    return _current


def normalize(value: str | None) -> Language | None:
    """`cs`, `cs_CZ.UTF-8`, `en_US` → jazyk; `auto`, prázdné, `C`, `POSIX` → None."""
    if not value:
        return None
    code = value.split(".")[0].split("@")[0].replace("-", "_").lower()
    if code in {"auto", "c", "posix"}:
        return None
    code = code.split("_")[0]
    if code == "cs" or code == "sk":
        return "cs"
    return "en"


def _argv_lang(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def _config_lang() -> str | None:
    from repo_doctor import paths

    try:
        data = tomllib.loads(paths.config_file().read_text("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None
    ui = data.get("ui")
    value = ui.get("language") if isinstance(ui, dict) else None
    return value if isinstance(value, str) else None


def detect(argv: list[str] | None = None, env: dict[str, str] | None = None) -> Language:
    env = dict(os.environ) if env is None else env
    for value in (
        _argv_lang(sys.argv[1:] if argv is None else argv),
        env.get("REPO_DOCTOR_LANG"),
        _config_lang(),
    ):
        if (lang := normalize(value)) is not None:
            return lang
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if value := env.get(var):
            return normalize(value) or "en"  # C / POSIX → angličtina
    return "en"


def init() -> Language:
    return set_language(detect())


# ---------------------------------------------------------------------- .po
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unquote(line: str) -> str:
    m = _STRING.search(line)
    if not m:
        return ""
    return re.sub(r"\\(.)", lambda e: _ESCAPES.get(e.group(1), e.group(1)), m.group(1))


def parse_po(text: str) -> dict[str, str]:
    """Jednoduchý parser .po: msgid/msgstr (i víceřádkové), bez fuzzy a prázdných překladů."""
    result: dict[str, str] = {}
    msgid: list[str] = []
    msgstr: list[str] = []
    target: list[str] | None = None
    fuzzy = False

    def flush() -> None:
        nonlocal fuzzy
        key, value = "".join(msgid), "".join(msgstr)
        if key and value and not fuzzy:
            result[key] = value
        msgid.clear()
        msgstr.clear()
        fuzzy = False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#,") and "fuzzy" in line:
            if msgstr:
                flush()
            fuzzy = True
        elif line.startswith("msgid "):
            if msgstr:
                flush()
            msgid.append(_unquote(line[6:]))
            target = msgid
        elif line.startswith("msgstr "):
            msgstr.append(_unquote(line[7:]))
            target = msgstr
        elif line.startswith('"') and target is not None:
            target.append(_unquote(line))
        elif not line:
            if msgstr:
                flush()
            target = None
    if msgstr:
        flush()
    return result


@cache
def catalog(lang: Language) -> dict[str, str]:
    try:
        return parse_po((LOCALE_DIR / f"{lang}.po").read_text("utf-8"))
    except OSError:
        return {}
