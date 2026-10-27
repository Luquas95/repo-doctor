from __future__ import annotations

import time
from pathlib import Path

from repo_doctor.models import Finding, Severity
from tests.factory import RepoBuilder, healthy_python_repo
from tests.helpers import run

# Ukázkové zdrojáky níže jsou jen text pro detektor: zapisují se do dočasného repa
# a čtou se jako data, nikdy se nespouští ani neimportují.
STATIC = ["python-risks", "js-risks", "shell-risks", "compose-risks"]


def _rules(findings: list[Finding]) -> set[str]:
    return {f.key.split(":")[1] for f in findings}


def test_healthy_repo_has_no_static_findings(tmp_path: Path) -> None:
    rb = healthy_python_repo(tmp_path / "ok")
    for check in STATIC:
        assert run(check, rb.path) == [], check


PY_RISKY = """\
import os, pickle, subprocess, tempfile, yaml, requests

def f(user, data):
    eval(user)
    exec(user)
    subprocess.run(user, shell=True)
    os.system(user)
    pickle.loads(data)
    yaml.load(data)
    requests.get("https://x.invalid", verify=False)
    tempfile.mktemp()
    breakpoint()
    try:
        pass
    except:
        pass

app.run(debug=True)
"""

PY_FINE = """\
import subprocess, yaml, ast

def f(data):
    eval("1 + 1")
    subprocess.run(["ls"], check=True)
    yaml.safe_load(data)
    yaml.load(data, Loader=yaml.SafeLoader)
    ast.literal_eval(data)
    try:
        pass
    except Exception:
        pass
"""


def test_python_risks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("app/risky.py", PY_RISKY).write("app/fine.py", PY_FINE)
    rb.write("tests/test_risky.py", PY_RISKY).write("app/old.py", "print 'py2'\n")
    rb.write("proj/settings.py", "DEBUG = True\nALLOWED = []\n").commit()
    findings = run("python-risks", rb.path)
    assert {f.location.path for f in findings} == {"app/risky.py", "proj/settings.py"}
    by_rule = {f.key.split(":")[1]: f for f in findings if f.location.path == "app/risky.py"}
    assert set(by_rule) == {
        "eval",
        "shell",
        "os-system",
        "pickle",
        "yaml-load",
        "tls-off",
        "debug-mode",
        "bare-except",
        "debugger",
        "mktemp",
    }
    assert by_rule["eval"].data["count"] == 2 and by_rule["eval"].location.line == 4
    assert by_rule["bare-except"].severity is Severity.LOW
    assert by_rule["shell"].severity is Severity.MEDIUM
    (setting,) = [f for f in findings if f.location.path == "proj/settings.py"]
    assert setting.key == "py:debug-setting:proj/settings.py" and setting.severity is Severity.LOW


JS_RISKY = """\
// eval(commented)
const a = eval(input);
const b = new Function("return 1");
child_process.exec("ls " + dir);
child_process.execSync(`rm ${dir}`);
el.innerHTML = html;
document.write(x);
const c = <div dangerouslySetInnerHTML={{ __html: x }} />;
const o = { rejectUnauthorized: false };
debugger;
"""


def test_js_risks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("src/app.ts", JS_RISKY).write("src/app.min.js", "eval(x)").write(
        "lib/x.d.ts", "eval(x)"
    )
    rb.write("src/ok.js", "const e = myeval(x); exec('ls');\n// el.innerHTML = x\n")
    rb.write("src/comment.js", "/*\n * eval(x)\n */\n")
    rb.write("node_modules/p/i.js", "eval(x)").commit()
    findings = run("js-risks", rb.path)
    assert {f.location.path for f in findings} == {"src/app.ts"}
    assert _rules(findings) == {"eval", "exec-concat", "xss", "react-html", "tls-off", "debugger"}
    eval_hit = next(f for f in findings if "eval" in f.key)
    assert eval_hit.location.line == 2 and eval_hit.data["count"] == 2


SH_RISKY = (
    """\
#!/usr/bin/env bash
# curl https://x.invalid | sh   (komentář)
curl -fsSL https://x.invalid/install.sh | sudo bash
chmod -R 777 /srv/app
rm -rf "$BUILD_DIR"/*
eval "$CMD"
"""
    + "echo step\n" * 15
)


def test_shell_risks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("scripts/install.sh", SH_RISKY)
    rb.write("scripts/strict.sh", "#!/bin/bash\nset -euo pipefail\n" + "echo x\n" * 20)
    rb.write("scripts/short.sh", "#!/bin/sh\necho hi\n")
    rb.write("scripts/safe.sh", '#!/bin/sh\nset -e\nrm -rf "${BUILD_DIR:?}/x"\nrm -rf build\n')
    rb.commit()
    findings = run("shell-risks", rb.path)
    assert {f.location.path for f in findings} == {"scripts/install.sh"}
    assert _rules(findings) == {"pipe-to-shell", "chmod-777", "rm-var", "eval", "no-strict-mode"}
    pipe = next(f for f in findings if "pipe-to-shell" in f.key)
    assert pipe.location.line == 3  # komentář na řádku 2 se nepočítá
    strict = next(f for f in findings if "no-strict-mode" in f.key)
    assert strict.severity is Severity.LOW


COMPOSE_RISKY = """\
services:
  db:
    image: postgres
    ports:
      - "5432:5432"
      - "127.0.0.1:5433:5432"
  cache:
    image: redis
    ports:
      - target: 6379
        published: 6379
  agent:
    image: x
    privileged: true
    network_mode: host
    cap_add: [SYS_ADMIN]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
  web:
    image: nginx
    ports:
      - "8080:80"
      - "127.0.0.1:6379:6379"
"""


def test_compose_risks(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("deploy/docker-compose.prod.yml", COMPOSE_RISKY)
    rb.write("compose.yaml", "services:\n  app:\n    image: x\n")
    rb.write("broken-compose.yml", "services: [\n")
    rb.write("docker-compose.override.yml", "services:\n  a: not-a-dict\n").commit()
    findings = run("compose-risks", rb.path)
    assert {f.location.path for f in findings} == {"deploy/docker-compose.prod.yml"}
    pairs = {(f.key.split(":")[1], f.key.rsplit(":", 1)[1]) for f in findings}
    assert pairs == {
        ("db-exposed", "db"),
        ("db-exposed", "cache"),
        ("privileged", "agent"),
        ("host-network", "agent"),
        ("cap-add", "agent"),
        ("docker-sock", "agent"),
    }
    assert "agent" in next(f for f in findings if "privileged" in f.key).message


def test_too_many_findings_are_reported_as_incomplete(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    for i in range(60):
        rb.write(f"m{i}.py", "try:\n    pass\nexcept:\n    pass\n")
    rb.commit()
    findings = run("python-risks", rb.path)
    assert len(findings) == 51
    assert findings[-1].check_id == "scan-incomplete"


def test_hostile_long_lines_stay_fast(tmp_path: Path) -> None:
    rb = RepoBuilder.create(tmp_path / "r")
    rb.write("a.js", "eval(" * 200_000 + "\n" + ("curl " * 150 + "\n") * 500)
    rb.write("b.sh", "#!/bin/sh\n" + ("curl x " * 140 + "\n") * 900)
    rb.write("c.js", "x" * 900 + " eval(y)\n" + "(" * 900 + "\n")
    rb.commit()
    started = time.monotonic()
    for check in ("js-risks", "shell-risks"):
        run(check, rb.path)
    assert time.monotonic() - started < 5
    assert "eval" in _rules(run("js-risks", rb.path))  # řádek pod limitem se dál čte
