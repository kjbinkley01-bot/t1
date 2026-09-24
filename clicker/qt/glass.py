"""Liquid Glass rendering for the Qt interface.

The look follows the Liquid Glass iOS 26 kit (assets/liquid_glass_tokens.json):
glass is a blurred, tinted view of the wallpaper *behind* a surface, lit along
its rim from 315 degrees (top left), with large continuous radii. Content sits
on top of the glass and is never blurred itself.

Everything here paints from cached pixmaps: the wallpaper and its blurred copy
are rendered once per window size, so painting a glass panel is one clipped
pixmap copy plus a few strokes.
"""

import json
import math
import os
import sys

import cv2
import numpy as np
from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
                            QObject)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QIcon, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ASSETS = os.path.join(ROOT, "assets")

try:
    with open(os.path.join(ASSETS, "liquid_glass_tokens.json"), encoding="utf-8") as _f:
        TOKENS = json.load(_f)
except (OSError, ValueError):
    TOKENS = {}

ACCENT = QColor("#0088ff")   # accent/blue
GREEN = QColor("#34c759")    # accent/green
RED = QColor("#ff453a")


# ---------------------------------------------------------------- modes

class Mode:
    """Colors for content over dark or over light glass (the kit's two modes)."""

    def __init__(self, dark):
        self.dark = dark
        if dark:
            self.text = QColor("#ffffff")
            self.detail = QColor(255, 255, 255, 150)      # label-detail, a little stronger for dense UI
            self.faint = QColor(255, 255, 255, 84)
            self.tint = QColor(18, 20, 34, 118)           # glass tint over the blurred wallpaper
            self.well = QColor(255, 255, 255, 22)         # glass/symbol-well, lifted for legibility
            self.well_hover = QColor(255, 255, 255, 44)
            self.field = QColor(0, 0, 0, 70)
            self.line = QColor(255, 255, 255, 30)
            self.rim_hi = 0.62
            self.rim_lo = 0.26
            self.shadow = 0.34
            self.sel = QColor(255, 255, 255, 46)          # selection reads as a lit glass row
        else:
            self.text = QColor("#0b0d12")
            self.detail = QColor(11, 13, 18, 150)
            self.faint = QColor(11, 13, 18, 90)
            self.tint = QColor(255, 255, 255, 150)
            self.well = QColor(255, 255, 255, 120)
            self.well_hover = QColor(255, 255, 255, 190)
            self.field = QColor(255, 255, 255, 150)
            self.line = QColor(0, 0, 0, 26)
            self.rim_hi = 0.95
            self.rim_lo = 0.55
            self.shadow = 0.16
            self.sel = QColor(0, 136, 255, 46)


# ---------------------------------------------------------------- fonts and icons

_family = None


def load_fonts():
    """Register the bundled Inter font; returns the family to use."""
    global _family
    if _family:
        return _family
    fams = []
    folder = os.path.join(ASSETS, "fonts")
    for name in ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"):
        fid = QFontDatabase.addApplicationFont(os.path.join(folder, name))
        if fid >= 0:
            fams += QFontDatabase.applicationFontFamilies(fid)
    _family = fams[0] if fams else ("Segoe UI" if sys.platform == "win32" else "Sans Serif")
    return _family


def font(size=10, weight=QFont.Weight.Normal):
    f = QFont(load_fonts())
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


_icon_cache = {}


def icon_pixmap(name, color, size, dpr=1.0):
    """A Phosphor fill icon tinted to color, as a crisp pixmap."""
    key = (name, QColor(color).name(QColor.NameFormat.HexArgb), int(size), dpr)
    hit = _icon_cache.get(key)
    if hit is not None:
        return hit
    path = os.path.join(ASSETS, "icons", f"{name}.svg")
    try:
        with open(path, encoding="utf-8") as f:
            svg = f.read()
    except OSError:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"/>'
    c = QColor(color)
    svg = svg.replace("currentColor", c.name()).replace("<svg ", f'<svg fill-opacity="{c.alphaF():.3f}" ', 1)
    r = QSvgRenderer(svg.encode("utf-8"))
    px = int(round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    if len(_icon_cache) > 400:
        _icon_cache.clear()
    _icon_cache[key] = pm
    return pm


def qicon(name, color, size=18):
    return QIcon(icon_pixmap(name, color, size, 2.0))


# ---------------------------------------------------------------- wallpaper

WALLPAPERS = [
    ("aurora", "Aurora (kit gradient)", True),
    ("dusk", "Dusk", True),
    ("ocean", "Deep Ocean", True),
    ("mist", "Mist (light)", False),
    ("blossom", "Blossom (light)", False),
]
WALLPAPER_DARK = {k: d for k, _, d in WALLPAPERS}

# (base diagonal stops, blobs as (x, y, radius, color, alpha)); coordinates are fractions of the size
_SCENES = {
    "aurora": ([(0.0, "#2d4fd6"), (0.45, "#7a4fd8"), (0.78, "#d0679f"), (1.0, "#f08a6e")],
               [(0.12, 0.18, 0.55, "#3c7bff", 0.75), (0.85, 0.12, 0.45, "#b25cff", 0.55),
                (0.7, 0.9, 0.6, "#ff8f6b", 0.6), (0.25, 0.85, 0.45, "#5b3bd1", 0.5)]),
    "dusk": ([(0.0, "#0e1330"), (0.5, "#2a1f5c"), (1.0, "#5a2150")],
             [(0.18, 0.22, 0.5, "#3d5afe", 0.55), (0.82, 0.2, 0.42, "#9c27b0", 0.45),
              (0.62, 0.92, 0.55, "#ff5a7a", 0.35), (0.1, 0.9, 0.4, "#00bcd4", 0.25)]),
    "ocean": ([(0.0, "#04142b"), (0.55, "#0b3a5c"), (1.0, "#0f6b73")],
              [(0.2, 0.15, 0.5, "#1e88e5", 0.6), (0.85, 0.35, 0.45, "#26c6da", 0.4),
               (0.55, 0.95, 0.6, "#3949ab", 0.45)]),
    "mist": ([(0.0, "#eef3ff"), (0.5, "#f5eefc"), (1.0, "#fdf0ec")],
             [(0.15, 0.2, 0.5, "#b9ccff", 0.8), (0.85, 0.2, 0.45, "#e2c8ff", 0.7),
              (0.7, 0.9, 0.6, "#ffd3c4", 0.7), (0.2, 0.85, 0.45, "#c7f0ff", 0.55)]),
    "blossom": ([(0.0, "#fff0f5"), (0.5, "#ffe9ef"), (1.0, "#f1ecff")],
                [(0.2, 0.2, 0.55, "#ffb3cd", 0.8), (0.85, 0.3, 0.45, "#ffd6a8", 0.6),
                 (0.5, 0.95, 0.6, "#c9b8ff", 0.7)]),
}


def _hex_rgb(c):
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def render_scene(name, w, h):
    """Paint a gradient wallpaper as an RGB uint8 array (fast: computed at low resolution)."""
    stops, blobs = _SCENES.get(name, _SCENES["aurora"])
    sw, sh = max(8, w // 6), max(8, h // 6)
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    t = (xx / sw * 0.6 + yy / sh * 0.4)
    img = np.zeros((sh, sw, 3), np.float32)
    pos = [s[0] for s in stops]
    cols = [_hex_rgb(s[1]) for s in stops]
    for ch in range(3):
        img[..., ch] = np.interp(t, pos, [c[ch] for c in cols])
    diag = math.hypot(sw, sh)
    for bx, by, br, col, alpha in blobs:
        d = np.hypot(xx - bx * sw, yy - by * sh) / (br * diag)
        a = np.clip(1 - d, 0, 1) ** 2 * alpha
        img = img * (1 - a[..., None]) + _hex_rgb(col) * a[..., None]
    img = cv2.GaussianBlur(img, (0, 0), max(1.0, min(sw, sh) * 0.04))
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)
    noise = np.random.default_rng(7).normal(0, 1.2, (h, w, 1)).astype(np.float32)  # tiny grain, no banding
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def load_image_cover(path, w, h):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    ih, iw = img.shape[:2]
    k = max(w / iw, h / ih)
    img = cv2.resize(img, (max(w, int(iw * k + 1)), max(h, int(ih * k + 1))), interpolation=cv2.INTER_AREA)
    y0, x0 = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
    return np.ascontiguousarray(img[y0:y0 + h, x0:x0 + w])


def np_to_pixmap(arr):
    h, w = arr.shape[:2]
    qimg = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class Backdrop(QObject):
    """The window's wallpaper and its frosted (blurred) copy, rebuilt when the size settles."""

    changed = Signal()

    def __init__(self, scene="aurora", image_path=None):
        super().__init__()
        self.scene = scene
        self.image_path = image_path
        self.size = QSize(0, 0)
        self.sharp = None
        self.frost = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._rebuild)
        self._pending = None

    def set_scene(self, scene, image_path=None):
        self.scene, self.image_path = scene, image_path
        if self.size.width() > 0:
            self._pending = self.size
            self._rebuild()

    def resize(self, size):
        if size == self.size and self.sharp is not None:
            return
        self._pending = QSize(size)
        if self.sharp is None:
            self._rebuild()
        else:
            self._timer.start(90)  # while dragging, the old images are stretched; rebuild when it settles

    def _rebuild(self):
        size = self._pending or self.size
        w, h = max(16, size.width()), max(16, size.height())
        arr = load_image_cover(self.image_path, w, h) if self.image_path else None
        if arr is None:
            arr = render_scene(self.scene, w, h)
        small = cv2.resize(arr, (max(4, w // 4), max(4, h // 4)), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 9)  # ~36 px at full size: the frosted look
        frost = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
        self.sharp, self.frost = np_to_pixmap(arr), np_to_pixmap(frost)
        self.size = QSize(w, h)
        self.changed.emit()


# ---------------------------------------------------------------- painting

def rounded(rect, radius):
    path = QPainterPath()
    r = min(radius, rect.width() / 2, rect.height() / 2)
    path.addRoundedRect(rect, r, r)
    return path


_shadow_cache = {}


def shadow_pixmap(w, h, radius, blur, alpha):
    key = (int(w), int(h), int(radius), int(blur), round(alpha, 2))
    hit = _shadow_cache.get(key)
    if hit is not None:
        return hit
    pad = int(blur * 2)
    W, H = int(w) + 2 * pad, int(h) + 2 * pad
    mask = np.zeros((H, W), np.uint8)
    r = int(min(radius, w / 2, h / 2))
    cv2.rectangle(mask, (pad + r, pad), (pad + int(w) - r, pad + int(h)), 255, -1)
    cv2.rectangle(mask, (pad, pad + r), (pad + int(w), pad + int(h) - r), 255, -1)
    for cx, cy in ((pad + r, pad + r), (pad + int(w) - r, pad + r), (pad + r, pad + int(h) - r),
                   (pad + int(w) - r, pad + int(h) - r)):
        cv2.circle(mask, (cx, cy), r, 255, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), max(1, blur / 2))
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = (mask.astype(np.float32) * alpha).astype(np.uint8)
    img = QImage(rgba.data, W, H, 4 * W, QImage.Format.Format_RGBA8888).copy()
    pm = QPixmap.fromImage(img)
    if len(_shadow_cache) > 200:
        _shadow_cache.clear()
    _shadow_cache[key] = (pm, pad)
    return pm, pad


def paint_glass(p, rect, radius, backdrop, origin, mode, light=0.7, shadow=True, tint=None, lift=0.0):
    """Paint one glass surface.

    rect     where to paint, in the widget's coordinates
    origin   the widget's top left in the window, so the right slice of the frosted wallpaper shows
    light    rim light strength (kit: regular 0.7, clear 0.5), falling from 315 degrees
    lift     0..1 extra brightness for hover
    """
    rect = QRectF(rect)
    path = rounded(rect, radius)
    if shadow and mode.shadow > 0:
        pm, pad = shadow_pixmap(rect.width(), rect.height(), radius, 28, mode.shadow)
        p.drawPixmap(QPointF(rect.x() - pad, rect.y() - pad + 6), pm)
    p.save()
    p.setClipPath(path)
    if backdrop is not None and backdrop.frost is not None:
        src = QRectF(origin.x() + rect.x(), origin.y() + rect.y(), rect.width(), rect.height())
        p.drawPixmap(rect, backdrop.frost, src)
    p.fillPath(path, tint or mode.tint)
    if lift:
        p.fillPath(path, QColor(255, 255, 255, int(28 * lift)))
    # depth: a soft brighter band just inside the edge, like light caught in thick glass
    edge = QPen(QColor(255, 255, 255, int(26 if mode.dark else 60)), min(10.0, radius * 0.5))
    p.setPen(edge)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()
    # specular rim, strongest top left (315 degrees) and a weaker bounce bottom right
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    hi = int(255 * mode.rim_hi * light)
    lo = int(255 * mode.rim_lo * light)
    g.setColorAt(0.0, QColor(255, 255, 255, hi))
    g.setColorAt(0.35, QColor(255, 255, 255, int(hi * 0.18)))
    g.setColorAt(0.65, QColor(255, 255, 255, int(lo * 0.25)))
    g.setColorAt(1.0, QColor(255, 255, 255, lo))
    p.setPen(QPen(QBrush(g), 1.2))
    p.drawPath(rounded(rect.adjusted(0.6, 0.6, -0.6, -0.6), radius))


def window_origin(widget):
    """Where a widget's top left sits in its window (for sampling the backdrop)."""
    return widget.mapTo(widget.window(), QPointF(0, 0).toPoint())


# ---------------------------------------------------------------- animation helper

def animate(owner, start, end, ms, on_value, curve=QEasingCurve.Type.OutCubic, done=None, attr="_anim"):
    """Run a value animation, replacing any previous one stored on owner.attr."""
    old = getattr(owner, attr, None)
    if old is not None:
        old.stop()
    a = QVariantAnimation(owner)
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.setDuration(0 if not motion_on() else ms)
    a.setEasingCurve(curve)
    a.valueChanged.connect(on_value)
    if done:
        a.finished.connect(done)
    setattr(owner, attr, a)
    a.start()
    return a


_motion = {"on": True}


def motion_on():
    return _motion["on"]


def set_motion(on):
    _motion["on"] = bool(on)


class GlassPanel(QWidget):
    """A glass card. Put content in it with a layout, like any widget."""

    def __init__(self, parent=None, radius=26, light=0.7, shadow=True):
        super().__init__(parent)
        self.radius = radius
        self.light = light
        self.shadow = shadow
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _e):
        win = self.window()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = 1
        paint_glass(p, QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), self.radius,
                    getattr(win, "backdrop", None), window_origin(self), getattr(win, "mode", Mode(True)),
                    light=self.light, shadow=False)
        p.end()


def radial_glow(p, center, radius, color):
    g = QRadialGradient(center, radius)
    c = QColor(color)
    g.setColorAt(0, c)
    c.setAlpha(0)
    g.setColorAt(1, c)
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(center, radius, radius)
