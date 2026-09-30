"""Zdroje tokenů: proměnná prostředí, příkaz (token_cmd) nebo systémová klíčenka.

Token se nikdy neukládá do config.toml, neloguje a výstup `token_cmd` nikam nepropaguje
(ani do chybových hlášek).
"""

from __future__ import annotations

import contextlib
import os
import shlex
import subprocess
from collections.abc import Callable

from repo_doctor.config import ForgeConfig
from repo_doctor.masking import Token

KEYRING_SERVICE = "repo-doctor"


class TokenError(Exception):
    """Token nelze získat. Zpráva nikdy neobsahuje hodnotu tokenu ani výstup příkazu."""


def _run_cmd(cmd: str, timeout: float) -> str:
    try:
        args = shlex.split(cmd)
    except ValueError as err:
        raise TokenError(f"token_cmd nejde rozparsovat: {err}") from None
    if not args:
        raise TokenError("token_cmd je prázdný")
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise TokenError(f"token_cmd: program {args[0]!r} nebyl nalezen") from None
    except subprocess.TimeoutExpired:
        raise TokenError(f"token_cmd nedoběhl do {timeout:g} s") from None
    if proc.returncode != 0:
        raise TokenError(
            f"token_cmd skončil s kódem {proc.returncode} (výstup se z bezpečnostních důvodů nezobrazuje)"
        )
    for line in proc.stdout.splitlines():
        if line.strip():
            return line.strip()
    raise TokenError("token_cmd nevrátil žádný výstup")


def _keyring_get(name: str) -> str | None:
    import keyring
    from keyring.errors import KeyringError

    try:
        value: str | None = keyring.get_password(KEYRING_SERVICE, name)
    except KeyringError as err:
        raise TokenError(f"klíčenka není dostupná: {type(err).__name__}") from None
    except Exception as err:  # backendy keyringu hází různé výjimky
        raise TokenError(f"klíčenka není dostupná: {type(err).__name__}") from None
    return value


def store_in_keyring(name: str, value: str) -> None:
    import keyring

    try:
        keyring.set_password(KEYRING_SERVICE, name, value)
    except Exception as err:
        raise TokenError(f"token nelze uložit do klíčenky: {type(err).__name__}") from None


def delete_from_keyring(name: str) -> None:
    import keyring

    with contextlib.suppress(Exception):  # token v klíčence být nemusí
        keyring.delete_password(KEYRING_SERVICE, name)


def resolve_token(
    forge: ForgeConfig,
    *,
    cmd_runner: Callable[[str, float], str] = _run_cmd,
    keyring_get: Callable[[str], str | None] = _keyring_get,
    timeout: float = 15.0,
) -> Token | None:
    source = forge.token_source or "none"
    if source == "none":
        return None
    if source == "env":
        name = forge.token_env or ""
        value = os.environ.get(name, "").strip()
        if not value:
            raise TokenError(f"proměnná prostředí {name} není nastavená")
        return Token(value)
    if source == "cmd":
        return Token(cmd_runner(forge.token_cmd or "", timeout))
    stored = keyring_get(forge.name)
    if not stored:
        raise TokenError(f"v klíčence není token pro hosting {forge.name}")
    return Token(stored.strip())
