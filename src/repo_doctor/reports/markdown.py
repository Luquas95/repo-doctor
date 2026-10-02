"""Markdown report – pro uložení nebo vložení do issue."""

from __future__ import annotations

import re
from datetime import datetime

from repo_doctor.models import RepoResult, ScanResult, Severity
from repo_doctor.reports import local_time
from repo_doctor.scoring import band, gauge, score_label, sort_score


def _code(text: str) -> str:
    """Kódový span, který zachová i zpětné apostrofy v textu (a escapuje `|` pro tabulky)."""
    text = text.replace("|", "\\|").replace("\n", " ")
    fence = "`" * (max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").replace("`", "'")


def _counts(repo: RepoResult) -> str:
    c = repo.counts()
    return " ".join(f"{s.symbol}{c[s]}" for s in Severity)


def render(result: ScanResult, *, no_pulse_days: int = 90, now: datetime | None = None) -> str:
    s = result.summary(no_pulse_days, now)
    when = local_time(result.finished_at or result.started_at)
    lines = [
        "# repo-doctor – report",
        "",
        f"Sken {when}{' (offline)' if result.offline else ''}{' – **přerušený**' if result.cancelled else ''}.",
        "",
        "| repozitáře | ▲ HIGH | ◆ MED | ● LOW | zdraví |",
        "|---:|---:|---:|---:|---:|",
        f"| {s.repos} | {s.by_severity[Severity.HIGH]} | {s.by_severity[Severity.MEDIUM]} | "
        f"{s.by_severity[Severity.LOW]} | {s.health}/100 |",
        "",
    ]
    if result.warnings:
        lines += ["> **Upozornění**", ">"]
        lines += [f"> - {_cell(w)}" for w in result.warnings]
        lines.append("")
    lines += [
        "## Přehled",
        "",
        "| skóre | repozitář | pásmo | nálezy | hosting |",
        "|---:|---|---|---|---|",
    ]
    ordered = sorted(result.repos, key=lambda r: (sort_score(r.score), r.name))
    for r in ordered:
        vis = {"public": "◉ veřejné", "private": "○ privátní"}.get(r.visibility, "")
        host = f"{r.forge or '—'} {vis}".strip()
        lines.append(
            f"| {score_label(r.score)} {gauge(r.score)} | `{_cell(r.name)}` | {band(r, no_pulse_days, now).label} | "
            f"{_counts(r)} | {_cell(host)} |"
        )
    lines.append("")
    clean = [r for r in ordered if not r.findings and not r.errors]
    for r in ordered:
        if r in clean:
            continue
        lines += [f"## {_cell(r.name)} – {score_label(r.score)}/100", "", f"`{_cell(r.path)}`", ""]
        if not r.findings:
            lines += ["Bez nálezů. ✓", ""]
        else:
            lines += ["| severity | kontrola | nález | kde |", "|---|---|---|---|"]
            for f in sorted(r.findings, key=lambda f: (-f.severity.rank, f.check_id)):
                where = f.location.render()
                if f.snippet:
                    where = f"{where} · {_code(f.snippet)}" if where else _code(f.snippet)
                fix = " ✓" if f.fixable else ""
                lines.append(
                    f"| {f.severity.symbol} {f.severity.short} | `{f.check_id}`{fix} | {_cell(f.message)} | {_cell(where)} |"
                )
            lines.append("")
        if r.skipped:
            lines.append(
                "Přeskočeno: "
                + ", ".join(f"`{k}` ({_cell(v)})" for k, v in sorted(r.skipped.items()))
            )
            lines.append("")
        if r.errors:
            lines.append(
                "Chyby: " + ", ".join(f"`{k}`: {_cell(v)}" for k, v in sorted(r.errors.items()))
            )
            lines.append("")
        if r.allowlisted:
            lines += [f"Skryto allowlistem: {r.allowlisted}", ""]
    if clean:
        lines += ["## Bez nálezů ✓", "", ", ".join(f"`{_cell(r.name)}`" for r in clean), ""]
    lines += ["---", "✓ = opravitelné automaticky v TUI (`repo-doctor`, obrazovka Léčba).", ""]
    return "\n".join(lines)
