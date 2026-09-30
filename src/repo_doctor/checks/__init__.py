"""Kontroly. Každý modul v tomto balíčku se načte automaticky; nová kontrola = nový soubor
s třídou odvozenou od `Check` a dekorátorem `@register`."""

from repo_doctor.checks.base import (
    REGISTRY,
    Check,
    RepoContext,
    SkipCheck,
    all_checks,
    check_ids,
    get_check,
    register,
    select_checks,
)

__all__ = [
    "REGISTRY",
    "Check",
    "RepoContext",
    "SkipCheck",
    "all_checks",
    "check_ids",
    "get_check",
    "register",
    "select_checks",
]
