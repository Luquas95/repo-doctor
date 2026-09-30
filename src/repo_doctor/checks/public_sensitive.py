"""Veřejné repo s konfigurací infrastruktury (privátní IP, Tailscale, inventáře)."""

from __future__ import annotations

import ipaddress
import re
from pathlib import PurePosixPath

from repo_doctor.checks.base import Check, RepoContext, SkipCheck, register
from repo_doctor.models import Category, Finding, Severity
from repo_doctor.secrets_scan import LOCKFILES

IPV4 = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
TS_HOST = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts\.net\b", re.IGNORECASE)
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
CONFIG_EXT = frozenset(
    {
        ".yml",
        ".yaml",
        ".ini",
        ".cfg",
        ".conf",
        ".toml",
        ".json",
        ".env",
        ".tf",
        ".tfvars",
        ".hcl",
        ".properties",
        ".sh",
        ".nix",
    }
)
INFRA_NAMES = re.compile(
    r"(?i)^(inventory([._-].*)?|hosts(\.ya?ml|\.ini)?|.*\.tfstate(\.backup)?|kubeconfig|ssh_config|wg\d*\.conf|"
    r"docker-compose.*\.ya?ml|compose\.ya?ml|ansible\.cfg)$"
)


def classify_ip(raw: str) -> str | None:
    try:
        ip = ipaddress.IPv4Address(raw)
    except ValueError:
        return None
    if ip in TAILSCALE_NET:
        return "adresy 100.x (Tailscale)"
    if ip.is_private and not ip.is_loopback and not ip.is_link_local and raw != "0.0.0.0":  # noqa: S104
        return "privátní IP adresy"
    return None


def scan_infra(text: str) -> set[str]:
    kinds: set[str] = set()
    for m in IPV4.finditer(text):
        kind = classify_ip(m.group(1))
        if kind:
            kinds.add(kind)
    if TS_HOST.search(text):
        kinds.add("hostname *.ts.net")
    return kinds


@register
class PublicSensitive(Check):
    id = "public-sensitive"
    title = "Veřejné repo obsahuje konfiguraci infrastruktury"
    severity = Severity.HIGH
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        if repo.visibility == "unknown":
            raise SkipCheck("viditelnost repa na hostingu neznámá")
        if repo.visibility != "public":
            return []
        findings: list[Finding] = []
        for path in repo.tracked_files:
            p = PurePosixPath(path)
            if p.name in LOCKFILES:
                continue
            infra_name = bool(INFRA_NAMES.match(p.name)) or path.startswith(".ssh/")
            if not infra_name and p.suffix.lower() not in CONFIG_EXT:
                continue
            text = repo.read_text(path) or ""
            kinds = scan_infra(text)
            if p.name.endswith((".tfstate", ".tfstate.backup")):
                kinds.add("stav Terraformu")
            if not kinds:
                continue
            findings.append(
                self.finding(
                    f"veřejné repo obsahuje {', '.join(sorted(kinds))} · {path}",
                    path=path,
                    key=path,
                )
            )
        return findings[:20]
