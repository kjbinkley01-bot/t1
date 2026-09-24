"""Tiny frame based tweens on the Tk event loop, plus color math.

Animations run on the UI thread with after(), so they must stay cheap: each
frame should only move a canvas item or swap a cached image.
"""

import time

FRAME_MS = 16
motion = {"on": True}  # Settings > Reduce motion turns this off


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def hex_rgb(c):
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(a, b, t):
    """Blend color a toward b by t (0..1)."""
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex([x + (y - x) * t for x, y in zip(ra, rb)])


class Tween:
    """Calls step(eased t) every frame for duration_ms, then done().

    Starting a new tween with the same owner and key cancels the old one, so
    rapid hovers or clicks never pile up animations.
    """

    _running = {}

    def __init__(self, widget, duration_ms, step, done=None, ease=ease_out, key=None):
        self.widget = widget
        self.duration = max(1, duration_ms) / 1000.0
        self.step = step
        self.done = done
        self.ease = ease
        self.key = (id(widget), key)
        self.job = None
        old = Tween._running.get(self.key)
        if old:
            old.cancel()
        Tween._running[self.key] = self
        if not motion["on"] or duration_ms <= 0:
            self._finish()
            return
        self.t0 = time.perf_counter()
        self._tick()

    def _tick(self):
        try:
            t = min(1.0, (time.perf_counter() - self.t0) / self.duration)
            self.step(self.ease(t))
            if t >= 1.0:
                self._end()
                return
            self.job = self.widget.after(FRAME_MS, self._tick)
        except Exception:  # widget destroyed mid animation
            self._end(call_done=False)

    def _finish(self):
        try:
            self.step(1.0)
        except Exception:
            pass
        self._end()

    def _end(self, call_done=True):
        if Tween._running.get(self.key) is self:
            del Tween._running[self.key]
        if call_done and self.done:
            try:
                self.done()
            except Exception:
                pass

    def cancel(self):
        if self.job:
            try:
                self.widget.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if Tween._running.get(self.key) is self:
            del Tween._running[self.key]
