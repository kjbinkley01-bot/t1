"""Key names as written in scripts ('ctrl+s', 'enter', 'pgdn'), without importing any input library."""

import re

ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "win": "cmd", "windows": "cmd", "super": "cmd",
    "command": "cmd", "meta": "cmd", "escape": "esc", "return": "enter", "del": "delete",
    "ins": "insert", "pgup": "page_up", "pageup": "page_up", "pgdn": "page_down",
    "pagedown": "page_down", "bksp": "backspace", "back": "backspace", "spacebar": "space",
    "option": "alt", "prtsc": "print_screen", "printscreen": "print_screen",
    "capslock": "caps_lock", "numlock": "num_lock", "scrolllock": "scroll_lock",
    "apps": "menu", "arrowup": "up", "arrowdown": "down", "arrowleft": "left",
    "arrowright": "right", "altgr": "alt_gr",
}


def canonical(name):
    """'Page Down' -> 'page_down', 'ESCAPE' -> 'esc'; single characters keep their case."""
    n = str(name).strip()
    if len(n) == 1:
        return n
    low = n.lower().replace(" ", "_").replace("-", "_")
    low = ALIASES.get(low, low)
    low = ALIASES.get(low.replace("_", ""), low)
    return "+" if low == "plus" else low


def split_combo(text):
    """'ctrl+shift+s' -> ['ctrl', 'shift', 's'];  'ctrl++' -> ['ctrl', '+']."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("No keys given")
    if text == "+":
        return ["+"]
    trailing_plus = text.endswith("++")
    parts = [p for p in re.split(r"\s*\+\s*", text) if p]
    if trailing_plus:
        parts.append("+")
    return parts
