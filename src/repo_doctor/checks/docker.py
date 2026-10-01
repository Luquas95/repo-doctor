"""Hygiena Dockerfile. Automaticky opravitelné je jen chybějící .dockerignore."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from repo_doctor import templates
from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.models import Category, FileChange, Finding, Patch, Severity
from repo_doctor.secrets_scan import _looks_placeholder, entropy

NOT_SECRET_SUFFIX = re.compile(r"(?i)_(file|url|uri|path|dir|endpoint|host|name|user|username)$")
SECRET_NAME = re.compile(r"(?i)(pass(word)?|secret|token|api[_-]?key|private[_-]?key|credential)")


def is_dockerfile(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name == "dockerfile"
        or name.startswith("dockerfile.")
        or name.endswith(".dockerfile")
        or name == "containerfile"
    )


def _logical_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if not buf:
            start = i
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        buf += stripped
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


@register
class DockerHygiene(Check):
    id = "docker-hygiene"
    title = "Hygiena Dockerfile"
    severity = Severity.MEDIUM
    category = Category.SECURITY
    fixable = True

    def run(self, repo: RepoContext) -> list[Finding]:
        dockerfiles = [f for f in repo.tracked_files if is_dockerfile(f)]
        if not dockerfiles:
            return []
        findings: list[Finding] = []
        for path in dockerfiles:
            text = repo.read_text(path)
            if text is not None:
                findings.extend(self._analyze(path, text))
        if not repo.exists(".dockerignore"):
            findings.append(
                self.finding(
                    "chybí .dockerignore – do build contextu se dostane .git, .env a další",
                    severity=Severity.LOW,
                    path=".dockerignore",
                    key="dockerignore",
                    fixable=True,
                )
            )
        return findings

    def fix(self, repo: RepoContext, findings: list[Finding]) -> Patch | None:
        if not any(f.key == "dockerignore" for f in findings):
            return None
        content = templates.render(
            "dockerignore", templates.DOCKERIGNORE, repo.config.templates_dir
        )
        return Patch(
            check_id=self.id,
            title="Přidat .dockerignore",
            summary=".git, .env, build výstupy",
            changes=[
                FileChange(
                    path=".dockerignore",
                    action="create",
                    content=content,
                    old=repo.read_text(".dockerignore"),
                )
            ],
            notes=[
                "Úpravy Dockerfile (tagy, USER, ENV) jsou jen návrh v reportu – proveď je ručně."
            ],
        )

    def _analyze(self, path: str, text: str) -> list[Finding]:
        findings: list[Finding] = []
        stages: set[str] = set()
        final_user: str | None = None
        has_from = False
        for lineno, line in _logical_lines(text):
            instr, _, rest = line.partition(" ")
            instr = instr.upper()
            rest = rest.strip()
            if instr == "FROM":
                has_from = True
                final_user = None
                args = [a for a in rest.split() if not a.startswith("--")]
                if not args:
                    continue
                image = args[0]
                if len(args) >= 3 and args[1].lower() == "as":
                    stages.add(args[2].lower())
                if image.lower() in stages or image == "scratch" or "$" in image:
                    continue
                name = image.split("@", 1)[0]
                tag = name.rsplit(":", 1)[1] if ":" in name.rsplit("/", 1)[-1] else None
                if "@" in image:
                    continue
                if tag is None or tag == "latest":
                    findings.append(
                        self.finding(
                            f"FROM {image} – {'tag :latest' if tag else 'bez tagu'}, build není reprodukovatelný",
                            path=path,
                            line=lineno,
                            key=f"{path}:from:{image}",
                        )
                    )
            elif instr == "USER":
                final_user = rest.split()[0] if rest else None
            elif instr in {"ENV", "ARG"}:
                for name, value in _assignments(rest):
                    if (
                        SECRET_NAME.search(name)
                        and not NOT_SECRET_SUFFIX.search(name)
                        and value
                        and not value.startswith(("$", "/", "./"))
                        and "://" not in value
                        and not _looks_placeholder(value)
                        and entropy(value) > 2.5
                    ):
                        findings.append(
                            self.finding(
                                f"{instr} {name} obsahuje tajemství – zůstane ve vrstvách image",
                                severity=Severity.HIGH,
                                path=path,
                                line=lineno,
                                key=f"{path}:{instr}:{name}",
                            )
                        )
            elif instr == "ADD" and re.search(r"\bhttps?://", rest):
                findings.append(
                    self.finding(
                        "ADD z URL – použij RUN curl s ověřením kontrolního součtu",
                        path=path,
                        line=lineno,
                        key=f"{path}:add:{lineno}",
                    )
                )
        if has_from and (final_user is None or final_user.split(":")[0] in {"root", "0"}):
            findings.append(
                self.finding(
                    "kontejner běží pod rootem (ve finální fázi chybí USER)",
                    path=path,
                    key=f"{path}:user",
                )
            )
        # úpravy Dockerfile jsou jen návrh – automaticky opravitelný je pouze .dockerignore
        return [f.model_copy(update={"fixable": False}) for f in findings]


def _assignments(rest: str) -> list[tuple[str, str]]:
    if "=" not in rest.split(" ", 1)[0]:
        # ENV KEY value (starší syntaxe)
        parts = rest.split(None, 1)
        return [(parts[0], parts[1].strip("\"'") if len(parts) > 1 else "")] if parts else []
    result = []
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S*)", rest):
        result.append((m.group(1), m.group(2).strip("\"'")))
    return result
