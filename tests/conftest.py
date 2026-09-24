"""Test setup: a fake mouse/keyboard and a fake screen, so no real input happens.

The real clicker.inputs needs a display (pynput); tests swap in FakeInputs before
anything imports it, and draw on FakeScreen instead of capturing the monitor.
"""

import os
import sys
import types

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class FakeInputs(types.ModuleType):
    def __init__(self):
        super().__init__("clicker.inputs")
        self.reset()

    def reset(self):
        self.calls = []
        self.pos = (0, 0)

    def _rec(self, *call):
        self.calls.append(call)

    def position(self):
        return self.pos

    def move_to(self, x, y):
        self.pos = (int(x), int(y))
        self._rec("move", int(x), int(y))

    def smooth_move(self, x, y, *a, **k):
        self.move_to(x, y)

    def move_by(self, dx, dy):
        self.move_to(self.pos[0] + dx, self.pos[1] + dy)

    def move_by_angle(self, a, d):
        self._rec("angle", a, d)

    def click(self, button="left", count=1, mods=(), hold_s=0.0):
        self._rec("click", button, count, tuple(mods), self.pos)

    def press_button(self, name):
        self._rec("press", name)
        return name

    def get_button(self, name):
        return name

    def release_button(self, b):
        self._rec("release", b)

    def scroll(self, dx, dy):
        self._rec("scroll", dx, dy)

    def type_text(self, text, interval=0.0):
        self._rec("type", text)

    def press_combo(self, text, hold=0.02):
        self._rec("keys", text)

    def key_down(self, text):
        self._rec("key_down", text)
        return [text]

    def key_up(self, text):
        self._rec("key_up", text)
        return [text]

    def release_key(self, k):
        self._rec("release_key", k)

    def show_desktop(self):
        self._rec("desktop")

    def beep(self):
        self._rec("beep")

    def clicks(self):
        return [c for c in self.calls if c[0] == "click"]


FAKE_INPUTS = FakeInputs()
sys.modules["clicker.inputs"] = FAKE_INPUTS
import clicker  # noqa: E402

clicker.inputs = FAKE_INPUTS

from clicker import vision  # noqa: E402


class FakeScreen:
    """An 800 x 600 BGR canvas that vision.capture reads from."""

    def __init__(self, w=800, h=600):
        self.img = np.full((h, w, 3), 245, np.uint8)

    def bounds(self):
        h, w = self.img.shape[:2]
        return 0, 0, w, h

    def grab(self, x, y, w, h):
        out = np.zeros((h, w, 3), np.uint8)
        H, W = self.img.shape[:2]
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 > x0 and y1 > y0:
            out[y0 - y:y1 - y, x0 - x:x1 - x] = self.img[y0:y1, x0:x1]
        return out

    def paste(self, tpl, x, y):
        h, w = tpl.shape[:2]
        self.img[y:y + h, x:x + w] = tpl

    def clear(self):
        self.img[:] = 245


def make_template(w=40, h=24, seed=1):
    """A distinctive textured patch that template matching can lock onto."""
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    img[:, : w // 3] = (30, 90, 200)
    return img


@pytest.fixture
def screen():
    s = FakeScreen()
    vision.set_test_backend(s)
    yield s
    vision.set_test_backend(None)


@pytest.fixture
def fake_inputs():
    FAKE_INPUTS.reset()
    return FAKE_INPUTS


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep settings and run logs out of the real user folder."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path), 1))
    return tmp_path
