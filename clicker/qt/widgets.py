"""Glass controls: buttons, segmented tabs, switches, fields and the step table styling."""

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QHBoxLayout, QLabel, QSizePolicy,
                               QWidget)

from . import glass
from .glass import ACCENT, RED, animate, font, icon_pixmap, paint_glass, rounded, window_origin


def mode_of(widget):
    return getattr(widget.window(), "mode", glass.Mode(True))


class GlassButton(QAbstractButton):
    """A pill (or circle, with only an icon) in one of the kit's styles.

    kind: "glass" translucent well, "primary" accent blue, "on" white with black content
          (the kit's on-state), "danger" glass with red content, "record" solid red.
    """

    def __init__(self, text="", icon=None, kind="glass", parent=None, small=False, tip=None):
        super().__init__(parent)
        self.setText(text)
        self.icon_name = icon
        self.kind = kind
        self.small = small
        self._hover = 0.0
        self._press = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(font(9.5 if small else 10.5, QFont.Weight.DemiBold if kind in ("primary", "record", "on")
                          else QFont.Weight.Medium))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if tip:
            self.setToolTip(tip)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        h = 30 if self.small else 36
        if not self.text():
            return QSize(h, h)
        w = fm.horizontalAdvance(self.text()) + (24 if self.small else 32)
        if self.icon_name:
            w += (14 if self.small else 18) + 6
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def enterEvent(self, e):
        animate(self, self._hover, 1.0, 160, self._set_hover, attr="_hanim")
        super().enterEvent(e)

    def leaveEvent(self, e):
        animate(self, self._hover, 0.0, 220, self._set_hover, attr="_hanim")
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        animate(self, self._press, 1.0, 90, self._set_press, attr="_panim")
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        animate(self, self._press, 0.0, 260, self._set_press, curve=QEasingCurve.Type.OutBack, attr="_panim")
        super().mouseReleaseEvent(e)

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def _set_press(self, v):
        self._press = float(v)
        self.update()

    def _colors(self, m):
        on = self.isEnabled()
        if self.kind == "primary":
            fill = QColor(ACCENT).lighter(100 + int(12 * self._hover))
            return fill, QColor("#ffffff"), False
        if self.kind == "record":
            return QColor(RED).lighter(100 + int(10 * self._hover)), QColor("#ffffff"), False
        if self.kind == "on":
            return QColor(255, 255, 255, 235 + int(20 * self._hover)), QColor("#000000"), False
        fg = QColor(RED) if self.kind == "danger" else QColor(m.text)
        if not on:
            fg = QColor(m.faint)
        return None, fg, True

    def _capsule(self, m, w, h):
        """The button's glass capsule as a cached pixmap (hover is quantized to 16 steps)."""
        hq = round(self._hover * 16) / 16
        dpr = self.devicePixelRatioF()
        key = (int(w), int(h), self.kind, hq, self.isEnabled(), id(m), dpr)
        pm = _CAPSULES.get(key)
        if pm is not None:
            return pm
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, w, h)
        radius = h / 2
        saved = self._hover
        self._hover = hq
        fill, _fg, is_glass = self._colors(m)
        self._hover = saved
        if is_glass:
            well, hov = QColor(m.well), QColor(m.well_hover)
            well = QColor(int(well.red() + (hov.red() - well.red()) * hq),
                          int(well.green() + (hov.green() - well.green()) * hq),
                          int(well.blue() + (hov.blue() - well.blue()) * hq),
                          int(well.alpha() + (hov.alpha() - well.alpha()) * hq))
            paint_glass(p, r, radius, None, QPoint(0, 0), m, light=0.55 + 0.25 * hq, shadow=False, tint=well)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(rounded(r, radius))
            paint_glass(p, r, radius, None, QPoint(0, 0), m, light=0.45, shadow=False, tint=QColor(0, 0, 0, 0))
        p.end()
        if len(_CAPSULES) > 1500:
            _CAPSULES.clear()
        _CAPSULES[key] = pm
        return pm

    def paintEvent(self, _e):
        m = mode_of(self)
        p = QPainter(self)
        base = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not self.isEnabled():
            p.setOpacity(0.55)
        pm = self._capsule(m, base.width(), base.height())
        # pressed controls shrink a little, like the kit's springy tiles
        k = 1 - 0.045 * self._press
        r = QRectF(base.center().x() - base.width() * k / 2, base.center().y() - base.height() * k / 2,
                   base.width() * k, base.height() * k)
        if k < 0.999:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(r, pm, QRectF(pm.rect()))
        else:
            p.drawPixmap(base.topLeft(), pm)
        _fill, fg, _g = self._colors(m)
        isz = 14 if self.small else 17
        text = self.text()
        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(text) if text else 0
        gap = 6 if (text and self.icon_name) else 0
        total = (isz if self.icon_name else 0) + gap + tw
        x = r.center().x() - total / 2
        if self.icon_name:
            p.drawPixmap(QPointF(x, r.center().y() - isz / 2), icon_pixmap(self.icon_name, fg, isz,
                                                                            self.devicePixelRatioF()))
            x += isz + gap
        if text:
            p.setPen(fg)
            p.setFont(self.font())
            p.drawText(QRectF(x, r.y(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       text)
        p.end()


_CAPSULES = {}


class SegmentedTabs(QWidget):
    """The tab bar: a glass capsule with a lens that glides to the chosen tab."""

    changed = Signal(str)

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.tabs = list(tabs)
        self.current = self.tabs[0][0]
        self.setFont(font(10.5, QFont.Weight.DemiBold))
        self._lens = None       # (x, w) now
        self._from = None
        self._to = None
        self._hover = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)

    def _slots(self):
        fm = QFontMetrics(self.font())
        x, out = 5.0, {}
        for key, text in self.tabs:
            w = fm.horizontalAdvance(text) + 36
            out[key] = (x, w)
            x += w + 2
        return out, x + 3

    def sizeHint(self):
        return QSize(int(self._slots()[1]), 44)

    def minimumSizeHint(self):
        return self.sizeHint()

    def select(self, key, animate_it=True):
        slots, _ = self._slots()
        if key not in slots:
            return
        self.current = key
        target = slots[key]
        start = self._lens or target
        self._from, self._to = start, target
        if not animate_it or self._lens is None:
            self._lens = target
            self.update()
            return

        def step(t):
            t = float(t)
            (sx, sw), (tx, tw) = self._from, self._to
            # liquid feel: the lens stretches toward the target, then settles
            stretch = 1 + 0.18 * (1 - abs(2 * t - 1))
            w = (sw + (tw - sw) * t) * stretch
            cx = sx + sw / 2 + ((tx + tw / 2) - (sx + sw / 2)) * t
            self._lens = (cx - w / 2, w)
            self.update()
        animate(self, 0.0, 1.0, 340, step, curve=QEasingCurve.Type.OutCubic, attr="_lanim",
                done=lambda: (setattr(self, "_lens", self._to), self.update()))

    def _key_at(self, x):
        for key, (sx, w) in self._slots()[0].items():
            if sx <= x <= sx + w:
                return key
        return None

    def mouseMoveEvent(self, e):
        k = self._key_at(e.position().x())
        if k != self._hover:
            self._hover = k
            self.update()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, e):
        k = self._key_at(e.position().x())
        if k and k != self.current:
            self.select(k)
            self.changed.emit(k)

    def paintEvent(self, _e):
        m = mode_of(self)
        win = self.window()
        slots, total = self._slots()
        origin = window_origin(self)
        dpr = self.devicePixelRatioF()
        h = self.height()

        def draw_bar(pp):
            bar = QRectF(0.5, 0.5, total, h - 1)
            paint_glass(pp, bar, bar.height() / 2, getattr(win, "backdrop", None), origin, m, light=0.7, shadow=False)
        if not hasattr(self, "_bar_cache"):
            self._bar_cache = glass.SurfaceCache()
        bar_pm = self._bar_cache.get((self.width(), h, total, origin.x(), origin.y(), glass.backdrop_key(win)),
                                     self.width(), h, dpr, draw_bar)
        if self._lens is None:
            self._lens = slots[self.current]
        lx, lw = self._lens
        lens_pm = _make_lens(m, int(round(lw)), h - 10, dpr)
        p = QPainter(self)
        p.drawPixmap(0, 0, bar_pm)
        p.drawPixmap(QPointF(lx, 5), lens_pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self.font())
        for key, text in self.tabs:
            sx, w = slots[key]
            c = QColor(m.text)
            if key != self.current and key != self._hover:
                c = QColor(m.detail)
            p.setPen(c)
            p.drawText(QRectF(sx, 0, w, self.height()), Qt.AlignmentFlag.AlignCenter, text)
        p.end()


_LENSES = {}  # the tab lens at each width it passes through while gliding


def _make_lens(m, w, h, dpr):
    key = (w, h, id(m), dpr)
    pm = _LENSES.get(key)
    if pm is None:
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_glass(p, QRectF(0, 0, w, h), h / 2, None, QPoint(0, 0), m, light=0.9, shadow=False,
                    tint=QColor(255, 255, 255, 64 if m.dark else 210))
        p.end()
        if len(_LENSES) > 400:
            _LENSES.clear()
        _LENSES[key] = pm
    return pm



class GlassSwitch(QCheckBox):
    """An iOS style switch with a sliding knob (green when on, like the kit's accent/green)."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._pos = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(font(10))
        self.toggled.connect(lambda on: animate(self, self._pos, 1.0 if on else 0.0, 220, self._set_pos,
                                                curve=QEasingCurve.Type.OutBack, attr="_sanim"))

    def setChecked(self, on):
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(46 + (10 + fm.horizontalAdvance(self.text()) if self.text() else 0), 28)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        m = mode_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 3, 44, 22)
        off = QColor(255, 255, 255, 50) if m.dark else QColor(0, 0, 0, 40)
        on = QColor(glass.GREEN)
        t = self._pos
        col = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t), int(off.alpha() + (on.alpha() - off.alpha()) * t))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, 11, 11)
        kx = track.x() + 2 + (track.width() - 22) * t
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(kx, track.y() + 3, 18, 18))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(kx, track.y() + 2, 18, 18))
        if self.text():
            p.setPen(m.text if self.isEnabled() else m.faint)
            p.setFont(self.font())
            p.drawText(QRectF(54, 0, self.width() - 54, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class Caption(QLabel):
    """Small caps section title, like the kit's headings."""

    def __init__(self, text, parent=None):
        super().__init__(text.upper(), parent)
        f = font(8.5, QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        self.setFont(f)
        self.setProperty("role", "caption")


def row(*widgets, spacing=8, stretch_last=False):
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for x in widgets:
        if x is None:
            lay.addStretch(1)
        elif isinstance(x, int):
            lay.addSpacing(x)
        else:
            lay.addWidget(x)
    if stretch_last:
        lay.addStretch(1)
    return w


def stylesheet(m):
    """Qt style sheet for the plain widgets (fields, lists, menus, scroll bars) in this mode."""
    def rgba(c):
        c = QColor(c)
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"
    text, detail, faint = rgba(m.text), rgba(m.detail), rgba(m.faint)
    caret = caret_file(m.detail)
    field, line, sel = rgba(m.field), rgba(m.line), rgba(m.sel)
    popup = "rgba(28,30,44,245)" if m.dark else "rgba(250,250,253,248)"
    hover_row = "rgba(255,255,255,18)" if m.dark else "rgba(0,0,0,12)"
    alt = "rgba(255,255,255,7)" if m.dark else "rgba(255,255,255,70)"
    warn = "#ffd166" if m.dark else "#8a5a00"
    return f"""
    * {{ color: {text}; }}
    QLabel {{ background: transparent; }}
    QLabel[role="caption"] {{ color: {detail}; }}
    QLabel[role="detail"] {{ color: {detail}; }}
    QLabel[role="error"] {{ color: #ff6b6b; }}
    QLabel[role="warn"] {{ color: {warn}; }}
    QToolTip {{ background: {popup}; color: {text}; border: 1px solid {line}; border-radius: 8px; padding: 6px 8px; }}
    QLineEdit, QComboBox, QSpinBox {{
        background: {field}; border: 1px solid {line}; border-radius: 10px; padding: 5px 10px;
        selection-background-color: rgba(0,136,255,140); min-height: 20px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid rgba(0,136,255,220); }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {faint}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{ image: url("{caret}"); width: 11px; height: 11px; margin-right: 9px; }}
    QComboBox QAbstractItemView {{ background: {popup}; border: 1px solid {line}; border-radius: 10px;
        padding: 4px; outline: none; selection-background-color: {sel}; }}
    QMenu {{ background: {popup}; border: 1px solid {line}; border-radius: 12px; padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 8px; }}
    QMenu::item:selected {{ background: {sel}; }}
    QMenu::separator {{ height: 1px; background: {line}; margin: 5px 8px; }}
    QTreeWidget {{ background: transparent; border: none; outline: none; alternate-background-color: {alt}; }}
    QListWidget {{ background: {field}; border: 1px solid {line}; border-radius: 12px; padding: 4px; outline: none; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
    QListWidget::item:hover {{ background: {hover_row}; }}
    QListWidget::item:selected {{ background: {sel}; color: {text}; }}
    QTreeWidget::item {{ height: 30px; border: none; padding-left: 4px; }}
    QTreeWidget::item:hover {{ background: {hover_row}; }}
    QTreeWidget::item:selected {{ background: {sel}; color: {text}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: transparent; color: {detail}; border: none; padding: 6px 4px;
        font-weight: 700; font-size: 8pt; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {line}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
    QScrollBar::handle:horizontal {{ background: {line}; border-radius: 3px; min-width: 30px; }}
    QMessageBox, QDialog {{ background: {popup}; }}
    """


def caret_file(color):
    """Style sheets need a file for the combo box arrow: write a tinted copy of the caret icon."""
    import os
    from .. import storage
    c = QColor(color)
    path = os.path.join(storage.data_dir(), "ui-cache", f"caret-{c.name()[1:]}.svg").replace("\\", "/")
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(os.path.join(glass.ASSETS, "icons", "caret-down.svg"), encoding="utf-8") as f:
            svg = f.read().replace("currentColor", c.name())
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    return path


def apply_style(app, m):
    app.setStyleSheet(stylesheet(m))
    app.setFont(font(10))


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def dpr():
    return QApplication.primaryScreen().devicePixelRatio() if QApplication.primaryScreen() else 1.0

