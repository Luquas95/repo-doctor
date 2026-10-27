"""Lehká statická analýza: rizikové vzory ve zdrojácích, skriptech a Compose souborech.

Nic se nespouští ani neimportuje. Python se jen parsuje (`ast.parse`), ostatní jazyky se
čtou po řádcích jednoduchými regexy bez vnořených kvantifikátorů (odolné proti ReDoS).
Nález je vždy jeden na soubor a pravidlo, s prvním řádkem a počtem výskytů.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from typing import Any

import yaml

from repo_doctor.checks.base import Check, RepoContext, register
from repo_doctor.checks.quality import _is_test, _is_vendored
from repo_doctor.i18n import N_, _
from repo_doctor.models import Category, Finding, Severity

MAX_FILES = 3000  # horní mez čtených souborů na kontrolu (obří monorepa)
MAX_FINDINGS = 50
MAX_LINE = 1000  # delší řádky jsou minifikovaný kód; zároveň strop pro cenu regexů na cizím vstupu

Rule = tuple[Severity, str]
Hits = dict[str, list[int]]


def _files(repo: RepoContext, accept: Callable[[str], bool], *, tests: bool = False) -> list[str]:
    found = [
        f
        for f in repo.tracked_files
        if accept(f) and not _is_vendored(f) and (tests or not _is_test(f))
    ]
    return found[:MAX_FILES]


def _emit(
    check: Check, path: str, hits: Hits, rules: dict[str, Rule], prefix: str
) -> Iterable[Finding]:
    for rule, lines in sorted(hits.items()):
        severity, text = rules[rule]
        yield check.finding(
            _(text),
            severity=severity,
            path=path,
            line=min(lines),
            key=f"{prefix}:{rule}:{path}",
            count=len(lines),
        )


def _run(
    check: Check,
    repo: RepoContext,
    files: list[str],
    scan: Callable[[str, str], Hits],
    rules: dict[str, Rule],
    prefix: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        text = repo.read_text(path)
        if text is None:
            continue
        findings.extend(_emit(check, path, scan(path, text), rules, prefix))
        if len(findings) >= MAX_FINDINGS:
            findings = findings[:MAX_FINDINGS]
            findings.append(
                check.incomplete(
                    _("nálezů je příliš mnoho, vypsáno prvních {n}").format(n=MAX_FINDINGS)
                )
            )
            break
    return findings


# --------------------------------------------------------------------------- Python

PY_RULES: dict[str, Rule] = {
    "eval": (
        Severity.MEDIUM,
        N_("eval()/exec() s nekonstantním argumentem (spuštění cizího kódu)."),
    ),
    "shell": (Severity.MEDIUM, N_("Volání procesu přes shell=True (vstřikování příkazů).")),
    "os-system": (Severity.MEDIUM, N_("os.system()/os.popen() spouští příkaz přes shell.")),
    "pickle": (Severity.MEDIUM, N_("pickle/marshal.load() z nedůvěryhodných dat spustí kód.")),
    "yaml-load": (
        Severity.MEDIUM,
        N_("yaml.load() bez SafeLoader umí vytvářet libovolné objekty."),
    ),
    "tls-off": (Severity.MEDIUM, N_("verify=False vypíná ověření TLS certifikátu.")),
    "debug-mode": (Severity.MEDIUM, N_("Aplikace se spouští s debug=True (konzole na dálku).")),
    "debug-setting": (Severity.LOW, N_("DEBUG = True v nastavení, v produkci musí být vypnuté.")),
    "bare-except": (Severity.LOW, N_("Holé except: schová i KeyboardInterrupt a skutečné chyby.")),
    "debugger": (Severity.LOW, N_("Zapomenuté ladicí volání (breakpoint, pdb.set_trace).")),
    "mktemp": (Severity.LOW, N_("tempfile.mktemp() je náchylné na souběh, použij mkstemp().")),
}
_PICKLE = frozenset(
    {
        "pickle.load",
        "pickle.loads",
        "cPickle.load",
        "cPickle.loads",
        "marshal.load",
        "marshal.loads",
    }
)
_DEBUGGERS = frozenset({"breakpoint", "pdb.set_trace", "ipdb.set_trace", "pudb.set_trace"})


def _dotted(node: ast.expr) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _is_const(node: ast.expr | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def _safe_loader(call: ast.Call) -> bool:
    loader = next((k.value for k in call.keywords if k.arg == "Loader"), None)
    if loader is None and len(call.args) > 1:
        loader = call.args[1]
    return loader is not None and _dotted(loader).endswith("SafeLoader")


def python_hits(tree: ast.AST, *, settings: bool) -> Hits:
    hits: Hits = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            line = node.lineno
            if (
                name in ("eval", "exec")
                and node.args
                and not isinstance(node.args[0], ast.Constant)
            ):
                hits["eval"].append(line)
            if _is_const(kw.get("shell"), True):
                hits["shell"].append(line)
            if name in ("os.system", "os.popen"):
                hits["os-system"].append(line)
            if name in _PICKLE:
                hits["pickle"].append(line)
            if name == "yaml.load" and not _safe_loader(node):
                hits["yaml-load"].append(line)
            if _is_const(kw.get("verify"), False):
                hits["tls-off"].append(line)
            if name.endswith(".run") and _is_const(kw.get("debug"), True):
                hits["debug-mode"].append(line)
            if name in _DEBUGGERS:
                hits["debugger"].append(line)
            if name == "tempfile.mktemp":
                hits["mktemp"].append(line)
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            hits["bare-except"].append(node.lineno)
    if settings and isinstance(tree, ast.Module):
        for stmt in tree.body:
            if (
                isinstance(stmt, ast.Assign)
                and _is_const(stmt.value, True)
                and any(isinstance(t, ast.Name) and t.id == "DEBUG" for t in stmt.targets)
            ):
                hits["debug-setting"].append(stmt.lineno)
    return hits


def _scan_python(path: str, text: str) -> Hits:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return {}  # Python 2, šablony a podobně
    return python_hits(tree, settings="settings" in PurePosixPath(path).stem.lower())


@register
class PythonRisks(Check):
    id = "python-risks"
    title = N_("Rizikové vzory v Pythonu")
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        files = _files(repo, lambda f: f.endswith(".py"))
        return _run(self, repo, files, _scan_python, PY_RULES, "py")


# --------------------------------------------------------------------------- JavaScript

JS_RULES: dict[str, Rule] = {
    "eval": (Severity.MEDIUM, N_("eval() nebo new Function() spouští řetězec jako kód.")),
    "exec-concat": (
        Severity.MEDIUM,
        N_("exec()/execSync() se skládaným příkazem (vstřikování příkazů)."),
    ),
    "xss": (
        Severity.MEDIUM,
        N_("innerHTML = … nebo document.write vkládá řetězec jako HTML (XSS)."),
    ),
    "react-html": (
        Severity.LOW,
        N_("dangerouslySetInnerHTML: ověř, že vkládaný obsah nikdy nepochází od uživatele."),
    ),
    "tls-off": (
        Severity.MEDIUM,
        N_("Vypnuté ověření TLS certifikátu (rejectUnauthorized: false)."),
    ),
    "debugger": (Severity.LOW, N_("Zapomenutý příkaz debugger.")),
}
_JS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("eval", re.compile(r"(?<![\w.$])eval\s*\(|\bnew\s+Function\s*\(")),
    (
        "exec-concat",
        re.compile(r"\b(?:exec|execSync)\s*\(\s*(?:`[^`]*\$\{|[\w.$\"']+\s*\+)"),
    ),
    ("xss", re.compile(r"\.innerHTML\s*\+?=(?!=)|\bdocument\.write(?:ln)?\s*\(")),
    ("react-html", re.compile(r"dangerouslySetInnerHTML")),
    (
        "tls-off",
        re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0"),
    ),
    ("debugger", re.compile(r"^\s*debugger\s*;?\s*$")),
)
_JS_EXT = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")


def _scan_lines(
    text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...], comment: tuple[str, ...]
) -> Hits:
    hits: Hits = defaultdict(list)
    for number, line in enumerate(text.splitlines(), start=1):
        if len(line) > MAX_LINE or line.lstrip().startswith(comment):
            continue
        for rule, pattern in patterns:
            if pattern.search(line):
                hits[rule].append(number)
    return hits


def _scan_js(path: str, text: str) -> Hits:
    return _scan_lines(text, _JS_PATTERNS, ("//", "*", "/*"))


@register
class JsRisks(Check):
    id = "js-risks"
    title = N_("Rizikové vzory v JavaScriptu a TypeScriptu")
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        files = _files(
            repo, lambda f: f.endswith(_JS_EXT) and not f.endswith((".min.js", ".d.ts", ".min.mjs"))
        )
        return _run(self, repo, files, _scan_js, JS_RULES, "js")


# --------------------------------------------------------------------------- shell

SH_RULES: dict[str, Rule] = {
    "pipe-to-shell": (
        Severity.MEDIUM,
        N_("Stažený skript se rovnou pouští v shellu (… | sh), bez kontroly obsahu."),
    ),
    "chmod-777": (Severity.MEDIUM, N_("chmod 777 dává zápis úplně všem.")),
    "rm-var": (
        Severity.MEDIUM,
        N_("rm -rf s cestou začínající proměnnou: když je prázdná, maže se od kořene."),
    ),
    "eval": (Severity.MEDIUM, N_("eval s proměnnou spouští její obsah jako kód.")),
    "no-strict-mode": (
        Severity.LOW,
        N_("Skript nemá set -e/-u (ani pipefail), chyba uprostřed se přejde bez hlášení."),
    ),
}
_SH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "pipe-to-shell",
        re.compile(r"\b(?:curl|wget)\b[^|;&\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:ba|z|da)?sh\b"),
    ),
    ("chmod-777", re.compile(r"\bchmod\s+(?:-\w+\s+)*0?777\b")),
    (
        "rm-var",
        re.compile(
            r"\brm\s+(?:-\w+\s+)*-\w*[rR]\w*\s+(?:-\S+\s+)*[\"']?\$(?:\{[A-Za-z_]\w*\}|[A-Za-z_]\w*)[\"']?/"
        ),
    ),
    ("eval", re.compile(r"(?:^|[;&|]\s*)eval\s+[\"']?\$")),
)
_SHEBANG = re.compile(r"^#!\s*\S*(?:env\s+)?(?:ba|z|da|k)?sh\b")
_STRICT = re.compile(
    r"^\s*set\s+(?:-[a-zA-Z]*[eu]|-o\s+(?:errexit|nounset|pipefail))", re.MULTILINE
)
STRICT_MIN_LINES = 15  # krátké skripty nemusí mít ochranu


def _scan_shell(path: str, text: str) -> Hits:
    hits = _scan_lines(text, _SH_PATTERNS, ("#",))
    lines = text.splitlines()
    code = [ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if (
        lines
        and _SHEBANG.match(lines[0])
        and len(code) >= STRICT_MIN_LINES
        and not _STRICT.search(text)
    ):
        hits["no-strict-mode"].append(1)
    return hits


@register
class ShellRisks(Check):
    id = "shell-risks"
    title = N_("Rizikové vzory v shell skriptech")
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        files = _files(repo, lambda f: f.endswith((".sh", ".bash")), tests=True)
        return _run(self, repo, files, _scan_shell, SH_RULES, "sh")


# --------------------------------------------------------------------------- Compose

COMPOSE_RULES: dict[str, Rule] = {
    "privileged": (
        Severity.MEDIUM,
        N_("Kontejner běží s privileged: true (skoro root na hostiteli)."),
    ),
    "docker-sock": (
        Severity.MEDIUM,
        N_("Kontejner má připojený docker.sock, kdo ho ovládne, ovládne hostitele."),
    ),
    "host-network": (Severity.MEDIUM, N_("network_mode: host obchází izolaci sítě kontejneru.")),
    "cap-add": (
        Severity.MEDIUM,
        N_("cap_add: ALL nebo SYS_ADMIN dává kontejneru skoro root práva."),
    ),
    "db-exposed": (
        Severity.MEDIUM,
        N_("Port databáze nebo cache je otevřený na všech rozhraních (chybí 127.0.0.1:)."),
    ),
}
_DB_PORTS = frozenset({3306, 5432, 6379, 9200, 11211, 27017, 5984, 1433, 9042})
_COMPOSE_NAME = re.compile(r"^(docker-)?compose(\..+)?\.ya?ml$", re.IGNORECASE)


def _published(port: Any) -> tuple[int | None, bool]:
    """(zveřejněný port, je jen na loopbacku) z krátkého nebo dlouhého zápisu."""
    if isinstance(port, dict):
        host = port.get("published")
        local = str(port.get("host_ip", "")) in ("127.0.0.1", "::1", "localhost")
        return (int(str(host)) if str(host).isdigit() else None, local)
    if isinstance(port, int):
        return None, False  # samotný kontejnerový port se nezveřejňuje
    parts = str(port).split("/")[0].split(":")
    if len(parts) == 1:
        return None, False
    local = parts[0] in ("127.0.0.1", "::1", "[::1]", "localhost") and len(parts) == 3
    host = parts[-2]
    return (int(host) if host.isdigit() else None, local)


def compose_hits(doc: Any) -> dict[str, dict[str, list[int]]]:
    """{služba: {pravidlo: [1]}} (YAML nenese čísla řádků, `line` se nehlásí)."""
    result: dict[str, dict[str, list[int]]] = {}
    services = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services, dict):
        return result
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        hits: dict[str, list[int]] = defaultdict(list)
        if svc.get("privileged") is True:
            hits["privileged"].append(1)
        if str(svc.get("network_mode", "")) == "host":
            hits["host-network"].append(1)
        caps = svc.get("cap_add")
        if isinstance(caps, list) and {str(c).upper() for c in caps} & {"ALL", "SYS_ADMIN"}:
            hits["cap-add"].append(1)
        for volume in svc.get("volumes") or []:
            source = volume.get("source", "") if isinstance(volume, dict) else str(volume)
            if "docker.sock" in str(source):
                hits["docker-sock"].append(1)
        for port in svc.get("ports") or []:
            host, local = _published(port)
            if host in _DB_PORTS and not local:
                hits["db-exposed"].append(1)
        if hits:
            result[str(name)] = dict(hits)
    return result


@register
class ComposeRisks(Check):
    id = "compose-risks"
    title = N_("Rizikové nastavení Docker Compose")
    severity = Severity.MEDIUM
    category = Category.SECURITY

    def run(self, repo: RepoContext) -> list[Finding]:
        findings: list[Finding] = []
        for path in _files(
            repo, lambda f: bool(_COMPOSE_NAME.match(PurePosixPath(f).name)), tests=True
        ):
            text = repo.read_text(path)
            if text is None:
                continue
            try:
                doc = yaml.safe_load(text)
            except (yaml.YAMLError, RecursionError, ValueError):
                continue
            for service, rules in compose_hits(doc).items():
                for rule in rules:
                    severity, message = COMPOSE_RULES[rule]
                    findings.append(
                        self.finding(
                            _("Služba {service}: ").format(service=service) + _(message),
                            severity=severity,
                            path=path,
                            key=f"compose:{rule}:{path}:{service}",
                        )
                    )
        return findings[:MAX_FINDINGS]
