"""Screen trigger rules: WHEN a screen condition holds, THEN run outputs."""

import copy
import json
import threading
import time
import uuid

from . import inputs, model, vision
from .target import WindowIO, WindowNotFound
from .target import normalize as normalize_target

OUTPUT_TYPES = [
    ("click_match", "Click at match center"),
    ("click_at", "Click at position"),
    ("press_keys", "Press keys"),
    ("type_text", "Type text"),
    ("wait_ms", "Wait"),
    ("wait_vanish", "Wait until image vanishes"),
    ("run_script", "Run script file"),
    ("pause_script", "Pause running script"),
    ("resume_script", "Resume running script"),
    ("rewind", "Go back steps in running script"),
    ("stop_all", "Stop everything"),
    ("notify", "Show notification"),
    ("beep", "Play sound"),
    ("log", "Write to log"),
]
OUTPUT_LABEL = dict(OUTPUT_TYPES)
OUTPUT_ID = {v: k for k, v in OUTPUT_TYPES}
OUTPUT_HINT = {
    "click_match": "left, right, double or middle",
    "click_at": "x, y  (optionally x, y, right). Grab fills it from the cursor after 3 s.",
    "press_keys": "enter, esc, ctrl+s ...",
    "type_text": "Text to type",
    "wait_ms": "Milliseconds",
    "wait_vanish": "Timeout in seconds",
    "run_script": "Full path to a .clk file",
    "rewind": "How many steps back (1 repeats the current step)",
    "notify": "Message",
    "log": "Message",
}
NO_VALUE = {"pause_script", "resume_script", "stop_all", "beep"}

ACTIVE_MODES = [("script", "Only while a script runs"), ("always", "Always")]
ACTIVE_LABEL = dict(ACTIVE_MODES)
ACTIVE_ID = {v: k for k, v in ACTIVE_MODES}


def new_rule(name="New rule"):
    return {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "enabled": True,
        "condition": {"kind": "image_appears", "image": "", "region": None, "confidence": 0.9,
                      "grayscale": False, "x": None, "y": None, "color": "", "tolerance": 12,
                      "stable_ms": 800},
        "check_ms": 250,
        "hold_ms": 300,
        "outputs": [{"type": "click_match", "value": "left"}],
        "cooldown_s": 5,
        "max_fires": 0,
        "active": "always",   # new rules work on their own; "script" makes them helpers for a running script
        "pause_script": True,
    }


def describe_output(o):
    t = o.get("type")
    label = OUTPUT_LABEL.get(t, t)
    v = str(o.get("value") or "").strip()
    if t in NO_VALUE or not v:
        return label
    if t == "wait_ms":
        return f"Wait {v} ms"
    if t == "wait_vanish":
        return f"Wait until image vanishes, max {v} s"
    return f"{label}: {v}"


def describe_condition(c):
    k = c.get("kind")
    img = model.image_stem(c.get("image")) or "?"
    if c.get("images"):
        img += f" +{len(c['images'])}" + (" (all)" if c.get("image_mode") == model.IMAGE_MODES[1] else "")
    if k == "image_appears":
        return f"{img} appears"
    if k == "image_vanishes":
        return f"{img} disappears"
    if k == "pixel_is":
        return f"Pixel {c.get('x')}, {c.get('y')} is {c.get('color')}"
    if k == "pixel_changes":
        return f"Pixel {c.get('x')}, {c.get('y')} changes"
    if k == "region_changes":
        return "Region changes"
    if k == "region_stable":
        return "Region stops changing"
    return k or "?"


def describe_rule(r):
    outs = r.get("outputs") or []
    first = describe_output(outs[0]).lower() if outs else "nothing"
    more = f" (+{len(outs) - 1})" if len(outs) > 1 else ""
    return f"{describe_condition(r.get('condition') or {})}, then {first}{more}"


def check_rule(rule, assets):
    c = rule.get("condition") or {}
    k = c.get("kind")
    if k in ("image_appears", "image_vanishes") and not assets.has(c.get("image")):
        return "Capture or load the image to look for."
    if k in ("image_appears", "image_vanishes"):
        for n in c.get("images") or []:
            if not assets.has(n):
                return f"Image '{model.image_stem(n)}' is missing. Capture or load it again."
    if k in ("pixel_is", "pixel_changes") and (c.get("x") is None or c.get("y") is None):
        return "Enter the pixel position, or use Grab."
    if k == "pixel_is" and not c.get("color"):
        return "Enter the color to look for."
    if not rule.get("outputs"):
        return "Add at least one output."
    return None


class _State:
    def __init__(self, rule, assets):
        self.sig = json.dumps(rule.get("condition"), sort_keys=True)
        self.checker = vision.Checker(rule["condition"], assets.get)
        self.next_check = 0.0
        self.true_since = None
        self.last_fire = -1e9
        self.fires = 0
        self.error_at = -1e9


class TriggerEngine:
    """Watches the screen on a background thread.

    ctx must provide: script_running(), hold(), release(), pause(), resume(),
    rewind(n), stop_all(), run_script(path)
    """

    def __init__(self, get_rules, assets, emit, ctx, get_target=None, target_backend=None):
        """get_target() returns the window to watch and act in (background mode), or None for the screen."""
        self.get_rules = get_rules
        self.get_target = get_target or (lambda: None)
        self.target_backend = target_backend
        self.io = inputs
        self._io_target = None
        self._missing_at = -1e9
        self.assets = assets
        self.emit = emit
        self.ctx = ctx
        self.stop_event = threading.Event()
        self.thread = None
        self.states = {}
        self._reset_flag = False

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.running:
            return
        self.stop_event = threading.Event()
        self.states = {}
        self._waiting = set()   # rules skipped because they only act while a script runs (told once)
        self.thread = threading.Thread(target=self._main, daemon=True)
        self.thread.start()
        self.emit("log", ("Monitoring", f"Started with {self.active_count()} active rules", False))

    def stop(self):
        if self.running:
            self.stop_event.set()
            self.emit("log", ("Monitoring", "Stopped", False))

    def reset_counts(self):
        self._reset_flag = True

    def active_count(self):
        return sum(1 for r in self.get_rules() if r.get("enabled"))

    def _window(self, t):
        """A WindowIO for target t, reused while t stays the same."""
        if t is None:
            return None
        if self._io_target != t or not isinstance(self.io, WindowIO):
            self.io, self._io_target = WindowIO(t, backend=self.target_backend), t
        return self.io

    def _use_target(self):
        """Point this thread's input and screen reading at the chosen window. False while it isn't open."""
        t = normalize_target(self.get_target())
        if t is None:
            if self.io is not inputs:
                self.io, self._io_target = inputs, None
                vision.set_thread_source(None)
            return True
        io = self._window(t)
        try:
            io.attach()
        except WindowNotFound as e:
            now = time.monotonic()
            if now - self._missing_at > 10:
                self._missing_at = now
                self.emit("log", ("Monitoring", f"{e}. Waiting for it.", False))
            return False
        vision.set_thread_source(io)
        return True

    def _main(self):
        while not self.stop_event.is_set():
            if not self._use_target():
                self.stop_event.wait(1.0)
                continue
            if self._reset_flag:
                self._reset_flag = False
                for st in self.states.values():
                    st.fires = 0
            rules = [r for r in self.get_rules() if r.get("enabled")]
            now = time.monotonic()
            running = self.ctx.script_running()
            for rule in rules:
                if self.stop_event.is_set():
                    break
                rid = rule.get("id")
                st = self.states.get(rid)
                sig = json.dumps(rule.get("condition"), sort_keys=True)
                if st is None or st.sig != sig:
                    st = self.states[rid] = _State(rule, self.assets)
                if rule.get("active", "script") == "script" and not running:
                    st.true_since = None
                    if rid not in self._waiting:
                        self._waiting.add(rid)
                        self.emit("log", (rule.get("name") or "Rule", "Not checking: this rule only acts while a "
                                          "script runs, and none is. Set Active to Always to use it on its own.",
                                          False))
                    continue
                self._waiting.discard(rid)
                if now < st.next_check:
                    continue
                st.next_check = now + max(50, int(rule.get("check_ms") or 250)) / 1000.0
                try:
                    ok, match = st.checker.check()
                except Exception as e:
                    if now - st.error_at > 10:
                        st.error_at = now
                        self.emit("log", (rule.get("name"), f"Check failed: {e}", False))
                    continue
                if not ok:
                    st.true_since = None
                    continue
                if st.true_since is None:
                    st.true_since = now
                if (now - st.true_since) * 1000 < int(rule.get("hold_ms") or 0):
                    continue
                if now - st.last_fire < float(rule.get("cooldown_s") or 0):
                    continue
                limit = int(rule.get("max_fires") or 0)
                if limit and st.fires >= limit:
                    continue
                self._fire(rule, match, st, running)
                now = time.monotonic()
            self.stop_event.wait(0.02)
        vision.set_thread_source(None)
        vision.release_thread()

    def _fire(self, rule, match, st, running):
        name = rule.get("name") or "Rule"
        where = f" at {match.center[0]}, {match.center[1]}" if match else ""
        score = f" ({int(match.score * 100)}%)" if match and match.score < 1 else ""
        held = bool(rule.get("pause_script")) and running
        if held:
            self.ctx.hold()
        done = []
        try:
            if match and match.w < 4000:
                rect = match.rect
                if isinstance(self.io, WindowIO):
                    try:
                        rect = self.io.to_screen(rect)
                    except WindowNotFound:
                        pass
                self.emit("highlight", rect)
            for o in rule.get("outputs") or []:
                if self.stop_event.is_set():
                    break
                self._output(rule, o, match)
                done.append(describe_output(o))
        except Exception as e:
            self.emit("log", (name, f"Output failed: {e}", False))
        finally:
            if held:
                self.ctx.release()
        st.last_fire = time.monotonic()
        st.fires += 1
        st.true_since = None
        st.checker.reset()
        cool = rule.get("cooldown_s") or 0
        self.emit("log", (name, f"Matched{where}{score}. {'; '.join(done) or 'No outputs'}."
                          + (f" Cooldown {cool} s." if cool else ""), True))

    def _output(self, rule, o, match):
        t = o.get("type")
        v = str(o.get("value") or "").strip()
        io = self.io
        if t == "click_match":
            if not match:
                raise ValueError("no match position to click")
            back = io.position()
            io.move_to(*match.center)
            time.sleep(0.02)
            if v == "double":
                io.click("left", 2)
            else:
                io.click(v or "left", 1)
            time.sleep(0.02)
            io.move_to(*back)
        elif t == "click_at":
            parts = [p.strip() for p in v.split(",")]
            x, y = int(parts[0]), int(parts[1])
            btn = parts[2] if len(parts) > 2 and parts[2] else "left"
            back = io.position()
            io.move_to(x, y)
            time.sleep(0.02)
            if btn == "double":
                io.click("left", 2)
            else:
                io.click(btn, 1)
            io.move_to(*back)
        elif t == "press_keys":
            io.press_combo(v)
        elif t == "type_text":
            io.type_text(v)
        elif t == "wait_ms":
            self.stop_event.wait(max(0, int(float(v or 0))) / 1000.0)
        elif t == "wait_vanish":
            cond = copy.deepcopy(rule["condition"])
            cond["kind"] = "image_vanishes"
            checker = vision.Checker(cond, self.assets.get)
            ok, _, _ = vision.wait_for(checker, float(v or 10), 200, self.stop_event)
            if not ok:
                raise ValueError(f"image still visible after {v or 10} s")
        elif t == "run_script":
            self.ctx.run_script(v)
        elif t == "pause_script":
            self.ctx.pause()
        elif t == "resume_script":
            self.ctx.resume()
        elif t == "rewind":
            self.ctx.rewind(int(float(v or 1)))
        elif t == "stop_all":
            self.ctx.stop_all()
        elif t == "notify":
            self.emit("notify", v or rule.get("name"))
        elif t == "beep":
            io.beep()
        elif t == "log":
            self.emit("log", (rule.get("name"), v, False))
        else:
            raise ValueError(f"unknown output '{t}'")

    def test_rule(self, rule):
        """Check a rule once right now (called from the UI thread).

        Returns (ok, match); in background mode the match is in window positions.
        """
        t = normalize_target(self.get_target())
        io = WindowIO(t, backend=self.target_backend) if t else None
        if io:
            io.attach()
            vision.set_thread_source(io)
        try:
            checker = vision.Checker(rule["condition"], self.assets.get)
            ok, match = checker.check()
            if rule["condition"].get("kind") in ("pixel_changes", "region_changes"):
                time.sleep(0.3)
                ok, match = checker.check()
            return ok, match
        finally:
            if io:
                vision.set_thread_source(None)
