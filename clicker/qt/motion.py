"""App wide motion: smooth scrolling (mouse wheel and scroll-to jumps) and popups that fade in.

Installed once on the application, so every scroll area, list, menu and combo box gets it
without each widget having to opt in.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QVariantAnimation
from PySide6.QtWidgets import QAbstractItemView, QApplication, QGraphicsView, QMenu, QScrollArea, QWidget

from . import glass

SCROLL_MS = 220
FADE_IN = {"QComboBoxPrivateContainer", "QTipLabel"}  # combo box lists and tooltips
PIXEL_AREAS = (QScrollArea, QAbstractItemView, QGraphicsView)  # scroll bars measured in pixels (or made so)


class _Glide:
    """One scroll bar's running glide toward a target value."""

    def __init__(self, bar):
        self.bar = bar
        self.target = bar.value()
        self.anim = QVariantAnimation(bar)
        self.anim.setEasingCurve(glass.EASE)
        self.anim.valueChanged.connect(lambda v: bar.setValue(round(v)))

    def add(self, delta):
        base = self.target if self.anim.state() == QVariantAnimation.State.Running else self.bar.value()
        self.to(base + delta)

    def to(self, value, start=None):
        """Glide to value, from start (default: where the bar is now)."""
        self.target = max(self.bar.minimum(), min(self.bar.maximum(), value))
        self.anim.stop()
        self.anim.setDuration(SCROLL_MS)
        self.anim.setStartValue(float(self.bar.value() if start is None else start))
        self.anim.setEndValue(float(self.target))
        self.anim.start()


def _glide(bar):
    g = getattr(bar, "_clicker_glide", None)
    if g is None:
        g = bar._clicker_glide = _Glide(bar)
    return g


def smoothly(area, jump):
    """Run jump(), which scrolls area instantly (scrollToItem, ensureVisible...), as a glide instead."""
    if isinstance(area, QAbstractItemView):  # glide in pixels, not whole rows
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    bars = (area.verticalScrollBar(), area.horizontalScrollBar())
    before = [b.value() for b in bars]
    jump()
    if not glass.motion_on():
        return
    for bar, v0 in zip(bars, before):
        v1 = bar.value()
        if v1 != v0:
            g = _glide(bar)
            if g.anim.state() == QVariantAnimation.State.Running:
                v0 = g.anim.currentValue()  # already gliding: carry on from where it is
            bar.setValue(round(v0))  # nothing was painted in between, so the jump is never seen
            g.to(v1, start=v0)


class Motion(QObject):
    """Event filter for the whole application."""

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Type.Wheel and glass.motion_on():
            return self._wheel(obj, e)
        if t == QEvent.Type.Show and glass.motion_on() and isinstance(obj, QWidget) and obj.isWindow() and (
                isinstance(obj, QMenu) or obj.metaObject().className() in FADE_IN):
            glass.fade_in(obj, glass.FAST)
        return False

    def _wheel(self, obj, e):
        """Turn a mouse wheel notch into a short glide. Trackpads already scroll smoothly: left alone."""
        if not e.pixelDelta().isNull() or e.modifiers() or e.phase() != Qt.ScrollPhase.NoScrollPhase:
            return False
        area = obj.parent()
        if not isinstance(area, PIXEL_AREAS) or obj is not area.viewport():
            return False  # text boxes scroll by whole lines: a glide there would jump, so leave them to Qt
        d = e.angleDelta()
        vertical = abs(d.y()) >= abs(d.x())
        notches = (d.y() if vertical else d.x()) / 120.0
        bar = area.verticalScrollBar() if vertical else area.horizontalScrollBar()
        if not notches or bar is None or bar.maximum() <= bar.minimum():
            return False
        if (notches > 0 and bar.value() <= bar.minimum()) or (notches < 0 and bar.value() >= bar.maximum()):
            return False  # at the end: let an outer scroll area take it, as Qt normally would
        if isinstance(area, QAbstractItemView):
            # rows scroll by pixel so the glide can be smooth; a notch still moves about three rows
            mode = QAbstractItemView.ScrollMode.ScrollPerPixel
            if vertical and area.verticalScrollMode() != mode:
                area.setVerticalScrollMode(mode)
            elif not vertical and area.horizontalScrollMode() != mode:
                area.setHorizontalScrollMode(mode)
            model = area.model()
            row = area.sizeHintForRow(0) if vertical and model is not None and model.rowCount() else 0
            step = max(row, 20)
        else:
            step = max(bar.singleStep(), 20)
        _glide(bar).add(-notches * QApplication.wheelScrollLines() * step)
        e.accept()
        return True


def install(app):
    m = Motion(app)
    app.installEventFilter(m)
    return m
