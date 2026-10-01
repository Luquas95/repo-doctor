"""Maskování tajemství a tokenů.

Tajemství se v repo-doctoru nikdy nevypisuje. Nálezy nesou jen maskovanou podobu
(`AKIA…(20 znaků)`), tokeny hostingů jsou zabalené v `Token` a všechny zaregistrované
hodnoty se navíc odstraňují z logů filtrem `RedactingFilter`.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable

VISIBLE_PREFIX = 4
ELLIPSIS = "…"


def mask(secret: str, *, prefix: int = VISIBLE_PREFIX) -> str:
    """Vrátí maskovanou podobu: první `prefix` znaků + `…` + délka.

    Krátká tajemství (do 8 znaků) neukazují ani prefix, protože by prozradila příliš.
    """
    length = len(secret)
    shown = secret[:prefix] if length > 2 * prefix else ""
    return f"{shown}{ELLIPSIS}({length} znaků)"


class _Registry:
    """Globální registr hodnot, které se nesmí nikde objevit (tokeny, nalezená tajemství)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: set[str] = set()
        self._pattern: re.Pattern[str] | None = None

    def add(self, value: str) -> None:
        if len(value) < 6:  # příliš krátké hodnoty by maskovaly běžný text
            return
        with self._lock:
            if value not in self._values:
                self._values.add(value)
                self._pattern = None

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._pattern = None

    def redact(self, text: str) -> str:
        with self._lock:
            if not self._values:
                return text
            if self._pattern is None:
                ordered = sorted(self._values, key=len, reverse=True)
                self._pattern = re.compile("|".join(re.escape(v) for v in ordered))
            pattern = self._pattern
        return pattern.sub(lambda m: mask(m.group(0)), text)


REGISTRY = _Registry()


def register_secret(value: str) -> None:
    REGISTRY.add(value)


def redact(text: str) -> str:
    """Nahradí všechny zaregistrované hodnoty jejich maskovanou podobou."""
    return REGISTRY.redact(text)


_URL_USERINFO = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
_URL_TOKEN_PARAM = re.compile(
    r"(?P<key>[?&](?:private_token|access_token|token|oauth_token|api_key|apikey|password)=)[^&#\s]+",
    re.IGNORECASE,
)


def redact_url_credentials(url: str) -> str:
    """Odstraní celou userinfo část (`https://user:token@host`, `https://<token>@host`)
    i tokeny v query (`?private_token=…`). Funguje i bez registrace hodnoty."""
    url = _URL_USERINFO.sub(r"\g<scheme>…@", url)
    return _URL_TOKEN_PARAM.sub(r"\g<key>…", url)


class Token:
    """Obal API tokenu. `str()`/`repr()` nikdy neprozradí hodnotu."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value
        register_secret(value)

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return f"Token({mask(self._value)})"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Token) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("token", self._value))

    def __reduce__(self) -> tuple[object, ...]:  # pickle by token prozradil
        raise TypeError("Token nelze serializovat")


class RedactingFilter(logging.Filter):
    """Logging filtr, který z každé zprávy odstraní zaregistrovaná tajemství."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact_url_credentials(redact(message))
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def install_log_redaction(
    loggers: Iterable[str] = ("", "repo_doctor", "httpx", "httpcore"),
) -> None:
    for name in loggers:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(RedactingFilter())
        for handler in logger.handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(RedactingFilter())
