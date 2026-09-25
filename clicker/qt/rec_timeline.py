"""Recording editor: a timeline of clicks, movement and keys you can trim, cut and tighten."""

import copy

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QLineEdit, QScrollArea, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import recedit
from ..recorder import MOD_KEYS, key_text
from .glass import GlassPanel, font
from .widgets import Caption, GlassButton, mode_of

LANES = [("Clicks", 52), ("Movement", 44), ("Keys", 44)]
SCREEN_LANE = ("Screen", 54)
RULER_H = 24
HANDLE = QColor("#ffd60a")
SEL = QColor(255, 90, 100)
CLICK = QColor("#7fdcff")


def fmt_t(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:04.1f}"


class Timeline(QWidget):
    """Paints the events; drag across it to select, drag the yellow handles to trim."""

    selection_changed = Signal()
    trimmed = Signal(float, float)
    hovered = Signal(float)

    def __init__(self):
        super().__init__()
        self.events = []
        self.zoom = 1.0
        self.sel = None          # (a, b) seconds
        self.trim = None         # (start, end) while dragging a handle
        self.pause_min = 2.0
        self._drag = None        # "sel" | "start" | "end"
        self._anchor = 0.0
        self.fit_width = 900
        self.snaps = {}
        self._pm = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(RULER_H + sum(h for _n, h in LANES) + 8)

    @property
    def lanes(self):
        has = any(e["type"] == "snap" for e in self.events)
        return ([SCREEN_LANE] if has else []) + LANES

    def snap_pixmap(self, name, h):
        from PySide6.QtGui import QPixmap
        key = (name, h)
        pm = self._pm.get(key)
        if pm is None and name in self.snaps:
            pm = QPixmap()
            pm.loadFromData(self.snaps[name], "JPG")
            pm = pm.scaledToHeight(h, Qt.TransformationMode.SmoothTransformation)
            if len(self._pm) > 600:
                self._pm.clear()
            self._pm[key] = pm
        return pm

    # ------------------------------------------------------------ geometry

    @property
    def duration(self):
        return max(0.5, recedit.length(self.events))

    def px_per_s(self):
        return max(2.0, (self.fit_width - 24) / self.duration * self.zoom)

    def x_of(self, t):
        return 12 + t * self.px_per_s()

    def t_of(self, x):
        return min(self.duration, max(0.0, (x - 12) / self.px_per_s()))

    def sizeHint(self):
        return QSize(int(self.x_of(self.duration) + 12), self.minimumHeight())

    def relayout(self, fit_width=None):
        if fit_width:
            self.fit_width = fit_width
        self.setMinimumWidth(int(self.x_of(self.duration) + 12))
        self.updateGeometry()
        self.update()

    def set_events(self, events, snaps=None):
        self.events = events
        if snaps is not None and snaps is not self.snaps:
            self.snaps = snaps
            self._pm = {}
        self.sel = None
        self.trim = None
        self.setMinimumHeight(RULER_H + sum(h for _n, h in self.lanes) + 8)
        self.relayout()

    # ------------------------------------------------------------ mouse

    def _handles(self):
        s, e = self.trim or (0.0, self.duration)
        return self.x_of(s), self.x_of(e)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton or not self.events:
            return
        x = ev.position().x()
        hs, he = self._handles()
        if abs(x - hs) <= 7:
            self._drag = "start"
            self.trim = (0.0, self.duration)
        elif abs(x - he) <= 7:
            self._drag = "end"
            self.trim = (0.0, self.duration)
        else:
            self._drag = "sel"
            self._anchor = self.t_of(x)
            self.sel = None
        self.update()

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        self.hovered.emit(self.t_of(x))
        if self._drag is None:
            hs, he = self._handles()
            near = self.events and (abs(x - hs) <= 7 or abs(x - he) <= 7)
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.IBeamCursor)
            return
        t = self.t_of(x)
        if self._drag == "sel":
            a, b = sorted((self._anchor, t))
            self.sel = (a, b) if b - a > 0.02 else None
            self.selection_changed.emit()
        elif self._drag == "start":
            self.trim = (min(t, self.trim[1] - 0.1), self.trim[1])
        else:
            self.trim = (self.trim[0], max(t, self.trim[0] + 0.1))
        self.update()

    def mouseReleaseEvent(self, _ev):
        drag, self._drag = self._drag, None
        if drag in ("start", "end") and self.trim:
            s, e = self.trim
            self.trim = None
            if s > 0.005 or e < self.duration - 0.005:
                self.trimmed.emit(s, e)
        elif drag == "sel":
            self.selection_changed.emit()
        self.update()

    # ------------------------------------------------------------ painting

    def paintEvent(self, e):
        m = mode_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        vis = e.rect()
        t0, t1 = self.t_of(vis.left() - 40), self.t_of(vis.right() + 40)
        # ruler
        p.setFont(font(8))
        step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if s * self.px_per_s() >= 64)
        t = (int(t0 / step)) * step
        while t <= min(t1, self.duration) + 1e-6:
            x = self.x_of(t)
            p.setPen(m.line)
            p.drawLine(QPointF(x, RULER_H - 6), QPointF(x, h))
            p.setPen(m.detail)
            p.drawText(QPointF(x + 3, RULER_H - 9), fmt_t(t) if step < 60 else f"{int(t // 60)}m")
            t += step
        y = RULER_H
        lane_y = {}
        for name, lh in self.lanes:
            lane_y[name] = (y, lh)
            p.setPen(m.line)
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += lh
        # long pauses, hatched
        hatch = QBrush(QColor(255, 255, 255, 34) if m.dark else QColor(0, 0, 0, 26), Qt.BrushStyle.BDiagPattern)
        for a, b in recedit.pauses(self.events, self.pause_min):
            r = QRectF(self.x_of(a), RULER_H, self.x_of(b) - self.x_of(a), h - RULER_H)
            if r.right() < vis.left() or r.left() > vis.right():
                continue
            p.fillRect(r, hatch)
            p.setPen(QPen(m.detail, 1, Qt.PenStyle.DashLine))
            p.drawLine(r.topLeft(), r.bottomLeft())
            p.drawLine(r.topRight(), r.bottomRight())
            if r.width() > 70:
                lab = f"Idle {b - a:.1f} s"
                p.setFont(font(8, QFont.Weight.DemiBold))
                tw = p.fontMetrics().horizontalAdvance(lab) + 14
                box = QRectF(r.center().x() - tw / 2, lane_y["Movement"][0] + 10, tw, 20)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(20, 12, 50, 200) if m.dark else QColor(255, 255, 255, 220))
                p.drawRoundedRect(box, 9, 9)
                p.setPen(m.text)
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, lab)
        # screen snapshots as a film strip, one frame wherever it fits
        if "Screen" in lane_y:
            sy, sh = lane_y["Screen"]
            last_right = -1e9
            for ev in self.events:
                if ev["type"] != "snap" or ev["t"] < t0 - 5 or ev["t"] > t1:
                    continue
                x = self.x_of(ev["t"])
                if x < last_right + 2:
                    continue
                pm = self.snap_pixmap(ev.get("snap"), sh - 8)
                if pm is None:
                    continue
                p.drawPixmap(int(x), int(sy + 4), pm)
                last_right = x + pm.width()
        # movement: the cursor's height over time, as a thin line
        cy, ch = lane_y["Movement"]
        moves = [ev for ev in self.events if ev["type"] in ("move", "mouse_down", "mouse_up", "scroll")
                 and t0 <= ev["t"] <= t1]
        if moves:
            ys = [ev["y"] for ev in moves]
            lo, hi = min(ys), max(ys)
            span = max(1, hi - lo)
            path = QPainterPath()
            prev_t = None
            for ev in moves:
                pt = QPointF(self.x_of(ev["t"]), cy + 8 + (ev["y"] - lo) / span * (ch - 16))
                if prev_t is None or ev["t"] - prev_t > self.pause_min:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
                prev_t = ev["t"]
            p.setPen(QPen(QColor(m.text.red(), m.text.green(), m.text.blue(), 170), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        # clicks, drags and scrolls
        ky, kh = lane_y["Clicks"]
        mid = ky + kh / 2
        down = {}
        for ev in self.events:
            if ev["t"] < t0 - 30 or ev["t"] > t1:
                continue
            typ = ev["type"]
            if typ == "mouse_down":
                down[ev.get("button")] = ev
            elif typ == "mouse_up" and ev.get("button") in down:
                d = down.pop(ev.get("button"))
                dist = max(abs(ev["x"] - d["x"]), abs(ev["y"] - d["y"]))
                x = self.x_of(d["t"])
                col = CLICK if d.get("button", "left") == "left" else QColor("#ffb86b")
                if dist > 6:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(col)
                    p.drawRoundedRect(QRectF(x, mid - 4, max(6.0, self.x_of(ev["t"]) - x), 8), 4, 4)
                else:
                    p.setPen(QPen(col, 3))
                    p.setBrush(QColor("#ffffff"))
                    p.drawEllipse(QPointF(x, mid), 5.5, 5.5)
            elif typ == "scroll":
                x = self.x_of(ev["t"])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#c9a7ff"))
                up = ev.get("dy", 0) > 0
                tri = QPainterPath()
                tri.moveTo(x, mid + (-6 if up else 6))
                tri.lineTo(x - 5, mid + (3 if up else -3))
                tri.lineTo(x + 5, mid + (3 if up else -3))
                tri.closeSubpath()
                p.drawPath(tri)
        # keys as chips, typing merged into one chip
        ky, kh = lane_y["Keys"]
        p.setFont(font(8, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        last_right = -1e9
        chips = []
        mods = []
        for ev in self.events:
            if ev["type"] not in ("key_down", "key_up"):
                continue
            name = key_text(ev)
            if name in MOD_KEYS:  # modifiers only show as part of a combination like ctrl+s
                m_ = MOD_KEYS[name]
                if ev["type"] == "key_down" and m_ not in mods:
                    mods.append(m_)
                elif ev["type"] == "key_up" and m_ in mods:
                    mods.remove(m_)
                continue
            if ev["type"] != "key_down" or ev["t"] < t0 - 30 or ev["t"] > t1:
                continue
            held = [m_ for m_ in mods if m_ != "shift" or len(name) > 1]
            if held:
                chips.append((ev["t"], ev["t"], False, "+".join(held + [name])))
            elif chips and len(name) == 1 and chips[-1][2] and ev["t"] - chips[-1][1] < 1.5:
                chips[-1] = (chips[-1][0], ev["t"], True, chips[-1][3] + name)
            else:
                chips.append((ev["t"], ev["t"], len(name) == 1, name))
        for start, _end, typed, text in chips:
            label = f"“{text}”" if typed and len(text) > 1 else text
            x = self.x_of(start)
            tw = fm.horizontalAdvance(label) + 12
            p.setPen(Qt.PenStyle.NoPen)
            if x < last_right + 3:
                p.setBrush(QColor(255, 255, 255, 170) if m.dark else QColor(40, 30, 90, 150))
                p.drawEllipse(QPointF(x, ky + kh / 2), 3, 3)
                continue
            p.setBrush(QColor(255, 255, 255, 225) if m.dark else QColor(40, 30, 90, 220))
            r = QRectF(x, ky + (kh - 22) / 2, tw, 22)
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor("#23184f") if m.dark else QColor("#ffffff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, label)
            last_right = r.right()
        # selection
        if self.sel:
            a, b = self.sel
            r = QRectF(self.x_of(a), RULER_H, self.x_of(b) - self.x_of(a), h - RULER_H)
            p.setPen(QPen(SEL, 1.5))
            c = QColor(SEL)
            c.setAlpha(60)
            p.setBrush(c)
            p.drawRoundedRect(r, 5, 5)
        # trim handles, with the cut part dimmed
        s, e2 = self.trim or (0.0, self.duration)
        hs, he = self.x_of(s), self.x_of(e2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        if hs > 12:
            p.drawRect(QRectF(0, RULER_H, hs, h - RULER_H))
        if he < self.x_of(self.duration):
            p.drawRect(QRectF(he, RULER_H, w - he, h - RULER_H))
        if self.events:
            p.setBrush(HANDLE)
            for x in (hs, he):
                p.drawRoundedRect(QRectF(x - 3, RULER_H, 6, h - RULER_H), 3, 3)


class RecordingEditor(GlassPanel):
    """The Edit recording panel of the Macro Recorder tab."""

    def __init__(self, tab):
        super().__init__(radius=30)
        self.tab = tab
        self.undo_stack, self.redo_stack = [], []
        self.original_len = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(Caption("Edit recording"))
        self.lbl_stats = QLabel("")
        self.lbl_stats.setProperty("role", "detail")
        head.addWidget(self.lbl_stats)
        head.addStretch(1)
        self.btn_undo = GlassButton("", icon="arrow-counter-clockwise", small=True, tip="Undo edit")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = GlassButton("", icon="arrow-clockwise", small=True, tip="Redo edit")
        self.btn_redo.clicked.connect(self.redo)
        zo = GlassButton("−", small=True, tip="Zoom out")
        zo.clicked.connect(lambda: self.set_zoom(self.timeline.zoom / 1.6))
        zi = GlassButton("+", small=True, tip="Zoom in")
        zi.clicked.connect(lambda: self.set_zoom(self.timeline.zoom * 1.6))
        for b in (self.btn_undo, self.btn_redo, zo, zi):
            head.addWidget(b)
        lay.addLayout(head)

        box = QHBoxLayout()
        box.setSpacing(0)
        labels = QWidget()
        labels.setFixedWidth(84)
        self.lane_box = QVBoxLayout(labels)
        self.lane_box.setContentsMargins(0, RULER_H, 0, 0)
        self.lane_box.setSpacing(0)
        self._lane_names = None
        box.addWidget(labels)
        self.timeline = Timeline()
        self.timeline.selection_changed.connect(self._on_selection)
        self.timeline.trimmed.connect(self._on_trim)
        self.timeline.hovered.connect(self._preview_at)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(self.timeline.minimumHeight() + 16)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: rgba(0,0,0,40); "
                                  "border-radius: 14px; }")
        box.addWidget(self.scroll, 1)
        lay.addLayout(box)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.lbl_sel = QLabel("Drag across the timeline to select. Drag the yellow handles to trim the ends.")
        self.lbl_sel.setProperty("role", "detail")
        row.addWidget(self.lbl_sel)
        self.btn_play = GlassButton("Play selection", icon="play", small=True)
        self.btn_play.clicked.connect(self.play_selection)
        self.btn_del = GlassButton("Delete", icon="trash", kind="danger", small=True)
        self.btn_del.clicked.connect(self.delete_selection)
        self.btn_keep = GlassButton("Keep only this", small=True)
        self.btn_keep.clicked.connect(self.keep_selection)
        for b in (self.btn_play, self.btn_del, self.btn_keep):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(QLabel("Pauses longer than"))
        self.e_long = QLineEdit("2.0")
        self.e_to = QLineEdit("0.5")
        for e in (self.e_long, self.e_to):
            e.setFixedWidth(52)
            e.setAlignment(Qt.AlignmentFlag.AlignRight)
            e.textChanged.connect(self._pause_opts)
        row.addWidget(self.e_long)
        row.addWidget(QLabel("s become"))
        row.addWidget(self.e_to)
        row.addWidget(QLabel("s"))
        self.btn_short = GlassButton("Shorten pauses", icon="timer", kind="primary", small=True)
        self.btn_short.clicked.connect(self.shorten)
        row.addWidget(self.btn_short)
        lay.addLayout(row)

        low = QHBoxLayout()
        low.setSpacing(12)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Time", "Event", "Where / key"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(150)
        self.tree.setColumnWidth(0, 80)
        self.tree.setColumnWidth(1, 130)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        low.addWidget(self.tree, 1)
        trim = QVBoxLayout()
        trim.setSpacing(8)
        trim.addWidget(Caption("Trim"))
        self.e_start, self.e_end = QLineEdit(), QLineEdit()
        for text, e in (("Start", self.e_start), ("End", self.e_end)):
            r = QHBoxLayout()
            lab = QLabel(text)
            lab.setFixedWidth(40)
            e.setFixedWidth(80)
            r.addWidget(lab)
            r.addWidget(e)
            r.addStretch(1)
            trim.addLayout(r)
        b = GlassButton("Apply trim", small=True)
        b.clicked.connect(self._apply_trim_fields)
        trim.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.preview = QLabel()
        self.preview.setFixedSize(250, 141)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: rgba(0,0,0,70); border-radius: 10px;")
        self.preview.hide()
        trim.addWidget(self.preview)
        tip = QLabel("Edits change the recording in Clicker; the file only changes when you Save.")
        tip.setProperty("role", "detail")
        tip.setWordWrap(True)
        tip.setFixedWidth(250)
        trim.addWidget(tip)
        trim.addStretch(1)
        low.addLayout(trim)
        lay.addLayout(low)
        self.load([])

    # ------------------------------------------------------------ state

    def load(self, events):
        """A new or opened recording: forget edit history."""
        self.undo_stack, self.redo_stack = [], []
        self.original_len = recedit.length(events)
        self._show(events)

    def _show(self, events):
        self.timeline.set_events(events, self.tab.snaps)
        names = [n for n, _h in self.timeline.lanes]
        if names != self._lane_names:
            self._lane_names = names
            while self.lane_box.count():
                it = self.lane_box.takeAt(0)
                if it.widget() is not None:
                    it.widget().deleteLater()
            for name, lh in self.timeline.lanes:
                lab = QLabel(name)
                lab.setProperty("role", "detail")
                lab.setFixedHeight(lh)
                self.lane_box.addWidget(lab)
            self.lane_box.addStretch(1)
            self.scroll.setFixedHeight(self.timeline.minimumHeight() + 16)
        self.preview.setVisible("Screen" in names)
        if "Screen" in names:
            self._preview_at(0.0)
        self.timeline.relayout(max(300, self.scroll.viewport().width()))
        self._refresh()

    def _preview_at(self, t):
        """Show the snapshot taken at (or just before) time t."""
        if not self.preview.isVisible():
            return
        best = None
        for e in self.tab.events:
            if e["type"] == "snap":
                if e["t"] <= t or best is None:
                    best = e
                if e["t"] > t:
                    break
        if best is None:
            return
        pm = self.timeline.snap_pixmap(best.get("snap"), 141)
        if pm is not None:
            if pm.width() > 250:
                pm = pm.scaledToWidth(250, Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pm)
            self.preview.setToolTip(f"Screen at {fmt_t(best['t'])}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.timeline.relayout(max(300, self.scroll.viewport().width()))

    def set_zoom(self, z):
        self.timeline.zoom = min(40.0, max(1.0, z))
        self.timeline.relayout()

    def _refresh(self):
        ev = self.tab.events
        n = sum(1 for e in ev if e["type"] != "snap")
        now = recedit.length(ev)
        text = f"{n} events · {fmt_t(now)}"
        if self.undo_stack and abs(now - self.original_len) > 0.05:
            text += f"  (was {fmt_t(self.original_len)})"
        self.lbl_stats.setText(text)
        self.btn_undo.setEnabled(bool(self.undo_stack))
        self.btn_redo.setEnabled(bool(self.redo_stack))
        self.e_start.setText(fmt_t(0))
        self.e_end.setText(fmt_t(now))
        self._refresh_pause_button()
        self._on_selection()

    def _pause_values(self):
        try:
            long_ = float(self.e_long.text())
            to = float(self.e_to.text())
            return (long_, to) if long_ > 0 and to >= 0 else (None, None)
        except ValueError:
            return None, None

    def _pause_opts(self, *_):
        long_, _to = self._pause_values()
        if long_:
            self.timeline.pause_min = long_
            self.timeline.update()
        self._refresh_pause_button()

    def _refresh_pause_button(self):
        long_, to = self._pause_values()
        k = len(recedit.pauses(self.tab.events, long_)) if long_ else 0
        self.btn_short.setText(f"Shorten {k} pause{'s' if k != 1 else ''}" if k else "No long pauses")
        self.btn_short.setEnabled(bool(k) and to is not None)
        self.btn_short.updateGeometry()

    def _on_selection(self):
        sel = self.timeline.sel
        for b in (self.btn_play, self.btn_del, self.btn_keep):
            b.setEnabled(bool(sel) and not self.tab.recorder.active)
        self.tree.clear()
        ev = self.tab.events
        if sel:
            i, j = recedit.select(ev, *sel)
            items = ev[i:j]
            n = sum(1 for e in items if e["type"] != "snap")
            self.lbl_sel.setText(f"Selected {fmt_t(sel[0])} – {fmt_t(sel[1])} · {n} events")
            self.lbl_sel.setProperty("role", "error" if n else "detail")
        else:
            self.lbl_sel.setText("Drag across the timeline to select. Drag the yellow handles to trim the ends.")
            self.lbl_sel.setProperty("role", "detail")
            items = ev
        self.lbl_sel.style().unpolish(self.lbl_sel)
        self.lbl_sel.style().polish(self.lbl_sel)
        shown = [e for e in items if e["type"] not in ("move", "snap")][:300]
        for e in shown:
            kind, where = recedit.describe(e)
            self.tree.addTopLevelItem(QTreeWidgetItem([fmt_t(e["t"]), kind, where]))

    # ------------------------------------------------------------ edits

    def _apply(self, new, message):
        self.undo_stack.append(copy.deepcopy(self.tab.events))
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack = []
        self.tab.replace_events(new)
        self._show(new)
        self.tab.main.set_status(message)

    def delete_selection(self):
        if self.timeline.sel:
            a, b = self.timeline.sel
            self._apply(recedit.delete(self.tab.events, a, b), f"Deleted {b - a:.1f} s")

    def keep_selection(self):
        if self.timeline.sel:
            a, b = self.timeline.sel
            self._apply(recedit.keep_only(self.tab.events, a, b), f"Kept {b - a:.1f} s")

    def shorten(self):
        long_, to = self._pause_values()
        if long_ is None:
            return
        before = recedit.length(self.tab.events)
        new = recedit.shorten_pauses(self.tab.events, long_, to)
        self._apply(new, f"Shortened pauses: {before - recedit.length(new):.1f} s shorter")

    def _on_trim(self, s, e):
        self._apply(recedit.trim(self.tab.events, s, e), f"Trimmed to {fmt_t(s)} – {fmt_t(e)}")

    def _apply_trim_fields(self):
        def parse(text):
            text = text.strip()
            if ":" in text:
                m, s = text.split(":", 1)
                return int(m) * 60 + float(s)
            return float(text)
        try:
            s, e = parse(self.e_start.text()), parse(self.e_end.text())
        except ValueError:
            self.tab.main.set_status("Trim times look like 0:01.8 or 1.8", error=True)
            return
        if e <= s:
            self.tab.main.set_status("The end must be after the start.", error=True)
            return
        if s <= 0.005 and e >= recedit.length(self.tab.events) - 0.005:
            return
        self._on_trim(s, e)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.tab.events))
            prev = self.undo_stack.pop()
            self.tab.replace_events(prev)
            self._show(prev)

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.tab.events))
            nxt = self.redo_stack.pop()
            self.tab.replace_events(nxt)
            self._show(nxt)

    def play_selection(self):
        if self.timeline.sel:
            a, b = self.timeline.sel
            part = recedit.trim(self.tab.events, a, b)
            self.tab.play_events(part, f"Playing {fmt_t(a)} – {fmt_t(b)}")
