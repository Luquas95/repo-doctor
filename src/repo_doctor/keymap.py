"""Definice klávesových zkratek (jediný zdroj pravdy pro TUI, nápovědu i README).

Uživatel může akce přemapovat v `config.toml`, sekce `[keys]` (akce → klávesa).
Neplatné nebo kolidující mapování je chyba se srozumitelným popisem.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

CONTEXTS: dict[str, str] = {
    "global": "Globální",
    "nav": "Pohyb",
    "dashboard": "Přehled (triáž)",
    "detail": "Karta repa",
    "fix": "Léčba",
    "folders": "Složky",
    "forges": "Hostingy",
    "remote": "Vzdálená repa",
    "settings": "Nastavení",
    "export": "Export",
}


@dataclass(frozen=True)
class KeyAction:
    id: str
    key: str
    context: str
    description: str
    action: str
    show: bool = True
    label: str = ""  # jak klávesu zobrazit (výchozí: key)

    @property
    def display(self) -> str:
        return self.label or display_key(self.key)


def _a(
    id: str,
    key: str,
    ctx: str,
    desc: str,
    action: str | None = None,
    *,
    show: bool = True,
    label: str = "",
) -> KeyAction:
    return KeyAction(id, key, ctx, desc, action or id, show, label)


ACTIONS: tuple[KeyAction, ...] = (
    # globální
    _a("help", "question_mark", "global", "nápověda", label="?"),
    _a("command_palette", "ctrl+p", "global", "příkazová paleta", show=False),
    _a("screen_overview", "1", "global", "přehled", "switch_screen_n(1)", show=False),
    _a("screen_detail", "2", "global", "karta repa", "switch_screen_n(2)", show=False),
    _a("screen_fix", "3", "global", "léčba", "switch_screen_n(3)", show=False),
    _a("screen_folders", "4", "global", "složky", "switch_screen_n(4)"),
    _a("screen_forges", "5", "global", "hostingy", "switch_screen_n(5)"),
    _a("screen_remote", "6", "global", "vzdálená repa", "switch_screen_n(6)", show=False),
    _a("screen_settings", "7", "global", "nastavení", "switch_screen_n(7)", show=False),
    _a("screen_export", "8", "global", "export", "switch_screen_n(8)", show=False),
    _a("search", "slash", "global", "hledat", label="/"),
    _a("scan_all", "R", "global", "sken"),
    _a("scan_repo", "r", "global", "sken repa", show=False),
    _a("cancel_scan", "x", "global", "zrušit sken", show=False),
    _a("toggle_offline", "O", "global", "offline režim", show=False),
    _a("toggle_theme", "t", "global", "světlé / tmavé téma", show=False),
    _a("back", "q", "global", "zpět / konec", "go_back"),
    _a("quit", "ctrl+c", "global", "okamžitý konec", show=False),
    # pohyb (platí ve všech seznamech)
    _a("cursor_down", "j", "nav", "dolů", show=False),
    _a("cursor_up", "k", "nav", "nahoru", show=False),
    _a("cursor_top", "g", "nav", "začátek seznamu", show=False),
    _a("cursor_bottom", "G", "nav", "konec seznamu", show=False),
    _a("half_page_down", "ctrl+d", "nav", "půl stránky dolů", show=False),
    _a("half_page_up", "ctrl+u", "nav", "půl stránky nahoru", show=False),
    _a("focus_next", "tab", "nav", "další panel", show=False),
    _a("focus_previous", "shift+tab", "nav", "předchozí panel", show=False),
    # přehled
    _a("open_card", "enter", "dashboard", "karta", label="⏎"),
    _a("dash_fix", "f", "dashboard", "léčba", "open_fix"),
    _a("collapse_band", "z", "dashboard", "sbalit"),
    _a("sort_cycle", "S", "dashboard", "řadit podle sloupce", show=False),
    _a("sort_reverse", "s", "dashboard", "obrátit řazení", show=False),
    _a("filter_high", "alt+1", "dashboard", "filtr ▲ HIGH", show=False),
    _a("filter_medium", "alt+2", "dashboard", "filtr ◆ MED", show=False),
    _a("filter_low", "alt+3", "dashboard", "filtr ● LOW", show=False),
    _a("problems_only", "p", "dashboard", "jen problémová repa", show=False),
    _a("group_cycle", "alt+g", "dashboard", "seskupit: triáž / složka / hosting", show=False),
    _a("toggle_sidebar", "b", "dashboard", "levý panel", show=False),
    # karta repa
    _a("detail_fix", "f", "detail", "léčba", "open_fix"),
    _a("allowlist", "a", "detail", "allowlist"),
    _a("open_editor", "o", "detail", "editor"),
    _a("open_web", "w", "detail", "web"),
    _a("copy_path", "y", "detail", "kopírovat cestu"),
    # léčba
    _a("toggle_fix", "space", "fix", "vybrat", label="space"),
    _a("select_all", "A", "fix", "vše"),
    _a("confirm_fix", "enter", "fix", "potvrdit", label="⏎"),
    # složky
    _a("folder_add", "n", "folders", "přidat"),
    _a("folder_edit", "e", "folders", "upravit"),
    _a("folder_delete", "d", "folders", "odebrat"),
    _a("folder_toggle", "space", "folders", "zapnout / vypnout", label="space"),
    # hostingy
    _a("forge_add", "n", "forges", "přidat"),
    _a("forge_edit", "e", "forges", "upravit"),
    _a("forge_delete", "d", "forges", "odebrat"),
    _a("forge_test", "T", "forges", "otestovat připojení"),
    # vzdálená repa
    _a("clone", "c", "remote", "naklonovat"),
    _a("remote_view", "v", "remote", "přepnout pohled"),
    _a("remote_refresh", "ctrl+r", "remote", "načíst znovu", show=False),
    # nastavení
    _a("settings_allow_remove", "d", "settings", "odebrat z allowlistu", show=False),
    # export
    _a("export", "e", "export", "exportovat"),
)

BY_ID: dict[str, KeyAction] = {a.id: a for a in ACTIONS}

_SYMBOLS = {
    "?": "question_mark",
    "/": "slash",
    " ": "space",
    "⏎": "enter",
    "return": "enter",
    "esc": "escape",
}
_NAMED = {
    "enter",
    "escape",
    "tab",
    "space",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "pageup",
    "pagedown",
    "up",
    "down",
    "left",
    "right",
    "question_mark",
    "slash",
    "exclamation_mark",
    "at",
    "number_sign",
    "dollar_sign",
    "percent_sign",
    "circumflex_accent",
    "ampersand",
    "asterisk",
    "plus",
    "minus",
    "equals_sign",
    "comma",
    "full_stop",
    "colon",
    "semicolon",
    "less_than_sign",
    "greater_than_sign",
    "underscore",
    "left_square_bracket",
    "right_square_bracket",
    "left_curly_bracket",
    "right_curly_bracket",
    "vertical_line",
    "tilde",
    "grave_accent",
    "apostrophe",
    "quotation_mark",
    "backslash",
} | {f"f{i}" for i in range(1, 25)}
_KEY_RE = re.compile(r"^((ctrl|alt|shift|super|meta)\+)*([A-Za-z0-9]|[a-z_0-9]+)$")
RESERVED = {"escape"}  # Esc vždy znamená zpět/zrušit


class KeymapError(Exception):
    """Neplatné mapování kláves v [keys]."""


def normalize_key(key: str) -> str:
    key = key.strip()
    key = _SYMBOLS.get(key, key)
    parts = key.split("+")
    base = parts[-1]
    base = _SYMBOLS.get(base, base)
    mods = [m.lower() for m in parts[:-1]]
    if len(base) > 1:
        base = base.lower()
    return "+".join([*sorted(mods), base])


def display_key(key: str) -> str:
    rev = {"question_mark": "?", "slash": "/", "enter": "⏎", "escape": "esc", "space": "space"}
    parts = key.split("+")
    parts[-1] = rev.get(parts[-1], parts[-1])
    return "+".join(parts)


def is_valid_key(key: str) -> bool:
    norm = normalize_key(key)
    m = _KEY_RE.match(norm)
    if not m:
        return False
    base = m.group(3)
    return len(base) == 1 or base in _NAMED


def _conflicts(ctx_a: str, ctx_b: str) -> bool:
    if ctx_a == ctx_b:
        return True
    return "global" in (ctx_a, ctx_b) or "nav" in (ctx_a, ctx_b)


def build_keymap(overrides: Mapping[str, str]) -> dict[str, str]:
    """Vrátí {id akce: klávesa} po aplikaci přemapování. Při chybě KeymapError."""
    problems: list[str] = []
    result = {a.id: a.key for a in ACTIONS}
    for action_id, key in overrides.items():
        if action_id not in BY_ID:
            problems.append(f"neznámá akce `{action_id}` (platné: {', '.join(sorted(BY_ID))})")
            continue
        if not isinstance(key, str) or not is_valid_key(key):
            problems.append(f"`{action_id}`: neplatná klávesa {key!r}")
            continue
        if normalize_key(key) in RESERVED:
            problems.append(f"`{action_id}`: klávesa {key!r} je vyhrazená (Esc = zpět)")
            continue
        result[action_id] = normalize_key(key)
    seen: dict[str, list[KeyAction]] = {}
    for a in ACTIONS:
        seen.setdefault(normalize_key(result[a.id]), []).append(a)
    for key, actions in sorted(seen.items()):
        for i, first in enumerate(actions):
            for second in actions[i + 1 :]:
                # stejná akce ve dvou kontextech (např. `f` léčba) kolizí není
                if first.action == second.action and first.context != second.context:
                    continue
                if _conflicts(first.context, second.context):
                    problems.append(
                        f"kolize: klávesa {display_key(key)!r} je přiřazena akcím `{first.id}` "
                        f"({CONTEXTS[first.context]}) a `{second.id}` ({CONTEXTS[second.context]})"
                    )
    if problems:
        raise KeymapError(
            "Neplatné mapování kláves v [keys]:\n" + "\n".join(f"  • {p}" for p in problems)
        )
    return result


def grouped(keymap: Mapping[str, str] | None = None) -> dict[str, list[tuple[str, str]]]:
    """Pro nápovědu: {kontext: [(klávesa, popis)]} podle aktuálního mapování."""
    keymap = keymap or {a.id: a.key for a in ACTIONS}
    out: dict[str, list[tuple[str, str]]] = {label: [] for label in CONTEXTS.values()}
    for a in ACTIONS:
        key = keymap.get(a.id, a.key)
        shown = a.label if a.label and key == a.key else display_key(key)
        out[CONTEXTS[a.context]].append((shown, a.description))
    return {k: v for k, v in out.items() if v}
