"""Action catalog, script structure, descriptions and field parsing."""

import copy
import re

APP_NAME = "Clicker"
APP_VERSION = "2.8.0"

ACTION_GROUPS = [
    ("Mouse", [
        "Left Click", "Right Click", "Middle Click", "Double Click", "Double Right Click",
        "Triple Click", "Ctrl + Click", "Shift + Click", "Alt + Click", "Ctrl + Shift + Click",
        "Ctrl + Alt + Click", "Shift + Right Click", "Ctrl + Right Click",
        "X1 Button Click", "X2 Button Click",
        "Begin Dragging", "End Dragging", "Begin Right Dragging", "End Right Dragging",
        "Move Mouse", "Move Mouse by Offset", "Move Mouse by Angle",
        "Scroll Up", "Scroll Down", "Scroll Left", "Scroll Right",
        "Save Cursor Location", "Restore Cursor Location",
    ]),
    ("Keyboard", ["Type Text", "Send Keystroke", "Hot Key", "Key Down", "Key Up"]),
    ("Screen", [
        "Click Image", "Wait for Image", "Wait for Image to Vanish", "Wait for Pixel Color",
        "Wait for Screen to Settle", "If Image Found", "If Image Not Found", "If Pixel Color", "Count Image",
    ]),
    ("Text", ["Read Text", "Wait for Text", "If Text on Screen"]),
    ("Windows", ["Wait for Window", "If Window Open", "Focus Window", "Move Window", "Close Window"]),
    ("Apps and clipboard", ["Open", "Set Clipboard", "Copy Clipboard to Variable", "Save Screenshot"]),
    ("Variables", ["Set Variable", "Increment Variable", "If Variable"]),
    ("Loops", [
        "While Image Found", "While Image Not Found", "While Pixel Color", "While Variable",
        "End While", "Loop Back",
    ]),
    ("Flow", [
        "Delay", "Random Delay", "Go to Step", "Call Subroutine", "Return", "Run Script File",
        "Show Notification", "Beep", "Show Desktop", "Stop Script",
    ]),
]
ALL_ACTIONS = [a for _, acts in ACTION_GROUPS for a in acts]
ACTION_GROUP = {a: g for g, acts in ACTION_GROUPS for a in acts}

# action: (button, click count, modifier keys)
CLICK_MAP = {
    "Left Click": ("left", 1, ()),
    "Right Click": ("right", 1, ()),
    "Middle Click": ("middle", 1, ()),
    "Double Click": ("left", 2, ()),
    "Double Right Click": ("right", 2, ()),
    "Triple Click": ("left", 3, ()),
    "Ctrl + Click": ("left", 1, ("ctrl",)),
    "Shift + Click": ("left", 1, ("shift",)),
    "Alt + Click": ("left", 1, ("alt",)),
    "Ctrl + Shift + Click": ("left", 1, ("ctrl", "shift")),
    "Ctrl + Alt + Click": ("left", 1, ("ctrl", "alt")),
    "Shift + Right Click": ("right", 1, ("shift",)),
    "Ctrl + Right Click": ("right", 1, ("ctrl",)),
    "X1 Button Click": ("x1", 1, ()),
    "X2 Button Click": ("x2", 1, ()),
}
DRAG_MAP = {
    "Begin Dragging": ("left", True),
    "End Dragging": ("left", False),
    "Begin Right Dragging": ("right", True),
    "End Right Dragging": ("right", False),
}
SCROLL_MAP = {
    "Scroll Up": (0, 1), "Scroll Down": (0, -1),
    "Scroll Left": (-1, 0), "Scroll Right": (1, 0),
}
NEEDS_XY = set(DRAG_MAP) | {"Move Mouse", "Wait for Pixel Color", "If Pixel Color", "While Pixel Color"}
XY_OPTIONAL = set(CLICK_MAP) | set(SCROLL_MAP)
XY_IS_OFFSET = {"Move Mouse by Offset", "Click Image"}
MOUSE_ACTIONS = set(CLICK_MAP) | set(DRAG_MAP) | set(SCROLL_MAP) | {
    "Move Mouse", "Move Mouse by Offset", "Move Mouse by Angle", "Click Image"}
IMAGE_ACTIONS = {"Click Image", "Wait for Image", "Wait for Image to Vanish",
                 "If Image Found", "If Image Not Found", "While Image Found", "While Image Not Found", "Count Image"}
IMAGE_MODES = ["any of them", "all of them"]
WHILE_ACTIONS = {"While Image Found", "While Image Not Found", "While Pixel Color", "While Variable"}
TEXT_OPS = ["contains", "not contains", "=", "!=", "<", "<=", ">", ">="]
SCREEN_ACTIONS = set(dict(ACTION_GROUPS)["Screen"]) | {"Read Text", "Wait for Text", "If Text on Screen", "While Image Found",
                                                      "While Image Not Found", "While Pixel Color"}
COMPARE_OPS = ["=", "!=", "<", "<=", ">", ">=", "contains", "not contains"]
TARGET_KEYS = ("goto", "else_goto")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
MAX_CALL_DEPTH = 50

_IMG = [
    ("image", "Image", 20, "image"),
    ("images", "Or these", 20, "images"),
    ("image_mode", "Look for", 10, "choice:" + ",".join(IMAGE_MODES)),
    ("region", "Search region", 16, "region"),
    ("confidence", "Match %", 5, "percent"),
]
_BRANCH = [("goto", "Then step", 10, "target"), ("else_goto", "Else step", 10, "target")]
_TIMEOUT = [("timeout_s", "Timeout s", 5, "int")]
_PIXEL = [("color", "Color", 9, "color"), ("tolerance", "Tolerance", 5, "int")]
_COMPARE = [("var", "Variable", 14, "var"), ("op", "Is", 10, "choice:" + ",".join(COMPARE_OPS)),
            ("value", "Value", 14, "text")]
_MAX = [("max_loops", "Max loops", 6, "int")]
_TEXT = [("region", "Region", 16, "region"), ("mode", "Read as", 8, "choice:text,number"),
         ("op", "Is", 10, "choice:" + ",".join(TEXT_OPS)), ("value", "Value", 16, "text"),
         ("var", "Save text to", 12, "var_opt")]
_WIN = [("title", "Title contains", 22, "text"), ("process", "Program", 14, "text")]

# action: list of (key, label, width, kind)
FIELD_SPECS = {
    "Type Text": [("text", "Text", 46, "text")],
    "Send Keystroke": [("keys", "Key", 16, "text")],
    "Hot Key": [("keys", "Keys", 20, "text")],
    "Key Down": [("keys", "Key", 16, "text")],
    "Key Up": [("keys", "Key", 16, "text")],
    "Scroll Up": [("amount", "Notches", 6, "int")],
    "Scroll Down": [("amount", "Notches", 6, "int")],
    "Scroll Left": [("amount", "Notches", 6, "int")],
    "Scroll Right": [("amount", "Notches", 6, "int")],
    "Click Image": _IMG + [("button", "Click", 8, "choice:left,right,double,middle")] + _TIMEOUT,
    "Wait for Image": _IMG + _TIMEOUT,
    "Wait for Image to Vanish": _IMG + _TIMEOUT,
    "If Image Found": _IMG + _BRANCH,
    "If Image Not Found": _IMG + _BRANCH,
    "Wait for Pixel Color": _PIXEL + _TIMEOUT,
    "If Pixel Color": _PIXEL + _BRANCH,
    "Count Image": [("image", "Image", 20, "image"), ("images", "Also count", 20, "images"),
                    ("region", "Search region", 16, "region"), ("confidence", "Match %", 5, "percent"),
                    ("var", "Save count to", 14, "var")],
    "Wait for Screen to Settle": [("region", "Region", 16, "region"),
                                  ("stable_ms", "Still for ms", 6, "int")] + _TIMEOUT,
    "Delay": [("ms", "Milliseconds", 8, "int")],
    "Random Delay": [("min_ms", "Min ms", 7, "int"), ("max_ms", "Max ms", 7, "int")],
    "Go to Step": [("goto", "Step", 10, "target")],
    "Loop Back": [("goto", "To step", 10, "target"), ("times", "Times", 5, "int")],
    "Call Subroutine": [("goto", "Step", 10, "target")],
    "Read Text": [("region", "Region", 16, "region"), ("var", "Save to", 14, "var"),
                  ("mode", "Read as", 8, "choice:text,number")],
    "Set Variable": [("var", "Variable", 14, "var"), ("value", "Value", 30, "text")],
    "Increment Variable": [("var", "Variable", 14, "var"), ("amount", "By", 6, "sint")],
    "If Variable": _COMPARE + _BRANCH,
    "While Image Found": _IMG + _MAX,
    "While Image Not Found": _IMG + _MAX,
    "While Pixel Color": _PIXEL + _MAX,
    "While Variable": _COMPARE + _MAX,
    "Wait for Text": _TEXT + _TIMEOUT,
    "If Text on Screen": _TEXT + _BRANCH,
    "Wait for Window": _WIN + _TIMEOUT,
    "If Window Open": _WIN + _BRANCH,
    "Focus Window": _WIN,
    "Move Window": _WIN + [("region", "Put it at", 18, "region")],
    "Close Window": _WIN,
    "Open": [("file", "App, file or URL", 30, "text"), ("args", "Arguments", 14, "text"),
             ("title", "Wait for window", 16, "text")] + _TIMEOUT,
    "Set Clipboard": [("value", "Text", 40, "text")],
    "Copy Clipboard to Variable": [("var", "Save to", 14, "var")],
    "Save Screenshot": [("region", "Region", 16, "region"), ("file", "Save to", 40, "text")],
    "Run Script File": [("file", "File", 40, "file")],
    "Show Notification": [("message", "Message", 44, "text")],
}

DEFAULTS = {
    "confidence": "90", "timeout_s": "10", "amount": "3", "tolerance": "12",
    "stable_ms": "800", "ms": "500", "min_ms": "200", "max_ms": "800", "times": "3",
    "button": "left", "goto": "", "else_goto": "", "region": "", "image": "",
    "text": "", "keys": "", "file": "", "message": "", "color": "",
    "var": "", "value": "", "op": "=", "mode": "text", "max_loops": "0",
    "title": "", "process": "", "args": "",
}

# per action defaults that differ from DEFAULTS
ACTION_DEFAULTS = {"Wait for Text": {"op": "contains"}, "If Text on Screen": {"op": "contains"}}

ACTION_HINTS = {
    "Click Image": "X and Y are an optional offset from the center of the match. Add more images under "
                   "Or these for a button with hover or night versions: any of them is clicked.",
    "Count Image": "Counts every place the image shows (and any extra images) and saves the number, "
                   "e.g. for If Variable ore_count >= 3.",
    "Move Mouse by Offset": "X and Y are how far to move from the current position.",
    "Move Mouse by Angle": "X is the angle in degrees (0 is right, 90 is up). Y is the distance in pixels.",
    "Wait for Pixel Color": "X and Y are the pixel to watch. Grab fills all three from under the cursor.",
    "If Pixel Color": "X and Y are the pixel to check. Step numbers left blank mean continue.",
    "If Image Found": "Step numbers left blank mean continue to the next step.",
    "If Image Not Found": "Step numbers left blank mean continue to the next step.",
    "Hot Key": "Examples: ctrl+s, alt+tab, ctrl+shift+esc, win+d",
    "Wait for Text": "Reads the region (blank = whole screen) until its text matches, e.g. contains Complete, "
                     "or read as number < 30. Save text to keeps what it read in a variable.",
    "If Text on Screen": "Reads the region once. Step numbers left blank mean continue.",
    "Wait for Window": "Waits until a window whose title contains the text (and/or of that program, "
                       "e.g. notepad.exe) is open. Windows only.",
    "If Window Open": "Step numbers left blank mean continue. Windows only.",
    "Focus Window": "Brings the window to the front (restoring it if minimized). Windows only.",
    "Move Window": "Draw where the window should go (x, y, width, height). Windows only.",
    "Close Window": "Asks the window to close, like clicking its X (it may ask to save). Windows only.",
    "Open": "An app (C:\\...\\app.exe or notepad), a file, a folder or a web address. Give a window title "
            "to wait until it's ready.",
    "Set Clipboard": "Puts the text on the clipboard; {variables} work.",
    "Copy Clipboard to Variable": "Saves the clipboard text in a variable, e.g. after Hot Key ctrl+c.",
    "Save Screenshot": "Saves a PNG. Save to can be a folder or a file name, with {variables}; blank saves to "
                       "the screenshots folder. The path goes in {last_screenshot}.",
    "Send Keystroke": "Examples: enter, tab, esc, f5, down, a",
    "Type Text": "Use {name} for script inputs, or {today}, {yesterday}, {tomorrow}, {time}.",
    "Loop Back": "Jumps back to the step the given number of times, then continues.",
    "Scroll Up": "X and Y are optional. Blank scrolls wherever the cursor is.",
    "Scroll Down": "X and Y are optional. Blank scrolls wherever the cursor is.",
    "Wait for Screen to Settle": "Blank region watches the whole screen.",
    "Go to Step": "A step number, or a label name you gave a step.",
    "Call Subroutine": "Jumps to a step or label, and Return comes back here. End the main part with Return.",
    "Return": "Goes back to the step after the last Call Subroutine. Outside a subroutine it ends this pass.",
    "Read Text": "Reads the text in the region (OCR) into a variable. Needs Tesseract installed.",
    "Set Variable": "Use {name} anywhere text is typed to insert the value. Other {variables} work here too.",
    "Increment Variable": "Adds the amount (use a negative number to subtract). Blank variables start at 0.",
    "If Variable": "Numbers compare as numbers; anything else compares as text.",
    "While Image Found": "Repeats the steps down to End While as long as the image is on screen.",
    "While Image Not Found": "Repeats the steps down to End While until the image shows up.",
    "While Pixel Color": "Repeats the steps down to End While while the pixel has this color.",
    "While Variable": "Repeats the steps down to End While while the comparison is true.",
    "End While": "Marks the end of the nearest While above it.",
}

WAIT_MODES = [
    ("none", "Fixed delay only"),
    ("image_appears", "Until image appears"),
    ("image_vanishes", "Until image disappears"),
    ("pixel_is", "Until pixel color matches"),
    ("region_stable", "Until screen stops changing"),
]
WAIT_LABEL = dict(WAIT_MODES)
WAIT_ID = {v: k for k, v in WAIT_MODES}

ON_TIMEOUT = [
    ("stop", "Stop script"),
    ("skip", "Skip this step"),
    ("retry", "Retry step"),
    ("retry_handler", "Retry, then error handler"),
    ("goto", "Go to step"),
    ("handler", "Run error handler"),
]
DEFAULT_RETRIES = 3
ON_TIMEOUT_LABEL = dict(ON_TIMEOUT)
ON_TIMEOUT_ID = {v: k for k, v in ON_TIMEOUT}

CONDITION_KINDS = [
    ("image_appears", "Image appears"),
    ("image_vanishes", "Image disappears"),
    ("pixel_is", "Pixel color equals"),
    ("pixel_changes", "Pixel color changes"),
    ("region_changes", "Region changes"),
    ("region_stable", "Region stops changing"),
]
CONDITION_LABEL = dict(CONDITION_KINDS)
CONDITION_ID = {v: k for k, v in CONDITION_KINDS}


# ---------------------------------------------------------------- structure

def new_script(name="Untitled"):
    return {
        "format": "clicker-script",
        "version": 2,
        "name": name,
        "description": "",
        "screen": None,
        "settings": {"repeat": 1, "speed": 1.0, "random_delay_ms": 0,
                     "restart_on_failure": 0, "scale_search": False},
        "inputs": [],
        "error_handler": None,
        "steps": [],
    }


def new_step(action="Left Click"):
    return {"action": action, "x": None, "y": None, "cursor_back": False,
            "delay_ms": 100, "repeat": 1, "comment": "", "label": "", "wait": {"mode": "none"}}


def normalize_script(data):
    """Fill in defaults so older or hand written scripts load cleanly."""
    if not isinstance(data, dict):
        raise ValueError("Script must be a JSON object")
    steps = data.get("steps")
    if not isinstance(steps, list):
        raise ValueError("Script has no 'steps' list")
    s = new_script(data.get("name") or "Untitled")
    for key in ("description", "screen", "error_handler"):
        if key in data:
            s[key] = data[key]
    s["error_handler"] = _norm_target(s["error_handler"])
    s["settings"].update(data.get("settings") or {})
    inputs = []
    for item in data.get("inputs") or []:
        if isinstance(item, str):
            item = {"name": item}
        if isinstance(item, dict) and item.get("name"):
            inputs.append({"name": str(item["name"]), "label": str(item.get("label") or item["name"]),
                           "default": str(item.get("default") or "")})
    s["inputs"] = inputs
    out = []
    for n, raw in enumerate(steps, 1):
        if not isinstance(raw, dict) or not raw.get("action"):
            raise ValueError(f"Step {n} has no action")
        st = new_step(raw["action"])
        st.update(raw)
        w = st.get("wait") or {}
        if not isinstance(w, dict):
            w = {}
        w.setdefault("mode", "none")
        st["wait"] = w
        for key in ("delay_ms", "repeat"):
            try:
                st[key] = int(st.get(key) or 0)
            except (TypeError, ValueError):
                raise ValueError(f"Step {n}: {key} must be a number")
        st["repeat"] = max(1, st["repeat"])
        for key in TARGET_KEYS:
            if key in st:
                st[key] = _norm_target(st[key])
        if "goto" in w:
            w["goto"] = _norm_target(w["goto"])
        st["label"] = str(st.get("label") or "").strip()
        for key in ("x", "y"):
            if st.get(key) in ("", None):
                st[key] = None
            else:
                try:
                    st[key] = int(round(float(st[key])))
                except (TypeError, ValueError):
                    raise ValueError(f"Step {n}: {key} must be a number")
        out.append(st)
    s["steps"] = out
    return s


def _norm_target(v):
    """Step numbers may arrive as "3" or 3.0; labels stay strings; blank is None."""
    if v in (None, "") or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    v = str(v).strip()
    if re.fullmatch(r"\d+", v):
        return int(v)
    return v or None


def copy_script(script):
    return copy.deepcopy(script)


def image_name(name):
    """Normalize an image reference to its stored file name."""
    name = (name or "").strip()
    if not name:
        return ""
    if not re.search(r"\.(png|jpg|jpeg|bmp)$", name, re.I):
        name += ".png"
    return name


def image_stem(name):
    name = image_name(name)
    return re.sub(r"\.(png|jpg|jpeg|bmp)$", "", name, flags=re.I)


def step_images(step):
    """The step's image followed by its alternates, as stored names."""
    out = []
    for n in [step.get("image")] + list(step.get("images") or []):
        n = image_name(n)
        if n and n not in out:
            out.append(n)
    return out


def referenced_images(script):
    names = []
    for st in script.get("steps", []):
        for n in step_images(st) + [(st.get("wait") or {}).get("image")]:
            n = image_name(n)
            if n and n not in names:
                names.append(n)
    return names


def is_screen_step(step):
    return step["action"] in SCREEN_ACTIONS or (step.get("wait") or {}).get("mode", "none") != "none"


# ---------------------------------------------------------------- parsing

def parse_int(raw, label, minimum=None, maximum=None, allow_blank=False):
    raw = str(raw if raw is not None else "").strip()
    if raw == "":
        if allow_blank:
            return None
        raise ValueError(f"{label} is required.")
    try:
        val = int(round(float(raw)))
    except ValueError:
        raise ValueError(f"{label} must be a whole number.")
    if minimum is not None and val < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and val > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return val


def parse_region(raw, label="Region"):
    raw = str(raw or "").strip()
    if not raw:
        return None
    parts = [p for p in re.split(r"[\s,;x]+", raw) if p]
    if len(parts) != 4:
        raise ValueError(f"{label} must be four numbers: x, y, width, height.")
    try:
        x, y, w, h = (int(round(float(p))) for p in parts)
    except ValueError:
        raise ValueError(f"{label} must be four numbers: x, y, width, height.")
    if w < 2 or h < 2:
        raise ValueError(f"{label} width and height must be at least 2.")
    return [x, y, w, h]


def format_region(region):
    return "" if not region else ", ".join(str(int(v)) for v in region)


def parse_color(raw, label="Color"):
    raw = str(raw or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", raw)
    if m:
        return "#" + m.group(1).upper()
    parts = [p for p in re.split(r"[\s,]+", raw) if p]
    if len(parts) == 3:
        try:
            r, g, b = (int(p) for p in parts)
            if all(0 <= v <= 255 for v in (r, g, b)):
                return "#%02X%02X%02X" % (r, g, b)
        except ValueError:
            pass
    raise ValueError(f"{label} must look like #1A2B3C.")


def color_to_rgb(color):
    c = parse_color(color)
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def parse_pixel_target(raw):
    """'x, y, #RRGGBB' -> (x, y, color)."""
    parts = [p for p in re.split(r"[\s,]+", str(raw or "").strip()) if p]
    if len(parts) != 3:
        raise ValueError("Pixel target must look like: 640, 410, #2E7D32 (use Grab).")
    x = parse_int(parts[0], "Pixel X")
    y = parse_int(parts[1], "Pixel Y")
    return x, y, parse_color(parts[2])


def parse_target(raw, label="Step"):
    """A jump target: a 1 based step number, a label name, or blank (None)."""
    raw = str(raw if raw is not None else "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+", raw):
        val = int(raw)
        if val < 1:
            raise ValueError(f"{label} must be at least 1.")
        return val
    if not LABEL_RE.match(raw):
        raise ValueError(f"{label} must be a step number or a label name (letters, digits, _ and -).")
    return raw


def parse_var(raw, label="Variable"):
    raw = str(raw or "").strip().strip("{}")
    if not NAME_RE.match(raw):
        raise ValueError(f"{label} must be a name like count or page_title (letters, digits and _).")
    return raw


def parse_field(kind, raw, label):
    raw = "" if raw is None else str(raw)
    if kind == "target":
        return parse_target(raw, label)
    if kind == "percent":
        return parse_int(raw, label, 50, 100) / 100.0
    if kind == "var":
        return parse_var(raw, label)
    if kind == "var_opt":
        return parse_var(raw, label) if raw.strip() else ""
    if kind == "sint":
        return parse_int(raw, label)
    if kind == "int":
        return parse_int(raw, label, 0)
    if kind == "region":
        return parse_region(raw, label)
    if kind == "color":
        return parse_color(raw, label)
    if kind == "image":
        return image_name(raw)
    if kind == "images":
        return [image_name(p) for p in re.split(r"[,;\n]+", raw) if p.strip()]
    if kind.startswith("choice:"):
        return raw.strip() or kind[7:].split(",")[0]
    return raw


def field_to_text(kind, value, label=""):
    if value is None:
        return ""
    if kind == "region":
        return format_region(value)
    if kind == "images":
        return ", ".join(image_stem(v) for v in value or [])
    if kind == "percent" or label == "Match %":
        return str(int(round(float(value) * 100)))
    return str(value)


# ---------------------------------------------------------------- jump targets

def label_map(steps):
    """{label: 0 based index} for every labelled step (first one wins)."""
    out = {}
    for i, st in enumerate(steps):
        name = str(st.get("label") or "").strip()
        if name and name not in out:
            out[name] = i
    return out


def resolve_target(steps, value, labels=None):
    """Turn a step number or label into a 0 based index. None means 'no jump'."""
    if value in (None, ""):
        return None
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        value = int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        idx = int(value) - 1
        if not 0 <= idx < len(steps):
            raise ValueError(f"Step {int(value)} does not exist.")
        return idx
    labels = label_map(steps) if labels is None else labels
    name = str(value).strip()
    if name not in labels:
        raise ValueError(f"No step is labelled '{name}'.")
    return labels[name]


def _target_slots(script):
    """Yield (container, key) for every place a step number can live."""
    for st in script.get("steps", []):
        for key in TARGET_KEYS:
            if key in st:
                yield st, key
        w = st.get("wait")
        if isinstance(w, dict) and "goto" in w:
            yield w, "goto"
    yield script, "error_handler"


def remap_targets(script, mapping):
    """Keep numeric jumps pointing at the same steps after the list changes.

    mapping: {old 0 based index: new 0 based index or None if deleted}.
    A jump to a deleted step moves to the next step that survived.
    Label jumps need no change. Updates script in place.
    """
    if not mapping:
        return
    old_n = max(mapping) + 1
    for box, key in list(_target_slots(script)):
        v = box.get(key)
        if isinstance(v, bool) or not isinstance(v, int):
            continue
        old = v - 1
        if not 0 <= old < old_n:
            continue
        new = mapping.get(old)
        k = old
        while new is None and k + 1 < old_n:
            k += 1
            new = mapping.get(k)
        box[key] = None if new is None else new + 1


def reorder(script, order):
    """Rebuild the step list. order holds old indexes, or step dicts for new steps."""
    old = script["steps"]
    new_steps, mapping = [], {i: None for i in range(len(old))}
    for pos, item in enumerate(order):
        if isinstance(item, int):
            new_steps.append(old[item])
            mapping[item] = pos
        else:
            new_steps.append(item)
    script["steps"] = new_steps
    remap_targets(script, mapping)


def match_blocks(steps):
    """Pair each While with its End While. Returns ({index: partner}, error or None)."""
    pairs, stack = {}, []
    for i, st in enumerate(steps):
        a = st.get("action")
        if st.get("disabled"):
            continue
        if a in WHILE_ACTIONS:
            stack.append(i)
        elif a == "End While":
            if not stack:
                return pairs, f"Step {i + 1}: End While has no While above it."
            j = stack.pop()
            pairs[i], pairs[j] = j, i
    if stack:
        return pairs, f"Step {stack[-1] + 1}: {steps[stack[-1]]['action']} has no End While."
    return pairs, None


def check_step(step, steps=None, labels=None):
    """Return an error message for an incomplete step, or None.

    Pass the whole step list to also check that jump targets exist.
    """
    a = step["action"]
    if a not in ACTION_GROUP:
        return f"Unknown action '{a}'."
    has_xy = step.get("x") is not None and step.get("y") is not None
    if a in NEEDS_XY and not has_xy:
        return f"{a} needs an X and Y position."
    if a == "Move Mouse by Angle" and not has_xy:
        return "Enter the angle in X and the distance in Y."
    if a in IMAGE_ACTIONS and not step.get("image"):
        return f"{a} needs an image. Use Capture or Load."
    if a in ("Type Text",) and not step.get("text"):
        return "Enter the text to type."
    if a in ("Send Keystroke", "Hot Key", "Key Down", "Key Up") and not step.get("keys"):
        return "Enter the key or keys."
    if a in ("Wait for Pixel Color", "If Pixel Color", "While Pixel Color") and not step.get("color"):
        return "Enter the color to look for, or use Grab."
    if a in ("Go to Step", "Loop Back", "Call Subroutine") and not step.get("goto"):
        return "Enter the step number or label to go to."
    if a == "Run Script File" and not step.get("file"):
        return "Choose the script file to run."
    if a == "Random Delay" and (step.get("min_ms") or 0) > (step.get("max_ms") or 0):
        return "Min ms must not be more than Max ms."
    if a in ("Wait for Text", "If Text on Screen") and not str(step.get("value") or "").strip():
        return "Enter the text or number to look for."
    if a in ("Wait for Window", "If Window Open", "Focus Window", "Move Window", "Close Window") \
            and not (str(step.get("title") or "").strip() or str(step.get("process") or "").strip()):
        return "Enter part of the window title, or the program name."
    if a == "Move Window" and not step.get("region"):
        return "Draw where the window should go."
    if a == "Open" and not str(step.get("file") or "").strip():
        return "Enter the app, file or web address to open."
    if a in ("Set Variable", "Increment Variable", "If Variable", "While Variable", "Read Text", "Count Image",
             "Copy Clipboard to Variable"):
        if not NAME_RE.match(str(step.get("var") or "")):
            return "Enter a variable name (letters, digits and _)."
    if a in ("If Variable", "While Variable") and step.get("op", "=") not in COMPARE_OPS:
        return f"Unknown comparison '{step.get('op')}'."
    lab = str(step.get("label") or "").strip()
    if lab and (not LABEL_RE.match(lab) or lab.isdigit()):
        return "Labels use letters, digits, _ and - and must not be just a number."
    if steps is not None:
        labels = label_map(steps) if labels is None else labels
        w = step.get("wait") or {}
        for v in [step.get(k) for k in TARGET_KEYS] + [w.get("goto") if w.get("on_timeout") == "goto" else None]:
            try:
                resolve_target(steps, v, labels)
            except ValueError as e:
                return str(e)
    return None


def wait_to_condition(w):
    mode = w.get("mode", "none")
    cond = {"kind": mode, "region": w.get("region"), "confidence": w.get("confidence", 0.9),
            "grayscale": w.get("grayscale", False)}
    if mode in ("image_appears", "image_vanishes"):
        cond["image"] = image_name(w.get("image"))
    elif mode == "pixel_is":
        cond.update(x=w.get("x"), y=w.get("y"), color=w.get("color"), tolerance=w.get("tolerance", 12))
    elif mode == "region_stable":
        cond["stable_ms"] = w.get("stable_ms", 800)
    return cond


# ---------------------------------------------------------------- describing

def _short(text, n=40):
    text = str(text or "").replace("\n", " ")
    return text if len(text) <= n else text[: n - 3] + "..."


def describe_wait(w):
    mode = (w or {}).get("mode", "none")
    t = (w or {}).get("timeout_s", 30)
    if mode in ("image_appears", "image_vanishes"):
        verb = "appears" if mode == "image_appears" else "disappears"
        return f"Until {image_stem(w.get('image')) or '?'} {verb}, max {t} s"
    if mode == "pixel_is":
        return f"Until pixel {w.get('x')}, {w.get('y')} is {w.get('color')}, max {t} s"
    if mode == "region_stable":
        return f"Until screen is still {w.get('stable_ms', 800)} ms, max {t} s"
    return ""


def _tgt(v, blank="?"):
    if v in (None, ""):
        return blank
    return f"step {v}" if isinstance(v, int) else f"'{v}'"


def describe_action(step):
    a = step["action"]
    img = image_stem(step.get("image")) or "?"
    if a == "Type Text":
        return f'Types "{_short(step.get("text"), 30)}"'
    if a in ("Send Keystroke", "Hot Key", "Key Down", "Key Up"):
        return f"Keys {step.get('keys', '')}"
    if a in SCROLL_MAP:
        return f"{step.get('amount', 1)} notches"
    alts = len(step_images(step)) - 1
    if alts > 0:
        img += f" +{alts}" + (" (all)" if step.get("image_mode") == IMAGE_MODES[1] else "")
    if a == "Count Image":
        return f"Count {img} into {{{step.get('var')}}}"
    if a == "Click Image":
        return f"Find {img}, max {step.get('timeout_s', 10)} s"
    if a == "Wait for Image":
        return f"Until {img} appears, max {step.get('timeout_s', 10)} s"
    if a == "Wait for Image to Vanish":
        return f"Until {img} disappears, max {step.get('timeout_s', 10)} s"
    if a in ("If Image Found", "If Image Not Found"):
        return f"{img} then {_tgt(step.get('goto'), 'next')}, else {_tgt(step.get('else_goto'), 'next')}"
    if a == "Wait for Pixel Color":
        return f"Until {step.get('color')}, max {step.get('timeout_s', 10)} s"
    if a == "If Pixel Color":
        return f"{step.get('color')} then {_tgt(step.get('goto'), 'next')}, else {_tgt(step.get('else_goto'), 'next')}"
    if a == "Wait for Screen to Settle":
        return f"Still {step.get('stable_ms', 800)} ms, max {step.get('timeout_s', 10)} s"
    if a == "Delay":
        return f"Wait {step.get('ms', 0)} ms"
    if a == "Random Delay":
        return f"Wait {step.get('min_ms', 0)} to {step.get('max_ms', 0)} ms"
    if a == "Go to Step":
        return f"Jump to {_tgt(step.get('goto'))}"
    if a == "Call Subroutine":
        return f"Call {_tgt(step.get('goto'))}"
    if a == "Read Text":
        where = format_region(step.get("region")) or "whole screen"
        return f"Read {step.get('mode') or 'text'} into {{{step.get('var')}}} from {where}"
    if a == "Set Variable":
        return f"{{{step.get('var')}}} = \"{_short(step.get('value'), 30)}\""
    if a == "Increment Variable":
        amt = int(step.get("amount") or 0)
        return f"{{{step.get('var')}}} {'+' if amt >= 0 else '-'} {abs(amt)}"
    if a == "If Variable":
        return (f"{{{step.get('var')}}} {step.get('op', '=')} \"{_short(step.get('value'), 16)}\" "
                f"then {_tgt(step.get('goto'), 'next')}, else {_tgt(step.get('else_goto'), 'next')}")
    if a in WHILE_ACTIONS:
        if a == "While Variable":
            cond = f"{{{step.get('var')}}} {step.get('op', '=')} \"{_short(step.get('value'), 16)}\""
        elif a == "While Pixel Color":
            cond = f"pixel is {step.get('color')}"
        else:
            cond = f"{img} {'is' if a == 'While Image Found' else 'is not'} on screen"
        cap = int(step.get("max_loops") or 0)
        return f"While {cond}" + (f", max {cap} loops" if cap else "")
    if a == "Loop Back":
        return f"Back to {_tgt(step.get('goto'))}, {step.get('times', 1)} times"
    if a in ("Wait for Text", "If Text on Screen"):
        where = format_region(step.get("region")) or "screen"
        cond = f"{step.get('mode') or 'text'} {step.get('op', 'contains')} \"{_short(step.get('value'), 16)}\""
        if a == "Wait for Text":
            return f"Until {where} {cond}, max {step.get('timeout_s', 10)} s"
        return f"{cond} then {_tgt(step.get('goto'), 'next')}, else {_tgt(step.get('else_goto'), 'next')}"
    if a in ("Wait for Window", "If Window Open", "Focus Window", "Move Window", "Close Window"):
        who = " · ".join(v for v in (str(step.get("title") or ""), str(step.get("process") or "")) if v)
        if a == "Wait for Window":
            return f"{who}, max {step.get('timeout_s', 10)} s"
        if a == "If Window Open":
            return f"{who} then {_tgt(step.get('goto'), 'next')}, else {_tgt(step.get('else_goto'), 'next')}"
        if a == "Move Window":
            return f"{who} to {format_region(step.get('region'))}"
        return who
    if a == "Open":
        what = _short(str(step.get("file", "")), 40)
        return what + (f", wait for {step.get('title')}" if step.get("title") else "")
    if a == "Set Clipboard":
        return f"\"{_short(step.get('value'), 30)}\""
    if a == "Copy Clipboard to Variable":
        return f"into {{{step.get('var')}}}"
    if a == "Save Screenshot":
        return (format_region(step.get("region")) or "whole screen") + (f" to {step.get('file')}" if step.get("file") else "")
    if a == "Run Script File":
        return _short(str(step.get("file", "")).replace("\\", "/").split("/")[-1])
    if a == "Show Notification":
        return _short(step.get("message"))
    return ""


def describe_step(step):
    """Return (x text, y text, condition text) for the step table."""
    a = step["action"]
    x, y = step.get("x"), step.get("y")
    if a in IMAGE_ACTIONS:
        xt, yt = ("match", "match") if a == "Click Image" else ("region", "region")
        if a == "Click Image" and (x or y):
            xt, yt = f"match{x:+d}" if x else "match", f"match{y:+d}" if y else "match"
    else:
        xt = "" if x is None else str(x)
        yt = "" if y is None else str(y)
    wait = describe_wait(step.get("wait"))
    act = describe_action(step)
    if wait and act:
        cond = f"{wait}; {act}"
    else:
        cond = wait or act or f"Delay {step.get('delay_ms', 0)} ms"
    return xt, yt, cond


def describe_for_import(step):
    """(label, waits for, timeout) for the import preview."""
    a = step["action"]
    w = step.get("wait") or {}
    label = a
    if a in ("Send Keystroke", "Hot Key"):
        label = f"{a} {step.get('keys', '')}"
    waits = describe_wait(w)
    timeout = f"{w.get('timeout_s', 30)} s" if w.get("mode", "none") != "none" else ""
    if a in SCREEN_ACTIONS:
        act = describe_action(step)
        waits = f"{waits}; {act}" if waits else act
        if "timeout_s" in step:
            timeout = f"{step['timeout_s']} s"
        elif a.startswith("If"):
            timeout = "check once"
    if not waits:
        act = describe_action(step)
        waits = act if act else f"Delay {step.get('delay_ms', 0)} ms"
    return label, waits, timeout or "none"
