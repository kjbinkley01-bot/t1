"""App wide motion: smooth mouse wheel scrolling and popups that fade in.

Installed once on the application, so every scroll area, list, menu and combo box gets it
without each widget having to opt in.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QVariantAnimation
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QApplication, QMenu, QWidget

from . import glass

SCROLL_MS = 220


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
        self.target = max(self.bar.minimum(), min(self.bar.maximum(), base + delta))
        self.anim.stop()
        self.anim.setDuration(SCROLL_MS)
        self.anim.setStartValue(float(self.bar.value()))
        self.anim.setEndValue(float(self.target))
        self.anim.start()


class Motion(QObject):
    """Event filter for the whole application."""

    def eventFilter(self, obj, e):
        t = e.type()
        if t == QEvent.Type.Wheel and glass.motion_on():
            return self._wheel(obj, e)
        if t == QEvent.Type.Show and glass.motion_on() and isinstance(obj, QWidget) and obj.isWindow() and (
                isinstance(obj, QMenu) or obj.metaObject().className() == "QComboBoxPrivateContainer"):
            glass.fade_in(obj, glass.FAST)
        return False

    def _wheel(self, obj, e):
        """Turn a mouse wheel notch into a short glide. Trackpads already scroll smoothly: left alone."""
        if not e.pixelDelta().isNull() or e.modifiers() or e.phase() != Qt.ScrollPhase.NoScrollPhase:
            return False
        area = obj.parent()
        if not isinstance(area, QAbstractScrollArea) or obj is not area.viewport():
            return False
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
        glide = getattr(bar, "_clicker_glide", None)
        if glide is None:
            glide = bar._clicker_glide = _Glide(bar)
        glide.add(-notches * QApplication.wheelScrollLines() * step)
        e.accept()
        return True


def install(app):
    m = Motion(app)
    app.installEventFilter(m)
    return m
