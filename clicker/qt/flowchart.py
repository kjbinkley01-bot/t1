"""Visual flow editor: the script as boxes and arrows, beside the step list.

Click a box to select its step, drag a box up or down to move the step, and drag from a box's round
handle onto another box to make it jump there (Go to, Loop Back, Call, and the jump style Ifs).
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView

from .. import flow, model
from . import glass, motion
from .flowview import color
from .glass import font

BOX_W, BOX_H, GAP, INDENT = 250, 40, 20, 26
LEFT = 20
JUMPABLE = {"Go to Step": "goto", "Loop Back": "goto", "Call Subroutine": "goto", "If Image Found": "goto",
            "If Image Not Found": "goto", "If Pixel Color": "goto", "If Variable": "goto",
            "If Text on Screen": "goto", "If Window Open": "goto"}


def group_color(action):
    g = model.ACTION_GROUP.get(action, "")
    return {"Mouse": QColor(90, 160, 255), "Keyboard": QColor(170, 130, 255), "Screen": QColor(80, 200, 230),
            "Text": QColor(80, 200, 230), "Windows": QColor(120, 200, 160), "Apps and clipboard": QColor(120, 200, 160),
            "Variables": QColor(255, 200, 90), "Blocks": QColor(255, 170, 70), "Loops": QColor(255, 140, 190),
            "Flow": QColor(200, 150, 255)}.get(g, QColor(200, 200, 220))


class StepBox(QGraphicsObject):
    def __init__(self, chart, i, step, depth):
        super().__init__()
        self.chart, self.i, self.step, self.depth = chart, i, step, depth
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.hover = False
        self.selected = False
        self.running = False
        self.dead = False
        self._press = None
        self._linking = False

    def boundingRect(self):
        return QRectF(-2, -2, BOX_W + 26, BOX_H + 4)

    def port(self):
        return QPointF(BOX_W + 10, BOX_H / 2)

    def paint(self, p, _opt, _w):
        dark = self.chart.dark
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, BOX_W, BOX_H)
        base = group_color(self.step["action"])
        fill = QColor(base)
        fill.setAlpha(60 if dark else 70)
        if self.selected:
            fill.setAlpha(120)
        if self.running:
            fill = QColor(0, 136, 255, 150)
        p.setBrush(fill)
        pen = QPen(QColor(255, 255, 255, 200) if self.selected else QColor(base.red(), base.green(), base.blue(), 170),
                   2 if self.selected or self.hover else 1)
        p.setPen(pen)
        p.drawRoundedRect(r, 10, 10)
        p.setOpacity(0.45 if self.dead else 1.0)
        txt = QColor("#ffffff") if dark else QColor("#141433")
        p.setPen(txt)
        p.setFont(font(8.5, QFont.Weight.DemiBold))
        label = f"{self.i + 1}  {self.step['action']}" + (f"   [{self.step['label']}]" if self.step.get("label") else "")
        p.drawText(QRectF(10, 3, BOX_W - 20, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, BOX_W - 20))
        p.setFont(font(7.5))
        det = model.describe_step(self.step)[2]
        sub = QColor(txt)
        sub.setAlpha(170)
        p.setPen(sub)
        p.drawText(QRectF(10, 20, BOX_W - 20, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(det, Qt.TextElideMode.ElideRight, BOX_W - 20))
        p.setOpacity(1.0)
        if self.step.get("bp"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ff453a"))
            p.drawEllipse(QPointF(-7, BOX_H / 2), 4, 4)
        if self.step["action"] in JUMPABLE:  # the link handle
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            p.setBrush(QColor(255, 196, 107) if self.hover else QColor(255, 255, 255, 60))
            p.drawEllipse(self.port(), 6, 6)

    def hoverEnterEvent(self, _e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, _e):
        self.hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.pos()
        self._linking = (self.step["action"] in JUMPABLE
                         and (pos - self.port()).manhattanLength() <= 12)
        self._press = e.scenePos()
        self._start_y = self.y()
        self.setZValue(10)
        if not self._linking:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.chart.select_from_chart(self.i)  # last: nothing of this box is touched after it

    def mouseMoveEvent(self, e):
        if self._press is None:
            return
        if self._linking:
            self.chart.show_link(self.mapToScene(self.port()), e.scenePos())
            return
        dy = e.scenePos().y() - self._press.y()
        if abs(dy) > 4:
            self.setY(self._start_y + dy)
            self.chart.show_drop(self.y() + BOX_H / 2)

    def mouseReleaseEvent(self, e):
        if self._press is None:
            return
        self._press = None
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if self._linking:
            self._linking = False
            self.chart.finish_link(self.i, e.scenePos())
            return
        if abs(self.y() - self._start_y) > 4:
            self.chart.finish_drag(self.i, self.y() + BOX_H / 2)
        else:
            self.setY(self._start_y)

    def mouseDoubleClickEvent(self, _e):
        self.chart.open_step(self.i)


class FlowChart(QGraphicsView):
    """Boxes and arrows for the Action Script tab. It rebuilds from the script after every change."""

    MIN_WIDTH = 320

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setStyleSheet("QGraphicsView { background: rgba(0,0,0,40); border: none; border-radius: 16px; }")
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setMinimumWidth(self.MIN_WIDTH)
        self.boxes = []
        self._link = None
        self._drop = None
        self.zoom = self._zoom_to = 1.0
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    @property
    def dark(self):
        return self.tab.main.mode.dark

    # ------------------------------------------------------------ building

    def rebuild(self):
        steps = self.tab.script["steps"]
        sc = self.scene_
        # where each step's box was, so boxes that moved can glide to their new places
        glide = getattr(self, "_glide", None)
        if glide is not None:
            glide.stop()
        before = {id(b.step): (b.step, b.pos()) for b in self.boxes} if glass.motion_on() and self.isVisible() else {}
        sc.clear()
        self._link = self._drop = None
        self.boxes = []
        info, _err = model.block_structure(steps)
        depth = info["depth"]
        dead = set(flow.unreachable(self.tab.script))
        y = 10
        pos = []
        for i, st in enumerate(steps):
            x = LEFT + depth[i] * INDENT
            pos.append((x, y))
            y += BOX_H + GAP
        # block containers behind the boxes
        for kind, table in (("while", info["pairs"]), ("ifblock", info["ifs"]), ("tryblock", info["tries"])):
            for a, v in table.items():
                b = v if kind == "while" else v.get("end")
                if b is None or b <= a or (kind != "while" and steps[a]["action"] not in ("If", "Try")):
                    continue
                x0, y0 = pos[a]
                _x1, y1 = pos[b]
                c = color(kind, self.dark)
                c.setAlpha(28)
                edge = color(kind, self.dark)
                edge.setAlpha(110)
                path = QPainterPath()
                path.addRoundedRect(QRectF(x0 - 8, y0 - 6, BOX_W + INDENT + 16 + 40, y1 - y0 + BOX_H + 12), 14, 14)
                it = sc.addPath(path, QPen(edge, 1, Qt.PenStyle.DashLine), QBrush(c))
                it.setZValue(-5)
        # sequential arrows
        seq_pen = QPen(QColor(255, 255, 255, 110) if self.dark else QColor(20, 20, 60, 110), 1.4)
        for i in range(len(steps) - 1):
            a = steps[i]["action"]
            if a in ("Go to Step", "Stop Script", "Return"):
                continue
            x0, y0 = pos[i]
            x1, y1 = pos[i + 1]
            p0 = QPointF(x0 + 30, y0 + BOX_H)
            p1 = QPointF(x1 + 30, y1)
            path = QPainterPath(p0)
            path.cubicTo(QPointF(p0.x(), p0.y() + GAP / 2), QPointF(p1.x(), p1.y() - GAP / 2), p1)
            self._arrow(path, p1, seq_pen, down=True)
        # jumps
        edges = flow.edges(steps)
        lanes = flow.lanes(edges)
        right = LEFT + max([d for d in depth] + [0]) * INDENT + BOX_W + 24
        for e, lane in zip(edges, lanes):
            if e["kind"] in flow.BRACKETS:
                continue
            xs, ys = pos[e["src"]]
            xd, yd = pos[e["dst"]]
            a = QPointF(xs + BOX_W + 10, ys + BOX_H / 2)
            b = QPointF(xd + BOX_W, yd + BOX_H / 2)
            out = right + 20 + lane * 16
            path = QPainterPath(a)
            path.cubicTo(QPointF(out, a.y()), QPointF(out, b.y()), b)
            c = color(e["kind"], self.dark)
            self._arrow(path, b, QPen(c, 2), down=False)
        decor = list(sc.items())
        moves, fresh = [], []
        for i, st in enumerate(steps):
            box = StepBox(self, i, st, depth[i])
            box.setPos(*pos[i])
            box.setZValue(1)
            box.dead = i in dead
            sc.addItem(box)
            self.boxes.append(box)
            old = before.get(id(st))
            if old is not None and old[0] is st:
                if old[1] != box.pos():
                    moves.append((box, old[1], box.pos()))
            elif before:
                fresh.append(box)
        if before and len(fresh) == len(steps):
            fresh = []  # nothing carried over (undo, a new script): just show it, no fading
        if moves or fresh:
            self._settle(moves, fresh, decor)
        w = right + 20 + (max(lanes) + 1 if lanes else 0) * 16 + 30
        sc.setSceneRect(QRectF(0, 0, max(w, 300), y + 10))
        self.set_selection(self.tab._selection())
        self.set_running(self.tab.running_row)

    def _settle(self, moves, fresh, decor):
        """Glide moved boxes from where they were; fade in new boxes and the redrawn arrows."""
        for box, a, _b in moves:
            box.setPos(a)
        for it in fresh + decor:
            it.setOpacity(0.0 if it in fresh else 0.2)

        def step(t):
            t = float(t)
            for box, a, b in moves:
                box.setPos(a + (b - a) * t)
            for it in fresh:
                it.setOpacity(t)
            for it in decor:
                it.setOpacity(0.2 + 0.8 * t)
        glass.animate(self, 0.0, 1.0, glass.SLOW, step, curve=glass.GLIDE, attr="_glide")

    def _arrow(self, path, tip, pen, down):
        sc = self.scene_
        it = sc.addPath(path, pen)
        it.setZValue(0)
        head = QPainterPath()
        if down:
            head.moveTo(tip.x() - 4, tip.y() - 6)
            head.lineTo(tip.x(), tip.y())
            head.lineTo(tip.x() + 4, tip.y() - 6)
        else:
            head.moveTo(tip.x() + 7, tip.y() - 4)
            head.lineTo(tip.x(), tip.y())
            head.lineTo(tip.x() + 7, tip.y() + 4)
        h = sc.addPath(head, pen)
        h.setZValue(0)

    # ------------------------------------------------------------ state from the tab

    def set_selection(self, rows):
        rows = set(rows)
        for b in self.boxes:
            on = b.i in rows
            if on != b.selected:
                b.selected = on
                b.update()
        if rows:
            first = min(rows)
            if first < len(self.boxes):
                motion.smoothly(self, lambda: self.ensureVisible(self.boxes[first], 20, 40))

    def set_running(self, row):
        for b in self.boxes:
            on = b.i == row
            if on != b.running:
                b.running = on
                b.update()
        if row is not None and 0 <= row < len(self.boxes):
            motion.smoothly(self, lambda: self.ensureVisible(self.boxes[row], 20, 60))

    # ------------------------------------------------------------ interactions

    def select_from_chart(self, i):
        self.tab.select_step(i)

    def open_step(self, i):
        self.tab.select_step(i)
        self.tab.e_comment.setFocus()

    def _row_at(self, y):
        return max(0, min(len(self.boxes), int((y - 10 + GAP / 2) // (BOX_H + GAP))))

    def show_drop(self, y):
        if self._drop is not None:
            self.scene_.removeItem(self._drop)
        row = self._row_at(y)
        ly = 10 + row * (BOX_H + GAP) - GAP / 2
        pen = QPen(QColor("#0a84ff"), 3)
        self._drop = self.scene_.addLine(LEFT - 6, ly, LEFT + BOX_W + 40, ly, pen)
        self._drop.setZValue(20)

    def finish_drag(self, i, y):
        if self._drop is not None:
            self.scene_.removeItem(self._drop)
            self._drop = None
        row = self._row_at(y)
        target = row if row <= i else row - 1  # index in the list without the moved step
        if target == i:
            self.rebuild()
            return
        self.tab.move_steps_to([i], target)

    def show_link(self, a, b):
        if self._link is not None:
            self.scene_.removeItem(self._link)
        path = QPainterPath(a)
        path.cubicTo(QPointF(a.x() + 60, a.y()), QPointF(b.x() + 60, b.y()), b)
        self._link = self.scene_.addPath(path, QPen(QColor("#ffc46b"), 2, Qt.PenStyle.DashLine))
        self._link.setZValue(30)

    def finish_link(self, i, scene_pos):
        if self._link is not None:
            self.scene_.removeItem(self._link)
            self._link = None
        target = None
        for b in self.boxes:
            if b.sceneBoundingRect().contains(scene_pos) and b.i != i:
                target = b.i
        if target is None:
            return
        self.tab.set_jump(i, target)

    def showEvent(self, e):
        super().showEvent(e)
        self.rebuild()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self._zoom_to = max(0.4, min(2.0, self._zoom_to * f))
            glass.animate(self, self.zoom, self._zoom_to, glass.FAST, self._set_zoom, attr="_zanim")
        else:
            super().wheelEvent(e)

    def _set_zoom(self, z):
        self.zoom = float(z)
        self.setTransform(QTransform.fromScale(self.zoom, self.zoom))
