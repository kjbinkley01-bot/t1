"""Action catalog, script structure, descriptions and field parsing."""

import copy
import re

APP_NAME = "Clicker"
APP_VERSION = "2.0"

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
        "Wait for Screen to Settle", "If Image Found", "If Image Not Found", "If Pixel Color",
    ]),
    ("Flow", [
        "Delay", "Random Delay", "Go to Step", "Loop Back", "Run Script File",
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
NEEDS_XY = set(DRAG_MAP) | {"Move Mouse", "Wait for Pixel Color", "If Pixel Color"}
XY_OPTIONAL = set(CLICK_MAP) | set(SCROLL_MAP)
XY_IS_OFFSET = {"Move Mouse by Offset", "Click Image"}
MOUSE_ACTIONS = set(CLICK_MAP) | set(DRAG_MAP) | set(SCROLL_MAP) | {
    "Move Mouse", "Move Mouse by Offset", "Move Mouse by Angle", "Click Image"}
IMAGE_ACTIONS = {"Click Image", "Wait for Image", "Wait for Image to Vanish",
                 "If Image Found", "If Image Not Found"}
SCREEN_ACTIONS = set(dict(ACTION_GROUPS)["Screen"])

_IMG = [
    ("image", "Image", 20, "image"),
    ("region", "Search region", 16, "region"),
    ("confidence", "Match %", 5, "int"),
]
_BRANCH = [("goto", "Then step", 5, "int"), ("else_goto", "Else step", 5, "int")]
_TIMEOUT = [("timeout_s", "Timeout s", 5, "int")]

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
    "Wait for Pixel Color": [("color", "Color", 9, "color"), ("tolerance", "Tolerance", 5, "int")] + _TIMEOUT,
    "If Pixel Color": [("color", "Color", 9, "color"), ("tolerance", "Tolerance", 5, "int")] + _BRANCH,
    "Wait for Screen to Settle": [("region", "Region", 16, "region"),
                                  ("stable_ms", "Still for ms", 6, "int")] + _TIMEOUT,
    "Delay": [("ms", "Milliseconds", 8, "int")],
    "Random Delay": [("min_ms", "Min ms", 7, "int"), ("max_ms", "Max ms", 7, "int")],
    "Go to Step": [("goto", "Step", 5, "int")],
    "Loop Back": [("goto", "To step", 5, "int"), ("times", "Times", 5, "int")],
    "Run Script File": [("file", "File", 40, "file")],
    "Show Notification": [("message", "Message", 44, "text")],
}

DEFAULTS = {
    "confidence": "90", "timeout_s": "10", "amount": "3", "tolerance": "12",
    "stable_ms": "800", "ms": "500", "min_ms": "200", "max_ms": "800", "times": "3",
    "button": "left", "goto": "", "else_goto": "", "region": "", "image": "",
    "text": "", "keys": "", "file": "", "message": "", "color": "",
}

ACTION_HINTS = {
    "Click Image": "X and Y are an optional offset from the center of the match.",
    "Move Mouse by Offset": "X and Y are how far to move from the current position.",
    "Move Mouse by Angle": "X is the angle in degrees (0 is right, 90 is up). Y is the distance in pixels.",
    "Wait for Pixel Color": "X and Y are the pixel to watch. Grab fills all three from under the cursor.",
    "If Pixel Color": "X and Y are the pixel to check. Step numbers left blank mean continue.",
    "If Image Found": "Step numbers left blank mean continue to the next step.",
    "If Image Not Found": "Step numbers left blank mean continue to the next step.",
    "Hot Key": "Examples: ctrl+s, alt+tab, ctrl+shift+esc, win+d",
    "Send Keystroke": "Examples: enter, tab, esc, f5, down, a",
    "Type Text": "Use {name} for script inputs, or {today}, {yesterday}, {tomorrow}, {time}.",
    "Loop Back": "Jumps back to the step the given number of times, then continues.",
    "Scroll Up": "X and Y are optional. Blank scrolls wherever the cursor is.",
    "Scroll Down": "X and Y are optional. Blank scrolls wherever the cursor is.",
    "Wait for Screen to Settle": "Blank region watches the whole screen.",
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
    ("retry", "Retry step (3x)"),
    ("goto", "Go to step"),
    ("handler", "Run error handler"),
]
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
        "settings": {"repeat": 1, "speed": 1.0, "random_delay_ms": 0},
        "inputs": [],
        "error_handler": None,
        "steps": [],
    }


def new_step(action="Left Click"):
    return {"action": action, "x": None, "y": None, "cursor_back": False,
            "delay_ms": 100, "repeat": 1, "comment": "", "wait": {"mode": "none"}}


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


def referenced_images(script):
    names = []
    for st in script.get("steps", []):
        for n in (st.get("image"), (st.get("wait") or {}).get("image")):
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


def parse_field(kind, raw, label):
    raw = "" if raw is None else str(raw)
    if kind == "int":
        if label in ("Then step", "Else step"):
            return parse_int(raw, label, 1, allow_blank=True)
        if label == "Match %":
            return parse_int(raw, label, 50, 100) / 100.0
        return parse_int(raw, label, 0)
    if kind == "region":
        return parse_region(raw, label)
    if kind == "color":
        return parse_color(raw, label)
    if kind == "image":
        return image_name(raw)
    if kind.startswith("choice:"):
        return raw.strip() or kind[7:].split(",")[0]
    return raw


def field_to_text(kind, value, label=""):
    if value is None:
        return ""
    if kind == "region":
        return format_region(value)
    if label == "Match %":
        return str(int(round(float(value) * 100)))
    return str(value)


def check_step(step, n_steps=None):
    """Return an error message for an incomplete step, or None."""
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
    if a in ("Wait for Pixel Color", "If Pixel Color") and not step.get("color"):
        return "Enter the color to look for, or use Grab."
    if a in ("Go to Step", "Loop Back") and not step.get("goto"):
        return "Enter the step number to go to."
    if a == "Run Script File" and not step.get("file"):
        return "Choose the script file to run."
    if a == "Random Delay" and (step.get("min_ms") or 0) > (step.get("max_ms") or 0):
        return "Min ms must not be more than Max ms."
    if n_steps is not None:
        for key in ("goto", "else_goto"):
            v = step.get(key)
            if v and not 1 <= v <= n_steps:
                return f"Step {v} does not exist."
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


def describe_action(step):
    a = step["action"]
    img = image_stem(step.get("image")) or "?"
    if a == "Type Text":
        return f'Types "{_short(step.get("text"), 30)}"'
    if a in ("Send Keystroke", "Hot Key", "Key Down", "Key Up"):
        return f"Keys {step.get('keys', '')}"
    if a in SCROLL_MAP:
        return f"{step.get('amount', 1)} notches"
    if a == "Click Image":
        return f"Find {img}, max {step.get('timeout_s', 10)} s"
    if a == "Wait for Image":
        return f"Until {img} appears, max {step.get('timeout_s', 10)} s"
    if a == "Wait for Image to Vanish":
        return f"Until {img} disappears, max {step.get('timeout_s', 10)} s"
    if a in ("If Image Found", "If Image Not Found"):
        return f"{img} then {step.get('goto') or 'next'}, else {step.get('else_goto') or 'next'}"
    if a == "Wait for Pixel Color":
        return f"Until {step.get('color')}, max {step.get('timeout_s', 10)} s"
    if a == "If Pixel Color":
        return f"{step.get('color')} then {step.get('goto') or 'next'}, else {step.get('else_goto') or 'next'}"
    if a == "Wait for Screen to Settle":
        return f"Still {step.get('stable_ms', 800)} ms, max {step.get('timeout_s', 10)} s"
    if a == "Delay":
        return f"Wait {step.get('ms', 0)} ms"
    if a == "Random Delay":
        return f"Wait {step.get('min_ms', 0)} to {step.get('max_ms', 0)} ms"
    if a == "Go to Step":
        return f"Jump to step {step.get('goto')}"
    if a == "Loop Back":
        return f"Back to {step.get('goto')}, {step.get('times', 1)} times"
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
