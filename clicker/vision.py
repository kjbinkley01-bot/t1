"""Screen capture, template matching, pixel checks and condition waiting."""

import sys
import threading
import time
from collections import namedtuple

import cv2
import numpy as np

try:
    import mss
except ImportError:  # allows tests without mss
    mss = None

from . import model

_local = threading.local()
_test_backend = None  # object with grab(x, y, w, h) and bounds() for tests


def set_test_backend(backend):
    global _test_backend
    _test_backend = backend


def _sct():
    s = getattr(_local, "sct", None)
    if s is None:
        s = mss.mss()
        _local.sct = s
    return s


def release_thread():
    """Close this thread's capture handle (call when a worker thread ends)."""
    s = getattr(_local, "sct", None)
    if s is not None:
        try:
            s.close()
        except Exception:
            pass
        _local.sct = None


def virtual_screen():
    """(left, top, width, height) covering all monitors."""
    if _test_backend:
        return _test_backend.bounds()
    m = _sct().monitors[0]
    return m["left"], m["top"], m["width"], m["height"]


def primary_screen():
    if _test_backend:
        return _test_backend.bounds()
    mons = _sct().monitors
    m = mons[1] if len(mons) > 1 else mons[0]
    return m["left"], m["top"], m["width"], m["height"]


def scale_percent():
    if sys.platform == "win32":
        try:
            import ctypes
            return int(ctypes.windll.shcore.GetScaleFactorForDevice(0))
        except Exception:
            return 100
    return 100


def display_info():
    _, _, w, h = primary_screen()
    return {"width": w, "height": h, "scale": scale_percent()}


def capture(region=None):
    """Return (BGR image, (origin x, origin y))."""
    if region is None:
        x, y, w, h = virtual_screen()
    else:
        x, y, w, h = (int(v) for v in region)
    if w <= 0 or h <= 0:
        raise ValueError("Region has no size")
    if _test_backend:
        img = _test_backend.grab(x, y, w, h)
    else:
        shot = _sct().grab({"left": x, "top": y, "width": w, "height": h})
        img = np.asarray(shot)[:, :, :3]
    return np.ascontiguousarray(img), (x, y)


def pixel(x, y):
    img, _ = capture((x, y, 1, 1))
    b, g, r = img[0, 0]
    return int(r), int(g), int(b)


def rgb_hex(rgb):
    return "#%02X%02X%02X" % tuple(rgb)


def color_distance(a, b):
    return max(abs(int(a[i]) - int(b[i])) for i in range(3))


# ---------------------------------------------------------------- images

def decode_png(data):
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Not a readable image")
    return img


def encode_png(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Could not encode image")
    return buf.tobytes()


def to_rgb(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


class Match(namedtuple("Match", "x y w h score")):
    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def rect(self):
        return self.x, self.y, self.w, self.h


def match_in(hay, needle, confidence=0.9, grayscale=False, ox=0, oy=0):
    if needle is None or hay is None:
        return None
    nh, nw = needle.shape[:2]
    hh, hw = hay.shape[:2]
    if nh > hh or nw > hw or nh == 0 or nw == 0:
        return None
    if grayscale:
        h2 = cv2.cvtColor(hay, cv2.COLOR_BGR2GRAY)
        n2 = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)
    else:
        h2, n2 = hay, needle
    if float(n2.std()) < 1e-3:
        # Flat single color template: normalized correlation is undefined.
        res = cv2.matchTemplate(h2, n2, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        channels = 1 if n2.ndim == 2 else n2.shape[2]
        rms = (min_val / (nw * nh * channels)) ** 0.5
        score, loc = 1.0 - rms / 255.0, min_loc
    else:
        res = cv2.matchTemplate(h2, n2, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        score, loc = float(max_val), max_loc
    if score < confidence:
        return None
    return Match(int(loc[0] + ox), int(loc[1] + oy), int(nw), int(nh), round(float(score), 3))


def find_image(needle, region=None, confidence=0.9, grayscale=False):
    hay, (ox, oy) = capture(region)
    return match_in(hay, needle, confidence, grayscale, ox, oy)


def frame_change(a, b):
    """Fraction of sampled pixels that differ noticeably between two frames."""
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    sa, sb = a[::3, ::3], b[::3, ::3]
    diff = cv2.absdiff(sa, sb).max(axis=2)
    return float(np.count_nonzero(diff > 18)) / diff.size


CHANGE_THRESHOLD = 0.003


class Checker:
    """Evaluates one screen condition. Keeps state for change detection."""

    def __init__(self, cond, get_image):
        self.c = dict(cond)
        self.get_image = get_image
        self.reset()

    def reset(self):
        self.base = None
        self.last = None
        self.still_since = None

    def _needle(self):
        name = model.image_name(self.c.get("image"))
        img = self.get_image(name) if name else None
        if img is None:
            raise ValueError(f"Image '{name or '(none)'}' is missing")
        return img

    def check(self):
        """Return (is_true, Match or None)."""
        k = self.c.get("kind")
        region = self.c.get("region") or None
        if k in ("image_appears", "image_vanishes"):
            m = find_image(self._needle(), region, float(self.c.get("confidence") or 0.9),
                           bool(self.c.get("grayscale")))
            if k == "image_appears":
                return m is not None, m
            return m is None, None
        if k in ("pixel_is", "pixel_changes"):
            x, y = int(self.c["x"]), int(self.c["y"])
            col = pixel(x, y)
            tol = int(self.c.get("tolerance") or 0)
            where = Match(x - 6, y - 6, 13, 13, 1.0)
            if k == "pixel_is":
                target = model.color_to_rgb(self.c["color"])
                return color_distance(col, target) <= tol, where
            if self.base is None:
                self.base = col
                return False, None
            return color_distance(col, self.base) > max(tol, 1), where
        if k in ("region_changes", "region_stable"):
            img, (ox, oy) = capture(region)
            h, w = img.shape[:2]
            where = Match(ox, oy, w, h, 1.0)
            if k == "region_changes":
                if self.base is None:
                    self.base = img
                    return False, None
                return frame_change(self.base, img) > CHANGE_THRESHOLD, where
            now = time.monotonic()
            if self.last is None or frame_change(self.last, img) > CHANGE_THRESHOLD:
                self.still_since = now
                self.last = img
                return False, None
            self.last = img
            stable = float(self.c.get("stable_ms") or 800) / 1000.0
            return now - self.still_since >= stable, where
        raise ValueError(f"Unknown condition '{k}'")


def wait_for(checker, timeout_s, poll_ms, stop_event, gate=None, hold_ms=0):
    """Poll a checker until true. Returns (ok, match, reason).

    reason is 'ok', 'timeout' or 'stopped'. gate() may block while paused and
    returns the seconds it blocked, which extends the deadline.
    """
    timeout_s = max(0.0, float(timeout_s or 0))
    poll = max(0.02, float(poll_ms or 250) / 1000.0)
    deadline = time.monotonic() + timeout_s
    true_since = None
    while True:
        if stop_event.is_set():
            return False, None, "stopped"
        if gate:
            deadline += gate()
            if stop_event.is_set():
                return False, None, "stopped"
        started = time.monotonic()
        ok, info = checker.check()
        now = time.monotonic()
        if ok:
            if true_since is None:
                true_since = now
            if (now - true_since) * 1000.0 >= (hold_ms or 0):
                return True, info, "ok"
        else:
            true_since = None
        if now >= deadline:
            return False, None, "timeout"
        spent = now - started
        stop_event.wait(max(0.0, min(poll - spent, deadline - now)) or 0.005)
