"""Vestavěný skener tajemství (regexy + entropie) a volitelné napojení na gitleaks.

Surová hodnota tajemství nikdy neopustí tento modul: výsledkem je `SecretMatch` s maskovanou
ukázkou a otiskem (sha256), podle kterého se nálezy deduplikují.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repo_doctor.gitwrap import git_env
from repo_doctor.masking import mask


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    pattern: re.Pattern[str]
    group: int = 0
    min_entropy: float | None = None
    keywords: tuple[str, ...] = ()


def _r(pattern: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(pattern, flags)


RULES: tuple[Rule, ...] = (
    Rule(
        "aws-access-key",
        "AWS access key",
        _r(r"\b((?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16})\b"),
        1,
        keywords=("AKIA", "ASIA", "ABIA", "ACCA"),
    ),
    Rule(
        "aws-secret-key",
        "AWS secret key",
        _r(r"(?i)aws_?secret_?(?:access_?)?key\W{0,5}[:=]\s*[\"']?([A-Za-z0-9/+=]{40})\b"),
        1,
        3.5,
        ("aws",),
    ),
    Rule(
        "github-token",
        "GitHub token",
        _r(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b"),
        1,
        keywords=("ghp_", "gho_", "ghu_", "ghs_", "ghr_"),
    ),
    Rule(
        "github-pat",
        "GitHub fine-grained token",
        _r(r"\b(github_pat_[A-Za-z0-9_]{60,255})\b"),
        1,
        keywords=("github_pat_",),
    ),
    Rule(
        "gitlab-token",
        "GitLab token",
        _r(r"\b(gl(?:pat|dt|rt|ptt|cbt)-[A-Za-z0-9_\-]{20,})"),
        1,
        keywords=("glpat-", "gldt-", "glrt-", "glptt-", "glcbt-"),
    ),
    Rule(
        "slack-token", "Slack token", _r(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})"), 1, keywords=("xox",)
    ),
    Rule(
        "slack-webhook",
        "Slack webhook",
        _r(r"(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{16,})"),
        1,
        keywords=("hooks.slack.com",),
    ),
    Rule(
        "anthropic-key",
        "Anthropic API klíč",
        _r(r"\b(sk-ant-[A-Za-z0-9]+-[A-Za-z0-9_\-]{32,})"),
        1,
        keywords=("sk-ant-",),
    ),
    Rule(
        "openai-key",
        "OpenAI API klíč",
        _r(r"\b(sk-(?:proj-|svcacct-|admin-)?(?!ant-)[A-Za-z0-9_\-]{32,})"),
        1,
        3.0,
        ("sk-",),
    ),
    Rule(
        "private-key",
        "Privátní klíč",
        _r(r"(-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----)"),
        1,
        keywords=("PRIVATE KEY",),
    ),
    Rule(
        "jwt",
        "JWT",
        _r(r"\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"),
        1,
        keywords=("eyJ",),
    ),
    Rule(
        "connection-string",
        "Connection string s heslem",
        _r(
            r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqps?|mssql|sqlserver)://[^:/\s@\"']+:([^@\s\"'/]{4,})@"
        ),
        1,
        keywords=("://",),
    ),
    Rule(
        "generic-secret",
        "Obecné tajemství",
        _r(
            r"(?i)\b(?:api[_-]?key|apikey|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|"
            r"private[_-]?token|password|passwd|secret|token)\b[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,200})[\"']"
        ),
        1,
        3.5,
        ("key", "secret", "token", "pass"),
    ),
)

LOCKFILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "go.sum",
        "composer.lock",
        "Gemfile.lock",
        "flake.lock",
        "bun.lockb",
    }
)
FIXTURE_DIRS = frozenset(
    {"fixtures", "__fixtures__", "testdata", "__snapshots__", "snapshots", "cassettes"}
)
SKIP_EXT = (".min.js", ".map", ".snap", ".svg", ".lock")
PLACEHOLDER = re.compile(
    r"(?i)(example|sample|dummy|placeholder|changeme|change_me|your[_-]|xxxx|\*\*\*\*|<[^>]*>|\$\{|\{\{|"
    r"redacted|fake|test[_-]?key|todo|replace)"
)
ALLOW_MARKERS = ("gitleaks:allow", "repo-doctor:allow")


@dataclass(frozen=True)
class SecretMatch:
    rule: str
    kind: str
    masked: str
    fingerprint: str
    path: str
    line: int
    commit: str | None = None
    commit_ts: int | None = None


def entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def is_excluded_path(path: str) -> bool:
    p = PurePosixPath(path)
    if p.name in LOCKFILES or p.name.endswith(SKIP_EXT):
        return True
    return any(part in FIXTURE_DIRS for part in p.parts[:-1])


def _looks_placeholder(value: str) -> bool:
    if PLACEHOLDER.search(value):
        return True
    return len(set(value)) <= 3


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _first_match(rule: Rule, line: str) -> str | None:
    for m in rule.pattern.finditer(line):
        value = m.group(rule.group)
        if rule.id != "private-key" and _looks_placeholder(value):
            continue
        if rule.min_entropy is not None and entropy(value) < rule.min_entropy:
            continue
        if rule.id == "generic-secret" and value.startswith(
            ("$", "%", "os.", "env.", "process.", "/")
        ):
            continue
        return value
    return None


def scan_line(line: str, path: str, lineno: int) -> Iterator[SecretMatch]:
    """Nejvýš jeden nález na řádek; specifická pravidla mají přednost před obecným."""
    if any(marker in line for marker in ALLOW_MARKERS):
        return
    lowered = line.lower()
    for rule in RULES:
        if rule.keywords and not any(k.lower() in lowered for k in rule.keywords):
            continue
        value = _first_match(rule, line)
        if value is not None:
            yield SecretMatch(
                rule=rule.id,
                kind=rule.kind,
                masked=mask(value),
                fingerprint=fingerprint(value),
                path=path,
                line=lineno,
            )
            return


def scan_text(text: str, path: str) -> list[SecretMatch]:
    if is_excluded_path(path):
        return []
    found: list[SecretMatch] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if len(line) > 4000:  # minifikované řádky
            continue
        found.extend(scan_line(line, path, i))
    return found


@dataclass
class HistoryScan:
    matches: list[SecretMatch]
    complete: bool


def parse_log_patch(lines: Iterable[str]) -> Iterator[SecretMatch]:
    """Parsuje `git log -p -U0 --format=%x00commit %H %ct` a skenuje přidané řádky."""
    commit: str | None = None
    commit_ts: int | None = None
    path: str | None = None
    lineno = 0
    for raw in lines:
        if raw.startswith("\0commit "):
            parts = raw[8:].split()
            commit = parts[0] if parts else None
            commit_ts = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            path = None
            continue
        if raw.startswith("+++ "):
            target = raw[4:]
            path = (
                None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            )
            if path and is_excluded_path(path):
                path = None
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and path is not None:
            for match in scan_line(raw[1:], path, lineno):
                yield SecretMatch(**{**match.__dict__, "commit": commit, "commit_ts": commit_ts})
            lineno += 1


# ---------------------------------------------------------------------- gitleaks
def gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


def _exec(cmd: list[str], timeout: float) -> None:
    subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=git_env(),
        stdin=subprocess.DEVNULL,
    )


def run_gitleaks(repo: Path, *, history: bool, timeout: float) -> list[SecretMatch]:
    """Spustí gitleaks a výsledky okamžitě maskuje. Report jde do soukromého dočasného souboru."""
    with tempfile.TemporaryDirectory(prefix="repo-doctor-gl-") as tmp:
        report = Path(tmp) / "report.json"
        cmd = [
            "gitleaks",
            "detect",
            "--source",
            str(repo),
            "--report-format",
            "json",
            "--report-path",
            str(report),
            "--no-banner",
            "--exit-code",
            "0",
            "--log-level",
            "error",
        ]
        if not history:
            cmd.append("--no-git")
        _exec(cmd, timeout)
        try:
            data = json.loads(report.read_text("utf-8") or "[]")
        except (OSError, json.JSONDecodeError):
            return []
    matches = []
    for item in data if isinstance(data, list) else []:
        secret = str(item.get("Secret") or item.get("Match") or "")
        date = str(item.get("Date") or "")
        ts: int | None = None
        if date:
            from datetime import datetime

            try:
                ts = int(datetime.fromisoformat(date.replace("Z", "+00:00")).timestamp())
            except ValueError:
                ts = None
        file = str(item.get("File", ""))
        if file.startswith(str(repo)):
            file = file[len(str(repo)) :].lstrip("/")
        matches.append(
            SecretMatch(
                rule=str(item.get("RuleID", "gitleaks")),
                kind=str(item.get("Description") or item.get("RuleID") or "tajemství"),
                masked=mask(secret),
                fingerprint=fingerprint(secret),
                path=file,
                line=int(item.get("StartLine") or 0),
                commit=str(item.get("Commit")) if item.get("Commit") else None,
                commit_ts=ts,
            )
        )
        del secret
    return matches
