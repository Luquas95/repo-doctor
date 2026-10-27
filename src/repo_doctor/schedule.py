"""Plánovaný sken přes **uživatelský** systemd timer (nic jako root).

`~/.config/systemd/user/repo-doctor.{service,timer}` spouští `repo-doctor scan --scheduled`.
Bez systemd (Termux, macOS…) se plánování neinstaluje a vypíše se řádek pro cron.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from repo_doctor.i18n import _

Interval = Literal["daily", "weekly"]
UNIT = "repo-doctor"
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(Exception):
    """Plánování nejde nastavit; zpráva je pro uživatele."""


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base and os.path.isabs(base) else Path.home() / ".config"
    return root / "systemd" / "user"


def executable() -> str:
    found = shutil.which("repo-doctor")
    if found:
        return found
    if getattr(sys, "frozen", False):  # sestavená aplikace: sys.executable je přímo binárka
        return sys.executable
    return f"{sys.executable} -m repo_doctor"


def systemd_available(runner: Runner | None = None) -> bool:
    if not shutil.which("systemctl") or not Path("/run/systemd/system").is_dir():
        return False
    try:
        proc = (runner or _run)(["systemctl", "--user", "show-environment"])
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, check=False, stdin=subprocess.DEVNULL
    )


def parse_time(value: str) -> tuple[int, int]:
    m = _TIME.match(value.strip())
    if not m:
        raise ScheduleError(
            _("neplatný čas {value!r} – zadej HH:MM v rozsahu 00:00–23:59").format(value=value)
        )
    return int(m.group(1)), int(m.group(2))


def parse_calendar(value: str | None) -> tuple[Interval, str] | None:
    """Opak `on_calendar`: `Mon *-*-* 08:00:00` → ("weekly", "08:00")."""
    m = re.match(r"^(Mon )?\*-\*-\* (\d\d):(\d\d)(?::00)?$", (value or "").strip())
    if not m:
        return None
    return ("weekly" if m.group(1) else "daily"), f"{m.group(2)}:{m.group(3)}"


def describe(value: str | None) -> str:
    """Čitelný popis rozvrhu timeru (`týdně v pondělí 08:00`)."""
    parsed = parse_calendar(value)
    if parsed is None:
        return value or "?"
    interval, time = parsed
    return (
        _("týdně v pondělí {time}").format(time=time)
        if interval == "weekly"
        else _("denně {time}").format(time=time)
    )


def on_calendar(interval: Interval, time: str) -> str:
    hour, minute = parse_time(time)
    day = "Mon " if interval == "weekly" else ""
    return f"{day}*-*-* {hour:02d}:{minute:02d}:00"


def cron_line(interval: Interval, time: str) -> str:
    hour, minute = parse_time(time)
    dow = "1" if interval == "weekly" else "*"
    return f"{minute} {hour} * * {dow} {executable()} scan --scheduled"


def service_text() -> str:
    return (
        "[Unit]\n" + _("Description=repo-doctor – plánovaný sken repozitářů\n\n") + "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={executable()} scan --scheduled\n"
        "Nice=10\n"
        "IOSchedulingClass=idle\n"
    )


def timer_text(interval: Interval, time: str) -> str:
    return (
        "[Unit]\n" + _("Description=repo-doctor – plánovaný sken repozitářů\n\n") + "[Timer]\n"
        f"OnCalendar={on_calendar(interval, time)}\n"
        "Persistent=true\n"
        "RandomizedDelaySec=10min\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def install(
    interval: Interval = "weekly", time: str = "08:00", runner: Runner | None = None
) -> list[Path]:
    if interval not in ("daily", "weekly"):
        raise ScheduleError(_("interval musí být daily nebo weekly"))
    run = runner or _run
    if not systemd_available(run):
        raise ScheduleError(
            _(
                "Uživatelský systemd tu není k dispozici – plánování se nenainstaluje. "
                "Do crontab -e můžeš přidat:\n  {line}"
            ).format(line=cron_line(interval, time))
        )
    directory = unit_dir()
    directory.mkdir(parents=True, exist_ok=True)
    files = [directory / f"{UNIT}.service", directory / f"{UNIT}.timer"]
    files[0].write_text(service_text(), "utf-8")
    files[1].write_text(timer_text(interval, time), "utf-8")
    for cmd in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"],
    ):
        proc = run(cmd)
        if proc.returncode != 0:
            raise ScheduleError(f"{' '.join(cmd)} selhal: {proc.stderr.strip()[:200]}")
    return files


def remove(runner: Runner | None = None) -> bool:
    run = runner or _run
    files = [unit_dir() / f"{UNIT}.timer", unit_dir() / f"{UNIT}.service"]
    existed = any(f.exists() for f in files)
    if shutil.which("systemctl"):
        run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"])
    for f in files:
        f.unlink(missing_ok=True)
    if shutil.which("systemctl"):
        run(["systemctl", "--user", "daemon-reload"])
    return existed


@dataclass
class Status:
    installed: bool
    active: bool = False
    schedule: str | None = None
    next_run: str | None = None
    systemd: bool = True


def status(runner: Runner | None = None) -> Status:
    timer = unit_dir() / f"{UNIT}.timer"
    if not timer.exists():
        return Status(False, systemd=systemd_available(runner))
    m = re.search(r"^OnCalendar=(.+)$", timer.read_text("utf-8"), re.M)
    st = Status(True, schedule=m.group(1).strip() if m else None)
    run = runner or _run
    try:
        proc = run(
            [
                "systemctl",
                "--user",
                "show",
                f"{UNIT}.timer",
                "-p",
                "ActiveState",
                "-p",
                "NextElapseUSecRealtime",
            ]
        )
    except (OSError, subprocess.SubprocessError):
        st.systemd = False
        return st
    props = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    st.active = props.get("ActiveState") == "active"
    st.next_run = props.get("NextElapseUSecRealtime") or None
    return st
