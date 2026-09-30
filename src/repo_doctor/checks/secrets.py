"""Tajemství v aktuálních souborech a v historii, commitnuté citlivé soubory."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import PurePosixPath

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.gitwrap import GitError, GitTimeout
from repo_doctor.models import Category, FileChange, Finding, Patch, Severity
from repo_doctor.secrets_scan import (
    SecretMatch,
    gitleaks_available,
    parse_log_patch,
    run_gitleaks,
    scan_text,
)


def _to_finding(check: Check, m: SecretMatch, *, history: bool) -> Finding:
    when = datetime.fromtimestamp(m.commit_ts, UTC) if m.commit_ts else None
    if history and m.commit:
        msg = f"{m.kind} v commitu {m.commit[:7]} · {m.path}"
    else:
        msg = f"{m.kind} v souboru {m.path}"
    return check.finding(
        msg,
        path=m.path,
        line=m.line or None,
        commit=m.commit if history else None,
        commit_date=when,
        snippet=m.masked,
        kind=m.kind,
        key=f"{m.rule}:{m.fingerprint}",
        rule=m.rule,
    )


@register
class SecretsTree(Check):
    id = "secrets-tree"
    title = "Tajemství v aktuálních souborech"
    severity = Severity.HIGH
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        if gitleaks_available():
            try:
                matches = run_gitleaks(
                    repo.path, history=False, timeout=repo.config.limits.history_timeout_s
                )
            except subprocess.TimeoutExpired:
                return [self.incomplete("gitleaks nestihl proběhnout v časovém limitu")]
            allowed = set(repo.all_files)
            matches = [m for m in matches if m.path in allowed]
        else:
            matches = []
            for rel in repo.all_files:
                text = repo.read_text(rel)
                if text:
                    matches.extend(scan_text(text, rel))
        seen: set[tuple[str, str]] = set()
        findings = []
        for m in matches:
            if (m.fingerprint, m.path) in seen:
                continue
            seen.add((m.fingerprint, m.path))
            findings.append(_to_finding(self, m, history=False))
        return findings


@register
class SecretsHistory(Check):
    id = "secrets-history"
    title = "Tajemství v historii commitů"
    severity = Severity.HIGH
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.head is None and not repo.git.branches():
            return []
        timeout = repo.config.limits.history_timeout_s
        complete = True
        if gitleaks_available():
            try:
                matches = run_gitleaks(repo.path, history=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return [self.incomplete("gitleaks nestihl projít historii v časovém limitu")]
        else:
            matches = []
            try:
                lines = repo.git.stream_lines(
                    "log",
                    "--all",
                    "-p",
                    "-U0",
                    "--no-color",
                    "--no-textconv",
                    "--no-ext-diff",
                    "--no-renames",
                    "--format=%x00commit %H %ct",
                    timeout=timeout,
                )
                matches.extend(parse_log_patch(lines))
            except GitTimeout:
                complete = False
            except GitError:
                return []
        # log jde od nejnovějšího: poslední výskyt = commit, který tajemství přidal
        by_fp: dict[str, SecretMatch] = {}
        for m in matches:
            by_fp[m.fingerprint] = m
        findings = [_to_finding(self, m, history=True) for m in by_fp.values()]
        if not complete:
            findings.append(self.incomplete(f"historie neprošla celá za {timeout:g} s"))
        return findings


SENSITIVE_NAMES = frozenset(
    {
        ".env",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials.json",
        "credentials",
        ".htpasswd",
        ".netrc",
        ".pgpass",
        "secrets.yml",
        "secrets.yaml",
        "service-account.json",
        "terraform.tfvars",
        ".git-credentials",
        ".npmrc.secret",
    }
)
SENSITIVE_EXT = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ovpn", ".asc.key")
SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".tmpl", ".defaults")
SAFE_PUBLIC = re.compile(r"(?i)(public|pub|cert|chain|fullchain|ca)[._-]?[^/]*\.pem$")


def is_sensitive_file(path: str) -> bool:
    name = PurePosixPath(path).name
    lowered = name.lower()
    if lowered.endswith(SAFE_SUFFIXES) or ".example" in lowered:
        return False
    if lowered in SENSITIVE_NAMES:
        return True
    if lowered.startswith(".env.") or lowered.endswith(".env"):
        return True
    if lowered.endswith(SENSITIVE_EXT):
        return not SAFE_PUBLIC.search(lowered)
    return False


@register
class EnvCommitted(Check):
    id = "env-committed"
    title = "Commitnutý citlivý soubor"
    severity = Severity.HIGH
    category = Category.SECURITY
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        return [
            self.finding(
                f"{path} je v gitu – soubor s tajemstvími nemá být verzovaný",
                path=path,
                key=path,
            )
            for path in repo.tracked_files
            if is_sensitive_file(path)
        ]

    def fix(self, repo: RepoContext, findings: list[Finding]) -> Patch | None:
        paths = sorted({f.location.path for f in findings if f.location.path})
        if not paths:
            return None
        changes = [
            FileChange(
                path=".gitignore",
                action="append",
                content="\n".join("/" + p for p in paths),
                header=f"# repo-doctor: citlivé soubory ({repo.now:%Y-%m-%d})",
                old=repo.read_text(".gitignore"),
            )
        ]
        changes += [FileChange(path=p, action="untrack", old=None) for p in paths]
        return Patch(
            check_id=self.id,
            title="Přestat verzovat citlivé soubory",
            summary="git rm --cached " + " ".join(paths) + " (soubory na disku zůstanou)",
            changes=changes,
            notes=[
                "Tajemství z těchto souborů zůstávají v historii – považuj je za prozrazená a rotuj je.",
            ],
        )
