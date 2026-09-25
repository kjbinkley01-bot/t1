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


def set_thread_source(source):
    """Make this thread's captures read from source (grab(x, y, w, h) and bounds()), e.g. one window.

    Background mode uses it so a script's image and pixel checks look at its target window. None
    goes back to the real screen.
    """
    _local.source = source


def _source():
    return getattr(_local, "source", None) or _test_backend


def _sct():
    s = getattr(_local, "sct", None)
    if s is None:
        s = _local.sct = (getattr(mss, "MSS", None) or mss.mss)()  # mss 10 renamed mss.mss
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
    src = _source()
    if src:
        return src.bounds()
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
    src = _source()
    if src:
        img = src.grab(x, y, w, h)
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


class Match(namedtuple("Match", "x y w h score")):
    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def rect(self):
        return self.x, self.y, self.w, self.h


def _score_map(hay, n):
    """Match score at every position (1 = identical).

    A flat one-color template has no pattern for normalized correlation to use, so it is scored
    by color distance instead.
    """
    nh, nw = n.shape[:2]
    channels = 1 if n.ndim == 2 else n.shape[2]
    if float(n.reshape(-1, channels).std(axis=0).max()) < 1e-3:
        res = cv2.matchTemplate(hay, n, cv2.TM_SQDIFF)
        return 1.0 - np.sqrt(np.maximum(res, 0) / (nw * nh * channels)) / 255.0
    return np.nan_to_num(cv2.matchTemplate(hay, n, cv2.TM_CCOEFF_NORMED), nan=-1.0, posinf=-1.0, neginf=-1.0)


def _templates(hay, needle, grayscale, scales):
    """(hay, template) for each size to try, in order, skipping sizes that cannot match."""
    if grayscale:
        hay = cv2.cvtColor(hay, cv2.COLOR_BGR2GRAY)
        needle = cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY)
    hh, hw = hay.shape[:2]
    for f in scales or (1.0,):
        n2 = scaled(needle, float(f))
        nh, nw = n2.shape[:2]
        if nh > hh or nw > hw or nh == 0 or nw == 0 or (min(nh, nw) < 4 and abs(f - 1.0) > 1e-3):
            continue
        yield hay, n2


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
    for h2, n2 in _templates(hay, needle, grayscale, scales):
        _, best, _, (x, y) = cv2.minMaxLoc(_score_map(h2, n2))
        if best >= confidence:
            nh, nw = n2.shape[:2]
            return Match(int(x + ox), int(y + oy), int(nw), int(nh), round(float(best), 3))
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


def match_all_in(hay, needle, confidence=0.9, grayscale=False, ox=0, oy=0, scales=None, limit=500):
    """Every place needle shows in hay (best first), without overlapping duplicates."""
    if needle is None or hay is None:
        return []
    for h2, n2 in _templates(hay, needle, grayscale, scales):
        nh, nw = n2.shape[:2]
        score = _score_map(h2, n2)
        ys, xs = np.nonzero(score >= confidence)
        if not len(xs):
            continue
        vals = score[ys, xs]
        if len(vals) > 20000:  # keep the strongest candidates; the rest are neighbours of these
            keep = np.argpartition(-vals, 20000)[:20000]
            ys, xs, vals = ys[keep], xs[keep], vals[keep]
        order = np.argsort(-vals)
        picked = []
        for k in order:
            x, y = int(xs[k]), int(ys[k])
            if any(abs(x - px) < nw * 0.6 and abs(y - py) < nh * 0.6 for px, py, _ in picked):
                continue
            picked.append((x, y, float(vals[k])))
            if len(picked) >= limit:
                break
        return [Match(x + ox, y + oy, nw, nh, round(s, 3)) for x, y, s in picked]
    return []


def find_all(needle, region=None, confidence=0.9, grayscale=False, scales=None, limit=500):
    hay, (ox, oy) = capture(region)
    return match_all_in(hay, needle, confidence, grayscale, ox, oy, scales, limit)


def survey(needle, region=None, confidence=0.9, grayscale=False, scales=None, margin=0.15, limit=40):
    """Every match at or above confidence, and the near misses a little below it (best first each).

    Near misses show why a step fails ("the button was there at 84%") or might click the wrong thing."""
    hay, (ox, oy) = capture(region)
    found = match_all_in(hay, needle, max(0.3, confidence - margin), grayscale, ox, oy, scales, limit)
    return [m for m in found if m.score >= confidence], [m for m in found if m.score < confidence]


# ---------------------------------------------------------------- text (OCR)

class OcrUnavailable(RuntimeError):
    pass


NO_TESSERACT = ("Tesseract OCR is not installed. Install it from "
                "https://github.com/UB-Mannheim/tesseract/wiki (Windows) or your package manager.")


def _tesseract_exe():
    """Path to the tesseract program (it is not on PATH after a default Windows install)."""
    import os
    import shutil
    exe = shutil.which("tesseract")
    if exe is None and sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            cand = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
            if os.path.isfile(cand):
                return cand
    return exe


def _tesseract(args, data=None):
    import subprocess
    exe = _tesseract_exe()
    if exe is None:
        raise OcrUnavailable(NO_TESSERACT)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
    try:
        r = subprocess.run([exe, *args], input=data, capture_output=True, timeout=30, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OcrUnavailable(f"Tesseract OCR could not run: {e}")
    if r.returncode != 0:
        raise OcrUnavailable("Tesseract OCR failed: " + r.stderr.decode("utf-8", "replace").strip()[-200:])
    return r.stdout.decode("utf-8", "replace")


def ocr_problem():
    """None when text reading works, else a message saying what is missing."""
    try:
        _tesseract(["--version"])
        return None
    except OcrUnavailable as e:
        return str(e)


def ocr_image(img, mode="text"):
    """Read text from a BGR image. mode 'number' keeps digits, sign and decimal point."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h = gray.shape[0]
    if h < 40:  # small UI text reads far better enlarged
        f = 40.0 / max(1, h)
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    if float(gray.mean()) < 110:  # light text on dark background
        gray = 255 - gray
    args = ["stdin", "stdout", "--psm", "7" if gray.shape[0] < 120 else "6"]
    if mode == "number":
        args += ["-c", "tessedit_char_whitelist=0123456789.,-"]
    text = " ".join(_tesseract(args, cv2.imencode(".png", gray)[1].tobytes()).split())
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

    def __init__(self, cond, get_image, memory=None):
        """memory: an optional dict shared between checkers that remembers where images were last seen."""
        self.c = dict(cond)
        self.get_image = get_image
        self.memory = memory
        self.reset()

    def reset(self):
        self.base = None
        self.last = None
        self.still_since = None
        self.last_by = {}        # image name -> where it was last found
        self.matched_name = None  # which image the last check found (steps can list several)
        if self.memory is not None and self.c.get("kind") in ("image_appears", "image_vanishes"):
            for name in self._names():
                hit = self.memory.get(self._mem_key(name))
                if hit is not None:
                    self.last_by[name] = hit

    def _names(self):
        return model.step_images(self.c)

    def _mem_key(self, name):
        r = self.c.get("region")
        return name, tuple(r) if r else None

    def _find(self, needle, region, conf, gray, scales, name=None):
        """Search near the last match first; things on screen rarely move far between checks."""
        name = name or model.image_name(self.c.get("image"))
        m = self.last_by.get(name)
        if m is not None:
            pad = max(24, m.w // 2, m.h // 2)
            near = [m.x - pad, m.y - pad, m.w + 2 * pad, m.h + 2 * pad]
            if region:
                rx, ry, rw, rh = (int(v) for v in region)
                x0, y0 = max(near[0], rx), max(near[1], ry)
                x1, y1 = min(near[0] + near[2], rx + rw), min(near[1] + near[3], ry + rh)
                near = [x0, y0, x1 - x0, y1 - y0]
            sx, sy, sw, sh = virtual_screen()
            x0, y0 = max(near[0], sx), max(near[1], sy)
            x1, y1 = min(near[0] + near[2], sx + sw), min(near[1] + near[3], sy + sh)
            if x1 - x0 >= m.w and y1 - y0 >= m.h:
                hit = find_image(needle, [x0, y0, x1 - x0, y1 - y0], conf, gray, scales)
                if hit is not None:
                    self._remember(name, hit)
                    return hit
        hit = find_image(needle, region, conf, gray, scales)
        self._remember(name, hit)
        return hit

    def _remember(self, name, hit):
        if hit is None:
            self.last_by.pop(name, None)
            return
        self.last_by[name] = hit
        if self.memory is not None:
            if len(self.memory) > 200:
                self.memory.clear()
            self.memory[self._mem_key(name)] = hit

    def _needle(self, name=None):
        name = name or model.image_name(self.c.get("image"))
        img = self.get_image(name) if name else None
        if img is None:
            raise ValueError(f"Image '{name or '(none)'}' is missing")
        return img

    def _find_images(self, region):
        """The step's image, or with alternates: any one of them (first found) or all of them."""
        conf = float(self.c.get("confidence") or 0.9)
        gray = bool(self.c.get("grayscale"))
        scales = self.c.get("scales")
        names = self._names() or [model.image_name(self.c.get("image"))]
        need_all = self.c.get("image_mode") == model.IMAGE_MODES[1] and len(names) > 1
        # try the one that matched last time first: the screen usually still shows the same state
        if self.matched_name in names and not need_all:
            names = [self.matched_name] + [n for n in names if n != self.matched_name]
        first = None
        for name in names:
            m = self._find(self._needle(name), region, conf, gray, scales, name)
            if m is None:
                if need_all:
                    return None
                continue
            if first is None:
                first = m
                self.matched_name = name
            if not need_all:
                return m
        return first

    def check(self):
        """Return (is_true, Match or None)."""
        k = self.c.get("kind")
        region = self.c.get("region") or None
        if k in ("image_appears", "image_vanishes"):
            m = self._find_images(region)
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
