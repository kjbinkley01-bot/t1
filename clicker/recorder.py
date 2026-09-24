"""Macro recording, playback with variation, and conversion to action steps."""

import random
import threading
import time

try:
    from pynput import keyboard, mouse
    from pynput.keyboard import Key, KeyCode
    from pynput.mouse import Button
except ImportError:  # no display (tests, servers): window playback and conversion still work
    keyboard = mouse = Key = KeyCode = Button = None

from . import inputs, model, vision
from .runner import Job, JobStopped
from .target import WindowIO, WindowNotFound, recorded_vk
from .target import normalize as normalize_target

MOD_KEYS = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
}


def encode_key(key):
    if Key is not None and isinstance(key, Key):
        return {"key": key.name}
    return {"char": getattr(key, "char", None), "vk": getattr(key, "vk", None)}


def decode_key(ev):
    if ev.get("key"):
        return Key[ev["key"]]
    char, vk = ev.get("char"), ev.get("vk")
    if char and char.isprintable():
        return KeyCode.from_char(char)
    if vk is not None:
        return KeyCode.from_vk(vk)
    return KeyCode.from_char(char or " ")


def key_text(ev):
    """Readable key name for conversion: 'enter', 'a', 'f5'."""
    if ev.get("key"):
        return ev["key"]
    vk, char = ev.get("vk"), ev.get("char")
    if vk is not None and (48 <= vk <= 57 or 65 <= vk <= 90):
        return chr(vk).lower()
    if char and char.isprintable():
        return char
    return f"vk{vk}" if vk is not None else ""


class Recorder:
    def __init__(self, is_hotkey):
        self.is_hotkey = is_hotkey
        self.events = []
        self.active = False
        self._lock = threading.Lock()
        self._ml = None
        self._kl = None
        self.started = 0.0

    @property
    def count(self):
        return len(self.events)

    def start(self, clicks=True, moves=True, keys=True, move_interval=0.02):
        if self.active:
            return
        self.events = []
        self.opts = {"clicks": clicks, "moves": moves, "keys": keys}
        self._move_interval = move_interval
        self._last_move = -1.0
        self.started = time.monotonic()
        self._ml = mouse.Listener(on_move=self._on_move, on_click=self._on_click, on_scroll=self._on_scroll)
        self._kl = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._ml.start()
        self._kl.start()
        self.active = True

    def _add(self, ev):
        ev["t"] = round(time.monotonic() - self.started, 4)
        with self._lock:
            self.events.append(ev)

    def _on_move(self, x, y, injected=False):
        if injected or not self.opts["moves"]:
            return
        t = time.monotonic() - self.started
        if t - self._last_move >= self._move_interval:
            self._last_move = t
            self._add({"type": "move", "x": int(x), "y": int(y)})

    def _on_click(self, x, y, button, pressed, injected=False):
        if injected or not self.opts["clicks"]:
            return
        self._add({"type": "mouse_down" if pressed else "mouse_up",
                   "x": int(x), "y": int(y), "button": button.name})

    def _on_scroll(self, x, y, dx, dy, injected=False):
        if injected or not self.opts["clicks"]:
            return
        self._add({"type": "scroll", "x": int(x), "y": int(y), "dx": int(dx), "dy": int(dy)})

    def _on_press(self, key, injected=False):
        if injected or not self.opts["keys"] or self.is_hotkey(key):
            return
        self._add({"type": "key_down", **encode_key(key)})

    def _on_release(self, key, injected=False):
        if injected or not self.opts["keys"] or self.is_hotkey(key):
            return
        self._add({"type": "key_up", **encode_key(key)})

    def stop(self, trim_last_click=False):
        if not self.active:
            return self.events
        self.active = False
        self._ml.stop()
        self._kl.stop()
        with self._lock:
            events = sorted(self.events, key=lambda e: e["t"])
        if trim_last_click:
            downs = [i for i, e in enumerate(events) if e["type"] == "mouse_down"]
            if downs and all(e["type"] in ("move", "mouse_up") for e in events[downs[-1] + 1:]):
                events = events[:downs[-1]]
        while events and events[-1]["type"] == "move":
            events.pop()
        # drop key releases whose press happened before recording started
        down = set()
        cleaned = []
        for e in events:
            if e["type"] == "key_down":
                down.add(key_text(e))
            elif e["type"] == "key_up" and key_text(e) not in down:
                continue
            cleaned.append(e)
        self.events = cleaned
        return cleaned


MOUSE_EVENTS = ("move", "mouse_down", "mouse_up", "scroll")


def to_window(events, origin, size):
    """Screen positions -> positions inside a window's content area.

    Mouse events outside the window are dropped (a press and its release go together), keys are kept.
    Returns (events, dropped_count).
    """
    ox, oy = origin
    w, h = size
    out, dropped, skipped_downs = [], 0, set()
    for e in events:
        if e["type"] not in MOUSE_EVENTS:
            out.append(e)
            continue
        x, y = e["x"] - ox, e["y"] - oy
        inside = 0 <= x < w and 0 <= y < h
        if e["type"] == "mouse_up":
            if e.get("button") in skipped_downs:
                skipped_downs.discard(e.get("button"))
                dropped += 1
                continue
            x, y = min(max(x, 0), w - 1), min(max(y, 0), h - 1)  # a drag may end just outside
        elif not inside:
            if e["type"] == "mouse_down":
                skipped_downs.add(e.get("button"))
            dropped += 1
            continue
        out.append(dict(e, x=x, y=y))
    return out, dropped


class Player(Job):
    kind = "recording"

    def __init__(self, events, emit, repeat=1, speed_min=100, speed_max=100,
                 dx_min=0, dx_max=0, dy_min=0, dy_max=0, whole=True,
                 gap_min=0.0, gap_max=0.0, settle=False, start_delay=0.0,
                 target=None, recorded_in=None, target_backend=None):
        """target: play inside this window (background mode). recorded_in: the window the recording's
        positions are measured from (None = the screen). Positions are converted between the two."""
        super().__init__(emit)
        self.target = normalize_target(target)
        self.recorded_in = normalize_target(recorded_in)
        self.backend = target_backend
        self.io = None if self.target is None else WindowIO(self.target, backend=target_backend)
        self.offset = (0, 0)
        self.events = list(events)
        self.repeat = max(0, int(repeat))
        self.speed = (max(1.0, float(speed_min)), max(1.0, float(speed_max)))
        self.dx = (float(dx_min), float(dx_max))
        self.dy = (float(dy_min), float(dy_max))
        self.whole = whole
        self.gap = (max(0.0, float(gap_min)), max(0.0, float(gap_max)))
        self.settle = settle
        self.start_delay = start_delay
        self.held_keys = []
        self.held_buttons = []
        self.result = None

    @staticmethod
    def _rand(pair):
        lo, hi = min(pair), max(pair)
        return random.uniform(lo, hi)

    def _play(self, ev, dx, dy):
        if self.io is not None:
            self._play_window(ev, dx, dy)
            return
        t = ev["type"]
        if t in ("move", "mouse_down", "mouse_up", "scroll"):
            inputs.move_to(ev["x"] + dx, ev["y"] + dy)
        if t == "mouse_down":
            b = Button[ev["button"]]
            inputs.mouse_ctl.press(b)
            self.held_buttons.append(b)
        elif t == "mouse_up":
            b = Button[ev["button"]]
            inputs.mouse_ctl.release(b)
            if b in self.held_buttons:
                self.held_buttons.remove(b)
        elif t == "scroll":
            inputs.scroll(ev["dx"], ev["dy"])
        elif t == "key_down":
            k = decode_key(ev)
            inputs.kb_ctl.press(k)
            self.held_keys.append(k)
        elif t == "key_up":
            k = decode_key(ev)
            inputs.kb_ctl.release(k)
            if k in self.held_keys:
                self.held_keys.remove(k)

    def _play_window(self, ev, dx, dy):
        io, t = self.io, ev["type"]
        if t in MOUSE_EVENTS:
            io.move_to(ev["x"] + dx, ev["y"] + dy)
        if t == "mouse_down":
            self.held_buttons.append(io.press_button(ev["button"]))
        elif t == "mouse_up":
            io.release_button(ev["button"])
            if ev["button"] in self.held_buttons:
                self.held_buttons.remove(ev["button"])
        elif t == "scroll":
            io.scroll(ev["dx"], ev["dy"])
        elif t == "key_down":
            self.held_keys.append(io.vk_down(recorded_vk(ev, io.b.char_vk)))
        elif t == "key_up":
            vk = recorded_vk(ev, io.b.char_vk)
            io.vk_up(vk)
            if vk in self.held_keys:
                self.held_keys.remove(vk)

    def _place(self):
        """Find the target window and work out how recorded positions map onto where we play."""
        if self.io is not None:
            self.io.attach()
            vision.set_thread_source(self.io)
            if self.recorded_in is None:  # recorded on the screen: the window is assumed to be where it was
                ox, oy = self.io.client_origin()
                self.offset = (-ox, -oy)
        elif self.recorded_in is not None:  # recorded in a window, played on the whole screen
            ox, oy = WindowIO(self.recorded_in, backend=self.backend).client_origin()
            self.offset = (ox, oy)

    def _settle(self, x, y):
        cond = {"kind": "region_stable", "region": [int(x) - 100, int(y) - 100, 200, 200], "stable_ms": 300}
        checker = vision.Checker(cond, lambda n: None)
        vision.wait_for(checker, 10, 60, self.stop_event, gate=self.gate)

    def _main(self):
        ok, reason = False, "Finished"
        try:
            if self.start_delay > 0:
                self.emit("state", f"Starting in {self.start_delay:g} s")
                self.sleep(self.start_delay)
            self._place()
            self.emit("state", "running")
            ox, oy = self.offset
            run = 0
            while self.repeat == 0 or run < self.repeat:
                run += 1
                self.emit("run", run)
                speed = self._rand(self.speed) / 100.0
                dx, dy = self._rand(self.dx), self._rand(self.dy)
                start = time.monotonic()
                shift = 0.0
                for ev in self.events:
                    self.check_stop()
                    target = start + shift + ev["t"] / speed
                    while True:
                        self.check_stop()
                        blocked = self.gate()
                        shift += blocked
                        target += blocked
                        remaining = target - time.monotonic()
                        if remaining <= 0:
                            break
                        self.stop_event.wait(min(remaining, 0.05))
                    if not self.whole and ev["type"] != "move":
                        dx, dy = self._rand(self.dx), self._rand(self.dy)
                    if self.settle and ev["type"] == "mouse_down":
                        t0 = time.monotonic()
                        self._settle(ev["x"] + dx + ox, ev["y"] + dy + oy)
                        shift += time.monotonic() - t0
                    self._play(ev, int(round(dx)) + ox, int(round(dy)) + oy)
                if self.repeat == 0 or run < self.repeat:
                    self.sleep(self._rand(self.gap))
            ok = True
        except JobStopped as e:
            reason = str(e)
        except WindowNotFound as e:
            reason = str(e)
        except Exception as e:
            reason = f"Error: {e}"
        finally:
            io = self.io or inputs
            for k in self.held_keys:
                io.release_key(k)
            for b in self.held_buttons:
                io.release_button(b)
            vision.set_thread_source(None)
            vision.release_thread()
            self.result = (ok, reason)
            self.emit("done", (ok, reason))


# ---------------------------------------------------------------- conversion

_CLICK_NAMES = {
    ("left", ()): "Left Click", ("right", ()): "Right Click", ("middle", ()): "Middle Click",
    ("x1", ()): "X1 Button Click", ("x2", ()): "X2 Button Click",
    ("left", ("ctrl",)): "Ctrl + Click", ("left", ("shift",)): "Shift + Click",
    ("left", ("alt",)): "Alt + Click", ("left", ("ctrl", "shift")): "Ctrl + Shift + Click",
    ("left", ("alt", "ctrl")): "Ctrl + Alt + Click", ("right", ("shift",)): "Shift + Right Click",
    ("right", ("ctrl",)): "Ctrl + Right Click",
}


def recording_to_steps(events):
    steps = []
    last_t = 0.0
    pending = None
    mods = set()
    last_click = None  # (step, t, x, y)

    def delay_from(t):
        return max(0, int(round((t - last_t) * 1000)))

    def add(step, t):
        nonlocal last_t
        steps.append(step)
        last_t = t
        return step

    for ev in events:
        typ = ev["type"]
        if typ == "mouse_down":
            pending = ev
        elif typ == "mouse_up" and pending and pending.get("button") == ev.get("button"):
            dist = max(abs(ev["x"] - pending["x"]), abs(ev["y"] - pending["y"]))
            btn = ev.get("button", "left")
            if dist <= 6:
                if (last_click and btn == "left" and not mods
                        and pending["t"] - last_click[1] < 0.45
                        and max(abs(pending["x"] - last_click[2]), abs(pending["y"] - last_click[3])) <= 6
                        and last_click[0]["action"] in ("Left Click", "Double Click")):
                    st = last_click[0]
                    st["action"] = "Double Click" if st["action"] == "Left Click" else "Triple Click"
                    last_t = ev["t"]
                    last_click = (st, ev["t"], ev["x"], ev["y"])
                else:
                    key = (btn, tuple(sorted(m for m in mods if m != "win")))
                    name = _CLICK_NAMES.get(key) or _CLICK_NAMES.get((btn, ()), "Left Click")
                    st = model.new_step(name)
                    st.update(x=pending["x"], y=pending["y"], delay_ms=delay_from(pending["t"]))
                    add(st, ev["t"])
                    last_click = (st, ev["t"], ev["x"], ev["y"])
            else:
                begin = "Begin Right Dragging" if btn == "right" else "Begin Dragging"
                end = "End Right Dragging" if btn == "right" else "End Dragging"
                st = model.new_step(begin)
                st.update(x=pending["x"], y=pending["y"], delay_ms=delay_from(pending["t"]))
                add(st, pending["t"])
                st = model.new_step(end)
                st.update(x=ev["x"], y=ev["y"], delay_ms=delay_from(ev["t"]))
                add(st, ev["t"])
                last_click = None
            pending = None
        elif typ == "scroll":
            action = "Scroll Up" if ev["dy"] > 0 else "Scroll Down" if ev["dy"] < 0 else (
                "Scroll Right" if ev["dx"] > 0 else "Scroll Left")
            amount = abs(ev["dy"]) or abs(ev["dx"]) or 1
            prev = steps[-1] if steps else None
            if (prev and prev["action"] == action and ev["t"] - last_t < 0.4
                    and prev.get("x") == ev["x"] and prev.get("y") == ev["y"]):
                prev["amount"] = prev.get("amount", 1) + amount
                last_t = ev["t"]
            else:
                st = model.new_step(action)
                st.update(x=ev["x"], y=ev["y"], amount=amount, delay_ms=delay_from(ev["t"]))
                add(st, ev["t"])
            last_click = None
        elif typ == "key_down":
            name = key_text(ev)
            if not name:
                continue
            if name in MOD_KEYS:
                mods.add(MOD_KEYS[name])
                continue
            held = sorted(m for m in mods if m != "shift")
            prev = steps[-1] if steps else None
            if held:
                combo = "+".join([m for m in ("ctrl", "alt", "shift", "win") if m in mods] + [name])
                st = model.new_step("Hot Key")
                st.update(keys=combo, delay_ms=delay_from(ev["t"]))
                add(st, ev["t"])
            elif len(name) == 1 or name == "space":
                ch = " " if name == "space" else (ev.get("char") or name)
                if prev and prev["action"] == "Type Text" and ev["t"] - last_t < 1.5:
                    prev["text"] += ch
                    last_t = ev["t"]
                else:
                    st = model.new_step("Type Text")
                    st.update(text=ch, delay_ms=delay_from(ev["t"]))
                    add(st, ev["t"])
            else:
                keys = ("shift+" + name) if "shift" in mods else name
                st = model.new_step("Send Keystroke")
                st.update(keys=keys, delay_ms=delay_from(ev["t"]))
                add(st, ev["t"])
            last_click = None
        elif typ == "key_up":
            name = key_text(ev)
            if name in MOD_KEYS:
                mods.discard(MOD_KEYS[name])
    for st in steps:
        st["delay_ms"] = min(st["delay_ms"], 60000)
    return steps
