"""Opravy – dočasná kostra (doplněno v bloku fix systému)."""

from __future__ import annotations

import difflib

from repo_doctor.models import Patch


def render_diff(patch: Patch) -> str:
    out: list[str] = []
    for change in patch.changes:
        old = (change.old or "").splitlines(keepends=True)
        new = (change.new or "").splitlines(keepends=True)
        out.extend(difflib.unified_diff(old, new, f"a/{change.path}", f"b/{change.path}"))
    return "".join(out)
