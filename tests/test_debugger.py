"""Debugger hooks in the runner: breakpoints, single steps, run to, start at."""

import threading
import time

from clicker.runner import Runner
from clicker.storage import AssetStore
from helpers import S, script


def start(sc, **kw):
    events = []
    r = Runner(sc, AssetStore(), lambda k, p=None: events.append((k, p)), speed=50)
    for k, v in kw.items():
        setattr(r, k, v)
    t = threading.Thread(target=r._main)
    t.start()
    return r, t, events


def wait_debug(events, n, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hits = [p for k, p in events if k == "debug"]
        if len(hits) >= n:
            return hits[n - 1]
        time.sleep(0.01)
    raise AssertionError(f"no debug pause #{n}: {events[-5:]}")


def typed(fake_inputs):
    return [c[1] for c in fake_inputs.calls if c[0] == "type"]


def test_breakpoint_then_step_then_continue(fake_inputs, screen):
    sc = script(S("Type Text", text="a"), S("Type Text", text="b", bp=True), S("Type Text", text="c"),
                S("Type Text", text="d"))
    r, t, ev = start(sc)
    hit = wait_debug(ev, 1)
    assert hit == {"step": 1, "why": "breakpoint"} and typed(fake_inputs) == ["a"]
    r.step_once()
    assert wait_debug(ev, 2) == {"step": 2, "why": "step"}
    assert typed(fake_inputs) == ["a", "b"]
    r.resume()
    t.join(3)
    assert typed(fake_inputs) == ["a", "b", "c", "d"] and r.result[0]


def test_run_to_and_start_at(fake_inputs, screen):
    sc = script(*[S("Type Text", text=str(k)) for k in range(5)])
    r, t, ev = start(sc, start_at=2, run_to=3)
    assert wait_debug(ev, 1) == {"step": 3, "why": "run to"}
    assert typed(fake_inputs) == ["2"]
    r.stop()
    t.join(3)
    assert typed(fake_inputs) == ["2"] and r.result == (False, "Stopped")


def test_breakpoints_can_change_while_running(fake_inputs, screen):
    sc = script(S("Type Text", text="a", bp=True), S("Type Text", text="b"), S("Type Text", text="c"))
    r, t, ev = start(sc)
    wait_debug(ev, 1)
    r.breakpoints.add(2)
    r.resume()
    assert wait_debug(ev, 2)["step"] == 2
    r.breakpoints.clear()
    r.resume()
    t.join(3)
    assert r.result[0] and typed(fake_inputs) == ["a", "b", "c"]
