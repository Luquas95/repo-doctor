from __future__ import annotations

import pytest

from repo_doctor.keymap import (
    ACTIONS,
    KeymapError,
    build_keymap,
    display_key,
    grouped,
    is_valid_key,
    normalize_key,
)


def test_defaults_have_no_collisions() -> None:
    km = build_keymap({})
    assert km["scan_all"] == "R"
    assert len(km) == len(ACTIONS)


def test_remap_ok() -> None:
    km = build_keymap({"scan_all": "F5", "detail_fix": "ctrl+f"})
    assert km["scan_all"] == "f5"
    assert km["detail_fix"] == "ctrl+f"


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"nope": "x"}, "neznámá akce"),
        ({"scan_all": "ctrl+"}, "neplatná klávesa"),
        ({"scan_all": "foo"}, "neplatná klávesa"),
        ({"scan_all": "esc"}, "vyhrazená"),
        ({"scan_all": "j"}, "kolize"),  # s pohybem
        ({"allowlist": "o"}, "kolize"),  # v rámci karty
        ({"clone": "t"}, "kolize"),  # s globální
    ],
)
def test_invalid(overrides: dict[str, str], needle: str) -> None:
    with pytest.raises(KeymapError) as exc:
        build_keymap(overrides)
    assert needle in str(exc.value)


def test_same_key_in_different_contexts_ok() -> None:
    build_keymap({"clone": "e"})  # e = export i upravit jinde, ale jiný kontext


def test_helpers() -> None:
    assert normalize_key("?") == "question_mark"
    assert normalize_key("Ctrl+Alt+X") == "alt+ctrl+X"
    assert display_key("question_mark") == "?"
    assert is_valid_key("alt+1") and is_valid_key("f12") and not is_valid_key("+")
    g = grouped()
    assert ("?", "nápověda") in g["Globální"]
    assert ("R", "sken") in g["Globální"]
    g2 = grouped({**build_keymap({"scan_all": "F5"})})
    assert ("f5", "sken") in g2["Globální"]
