"""`repo-doctor guard` – kontrola tajemství v commitech, které se chystají k pushi.

Spouští ho uživatelův vlastní `git push` přes hook `pre-push` (`.git/hooks/pre-push`
nebo pre-commit, stage `pre-push`). repo-doctor sám hooky při svých voláních gitu
nikdy nespouští (`core.hooksPath=/dev/null`) – tohle je opačný směr: uživatel ho volá
z hooku ve svém repu. Skenuje jen nové commity (rychlé), výstup je vždy maskovaný.
"""

from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from repo_doctor import czech
from repo_doctor.config import Config, ConfigError, effective_for_repo, load_repo_overrides
from repo_doctor.gitwrap import Git, GitError
from repo_doctor.i18n import N_, _
from repo_doctor.secrets_scan import SecretMatch, parse_log_patch

ZERO = re.compile(r"^0+$")
HOOK_SCRIPT = N_("""\
#!/bin/sh
# repo-doctor guard – kontrola tajemství před pushem (nainstaloval repo-doctor)
# Odinstalace: smaž tento soubor. Jednorázové obejití: git push --no-verify
if command -v repo-doctor >/dev/null 2>&1; then
    exec repo-doctor guard "$@"
fi
echo "repo-doctor guard: repo-doctor není v PATH – kontrola tajemství přeskočena" >&2
exit 0
""")


@dataclass
class GuardResult:
    matches: list[SecretMatch] = field(default_factory=list)
    ranges: list[str] = field(default_factory=list)
    allowlisted: int = 0
    errors: list[str] = field(default_factory=list)  # rozsah nešel projít → push se zastaví

    @property
    def blocked(self) -> bool:
        return bool(self.matches or self.errors)


def push_ranges(lines: Iterable[str], env: dict[str, str] | None = None) -> list[list[str]]:
    """Rozsahy revizí z hooku pre-push (stdin `lref lsha rref rsha`) nebo z pre-commitu."""
    env = dict(os.environ) if env is None else env
    out: list[list[str]] = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, _, remote_sha = parts
        if ZERO.match(local_sha):
            continue  # mazání větve – nic se neposílá
        if ZERO.match(remote_sha):
            out.append([local_sha, "--not", "--remotes"])
        else:
            out.append([f"{remote_sha}..{local_sha}"])
    if not out and env.get("PRE_COMMIT_TO_REF"):
        to_ref = env["PRE_COMMIT_TO_REF"]
        from_ref = env.get("PRE_COMMIT_FROM_REF", "")
        out.append(
            [f"{from_ref}..{to_ref}"]
            if from_ref and not ZERO.match(from_ref)
            else [to_ref, "--not", "--remotes"]
        )
    return out


def run_guard(
    repo: Path, lines: Iterable[str], config: Config, env: dict[str, str] | None = None
) -> GuardResult:
    from repo_doctor.checks.base import get_check
    from repo_doctor.checks.secrets import _to_finding

    git = Git(repo)
    with contextlib.suppress(ConfigError):  # neplatný .repo-doctor.toml nesmí vypnout kontrolu
        config = effective_for_repo(config, load_repo_overrides(repo))
    result = GuardResult()
    seen: set[tuple[str, str]] = set()
    for rng in push_ranges(lines, env):
        if len(rng) == 1 and ".." in rng[0]:
            base, _, tip = rng[0].partition("..")
            if base and not git.ok("cat-file", "-e", f"{base}^{{commit}}"):
                # remote má commit, který lokálně není (force push, nefetchnuto) → vše nové
                rng = [tip, "--not", "--remotes"]
        result.ranges.append(" ".join(rng))
        try:
            out = git.run(
                "log", "-p", "-U0", "--no-color", "--no-textconv", "--no-ext-diff",
                "--no-renames", "--format=%x00commit %H %ct", *rng, "--",
                timeout=120,
            )  # fmt: skip
        except GitError as err:
            result.errors.append(f"{' '.join(rng)}: {err.stderr.strip()[:200] or err}")
            continue
        for m in parse_log_patch(out.splitlines()):
            if (m.fingerprint, m.path) in seen:
                continue
            seen.add((m.fingerprint, m.path))
            result.matches.append(m)
    checks = [c for c in (get_check("secrets-history"), get_check("secrets-tree")) if c]
    allowed = {a.hash for a in config.allowlist}
    if checks and allowed:
        kept = [
            m for m in result.matches
            if not any(
                _to_finding(c, m, history=c.id == "secrets-history").fingerprint(repo.name)
                in allowed
                for c in checks
            )
        ]  # fmt: skip
        result.allowlisted = len(result.matches) - len(kept)
        result.matches = kept
    return result


def render(result: GuardResult) -> str:
    if result.errors and not result.matches:
        return "\n".join(
            [
                _("repo-doctor guard: push zastaven – nové commity nešlo zkontrolovat:"),
                *(f"  ! {e}" for e in result.errors[:5]),
                "",
                _(
                    "Zkus git fetch a push znovu. Výjimečně jde kontrolu obejít: git push --no-verify"
                ),
            ]
        )
    lines = [_("repo-doctor guard: push zastaven – v nových commitech jsou tajemství:")]
    for m in result.matches[:20]:
        commit = (m.commit or "")[:8]
        lines.append(f"  ▲ {m.kind}: {m.masked} · {m.path}:{m.line} · commit {commit}")
    if len(result.matches) > 20:
        lines.append(f"  {czech.more(len(result.matches) - 20)}")
    lines += [
        "",
        _("Co dál:"),
        _("  1. Tajemství z commitu odstraň (git commit --amend / git rebase -i) a zneplatni ho"),
        _("     u poskytovatele – i nepushnuté mohlo uniknout jinam."),
        _(
            "  2. Falešný poplach? Přidej ho do allowlistu (repo-doctor TUI, karta repa, klávesa a)."
        ),
        _("  3. Výjimečně jde kontrolu obejít: git push --no-verify"),
    ]
    return "\n".join(lines)
