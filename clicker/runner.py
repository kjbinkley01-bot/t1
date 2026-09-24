"""Background jobs: the action script runner and the shared pause/stop plumbing."""

import datetime
import os
import random
import re
import threading
import time

from . import inputs, model, storage, vision


class JobStopped(Exception):
    pass


class Job:
    """Thread with stop, user pause, and trigger hold support."""

    kind = "job"

    def __init__(self, emit):
        self.emit = emit
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._user_pause = False
        self._holds = 0
        self._rewind = 0
        self.thread = None
        self.status = "Idle"

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    @property
    def paused(self):
        return self._user_pause

    def start(self):
        self.thread = threading.Thread(target=self._main, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def pause(self):
        self._user_pause = True
        self.emit("state", "paused")

    def resume(self):
        self._user_pause = False
        self.emit("state", "running")

    def toggle_pause(self):
        self.resume() if self._user_pause else self.pause()

    def hold(self):
        with self._lock:
            self._holds += 1

    def release(self):
        with self._lock:
            self._holds = max(0, self._holds - 1)

    def rewind(self, steps):
        self._rewind = max(self._rewind, int(steps))

    def check_stop(self):
        if self.stop_event.is_set():
            raise JobStopped("Stopped")

    def gate(self):
        """Block while paused or held. Returns seconds spent blocked."""
        if not (self._user_pause or self._holds):
            return 0.0
        t0 = time.monotonic()
        while (self._user_pause or self._holds) and not self.stop_event.is_set():
            self.stop_event.wait(0.05)
        return time.monotonic() - t0

    def sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self.check_stop()
            end += self.gate()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self.stop_event.wait(min(remaining, 0.05))

    def _main(self):
        raise NotImplementedError


def builtin_values():
    today = datetime.date.today()
    return {
        "today": today.isoformat(),
        "yesterday": (today - datetime.timedelta(days=1)).isoformat(),
        "tomorrow": (today + datetime.timedelta(days=1)).isoformat(),
        "time": datetime.datetime.now().strftime("%H:%M"),
    }


class Runner(Job):
    kind = "script"

    def __init__(self, script, assets, emit, inputs_map=None, speed=1.0, repeat=1,
                 random_delay_ms=0, dry_run=False, start_delay=0.0, label="Script"):
        super().__init__(emit)
        self.script = model.copy_script(script)
        self.assets = assets
        self.values = dict(inputs_map or {})
        self.speed = max(0.05, float(speed or 1.0))
        self.repeat = max(0, int(repeat))
        self.random_delay_ms = max(0, int(random_delay_ms or 0))
        self.dry_run = dry_run
        self.start_delay = start_delay
        self.label = label
        self.saved_pos = None
        self.held_buttons = []
        self.held_keys = []
        self.current = None
        self.result = None

    # ------------------------------------------------------------ helpers

    def log(self, msg):
        self.emit("log", msg)

    def substitute(self, text):
        base = builtin_values()
        sub = lambda t, v: re.sub(r"\{(\w+)\}", lambda m: str(v.get(m.group(1), m.group(0))), str(t or ""))  # noqa: E731
        vals = dict(base)
        vals.update({k: sub(v, base) for k, v in self.values.items()})
        return sub(text, vals)

    def _wait(self, cond, timeout_s, poll_ms, assets):
        checker = vision.Checker(cond, assets.get)
        ok, match, why = vision.wait_for(checker, timeout_s, poll_ms, self.stop_event, gate=self.gate)
        if why == "stopped":
            raise JobStopped("Stopped")
        return ok, match

    # ------------------------------------------------------------ main

    def _main(self):
        reason = "Finished"
        ok = False
        try:
            if self.start_delay > 0:
                self.emit("state", f"Starting in {self.start_delay:g} s")
                self.sleep(self.start_delay)
            self.emit("state", "running")
            run = 0
            while self.repeat == 0 or run < self.repeat:
                run += 1
                self.emit("run", run)
                self._run_steps(self.script, self.assets, 0)
                self.check_stop()
            ok = True
        except JobStopped as e:
            reason = str(e) or "Stopped"
        except Exception as e:  # report anything unexpected instead of dying silently
            reason = f"Error: {e}"
        finally:
            for b in self.held_buttons:
                inputs.release_button(b)
            for k in self.held_keys:
                inputs.release_key(k)
            vision.release_thread()
            self.result = (ok, reason)
            self.emit("done", (ok, reason))

    def _run_steps(self, script, assets, depth):
        steps = script["steps"]
        n = len(steps)
        handler = script.get("error_handler")
        loops = {}
        i = 0
        while i < n:
            self.check_stop()
            self.gate()
            if depth == 0 and self._rewind:
                i = max(0, i - self._rewind)
                self._rewind = 0
            step = steps[i]
            if depth == 0:
                self.current = i
                self.emit("step", i)
            if step.get("disabled"):
                i += 1
                continue
            nxt = self._exec_step(step, i, n, handler, assets, loops, depth)
            if nxt is None:
                i += 1
            elif 0 <= nxt < n:
                i = nxt
            elif nxt == n:
                break
            else:
                raise JobStopped(f"Step {i + 1} jumps to step {nxt + 1}, which does not exist")

    def _policy(self, step, i, n, handler, what):
        w = step.get("wait") or {}
        mode = w.get("on_timeout", "stop")
        msg = f"Step {i + 1} {what}"
        if mode == "skip":
            self.log(msg + ", skipped")
            return ("next", None)
        if mode == "retry":
            return ("retry", None)
        if mode == "goto":
            target = w.get("goto")
            if target and 1 <= int(target) <= n:
                self.log(f"{msg}, going to step {target}")
                return ("jump", int(target) - 1)
        if mode == "handler":
            if handler and 1 <= int(handler) <= n:
                self.log(f"{msg}, running error handler at step {handler}")
                return ("jump", int(handler) - 1)
        raise JobStopped(msg)

    def _exec_step(self, step, i, n, handler, assets, loops, depth):
        attempts = 0
        while True:
            res = self._attempt(step, i, assets, loops, depth)
            if res[0] != "fail":
                break
            pol = self._policy(step, i, n, handler, res[1])
            if pol[0] == "retry":
                attempts += 1
                if attempts <= 3:
                    self.log(f"Step {i + 1} {res[1]}, retry {attempts} of 3")
                    continue
                raise JobStopped(f"Step {i + 1} {res[1]} after 3 retries")
            res = pol
            break
        if res[0] == "next":
            return None
        return res[1]

    def _attempt(self, step, i, assets, loops, depth):
        w = step.get("wait") or {}
        if w.get("mode", "none") != "none":
            timeout = float(w.get("timeout_s", 30))
            ok, _ = self._wait(model.wait_to_condition(w), timeout, w.get("poll_ms", 250), assets)
            if not ok:
                return ("fail", f"timed out after {timeout:g} s ({model.describe_wait(w)})")
        delay = float(step.get("delay_ms") or 0)
        if self.random_delay_ms:
            delay += random.uniform(-self.random_delay_ms, self.random_delay_ms)
        self.sleep(max(0.0, delay) / 1000.0 / self.speed)
        back = None
        if step.get("cursor_back") and step["action"] in model.MOUSE_ACTIONS and not self.dry_run:
            back = inputs.position()
        res = ("next", None)
        try:
            reps = max(1, int(step.get("repeat") or 1))
            for r in range(reps):
                res = self._do(step, i, assets, loops, depth)
                if res[0] != "next":
                    break
                if r < reps - 1:
                    self.sleep(max(0.03, delay / 1000.0 / self.speed))
        finally:
            if back:
                inputs.move_to(*back)
        return res

    def _goto(self, value):
        if not value:
            return ("next", None)
        return ("jump", int(value) - 1)

    def _do(self, step, i, assets, loops, depth):
        a = step["action"]
        x, y = step.get("x"), step.get("y")
        has_xy = x is not None and y is not None
        dry = self.dry_run
        tag = f"Step {i + 1} {a}"

        if a in model.CLICK_MAP:
            button, count, mods = model.CLICK_MAP[a]
            if dry:
                self.log(f"{tag} (dry run, not clicked)")
                if has_xy:
                    self.emit("highlight", (x - 8, y - 8, 17, 17))
                return ("next", None)
            if has_xy:
                inputs.move_to(x, y)
                time.sleep(0.01)
            inputs.click(button, count, mods)
            return ("next", None)

        if a in model.DRAG_MAP:
            button, begin = model.DRAG_MAP[a]
            if dry:
                return ("next", None)
            if begin:
                inputs.move_to(x, y)
                time.sleep(0.02)
                self.held_buttons.append(inputs.press_button(button))
            else:
                inputs.smooth_move(x, y)
                time.sleep(0.02)
                b = inputs.get_button(button)
                inputs.release_button(b)
                if b in self.held_buttons:
                    self.held_buttons.remove(b)
            return ("next", None)

        if a in model.SCROLL_MAP:
            dx, dy = model.SCROLL_MAP[a]
            amount = max(1, int(step.get("amount") or 1))
            if not dry:
                if has_xy:
                    inputs.move_to(x, y)
                    time.sleep(0.01)
                inputs.scroll(dx * amount, dy * amount)
            return ("next", None)

        if a == "Move Mouse":
            if not dry:
                inputs.move_to(x, y)
            return ("next", None)
        if a == "Move Mouse by Offset":
            if not dry:
                inputs.move_by(x or 0, y or 0)
            return ("next", None)
        if a == "Move Mouse by Angle":
            if not dry:
                inputs.move_by_angle(x or 0, y or 0)
            return ("next", None)
        if a == "Save Cursor Location":
            self.saved_pos = inputs.position()
            return ("next", None)
        if a == "Restore Cursor Location":
            if self.saved_pos and not dry:
                inputs.move_to(*self.saved_pos)
            return ("next", None)

        if a == "Type Text":
            text = self.substitute(step.get("text"))
            if dry:
                self.log(f"{tag}: would type {len(text)} characters")
            else:
                inputs.type_text(text)
            return ("next", None)
        if a in ("Send Keystroke", "Hot Key"):
            if not dry:
                inputs.press_combo(step.get("keys"))
            return ("next", None)
        if a == "Key Down":
            if not dry:
                self.held_keys.extend(inputs.key_down(step.get("keys")))
            return ("next", None)
        if a == "Key Up":
            if not dry:
                for k in inputs.key_up(step.get("keys")):
                    if k in self.held_keys:
                        self.held_keys.remove(k)
            return ("next", None)

        if a in model.IMAGE_ACTIONS:
            name = model.image_name(step.get("image"))
            if assets.get(name) is None:
                raise JobStopped(f"Step {i + 1}: image '{name}' is missing from the script")
            cond = {"kind": "image_vanishes" if a == "Wait for Image to Vanish" else "image_appears",
                    "image": name, "region": step.get("region"),
                    "confidence": step.get("confidence", 0.9), "grayscale": step.get("grayscale", False)}
            if a.startswith("If "):
                ok, m = self._wait(cond, 0, 100, assets)
                if m:
                    self.emit("highlight", m.rect)
                found = ok
                truth = found if a == "If Image Found" else not found
                self.log(f"{tag}: {'found' if found else 'not found'}")
                return self._goto(step.get("goto") if truth else step.get("else_goto"))
            timeout = float(step.get("timeout_s", 10))
            ok, m = self._wait(cond, timeout, 200, assets)
            if not ok:
                verb = "did not disappear" if a == "Wait for Image to Vanish" else "was not found"
                return ("fail", f"{model.image_stem(name)} {verb} within {timeout:g} s")
            if m:
                self.emit("highlight", m.rect)
            if a == "Click Image":
                cx, cy = m.center
                tx, ty = cx + (x or 0), cy + (y or 0)
                if dry:
                    self.log(f"{tag}: found at {tx}, {ty} ({int(m.score * 100)}%), not clicked")
                    return ("next", None)
                inputs.move_to(tx, ty)
                time.sleep(0.02)
                btn = step.get("button") or "left"
                if btn == "double":
                    inputs.click("left", 2)
                else:
                    inputs.click(btn, 1)
            return ("next", None)

        if a in ("Wait for Pixel Color", "If Pixel Color"):
            cond = {"kind": "pixel_is", "x": x, "y": y, "color": step.get("color"),
                    "tolerance": step.get("tolerance", 12)}
            if a == "If Pixel Color":
                ok, _ = self._wait(cond, 0, 100, assets)
                return self._goto(step.get("goto") if ok else step.get("else_goto"))
            timeout = float(step.get("timeout_s", 10))
            ok, _ = self._wait(cond, timeout, 100, assets)
            if not ok:
                return ("fail", f"pixel {x}, {y} did not turn {step.get('color')} within {timeout:g} s")
            return ("next", None)

        if a == "Wait for Screen to Settle":
            cond = {"kind": "region_stable", "region": step.get("region"),
                    "stable_ms": step.get("stable_ms", 800)}
            timeout = float(step.get("timeout_s", 10))
            ok, _ = self._wait(cond, timeout, 100, assets)
            if not ok:
                return ("fail", f"screen kept changing for {timeout:g} s")
            return ("next", None)

        if a == "Delay":
            self.sleep(float(step.get("ms") or 0) / 1000.0 / self.speed)
            return ("next", None)
        if a == "Random Delay":
            lo, hi = float(step.get("min_ms") or 0), float(step.get("max_ms") or 0)
            self.sleep(random.uniform(min(lo, hi), max(lo, hi)) / 1000.0 / self.speed)
            return ("next", None)
        if a == "Go to Step":
            return self._goto(step.get("goto"))
        if a == "Loop Back":
            times = int(step.get("times") or 1)
            count = loops.get(i, 0)
            if count < times:
                loops[i] = count + 1
                return self._goto(step.get("goto"))
            loops[i] = 0
            return ("next", None)
        if a == "Run Script File":
            if depth >= 5:
                raise JobStopped("Scripts are nested too deeply (more than 5 levels)")
            path = self.substitute(step.get("file"))
            if not os.path.isfile(path):
                return ("fail", f"script file not found: {path}")
            sub, sub_assets = storage.load_script(path)
            self.log(f"{tag}: running {os.path.basename(path)}")
            self._run_steps(sub, sub_assets, depth + 1)
            return ("next", None)
        if a == "Show Notification":
            self.emit("notify", self.substitute(step.get("message")))
            return ("next", None)
        if a == "Beep":
            inputs.beep()
            return ("next", None)
        if a == "Show Desktop":
            if not dry:
                inputs.show_desktop()
            return ("next", None)
        if a == "Stop Script":
            raise JobStopped(f"Stop Script reached at step {i + 1}")
        raise JobStopped(f"Step {i + 1}: unknown action '{a}'")
