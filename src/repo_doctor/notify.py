"""Upozornění plánovaného skenu: změny proti minulému skenu a jejich doručení.

Upozorňuje se jen na změny (nové HIGH nálezy, nově veřejné repo s citlivým obsahem, nové
zranitelné závislosti). Text je krátký: jen názvy rep a počty – nikdy tajemství ani cesty
k souborům s nálezy.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from repo_doctor import czech, netpolicy, paths
from repo_doctor.config import NotifyConfig
from repo_doctor.models import RepoResult, ScanResult, Severity

SENSITIVE_PUBLIC = "public-sensitive"
VULN = "deps-vulnerable"


@dataclass
class Changes:
    new_high: dict[str, int] = field(default_factory=dict)  # repo → počet nových HIGH
    newly_public: list[str] = field(default_factory=list)  # nově veřejné repo s citlivým obsahem
    new_vulns: dict[str, int] = field(default_factory=dict)  # repo → nové zranitelné závislosti

    def __bool__(self) -> bool:
        return bool(self.new_high or self.newly_public or self.new_vulns)

    def text(self) -> str:
        def repos(items: list[str]) -> str:
            shown = ", ".join(items[:3])
            return shown + (f" {czech.more(len(items) - 3)[2:]}" if len(items) > 3 else "")

        parts: list[str] = []
        if self.new_high:
            n = sum(self.new_high.values())
            what = czech.plural(n, "nový HIGH nález", "nové HIGH nálezy", "nových HIGH nálezů")
            parts.append(f"{n} {what} ({repos(sorted(self.new_high))})")
        if self.newly_public:
            parts.append(
                f"nově veřejné repo s citlivým obsahem: {repos(sorted(self.newly_public))}"
            )
        if self.new_vulns:
            n = sum(self.new_vulns.values())
            what = czech.plural(
                n,
                "nová zranitelná závislost",
                "nové zranitelné závislosti",
                "nových zranitelných závislostí",
            )
            parts.append(f"{n} {what} ({repos(sorted(self.new_vulns))})")
        return "; ".join(parts)


def _fingerprints(repo: RepoResult, pred: Callable[[str, Severity], bool]) -> set[str]:
    return {f.fingerprint(repo.name) for f in repo.findings if pred(f.check_id, f.severity)}


def diff(previous: ScanResult | None, current: ScanResult) -> Changes:
    """Co je nového proti minulému skenu. Bez minulého skenu se neupozorňuje (jen se uloží)."""
    changes = Changes()
    if previous is None:
        return changes
    before = {r.path: r for r in previous.repos}
    for repo in current.repos:
        old = before.get(repo.path)
        if old is None:
            continue  # nové repo – upozornit až na změny při dalším běhu

        def high(cid: str, sev: Severity) -> bool:
            return sev is Severity.HIGH

        def vuln(cid: str, sev: Severity) -> bool:
            return cid == VULN

        new_high = _fingerprints(repo, high) - _fingerprints(old, high)
        if new_high:
            changes.new_high[repo.name] = len(new_high)
        new_vulns = _fingerprints(repo, vuln) - _fingerprints(old, vuln)
        if new_vulns:
            changes.new_vulns[repo.name] = len(new_vulns)
        if (
            repo.visibility == "public"
            and old.visibility != "public"
            and any(f.check_id == SENSITIVE_PUBLIC for f in repo.findings)
        ):
            changes.newly_public.append(repo.name)
    return changes


# ---------------------------------------------------------------------- kanály
@dataclass
class Delivery:
    channel: str
    ok: bool
    detail: str = ""


def _graphical_session() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def send_desktop(title: str, text: str) -> Delivery:
    exe = shutil.which("notify-send")
    if not exe or not _graphical_session():
        return Delivery("desktop", False, "notify-send nebo grafická relace nejsou k dispozici")
    try:
        subprocess.run(
            [exe, "--app-name=repo-doctor", "--", title, text],
            check=True,
            timeout=10,
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError) as err:
        return Delivery("desktop", False, type(err).__name__)
    return Delivery("desktop", True)


def send_ntfy(
    cfg: NotifyConfig,
    title: str,
    text: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Delivery:
    url = cfg.ntfy_url or ""
    if url.startswith("http://") and not netpolicy.policy().allows_http_url(url):
        return Delivery("ntfy", False, "http:// jen pro host z allow_http_hosts")
    if not url.startswith(("https://", "http://")):
        return Delivery("ntfy", False, "neplatná URL")
    headers = {"Title": title, "Tags": "warning", "Priority": "high"}
    try:
        from repo_doctor.forges.tokens import TokenError, resolve_token

        token = resolve_token(cfg)
    except TokenError as err:
        return Delivery("ntfy", False, f"token: {err}")
    if token is not None:
        headers["Authorization"] = f"Bearer {token.reveal()}"
    try:
        with httpx.Client(timeout=15, transport=transport, follow_redirects=False) as client:
            resp = client.post(url, content=text.encode(), headers=headers)
    except httpx.HTTPError as err:
        return Delivery("ntfy", False, type(err).__name__)
    return Delivery("ntfy", resp.status_code < 300, f"HTTP {resp.status_code}")


def send_email(address: str, title: str, text: str) -> Delivery:
    exe = shutil.which("sendmail") or next(
        (p for p in ("/usr/sbin/sendmail", "/usr/lib/sendmail") if Path(p).is_file()), None
    )
    if not exe:
        return Delivery("email", False, "sendmail není nainstalovaný")
    message = (
        f"To: {address}\nSubject: {title}\nContent-Type: text/plain; charset=utf-8\n\n{text}\n"
    )
    try:
        subprocess.run(
            [exe, "-t", "-oi"], input=message.encode(), check=True, timeout=30, capture_output=True
        )
    except (subprocess.SubprocessError, OSError) as err:
        return Delivery("email", False, type(err).__name__)
    return Delivery("email", True)


def deliver(cfg: NotifyConfig, text: str, *, title: str = "repo-doctor") -> list[Delivery]:
    out: list[Delivery] = []
    if cfg.desktop:
        out.append(send_desktop(title, text))
    if cfg.ntfy_url:
        out.append(send_ntfy(cfg, title, text))
    if cfg.email:
        out.append(send_email(cfg.email, title, text))
    return out


# ---------------------------------------------------------------------- stav posledního běhu
@dataclass
class RunState:
    ts: str
    repos: int
    changes: str  # text upozornění, nebo "" (beze změn)
    deliveries: list[dict[str, object]] = field(default_factory=list)


def state_file() -> Path:
    return paths.data_dir() / "scheduled-last.json"


def save_state(result: ScanResult, changes: Changes, deliveries: list[Delivery]) -> RunState:
    state = RunState(
        ts=(result.finished_at or datetime.now(UTC)).isoformat(),
        repos=len(result.repos),
        changes=changes.text() if changes else "",
        deliveries=[asdict(d) for d in deliveries],
    )
    file = state_file()
    paths.ensure_private_dir(file.parent)
    file.write_text(json.dumps(asdict(state), ensure_ascii=False), "utf-8")
    return state


def load_state() -> RunState | None:
    try:
        data = json.loads(state_file().read_text("utf-8"))
        return RunState(**data)
    except (OSError, ValueError, TypeError):
        return None
