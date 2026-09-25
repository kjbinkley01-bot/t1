"""Background jobs: the action script runner and the shared pause/stop plumbing."""

import datetime
import os
import random
import re
import shlex
import subprocess
import sys
import threading
import time
import webbrowser

from . import clipboard, datafile, history, inputs, model, runlog, storage, target, vision


PROGRESS_MIN_S = 0.15  # shorter pauses would only flicker a progress bar


class JobStopped(Exception):
    """The run ended on purpose: the user stopped it or a Stop Script step."""


class ScriptFailed(JobStopped):
    """The run could not go on: a timeout, a missing image, a bad jump..."""


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
        self._last_yield = time.monotonic()
        self._pending_step = None
        self._step_sent_at = 0.0
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
        self.flush_step()
        t0 = time.monotonic()
        while (self._user_pause or self._holds) and not self.stop_event.is_set():
            self.stop_event.wait(0.05)
        return time.monotonic() - t0

    def show_step(self, i):
        """Tell the window which step is running, at most ~30 times a second.

        Fast loops run tens of thousands of steps a second; sending each one would
        flood the window. Anything that is about to wait sends the latest step first.
        """
        self._pending_step = i
        now = time.monotonic()
        if now - self._step_sent_at >= 0.033:
            self.flush_step(now)

    def flush_step(self, now=None):
        if self._pending_step is not None:
            self.emit("step", self._pending_step)
            self._pending_step = None
            self._step_sent_at = now or time.monotonic()

    def announce(self, seconds, kind):
        """Hook: a timed pause is starting (Runner shows it as a progress bar on the step)."""

    def sleep(self, seconds):
        if seconds > 0.01:
            self.flush_step()
        if seconds >= PROGRESS_MIN_S:
            self.announce(seconds, "delay")
        self._last_yield = time.monotonic() + max(0.0, seconds)
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


_VAR = re.compile(r"\{(\w+)\}")


def substitute(text, values):
    """Replace {name} with values[name]; unknown names are left as typed."""
    return _VAR.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), str(text or ""))


def to_number(v):
    """float for things that look like numbers ("1,200", " 3.5 "), else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").strip().replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def fmt_number(f):
    return str(int(f)) if float(f).is_integer() else f"{f:g}"


def compare(left, op, right):
    """Compare two values: numerically when both are numbers, else as text."""
    ln, rn = to_number(left), to_number(right)
    if op in ("contains", "not contains"):
        found = str(right).lower() in str(left).lower()
        return found if op == "contains" else not found
    if ln is not None and rn is not None:
        a, b = ln, rn
    else:
        a, b = str(left).strip().lower(), str(right).strip().lower()
    if op in ("=", "=="):
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    raise ValueError(f"Unknown comparison '{op}'")


STRUCTURE_ONLY = {"Else", "End If", "Try", "On Error", "End Try"}  # these never wait before running


def open_target(what, args=""):
    """Open an app, file, folder or web address the way double-clicking it would."""
    what = str(what or "").strip()
    if not what:
        raise ValueError("nothing to open")
    if re.match(r"^[a-z][a-z0-9+.-]*://", what, re.I) or what.lower().startswith("www."):
        webbrowser.open(what if "://" in what else "https://" + what)
        return
    if args:
        subprocess.Popen([what] + shlex.split(args, posix=sys.platform != "win32"))
    elif sys.platform == "win32":
        os.startfile(what)  # noqa: S606 (the user's own script)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", what])
    else:
        subprocess.Popen(["xdg-open", what] if os.path.exists(what) else [what])


def screenshot_path(raw):
    """Where Save Screenshot writes: a folder (timestamped name), a file, or the default folder."""
    stamp = datetime.datetime.now().strftime("shot_%Y%m%d-%H%M%S-%f")[:-3] + ".png"
    raw = str(raw or "").strip()
    if not raw:
        return os.path.join(storage.data_dir(), "screenshots", stamp)
    if os.path.isdir(raw) or raw.endswith(("/", "\\")):
        return os.path.join(raw, stamp)
    return raw if os.path.splitext(raw)[1] else raw + ".png"


class _Frame:
    """Per step list state: labels, While pairs, loop counters, call stack."""

    def __init__(self, script, assets, depth):
        self.script = script
        self.steps = script["steps"]
        self.assets = assets
        self.depth = depth
        self.labels = model.label_map(self.steps)
        blocks, err = model.block_structure(self.steps)
        if err:
            raise ScriptFailed(err)
        self.pairs, self.ifs, self.tries = blocks["pairs"], blocks["ifs"], blocks["tries"]
        self.try_stack = []  # Try steps whose body is running (innermost last)
        self.loops = {}
        self.whiles = {}
        self.rows = {}   # For Each Row state by step index
        self.calls = []
        try:
            self.handler = model.resolve_target(self.steps, script.get("error_handler"), self.labels)
        except ValueError as e:
            raise ScriptFailed(f"Error handler: {e}")

    def target(self, value, i):
        try:
            return model.resolve_target(self.steps, value, self.labels)
        except ValueError as e:
            raise ScriptFailed(f"Step {i + 1}: {e}")


class Runner(Job):
    kind = "script"

    def __init__(self, script, assets, emit, inputs_map=None, speed=1.0, repeat=1,
                 random_delay_ms=0, dry_run=False, start_delay=0.0, label="Script",
                 log_dir=None, save_log=True, target_backend=None, path=None, history_path=None):
        super().__init__(emit)
        self.path = path
        self.target_backend = target_backend  # also used by the window steps
        # run history goes next to the logs when a log folder is given (tests), else to the data folder
        self.history_path = history_path or (os.path.join(log_dir, "history.jsonl") if log_dir else None)
        self.fail_step = None
        self.started_at = None
        # debugging: pause before these top level steps / the next step / one step; start somewhere else
        self.debug_step = False
        self.run_to = None
        self.start_at = 0
        self.script = model.copy_script(script)
        self.breakpoints = {i for i, st in enumerate(self.script["steps"]) if st.get("bp")}
        self.assets = assets
        self.values = dict(inputs_map or {})
        self.speed = max(0.05, float(speed or 1.0))
        self.repeat = max(0, int(repeat))
        self.random_delay_ms = max(0, int(random_delay_ms or 0))
        self.dry_run = dry_run
        self.start_delay = start_delay
        self.label = label
        self.log_dir = log_dir
        self.save_log = save_log
        self.saved_pos = None
        self.held_buttons = []
        self.held_keys = []
        self.current = None
        self.result = None
        self.run_log = None
        self.scales = None
        self.last_region = None
        self.run_number = 0
        self._last_yield = time.monotonic()
        self.seen = {}  # where each image was last found, so the next search starts there
        # background mode: input and screen checks aim at one window instead of the whole desktop
        self.target = target.normalize((self.script.get("settings") or {}).get("target"))
        self.io = inputs if self.target is None else target.WindowIO(self.target, backend=target_backend)
        st = self.script.get("settings") or {}
        self.restarts = max(0, int(st.get("restart_on_failure") or 0))
        self.restart_delay = max(0.0, float(st.get("restart_delay_s", 3) or 0))

    # ------------------------------------------------------------ helpers

    def log(self, msg):
        self.emit("log", msg)
        self.note(msg)

    def note(self, msg, detail=False):
        """Write to the run log file only."""
        if self.run_log:
            self.run_log.write(msg, detail)

    def substitute(self, text):
        base = builtin_values()
        base["run"] = str(self.run_number)
        vals = dict(base)
        vals.update({k: substitute(v, base) for k, v in self.values.items()})
        return substitute(text, vals)

    def _scale_setup(self):
        """Template scale factors: follow the display scaling the script was built on."""
        factor = 1.0
        scr = self.script.get("screen") or {}
        try:
            built = int(scr.get("scale") or 0)
            if built:
                factor = vision.scale_percent() / float(built)
        except Exception:
            factor = 1.0
        search = bool((self.script.get("settings") or {}).get("scale_search"))
        self.scales = vision.scale_candidates(factor, search)
        if factor != 1.0:
            self.note(f"Display scaling differs from when the script was built; images scaled x{factor:.2f}")

    def _cond(self, cond):
        if cond.get("kind") in ("image_appears", "image_vanishes") and self.scales:
            cond = dict(cond, scales=self.scales)
        if cond.get("region"):
            self.last_region = cond["region"]
        return cond

    def _wait(self, cond, timeout_s, poll_ms, assets):
        if timeout_s:
            self.flush_step()
        timed = (timeout_s or 0) >= PROGRESS_MIN_S
        if timed:
            self.announce(float(timeout_s), "wait")
        checker = vision.Checker(self._cond(cond), assets.get, self.seen)
        self.last_checker = checker
        ok, match, why = vision.wait_for(checker, timeout_s, poll_ms, self.stop_event, gate=self.gate)
        if timed:
            self.emit("progress", None)  # found early: the bar goes away instead of running to the timeout
        if why == "stopped":
            raise JobStopped("Stopped")
        return ok, match

    def announce(self, seconds, kind):
        if self.current is not None:
            self.emit("progress", {"step": self.current, "start": time.monotonic(), "duration": float(seconds),
                                   "kind": kind})

    def _highlight(self, rect):
        if self.target is not None:
            try:
                rect = self.io.to_screen(rect)
            except Exception:
                return
        self.emit("highlight", rect)

    def _attach_target(self):
        """Background mode: find the target window and read the screen from it on this thread."""
        if self.target is None:
            return
        try:
            self.io.attach()
        except target.WindowNotFound as e:
            raise ScriptFailed(str(e))
        vision.set_thread_source(self.io)
        self.note(f"Running in window: {target.describe(self.target)}")

    def _release_held(self):
        for b in self.held_buttons:
            self.io.release_button(b)
        for k in self.held_keys:
            self.io.release_key(k)
        self.held_buttons, self.held_keys = [], []

    # ------------------------------------------------------------ main

    def _open_log(self):
        if not self.save_log:
            return
        try:
            self.run_log = runlog.RunLog(self.script.get("name") or self.label, self.log_dir)
            info = ""
            try:
                d = vision.display_info()
                info = f", screen {d['width']} x {d['height']} at {d['scale']}%"
            except Exception:
                pass
            self.run_log.write(f"Run of '{self.script.get('name') or self.label}' ({len(self.script['steps'])} steps"
                               f"{', dry run' if self.dry_run else ''}{info})")
            self.emit("logfile", self.run_log.dir)
        except Exception:
            self.run_log = None

    def _failed(self, reason):
        if self.fail_step is None and self.current is not None:
            steps = self.script["steps"]
            if 0 <= self.current < len(steps):
                self.fail_step = (self.current, history.step_title(steps[self.current], self.current))
        self.note(f"FAILED: {reason}")
        if self.run_log:
            self.run_log.screenshot("failure", self.last_region)

    def _main(self):
        reason = "Finished"
        ok = False
        self.started_at = time.time()
        self._open_log()
        try:
            self._attach_target()
            self._scale_setup()
            if self.start_delay > 0:
                self.emit("state", f"Starting in {self.start_delay:g} s")
                self.sleep(self.start_delay)
            self.emit("state", "running")
            restarts_left = self.restarts
            while self.repeat == 0 or self.run_number < self.repeat:
                self.run_number += 1
                self.emit("run", self.run_number)
                self.note(f"Pass {self.run_number}")
                while True:
                    try:
                        self._run_steps(self.script, self.assets, 0)
                        break
                    except JobStopped as e:
                        if not isinstance(e, ScriptFailed) or self.stop_event.is_set() or restarts_left <= 0:
                            raise
                        why = str(e)
                    except Exception as e:
                        if self.stop_event.is_set() or restarts_left <= 0:
                            raise
                        why = f"Error: {e}"
                    restarts_left -= 1
                    self._failed(why)
                    self._release_held()
                    self.log(f"{why}. Restarting from step 1 in {self.restart_delay:g} s "
                             f"({restarts_left} restart{'s' if restarts_left != 1 else ''} left)")
                    self.sleep(self.restart_delay)
                self.check_stop()
            ok = True
        except ScriptFailed as e:
            reason = str(e) or "Failed"
            self._failed(reason)
        except JobStopped as e:
            reason = str(e) or "Stopped"
        except Exception as e:  # report anything unexpected instead of dying silently
            reason = f"Error: {e}"
            self._failed(reason)
        finally:
            self.flush_step()
            self._release_held()
            vision.set_thread_source(None)
            vision.release_thread()
            self.note(f"Result: {reason}")
            if self.run_log:
                self.run_log.close()
            self.result = (ok, reason)
            self._record_history(ok, reason)
            self.emit("done", (ok, reason))

    def _record_history(self, ok, reason):
        if not self.save_log:
            return
        result = "finished" if ok else ("stopped" if reason.startswith("Stop") and self.fail_step is None
                                        else "failed")
        step = self.fail_step if result == "failed" else None
        history.record({
            "v": 1, "ts": round(self.started_at or time.time(), 3),
            "script": self.script.get("name") or (os.path.splitext(os.path.basename(self.path))[0]
                                                  if self.path else self.label),
            "path": self.path, "result": result, "reason": reason,
            "seconds": round(time.time() - (self.started_at or time.time()), 2),
            "passes": self.run_number,
            "step": step[0] + 1 if step else None, "step_desc": step[1] if step else None,
            "dry_run": bool(self.dry_run),
            "window": target.describe(self.target) if self.target else None,
            "log_dir": self.run_log.dir if self.run_log else None,
        }, self.history_path)

    def _run_steps(self, script, assets, depth):
        fr = _Frame(script, assets, depth)
        steps = fr.steps
        n = len(steps)
        i = 0
        while i < n:
            self.check_stop()
            self.gate()
            self._breathe()
            if depth == 0 and self._rewind:
                i = max(0, i - self._rewind)
                self._rewind = 0
            if depth == 0 and self.start_at:
                i, self.start_at = min(self.start_at, n - 1), 0
            step = steps[i]
            if depth == 0:
                self.current = i
                self.show_step(i)
                if self.debug_step or i in self.breakpoints or self.run_to == i:
                    self._debug_pause(i)
            if step.get("disabled"):
                i += 1
                continue
            if self.run_log:
                self.note(f"{'  ' * depth}Step {i + 1} {step['action']}"
                          + (f" [{step['label']}]" if step.get("label") else ""), detail=True)
            try:
                res = self._exec_step(step, i, fr)
            except JobStopped as e:
                if not isinstance(e, ScriptFailed) or self.stop_event.is_set():
                    raise
                res = self._caught(fr, i, str(e))
            except Exception as e:  # an unexpected error inside a Try is caught like a failure
                if self.stop_event.is_set():
                    raise
                res = self._caught(fr, i, f"Error: {e}")
            kind, arg = res
            if kind == "next":
                i += 1
            elif kind == "jump":
                i = arg
            elif kind == "call":
                if len(fr.calls) >= model.MAX_CALL_DEPTH:
                    raise ScriptFailed(f"Step {i + 1}: subroutines nested more than {model.MAX_CALL_DEPTH} deep")
                fr.calls.append(i + 1)
                i = arg
            elif kind == "return":
                if not fr.calls:
                    break
                i = fr.calls.pop()
            elif kind == "end":
                break
            else:
                raise ScriptFailed(f"Step {i + 1}: unknown result {kind}")

    def _caught(self, fr, i, message):
        """A step failed: jump to the innermost On Error around it, or re-raise when there is none."""
        while fr.try_stack:
            t = fr.try_stack[-1]
            body_end = fr.tries[t]["catch"]
            if t < i < body_end:
                fr.try_stack.pop()
                self.values["error"] = message
                self.log(f"Step {i + 1} failed ({message}); handled by the Try at step {t + 1}")
                end = fr.tries[t]["end"]
                return ("jump", body_end + 1) if body_end != end else ("jump", end + 1)
            fr.try_stack.pop()  # a jump left that Try: it no longer applies
        raise ScriptFailed(message)

    def _check(self, step, i, fr):
        """Evaluate an If / Else If check."""
        c = step.get("check") or "variable"
        if c.startswith("image"):
            ok, m = self._wait(self._image_cond(step, i, fr.assets), 0, 100, fr.assets)
            if m:
                self._highlight(m.rect)
            return ok if c == "image found" else not ok
        if c == "pixel color":
            cond = {"kind": "pixel_is", "x": step.get("x"), "y": step.get("y"), "color": step.get("color"),
                    "tolerance": step.get("tolerance", 12)}
            ok, _ = self._wait(cond, 0, 100, fr.assets)
            return ok
        if c == "variable":
            return self._compare(step, i)
        if c == "text on screen":
            try:
                text = self._read_screen_text(dict(step, var=""))
            except vision.OcrUnavailable as e:
                raise ScriptFailed(f"Step {i + 1}: {e}")
            return compare(text, step.get("op") or "contains", self.substitute(step.get("value") or ""))
        if c in ("window open", "window not open"):
            hwnd = self._find_win(self.substitute(step.get("title") or ""), self.substitute(step.get("process") or ""))
            return bool(hwnd) == (c == "window open")
        raise ScriptFailed(f"Step {i + 1}: unknown check '{c}'")

    def _block_step(self, step, i, fr, tag):
        a = step["action"]
        if a == "If":
            b = i
            while True:  # this branch, then each Else If / Else in turn
                act = fr.steps[b]["action"]
                if act == "End If":
                    self.log(f"{tag}: no branch matched")
                    return ("jump", b + 1)
                if act == "Else":
                    self.log(f"{tag}: else (step {b + 1})")
                    return ("jump", b + 1)
                if self._check(fr.steps[b], b, fr):
                    self.log(f"{tag}: step {b + 1} is true")
                    return ("jump", b + 1)
                b = fr.ifs[b]["next"]
        if a in ("Else If", "Else"):  # the branch above finished: skip the rest of the block
            return ("jump", fr.ifs[i]["end"] + 1)
        if a == "End If":
            return ("next", None)
        if a == "Try":
            fr.try_stack.append(i)
            return ("next", None)
        if a == "On Error":  # the Try part finished without failing
            if fr.try_stack and fr.tries.get(fr.try_stack[-1], {}).get("catch") == i:
                fr.try_stack.pop()
            return ("jump", fr.tries[i]["end"] + 1)
        if a == "End Try":
            for t in list(fr.try_stack)[::-1]:
                if fr.tries.get(t, {}).get("end") == i:
                    fr.try_stack.remove(t)
            return ("next", None)
        raise ScriptFailed(f"Step {i + 1}: unknown block step '{a}'")

    def _debug_pause(self, i):
        """Stop before step i until Continue or Step (a breakpoint, Run to here, or single stepping)."""
        why = "breakpoint" if i in self.breakpoints else ("step" if self.debug_step else "run to")
        self.debug_step = False
        if self.run_to == i:
            self.run_to = None
        self.flush_step()
        self._user_pause = True
        self.emit("debug", {"step": i, "why": why})
        self.emit("state", "paused")
        self.gate()
        self.check_stop()

    def step_once(self):
        """Run the next step, then pause again."""
        self.debug_step = True
        self.resume()

    def _breathe(self):
        """Give other threads a moment during long runs of zero delay steps.

        A tight loop would otherwise hold Python's interpreter lock and starve the
        window and the hotkey listener (so even the emergency stop key would lag).
        """
        now = time.monotonic()
        if now - self._last_yield > 0.015:
            time.sleep(0.002)
            self._last_yield = time.monotonic()

    def _policy(self, step, i, fr, what, attempts):
        """Decide what a failed step does. Returns a result tuple or ('retry', None)."""
        w = step.get("wait") or {}
        mode = w.get("on_timeout", "stop")
        msg = f"Step {i + 1} {what}"
        retries = max(0, int(w.get("retries", model.DEFAULT_RETRIES)))
        if mode in ("retry", "retry_handler") and attempts < retries:
            self.log(f"{msg}, retry {attempts + 1} of {retries}")
            return ("retry", None)
        if mode == "skip":
            self.log(msg + ", skipped")
            return ("next", None)
        if mode == "goto":
            target = fr.target(w.get("goto"), i)
            if target is not None:
                self.log(f"{msg}, going to step {target + 1}")
                return ("jump", target)
        if mode in ("handler", "retry_handler") and fr.handler is not None:
            self._failed(msg)
            self.log(f"{msg}, running error handler at step {fr.handler + 1}")
            return ("jump", fr.handler)
        if mode in ("retry", "retry_handler"):
            raise ScriptFailed(f"{msg} after {retries} retr{'y' if retries == 1 else 'ies'}")
        raise ScriptFailed(msg)

    def _exec_step(self, step, i, fr):
        attempts = 0
        while True:
            res = self._attempt(step, i, fr)
            if res[0] != "fail":
                return res
            pol = self._policy(step, i, fr, res[1], attempts)
            if pol[0] != "retry":
                return pol
            attempts += 1

    def _attempt(self, step, i, fr):
        w = step.get("wait") or {}
        if w.get("mode", "none") != "none":
            timeout = float(w.get("timeout_s", 30))
            ok, _ = self._wait(model.wait_to_condition(w), timeout, w.get("poll_ms", 250), fr.assets)
            if not ok:
                return ("fail", f"timed out after {timeout:g} s ({model.describe_wait(w)})")
        delay = 0.0 if step["action"] in STRUCTURE_ONLY else float(step.get("delay_ms") or 0)
        if self.random_delay_ms and delay:
            delay += random.uniform(-self.random_delay_ms, self.random_delay_ms)
        self.sleep(max(0.0, delay) / 1000.0 / self.speed)
        back = None
        if step.get("cursor_back") and step["action"] in model.MOUSE_ACTIONS and not self.dry_run:
            back = self.io.position()
        res = ("next", None)
        try:
            reps = max(1, int(step.get("repeat") or 1))
            for r in range(reps):
                res = self._do(step, i, fr)
                if res[0] != "next":
                    break
                if r < reps - 1:
                    self.sleep(max(0.03, delay / 1000.0 / self.speed))
        finally:
            if back:
                self.io.move_to(*back)
        return res

    def _goto(self, fr, value, i):
        t = fr.target(value, i)
        return ("next", None) if t is None else ("jump", t)

    def _image_cond(self, step, i, assets, kind="image_appears"):
        names = model.step_images(step)
        for name in names or [model.image_name(step.get("image"))]:
            if assets.get(name) is None:
                raise ScriptFailed(f"Step {i + 1}: image '{name}' is missing from the script")
        cond = {"kind": kind, "image": names[0] if names else "", "region": step.get("region"),
                "confidence": step.get("confidence", 0.9), "grayscale": step.get("grayscale", False)}
        if len(names) > 1:
            cond["images"] = names[1:]
            cond["image_mode"] = step.get("image_mode") or model.IMAGE_MODES[0]
        return cond

    def _var(self, step):
        return self.values.get(step.get("var"), "")

    def _compare(self, step, i):
        try:
            return compare(self._var(step), step.get("op", "="), self.substitute(step.get("value")))
        except ValueError as e:
            raise ScriptFailed(f"Step {i + 1}: {e}")

    def _while_true(self, step, i, fr):
        a = step["action"]
        if a in ("While Image Found", "While Image Not Found"):
            ok, m = self._wait(self._image_cond(step, i, fr.assets), 0, 100, fr.assets)
            if m:
                self._highlight(m.rect)
            return ok if a == "While Image Found" else not ok
        if a == "While Pixel Color":
            cond = {"kind": "pixel_is", "x": step.get("x"), "y": step.get("y"),
                    "color": step.get("color"), "tolerance": step.get("tolerance", 12)}
            ok, _ = self._wait(cond, 0, 100, fr.assets)
            return ok
        return self._compare(step, i)

    def _for_each(self, step, i, fr, tag):
        """Set one variable per column for the next row, or leave the loop when the rows run out."""
        end = fr.pairs[i]
        state = fr.rows.get(i)
        if state is None:
            path = self.substitute(step.get("file") or "")
            try:
                names, rows = datafile.read_table(path, self.substitute(step.get("sheet") or ""))
            except Exception as e:
                raise ScriptFailed(f"Step {i + 1}: {e}")
            start = max(1, int(step.get("start_row") or 1)) - 1
            rows = rows[start:]
            cap = int(step.get("max_rows") or 0)
            if cap:
                rows = rows[:cap]
            state = fr.rows[i] = {"names": names, "rows": rows, "next": 0, "start": start}
            self.log(f"{tag}: {len(rows)} row{'s' if len(rows) != 1 else ''} from {os.path.basename(path)}")
        k = state["next"]
        if k >= len(state["rows"]):
            del fr.rows[i]
            return ("jump", end + 1) if end + 1 < len(fr.steps) else ("end", None)
        state["next"] = k + 1
        for name, val in zip(state["names"], state["rows"][k]):
            self.values[name] = str(val)
        self.values["row"] = str(state["start"] + k + 1)
        self.values["row_count"] = str(state["start"] + len(state["rows"]))
        self.note(f"  row {self.values['row']}: " + ", ".join(
            f"{n}={model._short(v, 20)}" for n, v in list(zip(state["names"], state["rows"][k]))[:6]), detail=True)
        return ("next", None)

    def _read_screen_text(self, step):
        region = step.get("region")
        if region:
            self.last_region = region
        text = vision.read_text(region, step.get("mode") or "text")
        if step.get("var"):
            self.values[step["var"]] = text
        return text

    def _text_step(self, step, i, fr, tag):
        op = step.get("op") or "contains"
        want = self.substitute(step.get("value") or "")
        try:
            if step["action"] == "If Text on Screen":
                text = self._read_screen_text(step)
                ok = compare(text, op, want)
                self.log(f"{tag}: read \"{model._short(text, 40)}\", {'yes' if ok else 'no'}")
                return self._goto(fr, step.get("goto") if ok else step.get("else_goto"), i)
            timeout = float(step.get("timeout_s", 10))
            if timeout >= PROGRESS_MIN_S:
                self.flush_step()
                self.announce(timeout, "wait")
            end = time.monotonic() + timeout
            text = ""
            while True:
                text = self._read_screen_text(step)
                if compare(text, op, want):
                    self.emit("progress", None)
                    self.log(f"{tag}: read \"{model._short(text, 40)}\"")
                    return ("next", None)
                if time.monotonic() >= end:
                    self.emit("progress", None)
                    return ("fail", f"text was \"{model._short(text, 40)}\", not {op} \"{want}\" "
                                    f"within {timeout:g} s")
                self.sleep(0.25)
        except vision.OcrUnavailable as e:
            raise ScriptFailed(f"Step {i + 1}: {e}")
        except ValueError as e:
            raise ScriptFailed(f"Step {i + 1}: {e}")

    def _find_win(self, title, process):
        try:
            return target.find_window(title, process, self.target_backend)
        except target.WindowNotFound as e:
            raise ScriptFailed(f"{e} (window steps work on Windows)")

    def _wait_window(self, step, i, tag, title, process):
        timeout = float(step.get("timeout_s", 10))
        if timeout >= PROGRESS_MIN_S:
            self.flush_step()
            self.announce(timeout, "wait")
        end = time.monotonic() + timeout
        while True:
            hwnd = self._find_win(title, process)
            if hwnd:
                self.emit("progress", None)
                self.log(f"{tag}: {title or process} is open")
                return ("next", None)
            if time.monotonic() >= end:
                self.emit("progress", None)
                return ("fail", f"window '{title or process}' did not open within {timeout:g} s")
            self.sleep(0.25)

    def _window_step(self, step, i, fr, tag, dry):
        a = step["action"]
        title = self.substitute(step.get("title") or "")
        process = self.substitute(step.get("process") or "")
        if a == "Wait for Window":
            return self._wait_window(step, i, tag, title, process)
        hwnd = self._find_win(title, process)
        if a == "If Window Open":
            self.log(f"{tag}: {'open' if hwnd else 'not open'}")
            return self._goto(fr, step.get("goto") if hwnd else step.get("else_goto"), i)
        if not hwnd:
            return ("fail", f"window '{title or process}' is not open")
        if dry:
            self.log(f"{tag} (dry run)")
            return ("next", None)
        b = self.target_backend or target.default_backend()
        if a == "Focus Window":
            b.focus(hwnd)
            time.sleep(0.1)
        elif a == "Move Window":
            x, y, w, h = step["region"]
            b.move(hwnd, x, y, w, h)
        elif a == "Close Window":
            b.close(hwnd)
        self.log(tag)
        return ("next", None)

    def _do(self, step, i, fr):
        a = step["action"]
        assets = fr.assets
        x, y = step.get("x"), step.get("y")
        has_xy = x is not None and y is not None
        dry = self.dry_run
        tag = f"Step {i + 1} {a}"

        if a in model.CLICK_MAP:
            button, count, mods = model.CLICK_MAP[a]
            if dry:
                self.log(f"{tag} (dry run, not clicked)")
                if has_xy:
                    self._highlight((x - 8, y - 8, 17, 17))
                return ("next", None)
            if has_xy:
                self.io.move_to(x, y)
                time.sleep(0.01)
            self.io.click(button, count, mods)
            return ("next", None)

        if a in model.DRAG_MAP:
            button, begin = model.DRAG_MAP[a]
            if dry:
                return ("next", None)
            if begin:
                self.io.move_to(x, y)
                time.sleep(0.02)
                self.held_buttons.append(self.io.press_button(button))
            else:
                self.io.smooth_move(x, y)
                time.sleep(0.02)
                b = self.io.get_button(button)
                self.io.release_button(b)
                if b in self.held_buttons:
                    self.held_buttons.remove(b)
            return ("next", None)

        if a in model.SCROLL_MAP:
            dx, dy = model.SCROLL_MAP[a]
            amount = max(1, int(step.get("amount") or 1))
            if not dry:
                if has_xy:
                    self.io.move_to(x, y)
                    time.sleep(0.01)
                self.io.scroll(dx * amount, dy * amount)
            return ("next", None)

        if a == "Move Mouse":
            if not dry:
                self.io.move_to(x, y)
            return ("next", None)
        if a == "Move Mouse by Offset":
            if not dry:
                self.io.move_by(x or 0, y or 0)
            return ("next", None)
        if a == "Move Mouse by Angle":
            if not dry:
                self.io.move_by_angle(x or 0, y or 0)
            return ("next", None)
        if a == "Save Cursor Location":
            self.saved_pos = self.io.position()
            return ("next", None)
        if a == "Restore Cursor Location":
            if self.saved_pos and not dry:
                self.io.move_to(*self.saved_pos)
            return ("next", None)

        if a == "Type Text":
            text = self.substitute(step.get("text"))
            if dry:
                self.log(f"{tag}: would type {len(text)} characters")
            else:
                self.io.type_text(text)
            return ("next", None)
        if a in ("Send Keystroke", "Hot Key"):
            if not dry:
                self.io.press_combo(step.get("keys"))
            return ("next", None)
        if a == "Key Down":
            if not dry:
                self.held_keys.extend(self.io.key_down(step.get("keys")))
            return ("next", None)
        if a == "Key Up":
            if not dry:
                for k in self.io.key_up(step.get("keys")):
                    if k in self.held_keys:
                        self.held_keys.remove(k)
            return ("next", None)

        if a in model.WHILE_ACTIONS:
            end = fr.pairs[i]
            cap = int(step.get("max_loops") or 0)
            count = fr.whiles.get(i, 0)
            if self._while_true(step, i, fr) and not (cap and count >= cap):
                fr.whiles[i] = count + 1
                return ("next", None)
            if cap and count >= cap:
                self.log(f"{tag}: stopped looping after {cap} loops")
            fr.whiles[i] = 0
            return ("jump", end + 1) if end + 1 < len(fr.steps) else ("end", None)
        if a in ("End While", "Next Row"):
            return ("jump", fr.pairs[i])
        if a in model.IF_PARTS or a in model.TRY_PARTS:
            return self._block_step(step, i, fr, tag)
        if a == "For Each Row":
            return self._for_each(step, i, fr, tag)

        if a == "Count Image":
            cond = self._image_cond(step, i, assets)
            conf = float(cond["confidence"])
            region = cond.get("region")
            if region:
                self.last_region = region
            hits = []
            for name in model.step_images(step):
                hits += vision.find_all(assets.get(name), region, conf, bool(cond.get("grayscale")), self.scales)
            self.values[step.get("var")] = str(len(hits))
            if hits:
                x0 = min(m.x for m in hits)
                y0 = min(m.y for m in hits)
                x1 = max(m.x + m.w for m in hits)
                y1 = max(m.y + m.h for m in hits)
                self._highlight((x0, y0, x1 - x0, y1 - y0))
            self.log(f"{tag}: found {len(hits)}, {{{step.get('var')}}} = {len(hits)}")
            return ("next", None)

        if a in model.IMAGE_ACTIONS:
            cond = self._image_cond(step, i, assets,
                                    "image_vanishes" if a == "Wait for Image to Vanish" else "image_appears")
            name = cond["image"]
            if a.startswith("If "):
                ok, m = self._wait(cond, 0, 100, assets)
                if m:
                    self._highlight(m.rect)
                found = ok
                truth = found if a == "If Image Found" else not found
                self.log(f"{tag}: {'found' if found else 'not found'}")
                return self._goto(fr, step.get("goto") if truth else step.get("else_goto"), i)
            timeout = float(step.get("timeout_s", 10))
            ok, m = self._wait(cond, timeout, 200, assets)
            if not ok:
                verb = "did not disappear" if a == "Wait for Image to Vanish" else "was not found"
                return ("fail", f"{model.image_stem(name)} {verb} within {timeout:g} s")
            if m:
                self._highlight(m.rect)
            if len(model.step_images(step)) > 1 and m is not None:
                which = getattr(getattr(self, "last_checker", None), "matched_name", None)
                if which:
                    self.note(f"  matched {model.image_stem(which)}", detail=True)
            if a == "Click Image":
                cx, cy = m.center
                tx, ty = cx + (x or 0), cy + (y or 0)
                self.note(f"  found at {tx}, {ty} ({int(m.score * 100)}%)", detail=True)
                if dry:
                    self.log(f"{tag}: found at {tx}, {ty} ({int(m.score * 100)}%), not clicked")
                    return ("next", None)
                self.io.move_to(tx, ty)
                time.sleep(0.02)
                btn = step.get("button") or "left"
                if btn == "double":
                    self.io.click("left", 2)
                else:
                    self.io.click(btn, 1)
            return ("next", None)

        if a in ("Wait for Pixel Color", "If Pixel Color"):
            cond = {"kind": "pixel_is", "x": x, "y": y, "color": step.get("color"),
                    "tolerance": step.get("tolerance", 12)}
            if a == "If Pixel Color":
                ok, _ = self._wait(cond, 0, 100, assets)
                return self._goto(fr, step.get("goto") if ok else step.get("else_goto"), i)
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

        if a in ("Wait for Text", "If Text on Screen"):
            return self._text_step(step, i, fr, tag)
        if a in ("Wait for Window", "If Window Open", "Focus Window", "Move Window", "Close Window"):
            return self._window_step(step, i, fr, tag, dry)
        if a == "Open":
            what = self.substitute(step.get("file"))
            if dry:
                self.log(f"{tag}: would open {what}")
            else:
                try:
                    open_target(what, self.substitute(step.get("args") or ""))
                except Exception as e:
                    return ("fail", f"could not open {what}: {e}")
                self.log(f"{tag}: opened {what}")
            if step.get("title") and not dry:
                return self._wait_window(step, i, tag, str(step.get("title")), "")
            return ("next", None)
        if a == "Set Clipboard":
            text = self.substitute(step.get("value") or "")
            if not dry:
                try:
                    clipboard.set(text)
                except Exception as e:
                    return ("fail", f"could not set the clipboard: {e}")
            self.log(f"{tag}: \"{model._short(text, 40)}\"")
            return ("next", None)
        if a == "Copy Clipboard to Variable":
            try:
                text = clipboard.get()
            except Exception as e:
                return ("fail", f"could not read the clipboard: {e}")
            self.values[step["var"]] = text
            self.log(f"{tag}: {{{step['var']}}} = \"{model._short(text, 60)}\"")
            return ("next", None)
        if a == "Save Screenshot":
            region = step.get("region")
            try:
                img, _o = vision.capture(region)
                path = screenshot_path(self.substitute(step.get("file") or ""))
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "wb") as f:
                    f.write(vision.encode_png(img))
            except Exception as e:
                return ("fail", f"could not save the screenshot: {e}")
            self.values["last_screenshot"] = path
            self.log(f"{tag}: saved {path}")
            return ("next", None)

        if a == "Read Text":
            region = step.get("region")
            if region:
                self.last_region = region
            try:
                text = vision.read_text(region, step.get("mode") or "text")
            except vision.OcrUnavailable as e:
                raise ScriptFailed(f"Step {i + 1}: {e}")
            self.values[step["var"]] = text
            self.log(f"{tag}: {{{step['var']}}} = \"{model._short(text, 60)}\"")
            if region:
                self._highlight(tuple(region))
            return ("next", None)
        if a == "Set Variable":
            self.values[step["var"]] = self.substitute(step.get("value"))
            self.note(f"  {{{step['var']}}} = \"{model._short(self.values[step['var']], 60)}\"", detail=True)
            return ("next", None)
        if a == "Increment Variable":
            cur = to_number(self._var(step))
            if cur is None:
                if str(self._var(step)).strip():
                    raise ScriptFailed(f"Step {i + 1}: {{{step['var']}}} is \"{self._var(step)}\", not a number")
                cur = 0.0
            self.values[step["var"]] = fmt_number(cur + float(step.get("amount") or 0))
            self.note(f"  {{{step['var']}}} = {self.values[step['var']]}", detail=True)
            return ("next", None)
        if a == "If Variable":
            truth = self._compare(step, i)
            self.note(f"  {'true' if truth else 'false'} ({{{step['var']}}} is \"{self._var(step)}\")", detail=True)
            return self._goto(fr, step.get("goto") if truth else step.get("else_goto"), i)

        if a == "Delay":
            self.sleep(float(step.get("ms") or 0) / 1000.0 / self.speed)
            return ("next", None)
        if a == "Random Delay":
            lo, hi = float(step.get("min_ms") or 0), float(step.get("max_ms") or 0)
            self.sleep(random.uniform(min(lo, hi), max(lo, hi)) / 1000.0 / self.speed)
            return ("next", None)
        if a == "Go to Step":
            return self._goto(fr, step.get("goto"), i)
        if a == "Call Subroutine":
            t = fr.target(step.get("goto"), i)
            if t is None:
                raise ScriptFailed(f"{tag}: no step to call")
            return ("call", t)
        if a == "Return":
            return ("return", None)
        if a == "Loop Back":
            times = int(step.get("times") or 1)
            count = fr.loops.get(i, 0)
            if count < times:
                fr.loops[i] = count + 1
                return self._goto(fr, step.get("goto"), i)
            fr.loops[i] = 0
            return ("next", None)
        if a == "Run Script File":
            if fr.depth >= 5:
                raise ScriptFailed("Scripts are nested too deeply (more than 5 levels)")
            path = self.substitute(step.get("file"))
            if not os.path.isfile(path):
                return ("fail", f"script file not found: {path}")
            sub, sub_assets = storage.load_script(path)
            self.log(f"{tag}: running {os.path.basename(path)}")
            self._run_steps(sub, sub_assets, fr.depth + 1)
            return ("next", None)
        if a == "Show Notification":
            self.emit("notify", self.substitute(step.get("message")))
            return ("next", None)
        if a == "Beep":
            self.io.beep()
            return ("next", None)
        if a == "Show Desktop":
            if not dry:
                self.io.show_desktop()
            return ("next", None)
        if a == "Stop Script":
            raise JobStopped(f"Stop Script reached at step {i + 1}")
        raise ScriptFailed(f"Step {i + 1}: unknown action '{a}'")
