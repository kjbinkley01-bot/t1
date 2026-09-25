"""Image template thumbnails: in the step list and the "Or these" strip of image steps."""

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QMenu, QWidget

from .. import model
from . import glass
from .widgets import GlassButton

_cache = {}


def thumb(assets, name, w, h, dpr=1.0):
    """A rounded thumbnail of one template (cached), or None if it isn't in the script."""
    img = assets.get(name)
    if img is None:
        return None
    key = (model.image_name(name), id(img), w, h, round(dpr, 2))
    pm = _cache.get(key)
    if pm is not None:
        return pm
    import cv2
    ih, iw = img.shape[:2]
    k = min(w * dpr / iw, h * dpr / ih)
    k = min(k, 4.0)
    small = cv2.resize(img, (max(1, int(iw * k)), max(1, int(ih * k))),
                       interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_NEAREST)
    src = glass.np_to_pixmap(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    out = QPixmap(int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)
    p.setClipPath(path)
    p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 90))
    sw, sh = src.width() / dpr, src.height() / dpr
    p.drawPixmap(QRectF((w - sw) / 2, (h - sh) / 2, sw, sh), src, QRectF(src.rect()))
    p.setClipping(False)
    p.setPen(QColor(255, 255, 255, 110))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.end()
    if len(_cache) > 400:
        _cache.clear()
    _cache[key] = out
    return out


def step_icon(assets, step, w=34, h=20, dpr=1.0):
    """The step's image thumbnail; alternates show as a small stack with a count."""
    names = model.step_images(step)
    if not names:
        return QIcon()
    first = thumb(assets, names[0], w - (6 if len(names) > 1 else 0), h - (4 if len(names) > 1 else 0), dpr)
    if first is None:
        return QIcon()
    out = QPixmap(int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    if len(names) > 1:
        second = thumb(assets, names[1], w - 6, h - 4, dpr)
        if second is not None:
            p.setOpacity(0.75)
            p.drawPixmap(QPoint(6, 4), second)
            p.setOpacity(1.0)
    p.drawPixmap(QPoint(0, 0), first)
    p.end()
    return QIcon(out)


class _Thumb(QWidget):
    clicked = Signal(str)

    def __init__(self, tab, name):
        super().__init__()
        self.tab, self.name = tab, name
        self.setFixedSize(58, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{model.image_stem(name)} · click to remove")
        self._hover = False

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.name)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pm = thumb(self.tab.assets, self.name, 58, 36, self.devicePixelRatioF())
        if pm is not None:
            p.drawPixmap(QPoint(0, 0), pm)
        else:
            p.setPen(QColor("#ff7b7b"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "missing")
        if self._hover:
            p.fillRect(self.rect(), QColor(0, 0, 0, 120))
            p.setPen(QColor("#ffffff"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Remove")


class ImageStrip(QWidget):
    """Extra images for a step, as thumbnails with an Add button.

    Talks like a line edit to the form code (text / setText hold 'a, b, c'), and like a combo box to the
    Capture and Load helpers (setCurrentText adds an image).
    """

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.names = []
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self.add = GlassButton("Add", icon="plus", small=True, tip="Add another image this step may find")
        self.add.clicked.connect(self._menu)
        self._rebuild()

    # the form's view of it
    def text(self):
        return ", ".join(model.image_stem(n) for n in self.names)

    def setText(self, text):
        self.names = [model.image_name(p) for p in str(text or "").split(",") if p.strip()]
        self._rebuild()

    def currentText(self):
        return ""

    def setCurrentText(self, name):
        name = model.image_name(name)
        if name and name not in self.names:
            self.names.append(name)
            self._rebuild()

    def _remove(self, name):
        if name in self.names:
            self.names.remove(name)
            self._rebuild()

    def _rebuild(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None and w is not self.add:
                w.deleteLater()
        for n in self.names:
            t = _Thumb(self.tab, n)
            t.clicked.connect(self._remove)
            self.lay.addWidget(t)
        self.lay.addWidget(self.add)
        self.lay.addStretch(1)

    def _menu(self):
        m = QMenu(self)
        m.addAction("Capture from screen...", lambda: self.tab.capture_image(self))
        m.addAction("Load from file...", lambda: self.tab.load_image(self))
        have = [n for n in self.tab.assets.names() if model.image_name(n) not in self.names]
        if have:
            sub = m.addMenu("Use an image in this script")
            for n in have:
                sub.addAction(model.image_stem(n), lambda x=n: self.setCurrentText(x))
        m.exec(self.add.mapToGlobal(QPoint(0, self.add.height() + 4)))

    def sizeHint(self):
        return QSize(64 * len(self.names) + 90, 38)

