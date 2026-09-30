from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repo_doctor.checks import RepoContext, get_check
from repo_doctor.config import Config
from repo_doctor.gitwrap import Git
from repo_doctor.models import Finding

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def ctx(path: Path, config: Config | None = None, **kw: Any) -> RepoContext:
    return RepoContext(
        path=path,
        name=path.name,
        root=str(path.parent),
        config=config or Config(),
        git=Git(path),
        now=NOW,
        **kw,
    )


def run(check_id: str, path: Path, config: Config | None = None, **kw: Any) -> list[Finding]:
    check = get_check(check_id)
    assert check is not None
    return check.run(ctx(path, config, **kw))
