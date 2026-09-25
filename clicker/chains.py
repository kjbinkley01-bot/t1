"""Chains: run several scripts one after another, each as a card with its own options.

Build small scripts that each do one job (log in, collect rewards, farm...) and chain them. Every link
runs its script exactly as it would run on its own (its window, speed, pictures and run log), then:

    repeat    how many times to run that script in a row
    pause_s   seconds to wait before it starts
    on_fail   "stop" the chain, "skip" to the next link, or "retry" it (retries times) before stopping
    only_if   an expression like {gold} < 500: the card runs only when it is true (blank = always)

The chain itself can repeat (0 = until stopped). A chain file (.clkchain) only points at the scripts,
so editing a script changes every chain that uses it.
"""

import json
import os
import time

from . import expr, history, runner, storage

FORMAT = "clicker-chain"
EXT = ".clkchain"
ON_FAIL = [("stop", "Stop the chain"), ("skip", "Go on to the next"), ("retry", "Try again")]
ON_FAIL_LABEL = dict(ON_FAIL)


def new_chain(name="Untitled chain"):
    return {"format": FORMAT, "version": 1, "name": name, "repeat": 1, "links": []}


def new_link(path):
    return {"path": os.path.abspath(path), "repeat": 1, "pause_s": 0.0, "on_fail": "stop", "retries": 1,
            "only_if": ""}


def normalize(data):
    """A chain from a file (or anything close to one), with every field present and sane."""
    if not isinstance(data, dict) or data.get("format") not in (FORMAT, None) or not isinstance(
            data.get("links", []), list):
        raise ValueError("Not a Clicker chain")
    c = new_chain(str(data.get("name") or "Untitled chain"))
    c["repeat"] = max(0, int(data.get("repeat", 1) or 0))
    for ln in data.get("links", []):
        if not isinstance(ln, dict) or not ln.get("path"):
            continue
        link = new_link(ln["path"])
        link["repeat"] = max(1, int(ln.get("repeat", 1) or 1))
        link["pause_s"] = max(0.0, float(ln.get("pause_s", 0) or 0))
        link["on_fail"] = ln.get("on_fail") if ln.get("on_fail") in ON_FAIL_LABEL else "stop"
        link["retries"] = max(1, int(ln.get("retries", 1) or 1))
        link["only_if"] = str(ln.get("only_if") or "").strip()
        c["links"].append(link)
    return c


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return normalize(json.load(f))


def save(path, chain):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(normalize(chain), f, indent=2)
    os.replace(tmp, path)


def link_name(link):
    return os.path.splitext(os.path.basename(link["path"]))[0]


def describe_link(link):
    bits = [f"only if {link['only_if']}"] if link.get("only_if") else []
    if link.get("pause_s"):
        bits.append(f"wait {link['pause_s']:g} s")
    bits.append("once" if link.get("repeat", 1) == 1 else f"{link['repeat']} times")
    fail = link.get("on_fail", "stop")
    bits.append({"stop": "stop if it fails", "skip": "skip if it fails",
                 "retry": f"retry {link.get('retries', 1)}x if it fails"}[fail])
    return ", ".join(bits)


def problems(chain):
    """Reasons the chain can't start (missing or unreadable scripts)."""
    out = []
    if not chain["links"]:
        out.append("Add at least one script to the chain.")
    for i, ln in enumerate(chain["links"]):
        if not os.path.isfile(ln["path"]):
            out.append(f"Card {i + 1}: {ln['path']} is missing.")
        if ln.get("only_if"):
            try:
                expr.parse(ln["only_if"])
            except expr.ExprError as e:
                out.append(f"Card {i + 1}, only if: {e}.")
    return out


class ChainJob(runner.Job):
    """Runs the links in order on one thread; each run is an ordinary Runner, run in place."""

    kind = "chain"

    def __init__(self, chain, emit, path=None, inputs_map=None, save_log=True, log_dir=None, history_path=None,
                 target_backend=None):
        super().__init__(emit)
        self.chain = normalize(chain)
        self.path = path
        self.values = dict(inputs_map or {})
        self.save_log, self.log_dir, self.history_path = save_log, log_dir, history_path
        self.target_backend = target_backend
        self.label = self.chain["name"]
        # what the Runs panel and the mini status window show: one "step" per card
        self.script = {"name": self.chain["name"],
                       "steps": [{"action": f"Run {link_name(ln)}"} for ln in self.chain["links"]]}
        self.current = None
        self.sub = None
        self.run_number = 0
        self.repeat = self.chain["repeat"]
        self.started_at = None
        self.result = None
        self.outcomes = []   # (link index, ok, reason) for every run, in order

    # pause, hold and rewind act on the script that is running right now
    @property
    def paused(self):
        return self.sub.paused if self.sub is not None else self._user_pause

    def pause(self):
        self._user_pause = True
        if self.sub is not None:
            self.sub.pause()
        else:
            self.emit("state", "paused")

    def resume(self):
        self._user_pause = False
        if self.sub is not None:
            self.sub.resume()
        else:
            self.emit("state", "running")

    def hold(self):
        super().hold()
        if self.sub is not None:
            self.sub.hold()

    def release(self):
        super().release()
        if self.sub is not None:
            self.sub.release()

    def rewind(self, steps):
        if self.sub is not None:
            self.sub.rewind(steps)

    def _sub_emit(self, i):
        def emit(kind, payload=None):
            if kind in ("done", "run", "debug", "progress"):
                return  # the chain reports its own progress and end
            if kind == "step":
                self.emit("chain", {"link": i, "step": payload})
                return
            self.emit(kind, payload)
        return emit

    def _run_link(self, i, link):
        """One run of one card. Returns (ok, reason)."""
        script, assets = storage.load_script(link["path"])
        st = script.get("settings") or {}
        r = runner.Runner(script, assets, self._sub_emit(i), inputs_map=self.values, speed=st.get("speed", 1.0),
                          repeat=1, random_delay_ms=st.get("random_delay_ms", 0), label=link_name(link),
                          save_log=self.save_log, log_dir=self.log_dir, history_path=self.history_path,
                          target_backend=self.target_backend, path=link["path"])
        r.stop_event = self.stop_event          # stopping the chain stops the script
        r._user_pause = self._user_pause
        self.sub = r
        try:
            r._main()
        finally:
            self.sub = None
            self.values.update(r.values)        # variables carry on to the next card
        return r.result or (False, "Did not run")

    def _main(self):
        self.started_at = time.time()
        ok, reason = False, "Finished"
        try:
            self.emit("state", "running")
            while self.repeat == 0 or self.run_number < self.repeat:
                self.run_number += 1
                self.emit("run", self.run_number)
                for i, link in enumerate(self.chain["links"]):
                    self.current = i
                    self.show_step(i)
                    self.flush_step()
                    if link["pause_s"]:
                        self.emit("log", f"Card {i + 1}: waiting {link['pause_s']:g} s")
                        self.sleep(link["pause_s"])
                    self._link(i, link)
                self.check_stop()
            ok = True
        except runner.ScriptFailed as e:
            reason = str(e)
        except runner.JobStopped as e:
            reason = str(e) or "Stopped"
        except Exception as e:  # a script that can't be read, etc.
            reason = f"Error: {e}"
        finally:
            self.result = (ok, reason)
            self._record(ok, reason)
            self.emit("done", (ok, reason))

    def _link(self, i, link):
        name = link_name(link)
        if link.get("only_if"):
            vals = runner.builtin_values()
            vals["run"] = str(self.run_number)  # which time through the chain this is
            vals.update(self.values)
            try:
                go = expr.evaluate(link["only_if"], vals)
            except expr.ExprError as e:
                raise runner.ScriptFailed(f"Card {i + 1} ({name}), only if: {e}")
            if not go:
                self.emit("log", f"Card {i + 1} ({name}) skipped: {link['only_if']} is not true")
                self.emit("chain", {"link": i, "step": None, "skipped": True})
                return
        for n in range(link["repeat"]):
            tries = 1 + (link["retries"] if link["on_fail"] == "retry" else 0)
            for attempt in range(tries):
                self.check_stop()
                self.gate()
                self.emit("chain", {"link": i, "step": None, "pass": n + 1, "attempt": attempt + 1})
                ok, why = self._run_link(i, link)
                self.outcomes.append((i, ok, why))
                if ok:
                    break
                if self.stop_event.is_set():
                    raise runner.JobStopped("Stopped")
                if attempt < tries - 1:
                    self.emit("log", f"Card {i + 1} ({name}) failed: {why}. Trying again ({attempt + 2} of {tries})")
            else:
                if link["on_fail"] == "skip":
                    self.emit("log", f"Card {i + 1} ({name}) failed: {why}. Going on to the next card")
                    return
                raise runner.ScriptFailed(f"Card {i + 1} ({name}): {why}")

    def _record(self, ok, reason):
        if not self.save_log:
            return
        stopped = not ok and reason.startswith("Stop")
        history.record({
            "v": 1, "ts": round(self.started_at or time.time(), 3), "script": f"Chain: {self.chain['name']}",
            "path": self.path, "result": "finished" if ok else ("stopped" if stopped else "failed"),
            "reason": reason, "seconds": round(time.time() - (self.started_at or time.time()), 2),
            "passes": self.run_number, "step": (self.current + 1) if (not ok and self.current is not None) else None,
            "step_desc": self.script["steps"][self.current]["action"] if (not ok and self.current is not None)
            else None, "dry_run": False, "window": None, "log_dir": None,
        }, self.history_path)
