"""Česká slova podle čísla (1 repo, 2 repa, 5 rep)."""

from __future__ import annotations


def plural(n: int, one: str, few: str, many: str) -> str:
    """Tvar podle čísla: 1 → `one`, 2–4 → `few`, jinak `many` (včetně 0)."""
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


def count(n: int, one: str, few: str, many: str) -> str:
    """`5 rep`, `1 položka`…"""
    return f"{n} {plural(n, one, few, many)}"


def items(n: int) -> str:
    return count(n, "položka", "položky", "položek")


def repos(n: int) -> str:
    return count(n, "repo", "repa", "rep")


def commits(n: int) -> str:
    return count(n, "commit", "commity", "commitů")


def files(n: int) -> str:
    return count(n, "soubor", "soubory", "souborů")


def more(n: int) -> str:
    """`… a 1 další`, `… a 5 dalších`."""
    return f"… a {n} {plural(n, 'další', 'další', 'dalších')}"
