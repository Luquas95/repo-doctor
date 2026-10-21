from __future__ import annotations

import ast
import os
import re
import string
import subprocess
import sys
from pathlib import Path

import pytest

from repo_doctor import cli, czech, i18n, i18n_tools
from repo_doctor.i18n import _, parse_po

ROOT = Path(__file__).parent.parent
PACKAGE = ROOT / "src" / "repo_doctor"
# moduly přeložené ve fázi 1 (#33) – žádný český text mimo `_()`
PHASE1 = [
    *sorted((PACKAGE / "tui").rglob("*.py")),
    *(PACKAGE / f"{n}.py" for n in ("cli", "keymap", "models", "scoring", "czech", "tools")),
]
CZECH = re.compile(r"[ěščřžýáíéóůúňťďĚŠČŘŽÝÁÍÉÓŮÚŇŤĎ]")


def test_catalog_is_complete_and_has_no_obsolete_entries() -> None:
    todo, obsolete = i18n_tools.missing("en")
    assert todo == [], "přelož: uv run python -m repo_doctor.i18n_tools"
    assert obsolete == []


def test_translations_keep_placeholders() -> None:
    fields = lambda text: {f for _, f, _, _ in string.Formatter().parse(text) if f}  # noqa: E731
    for msgid, msgstr in i18n.catalog("en").items():
        if "{" not in msgid:
            continue
        # překlad smí placeholder vynechat (jiný slovosled), ale ne přidat nový
        assert fields(msgstr) <= fields(msgid), (msgid, msgstr)


def test_phase1_modules_have_no_untranslated_czech() -> None:
    offenders = []
    for path in PHASE1:
        tree = ast.parse(path.read_text("utf-8"))
        docs: set[int] = set()
        wrapped: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docs.add(id(first.value))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"_", "N_"}
            ):
                wrapped.update(id(a) for a in ast.walk(node))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs | wrapped
                and CZECH.search(node.value)
                and node.value not in {"čeština"}  # název jazyka se nepřekládá
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}")
    assert offenders == []


def test_parse_po() -> None:
    text = (
        'msgid ""\nmsgstr "Content-Type: text/plain\\n"\n\n'
        'msgid "jedna"\nmsgstr "one"\n\n'
        'msgid ""\n"víc\\n"\n"řádků"\nmsgstr ""\n"more\\n"\n"lines"\n\n'
        '#, fuzzy\nmsgid "nejisté"\nmsgstr "unsure"\n\n'
        'msgid "prázdné"\nmsgstr ""\n\n'
        'msgid "uvozovky \\"x\\""\nmsgstr "quotes \\"x\\""\n'
    )
    assert parse_po(text) == {
        "jedna": "one",
        "víc\nřádků": "more\nlines",
        'uvozovky "x"': 'quotes "x"',
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cs_CZ.UTF-8", "cs"),
        ("sk_SK", "cs"),
        ("en_US.UTF-8", "en"),
        ("de_DE@euro", "en"),
        ("cs", "cs"),
        ("auto", None),
        ("C", None),
        ("", None),
    ],
)
def test_normalize(value: str, expected: str | None) -> None:
    assert i18n.normalize(value) == expected


def test_detect_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = tmp_path / "repo-doctor" / "config.toml"
    cfg.parent.mkdir()
    assert i18n.detect([], {"LANG": "cs_CZ.UTF-8"}) == "cs"
    assert i18n.detect([], {"LANG": "C"}) == "en"
    assert i18n.detect([], {}) == "en"
    cfg.write_text('[ui]\nlanguage = "cs"\n')
    assert i18n.detect([], {"LANG": "en_US"}) == "cs"  # config má přednost před LANG
    cfg.write_text('[ui]\nlanguage = "auto"\n')
    assert i18n.detect([], {"LANG": "en_US"}) == "en"
    assert i18n.detect([], {"REPO_DOCTOR_LANG": "en", "LANG": "cs_CZ"}) == "en"
    assert i18n.detect(["--lang", "cs"], {"REPO_DOCTOR_LANG": "en"}) == "cs"
    assert i18n.detect(["scan", "--lang=en"], {}) == "en"
    cfg.write_text("neplatné toml [")
    assert i18n.detect([], {"LANG": "cs_CZ"}) == "cs"


def test_runtime_switch_and_plural() -> None:
    assert _("Nastavení") == "Nastavení"
    assert czech.repos(3) == "3 repa" and czech.more(7) == "… a 7 dalších"
    i18n.set_language("en")
    assert _("Nastavení") == "Settings"
    assert _("neexistující text") == "neexistující text"  # bez překladu zůstane originál
    assert czech.repos(1) == "1 repo" and czech.repos(3) == "3 repos"
    assert czech.more(2) == "… and 2 more"


def test_cli_lang_option_is_consumed(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--lang", "en", "config", "path"]) == 0
    assert i18n.language() == "en"
    assert capsys.readouterr().out.strip().endswith("config.toml")


def _run_en(code: str, home: Path) -> str:
    env = {
        **os.environ,
        "REPO_DOCTOR_LANG": "en",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
    }
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT, check=True
    )
    return proc.stdout


def test_english_cli_help(tmp_path: Path) -> None:
    out = _run_en("from repo_doctor import cli; cli.main(['--help'])", tmp_path)
    assert "Audit and maintenance of git repositories" in out
    assert "Scans repositories and prints a report." in out


def test_english_tui(tmp_path: Path) -> None:
    code = """
import asyncio
from tests.tui_helpers import make_app, screen_text
from pathlib import Path
import tempfile

async def main():
    app = make_app(Path(tempfile.mkdtemp()))
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        print(screen_text(app))
        await pilot.press("question_mark")
        await pilot.pause()
        print(screen_text(app))

asyncio.run(main())
"""
    out = _run_en(code, tmp_path)
    for needle in ("TRIAGE", "scan all repos", "repositories", "CRITICAL", "GLOBAL", "quit"):
        assert needle in out, needle
    assert "skenovat" not in out and "Nastavení" not in out


def test_render_po_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    messages = {"jedna": ["a.py:1"], 'víc\nřádků "x"\n': ["b.py:2"], "bez překladu": ["c.py:3"]}
    translations = {"jedna": "one", 'víc\nřádků "x"\n': 'more\nlines "x"\n'}
    text = i18n_tools.render_po("en", messages, translations)
    assert "#: a.py:1" in text
    assert parse_po(text) == translations
    monkeypatch.setattr(i18n_tools, "LOCALE_DIR", tmp_path)
    monkeypatch.setattr(i18n_tools, "extract", lambda: messages)
    i18n_tools.update("xx")
    assert parse_po((tmp_path / "xx.po").read_text()) == {}  # nový katalog bez překladů
    assert i18n_tools.missing("xx")[0] == sorted(messages)


def test_extract_finds_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "pkg" / "m.py"
    src.parent.mkdir()
    src.write_text('from x import _, N_\nA = N_("konstanta")\nprint(_("ahoj"), _(proměnná))\n')
    monkeypatch.setattr(i18n_tools, "PACKAGE", src.parent)
    found = i18n_tools.extract([src])
    assert set(found) == {"konstanta", "ahoj"} and found["ahoj"] == ["pkg/m.py:3"]
