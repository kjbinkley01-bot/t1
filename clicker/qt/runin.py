"""The "Run in" window choice shared by the tabs, and turning screen positions into window positions."""

from PySide6.QtCore import Signal

from .. import target
from .widgets import GlassButton


class RunInButton(GlassButton):
    """Shows where input goes ("Run in: Whole screen" / a window) and opens the window picker."""

    changed = Signal(object)  # the new target dict, or None for the whole screen

    def __init__(self, main, prefix="Run in", tip=None):
        tip = tip or "Send clicks and keys to one window, so you can keep using your mouse and computer"
        super().__init__(f"{prefix}: Whole screen", icon="cursor", tip=tip)
        self.tip = tip
        self.main = main
        self.prefix = prefix
        self.target = None
        self.clicked.connect(self.choose)

    MAX_NAME = 24

    def set_target(self, t):
        self.target = t = target.normalize(t)
        if t:
            name = t["title"] or t["process"]
            if len(name) > self.MAX_NAME:
                name = name[:self.MAX_NAME - 1].rstrip() + "…"
            how = "background" if t["method"] == "messages" else "quick switch"
            self.setText(f"{self.prefix}: {name} · {how}")
            self.setToolTip(f"{self.prefix}: {target.describe(t)}. Click to change.")
        else:
            self.setText(f"{self.prefix}: Whole screen")
            self.setToolTip(self.tip)
        self.set_kind("on" if self.target else "glass")
        self.updateGeometry()

    def choose(self):
        from .target_dialog import choose_target
        new = choose_target(self.main, self.target)
        if new == "unchanged":
            return
        self.set_target(new)
        self.changed.emit(self.target)


class WindowSpace:
    """Converts what the user picks on screen (positions, regions, captures) into a window's positions.

    With no window everything passes through unchanged.
    """

    def __init__(self, main, get_target):
        self.main = main
        self.get_target = get_target

    def target(self):
        return target.normalize(self.get_target())

    def offset(self):
        t = self.target()
        if not t:
            return 0, 0
        try:
            return target.WindowIO(t).client_origin()
        except Exception as e:
            self.main.set_status(f"{e}. Using screen positions.", error=True)
            return 0, 0

    def point(self, x, y):
        ox, oy = self.offset()
        return x - ox, y - oy

    def region(self, region):
        ox, oy = self.offset()
        x, y, w, h = region
        return [x - ox, y - oy, w, h]

    def to_screen(self, rect):
        ox, oy = self.offset()
        x, y, w, h = rect
        return [x + ox, y + oy, w, h]

    def image(self, region, fallback):
        """The window's own picture of a screen region (what a check will search), else fallback."""
        t = self.target()
        if not t:
            return fallback
        try:
            io = target.WindowIO(t)
            shot = io.grab(*self.region(region))
            return shot if float(shot.std()) > 1.0 else fallback
        except Exception:
            return fallback

    def pixel_hex(self, sx, sy, fallback):
        """Color at a screen position, read from the window's picture in background mode."""
        t = self.target()
        if not t:
            return fallback
        try:
            io = target.WindowIO(t)
            lx, ly = self.point(sx, sy)
            b, g, r = io.grab(lx, ly, 1, 1)[0, 0]
            return "#%02X%02X%02X" % (int(r), int(g), int(b))
        except Exception:
            return fallback
