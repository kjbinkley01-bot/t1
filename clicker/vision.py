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


def _match_once(h2, n2, ox, oy):
    nh, nw = n2.shape[:2]
    hh, hw = h2.shape[:2]
    if nh > hh or nw > hw or nh == 0 or nw == 0:
        return None
    channels = 1 if n2.ndim == 2 else n2.shape[2]
    if float(n2.reshape(-1, channels).std(axis=0).max()) < 1e-3:
        # Flat single color template (in every channel): normalized correlation is undefined.
        res = cv2.matchTemplate(h2, n2, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(res)
        rms = (min_val / (nw * nh * channels)) ** 0.5
        score, loc = 1.0 - rms / 255.0, min_loc
    else:
        res = cv2.matchTemplate(h2, n2, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        score, loc = float(max_val), max_loc
    return Match(int(loc[0] + ox), int(loc[1] + oy), int(nw), int(nh), round(float(score), 3))


_scaled_cache = {}
_scaled_lock = threading.Lock()


def scaled(img, factor):
    """Resize a template, cached so repeated polls stay cheap."""
    if abs(factor - 1.0) < 1e-3:
        return img
    key = (id(img), round(factor, 3))
    with _scaled_lock:
        hit = _scaled_cache.get(key)
        if hit is not None and hit[0] is img:
            return hit[1]
    h, w = img.shape[:2]
    nw, nh = max(1, int(round(w * factor))), max(1, int(round(h * factor)))
    out = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)
    with _scaled_lock:
        if len(_scaled_cache) > 256:
            _scaled_cache.clear()
        _scaled_cache[key] = (img, out)
    return out


def match_in(hay, needle, confidence=0.9, grayscale=False, ox=0, oy=0, scales=None):
    """Best match of needle in hay, or None if below confidence.

    scales: template size factors to try in order, e.g. [1.0, 1.25]. The first
    factor that clears the confidence wins, so put the most likely one first.
    """
    if needle is None or hay is None:
        return None
    if grayscale:
        hay = cv2.cvtColor(hay, cv2.COLOR_BGR2GRAY)
        needle = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)
    for f in scales or (1.0,):
        n2 = scaled(needle, float(f))
        if min(n2.shape[:2]) < 4 and abs(f - 1.0) > 1e-3:
            continue
        m = _match_once(hay, n2, ox, oy)
        if m is not None and m.score >= confidence:
            return m
    return None


def scale_candidates(factor=1.0, search=False):
    """Template scale factors to try: the expected one first, then a search band."""
    base = round(float(factor or 1.0), 3)
    out = [base]
    extra = [1.0]
    if search:
        extra += [base * f for f in (0.9, 1.1, 0.8, 1.25, 0.75, 1.5, 0.67)]
    for f in extra:
        f = round(f, 3)
        if f not in out:
            out.append(f)
    return out


def find_image(needle, region=None, confidence=0.9, grayscale=False, scales=None):
    hay, (ox, oy) = capture(region)
    return match_in(hay, needle, confidence, grayscale, ox, oy, scales)


# ---------------------------------------------------------------- text (OCR)

class OcrUnavailable(RuntimeError):
    pass


def _tesseract():
    try:
        import pytesseract
    except ImportError:
        raise OcrUnavailable("Reading text needs the pytesseract package (pip install pytesseract).")
    if sys.platform == "win32" and not getattr(_tesseract, "_located", False):
        import os
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            exe = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
            if os.path.isfile(exe):
                pytesseract.pytesseract.tesseract_cmd = exe
                break
        _tesseract._located = True
    return pytesseract


def ocr_problem():
    """None when text reading works, else a message saying what is missing."""
    try:
        pt = _tesseract()
        pt.get_tesseract_version()
        return None
    except OcrUnavailable as e:
        return str(e)
    except Exception:
        return ("Tesseract OCR is not installed. Install it from "
                "https://github.com/UB-Mannheim/tesseract/wiki (Windows) or your package manager.")


def ocr_image(img, mode="text"):
    """Read text from a BGR image. mode 'number' keeps digits, sign and decimal point."""
    pt = _tesseract()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h = gray.shape[0]
    if h < 40:  # small UI text reads far better enlarged
        f = 40.0 / max(1, h)
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    if float(gray.mean()) < 110:  # light text on dark background
        gray = 255 - gray
    config = "--psm 7" if gray.shape[0] < 120 else "--psm 6"
    if mode == "number":
        config += " -c tessedit_char_whitelist=0123456789.,-"
    try:
        text = pt.image_to_string(gray, config=config)
    except pt.TesseractNotFoundError:
        raise OcrUnavailable("Tesseract OCR is not installed. Install it from "
                             "https://github.com/UB-Mannheim/tesseract/wiki (Windows) or your package manager.")
    text = " ".join(text.split())
    if mode == "number":
        import re
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
        text = m.group(0).replace(",", "") if m else ""
    return text


def read_text(region=None, mode="text"):
    img, _ = capture(region)
    return ocr_image(img, mode)


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
                           bool(self.c.get("grayscale")), self.c.get("scales"))
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
