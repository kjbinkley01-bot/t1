"""Show all matches: outline every place a step's picture is on screen, with its score.

Solid green outlines clear the step's match setting; dashed amber ones are near misses a little below it.
Click anywhere or press Esc to close; it also fades away by itself.
"""

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import glass
from .glass import font

SHOW_MS = 7000


class MatchOverlay(QWidget):
    def __init__(self, hits, near, summary):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        area = QRect()
        for s in QGuiApplication.screens():
            area = area.united(s.geometry())
        self.setGeometry(area)
        self.hits, self.near, self.summary = hits, near, summary
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.dismiss)

    def open(self):
        glass.fade_in(self, glass.BASE)
        self.show()
        self.activateWindow()
        self.setFocus()
        self._t.start(SHOW_MS)

    def dismiss(self):
        glass.animate(self, self.windowOpacity(), 0.0, glass.BASE, lambda v: self.setWindowOpacity(float(v)),
                      curve=glass.EXIT, attr="_fade", done=self.close)

    def mousePressEvent(self, _e):
        self.dismiss()

    def keyPressEvent(self, _e):
        self.dismiss()

    def _box(self, p, rect, score, good):
        x, y, w, h = rect
        r = QRectF(x - self.x() - 3, y - self.y() - 3, w + 6, h + 6)
        color = QColor(glass.GREEN) if good else QColor("#ffb340")
        pen = QPen(color, 3 if good else 2, Qt.PenStyle.SolidLine if good else Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 6, 6)
        label = f"{round(score * 100)}%"
        p.setFont(font(9, QFont.Weight.Bold))
        tw = QFontMetrics(p.font()).horizontalAdvance(label) + 12
        pill = QRectF(r.x(), r.y() - 22 if r.y() > 26 else r.bottom() + 4, tw, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QColor("#10131c"))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for m in self.near:
            self._box(p, m.rect, m.score, False)
        for m in self.hits:
            self._box(p, m.rect, m.score, True)
        # what was found, at the top of the main screen
        scr = QGuiApplication.primaryScreen().geometry()
        p.setFont(font(10.5, QFont.Weight.DemiBold))
        text = self.summary + "     (click or press a key to close)"
        tw = QFontMetrics(p.font()).horizontalAdvance(text) + 36
        pill = QRectF(scr.center().x() - self.x() - tw / 2, scr.y() - self.y() + 24, tw, 36)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.setBrush(QColor(20, 22, 36, 225))
        p.drawRoundedRect(pill, 18, 18)
        p.setPen(QColor("#ffffff"))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


def summary_text(hits, near, confidence):
    pct = round(confidence * 100)
    if hits:
        s = f"{len(hits)} match{'es' if len(hits) != 1 else ''} at {pct}% or better"
        if len(hits) > 1:
            s += " (the step uses the best one)"
    else:
        s = f"No match at {pct}%"
    if near:
        s += f" · {len(near)} near miss{'es' if len(near) != 1 else ''}, best {round(near[0].score * 100)}%"
    return s
