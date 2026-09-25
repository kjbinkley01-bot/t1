"""Loop and jump overview: arrows beside the step list, and a Flow panel listing every jump."""

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from .. import flow
from .widgets import Caption, GlassButton

COLORS = {"while": QColor("#7fdcff"), "if": QColor("#ff9f0a"), "goto": QColor("#d7a8ff"),
          "loop": QColor("#ff9fcf"), "call": QColor("#7ee787"), "timeout": QColor("#ffd60a"),
          "ifblock": QColor("#ffc46b"), "tryblock": QColor("#a0e7a0")}
LIGHT = {"while": QColor("#0070b8"), "if": QColor("#c25e00"), "goto": QColor("#7a3fc0"),
         "loop": QColor("#c0397a"), "call": QColor("#1f8a3a"), "timeout": QColor("#a37b00"),
         "ifblock": QColor("#b0660a"), "tryblock": QColor("#2f7d32")}
LANE_W = 11
MAX_LANES = 8


def color(kind, dark=True):
    return (COLORS if dark else LIGHT).get(kind, QColor("#ffffff"))


class FlowRail(QWidget):
    """Draws each jump as an arrow from its step to where it leads, lined up with the tree's rows."""

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.edges = []
        self.lanes = []
        self.setFixedWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_edges(self, edges):
        self.edges = edges
        self.lanes = [min(l, MAX_LANES - 1) for l in flow.lanes(edges)]
        n = (max(self.lanes) + 1) if self.lanes else 0
        self.setFixedWidth(0 if not edges else 16 + n * LANE_W)
        self.update()

    def _row_y(self, idx, vp_top_local):
        tree = self.tab.tree
        it = tree.topLevelItem(idx)
        if it is None:
            return None
        r = tree.visualItemRect(it)
        if not r.isValid():
            return None
        return vp_top_local + r.center().y()

    def paintEvent(self, _e):
        if not self.edges:
            return
        tree = self.tab.tree
        vp = tree.viewport()
        top = self.mapFromGlobal(vp.mapToGlobal(QPoint(0, 0))).y()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipRect(QRectF(0, top, self.width(), vp.height()))
        sel = set(self.tab._selection()) if hasattr(self.tab, "_selection") else set()
        dark = self.tab.main.mode.dark
        right = self.width() - 3
        order = sorted(range(len(self.edges)),
                       key=lambda k: (self.edges[k]["src"] in sel or self.edges[k]["dst"] in sel))
        row_h = max(1, tree.visualItemRect(tree.topLevelItem(0)).height()) if tree.topLevelItemCount() else 24
        for k in order:
            e = self.edges[k]
            y1 = self._row_y(e["src"], top)
            y2 = self._row_y(e["dst"], top)
            if y1 is None or y2 is None:
                continue
            if max(y1, y2) < top - row_h or min(y1, y2) > top + vp.height() + row_h:
                continue
            x = right - 10 - self.lanes[k] * LANE_W
            hot = e["src"] in sel or e["dst"] in sel
            c = QColor(color(e["kind"], dark))
            if sel and not hot:
                c.setAlphaF(0.45)
            pen = QPen(c, 3.2 if hot else 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            if e["kind"] == "timeout":
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(QPointF(right, y1))
            r = min(6.0, abs(y2 - y1) / 2)
            dy = 1 if y2 > y1 else -1
            path.lineTo(x + r, y1)
            path.quadTo(x, y1, x, y1 + dy * r)
            path.lineTo(x, y2 - dy * r)
            path.quadTo(x, y2, x + r, y2)
            path.lineTo(right, y2)
            p.drawPath(path)
            if e["kind"] not in flow.BRACKETS:  # arrow head where it lands
                p.setPen(QPen(c, 2.2 if hot else 1.6))
                p.drawLine(QPointF(right - 5, y2 - 4), QPointF(right, y2))
                p.drawLine(QPointF(right - 5, y2 + 4), QPointF(right, y2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(right - 1, y1), 2.6 if hot else 2.0, 2.6 if hot else 2.0)


def _dot(c):
    pm = QPixmap(12, 12)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(c)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return QIcon(pm)


class FlowPanel(QWidget):
    """Every loop and jump in the script; click one to go to its step."""

    go = Signal(int)
    hide_me = Signal()

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.setFixedWidth(270)
        self.setObjectName("flowPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 4, 4)
        lay.setSpacing(6)
        h = QHBoxLayout()
        h.addWidget(Caption("Flow"))
        h.addStretch(1)
        b = GlassButton("Hide", small=True, tip="Hide the flow panel and arrows")
        b.clicked.connect(self.hide_me.emit)
        h.addWidget(b)
        lay.addLayout(h)
        self.lst = QListWidget()
        self.lst.setIconSize(QSize(12, 12))
        self.lst.setWordWrap(True)
        self.lst.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lst.itemClicked.connect(lambda it: self.go.emit(it.data(Qt.ItemDataRole.UserRole)[0]))
        self.lst.itemDoubleClicked.connect(lambda it: self.go.emit(it.data(Qt.ItemDataRole.UserRole)[1]))
        lay.addWidget(self.lst, 1)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setProperty("role", "warn")
        lay.addWidget(self.warn)
        self.btn_show = GlassButton("Show it", small=True)
        self.btn_show.clicked.connect(lambda: self.go.emit(self._dead[0]) if self._dead else None)
        lay.addWidget(self.btn_show, 0, Qt.AlignmentFlag.AlignLeft)
        self.hint = QLabel("Click a line to go to its step, double-click to go where it leads.")
        self.hint.setWordWrap(True)
        self.hint.setProperty("role", "detail")
        lay.addWidget(self.hint)
        self._dead = []

    def set_flow(self, steps, edges, dead):
        dark = self.tab.main.mode.dark
        self.lst.clear()
        for e in sorted(edges, key=lambda e: (e["src"], e["dst"])):
            span = (f"{e['src'] + 1}–{e['dst'] + 1}" if e["kind"] in flow.BRACKETS
                    else f"{e['src'] + 1} → {e['dst'] + 1}")
            it = QListWidgetItem(_dot(color(e["kind"], dark)), f"{span}   {e['text']}")
            it.setToolTip(e["text"])
            it.setData(Qt.ItemDataRole.UserRole, (e["src"], e["dst"]))
            self.lst.addItem(it)
        if not edges:
            self.lst.addItem("No loops or jumps yet.")
        self._dead = dead
        if dead:
            first = dead[0]
            more = f" (and {len(dead) - 1} more)" if len(dead) > 1 else ""
            why = flow.why_unreachable(steps, first)
            self.warn.setText(f"Step {first + 1} can never run{more}" + (f": {why}." if why else "."))
        self.warn.setVisible(bool(dead))
        self.btn_show.setVisible(bool(dead))
