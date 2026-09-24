"""Script packages (.clk / .clkpkg), recordings, assets, settings and validation."""

import json
import os
import re
import sys
import tempfile
import threading
import zipfile

from . import model, vision

SCRIPT_EXTS = (".clk", ".clkpkg", ".json")


class AssetStore:
    """Named PNG images kept in memory, decoded on demand."""

    def __init__(self):
        self._raw = {}
        self._cache = {}
        self._lock = threading.Lock()

    def names(self):
        return sorted(self._raw)

    def __len__(self):
        return len(self._raw)

    def has(self, name):
        return model.image_name(name) in self._raw

    def raw(self, name):
        return self._raw.get(model.image_name(name))

    def add_bytes(self, name, data):
        name = model.image_name(name)
        vision.decode_png(data)  # validates
        with self._lock:
            self._raw[name] = data
            self._cache.pop(name, None)
        return name

    def unique_name(self, base):
        base = re.sub(r"[^A-Za-z0-9_\-]+", "_", model.image_stem(base) or "image").strip("_") or "image"
        name, n = f"{base}.png", 2
        while name in self._raw:
            name = f"{base}_{n}.png"
            n += 1
        return name

    def add_image(self, img, base="image"):
        name = self.unique_name(base)
        self.put_image(name, img)
        return name

    def put_image(self, name, img):
        name = model.image_name(name)
        data = vision.encode_png(img)
        with self._lock:
            self._raw[name] = data
            self._cache[name] = img
        return name

    def get(self, name):
        name = model.image_name(name)
        if not name:
            return None
        with self._lock:
            img = self._cache.get(name)
            raw = self._raw.get(name)
        if img is not None or raw is None:
            return img
        img = vision.decode_png(raw)
        with self._lock:
            self._cache[name] = img
        return img

    def remove(self, name):
        name = model.image_name(name)
        with self._lock:
            self._raw.pop(name, None)
            self._cache.pop(name, None)

    def copy(self):
        other = AssetStore()
        with self._lock:
            other._raw = dict(self._raw)
            other._cache = dict(self._cache)
        return other


# ---------------------------------------------------------------- zip helpers

def _write_zip(path, json_name, data, assets, only=None):
    folder = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(json_name, json.dumps(data, indent=2))
            for name in assets.names():
                if only is None or name in only:
                    z.writestr(f"images/{name}", assets.raw(name))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _read_zip(path, json_names):
    assets = AssetStore()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        jname = next((n for n in json_names if n in names), None)
        if jname is None:
            jname = next((n for n in names if n.lower().endswith(".json") and "/" not in n), None)
        if jname is None:
            raise ValueError("Package has no script.json inside")
        data = json.loads(z.read(jname).decode("utf-8-sig"))
        for n in names:
            low = n.lower()
            if n.endswith("/") or not re.search(r"\.(png|jpg|jpeg|bmp)$", low):
                continue
            base = n.replace("\\", "/").split("/")[-1]
            try:
                img = vision.decode_png(z.read(n))
            except ValueError:
                continue
            assets.put_image(base if low.endswith(".png") else model.image_stem(base) + ".png", img)
    return data, assets


# ---------------------------------------------------------------- scripts

def load_script(path):
    """Load a .clk/.clkpkg package or a .json script. Returns (script, assets)."""
    if zipfile.is_zipfile(path):
        data, assets = _read_zip(path, ["script.json"])
    else:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("format") == "clicker-recording":
            raise ValueError("This is a recording. Open it in the Macro Recorder tab.")
        assets = AssetStore()
        folder = os.path.dirname(os.path.abspath(path))
        for name in model.referenced_images(model.normalize_script(data)):
            for cand in (os.path.join(folder, "images", name), os.path.join(folder, name)):
                if os.path.isfile(cand):
                    with open(cand, "rb") as f:
                        assets.put_image(name, vision.decode_png(f.read()))
                    break
    if isinstance(data, dict) and data.get("format") == "clicker-recording":
        raise ValueError("This is a recording. Open it in the Macro Recorder tab.")
    script = model.normalize_script(data)
    return script, assets


def parse_script_text(text):
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    data = json.loads(text)
    return model.normalize_script(data)


def save_script(path, script, assets):
    data = model.copy_script(script)
    used = set(model.referenced_images(data))
    _write_zip(path, "script.json", data, assets, only=used)


# ---------------------------------------------------------------- recordings

def save_recording(path, events, options):
    data = {"format": "clicker-recording", "version": 2, "options": options, "events": events,
            "length_seconds": events[-1]["t"] if events else 0}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def load_recording(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    events = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events, list):
        raise ValueError("Not a recording file")
    for e in events:
        if not isinstance(e, dict) or "t" not in e or "type" not in e:
            raise ValueError("Recording has malformed events")
    events.sort(key=lambda e: e["t"])
    return events, data.get("options") or {}


# ---------------------------------------------------------------- validation

def validate(script, assets):
    """Return a list of (level, message); level is 'ok', 'warn' or 'error'."""
    out = []
    steps = script["steps"]
    n = len(steps)
    if not n:
        return [("error", "The script has no steps")]
    missing = [name for name in model.referenced_images(script) if not assets.has(name)]
    total = len(model.referenced_images(script))
    if missing:
        out.append(("error", f"Missing images: {', '.join(missing[:4])}" + (" ..." if len(missing) > 4 else "")))
    elif total:
        out.append(("ok", f"All {total} image files present"))
    problems = []
    no_timeout = []
    seen = {}
    for i, st in enumerate(steps, 1):
        lab = str(st.get("label") or "").strip()
        if lab:
            if lab in seen:
                problems.append(f"Step {i}: label '{lab}' is already used by step {seen[lab]}")
            seen.setdefault(lab, i)
    _, block_err = model.match_blocks(steps)
    if block_err:
        problems.append(block_err)
    for i, st in enumerate(steps, 1):
        err = model.check_step(st, steps)
        if err:
            problems.append(f"Step {i}: {err}")
        w = st.get("wait") or {}
        if w.get("mode", "none") != "none" and "timeout_s" not in w:
            no_timeout.append(str(i))
        if st["action"] in ("Click Image", "Wait for Image", "Wait for Image to Vanish",
                            "Wait for Pixel Color", "Wait for Screen to Settle") and "timeout_s" not in st:
            no_timeout.append(str(i))
        if w.get("on_timeout") == "goto" and not w.get("goto"):
            problems.append(f"Step {i}: timeout jump has no step number")
    if problems:
        out.extend(("error", p) for p in problems[:5])
    else:
        out.append(("ok", "Every step has a valid action"))
    if no_timeout:
        out.append(("warn", f"Step {', '.join(sorted(set(no_timeout), key=int))} has no timeout, defaults applied"))
    try:
        model.resolve_target(steps, script.get("error_handler"))
    except ValueError as e:
        out.append(("error", f"Error handler: {e}"))
    if any(st["action"] == "Read Text" for st in steps):
        problem = vision.ocr_problem()
        if problem:
            out.append(("warn", f"Read Text steps will fail: {problem}"))
    scr = script.get("screen")
    if scr:
        try:
            cur = vision.display_info()
            same = (int(scr.get("width", 0)) == cur["width"] and int(scr.get("height", 0)) == cur["height"]
                    and int(scr.get("scale", 100)) == cur["scale"])
            label = f"Built for {scr.get('width')} x {scr.get('height')} at {scr.get('scale', 100)}%"
            if same:
                out.append(("ok", label + ", matches this screen"))
            else:
                out.append(("warn", label + f"; this screen is {cur['width']} x {cur['height']} at {cur['scale']}%"))
        except Exception:
            pass
    return out


def screen_matches(script):
    scr = script.get("screen")
    if not scr:
        return None
    cur = vision.display_info()
    return (int(scr.get("width", 0)) == cur["width"] and int(scr.get("height", 0)) == cur["height"]
            and int(scr.get("scale", 100)) == cur["scale"])


# ---------------------------------------------------------------- settings

def data_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, "Clicker")
    else:
        path = os.path.join(os.path.expanduser("~"), ".clicker")
    os.makedirs(path, exist_ok=True)
    return path


DEFAULT_HOTKEYS = {
    "add_action": "F6", "script_toggle": "F7", "emergency": "F8",
    "rec_toggle": "F9", "play_toggle": "F10", "pause": "F11",
}


def load_settings():
    path = os.path.join(data_dir(), "settings.json")
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    hk = dict(DEFAULT_HOTKEYS)
    hk.update(data.get("hotkeys") or {})
    data["hotkeys"] = hk
    data.setdefault("recent", [])
    data.setdefault("recorder", {})
    return data


def save_settings(settings):
    path = os.path.join(data_dir(), "settings.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, path)


def add_recent(settings, path):
    path = os.path.abspath(path)
    rec = [p for p in settings.get("recent", []) if p != path]
    settings["recent"] = [path] + rec[:7]


def triggers_path():
    return os.path.join(data_dir(), "triggers.clktrig")


def save_triggers(path, rules, assets):
    used = set()
    for r in rules:
        name = model.image_name((r.get("condition") or {}).get("image"))
        if name:
            used.add(name)
    _write_zip(path, "rules.json", {"format": "clicker-triggers", "version": 1, "rules": rules},
               assets, only=used)


def load_triggers(path):
    if not os.path.exists(path):
        return [], AssetStore()
    data, assets = _read_zip(path, ["rules.json"])
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError("Not a trigger rules file")
    return rules, assets
