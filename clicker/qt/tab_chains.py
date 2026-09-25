"""The Chains tab: scripts as cards in a row, run one after another.

Drag cards to reorder them (the others glide out of the way), click a card to set how many times it
runs, how long to wait before it and what happens if it fails. While the chain runs, the card that is
running glows and finished cards get a tick.
"""

import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QVBoxLayout, QWidget)

from .. import chains, library, storage
from . import dialogs, glass
from .glass import GlassPanel, font
from .library_dialog import pick_script, thumb_pixmap
from .widgets import Caption, GlassButton, mode_of

CARD_W, CARD_H, GAP = 196, 168, 46
THUMB_H = 92


class ChainCanvas(QWidget):
    """Lays the cards out in rows, draws the arrows between them, and handles drag to reorder."""

    selected = Signal(int)
    add_clicked = Signal()
    reordered = Signal(int, int)   # from index, to index

    def __init__(self, tab):
        super().__init__()
        self.tab = tab
        self.pos_of = {}       # card index -> QPointF currently drawn (animated)
        self.sel = None
        self.state = {}        # card index -> "running" / "done" / "failed"
        self.drag = None       # (index, grab offset, current point)
        self.hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(CARD_H + 40)

    # ------------------------------------------------------------ layout

    def cols(self):
        return max(1, int((self.width() - 20 + GAP) // (CARD_W + GAP)))

    def slot(self, k):
        c = self.cols()
        return QPointF(10 + (k % c) * (CARD_W + GAP), 10 + (k // c) * (CARD_H + 40))

    def count(self):
        return len(self.tab.chain["links"])

    def relayout(self, animate=True):
        n = self.count()
        rows = (n + 1 + self.cols() - 1) // self.cols()
        self.setMinimumHeight(max(CARD_H + 40, rows * (CARD_H + 40)))
        target = {k: self.slot(k) for k in range(n + 1)}  # the extra slot is the + card
        start = {k: self.pos_of.get(k, target[k]) for k in target}
        if not animate or not glass.motion_on() or not self.isVisible():
            self.pos_of = target
            self.update()
            return

        def step(t):
            t = float(t)
            self.pos_of = {k: start[k] + (target[k] - start[k]) * t for k in target}
            self.update()
        glass.animate(self, 0.0, 1.0, glass.BASE, step, curve=glass.GLIDE, attr="_glide")

    def resizeEvent(self, e):
        self.relayout(animate=False)
        super().resizeEvent(e)

    def rect_of(self, k):
        p = self.pos_of.get(k, self.slot(k))
        return QRectF(p.x(), p.y(), CARD_W, CARD_H)

    def index_at(self, pt):
        for k in range(self.count() + 1):
            if self.rect_of(k).contains(pt):
                return k
        return None

    def drop_index(self, pt):
        """The place a dragged card would land: the nearest slot."""
        best, bd = 0, None
        for k in range(self.count()):
            s = self.slot(k)
            d = (s.x() + CARD_W / 2 - pt.x()) ** 2 + (s.y() + CARD_H / 2 - pt.y()) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        return best

    # ------------------------------------------------------------ mouse

    def mousePressEvent(self, e):
        k = self.index_at(e.position())
        if k is None or e.button() != Qt.MouseButton.LeftButton:
            return
        if k == self.count():
            self.add_clicked.emit()
            return
        if self._remove_rect(k).contains(e.position()) and self.hover == k and not self.tab.running():
            self.tab.remove_link(k)
            return
        self.selected.emit(k)
        if not self.tab.running():
            self.drag = (k, e.position() - self.rect_of(k).topLeft(), e.position(), False)

    def mouseMoveEvent(self, e):
        if self.drag is not None:
            k, off, start, moving = self.drag
            if not moving and (e.position() - start).manhattanLength() < 6:
                return
            self.drag = (k, off, start, True)
            self.pos_of[k] = e.position() - off
            # the others make room where the card would land
            to = self.drop_index(e.position())
            order = [i for i in range(self.count()) if i != k]
            order.insert(to, k)
            for place, i in enumerate(order):
                if i != k:
                    self._glide_one(i, self.slot(place))
            self.update()
            return
        k = self.index_at(e.position())
        if k != self.hover:
            self.hover = k
            self.setCursor(Qt.CursorShape.PointingHandCursor if k is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def _glide_one(self, i, target):
        cur = self.pos_of.get(i, target)
        if (cur - target).manhattanLength() < 1 or getattr(self, f"_t{i}", None) == (target.x(), target.y()):
            return
        setattr(self, f"_t{i}", (target.x(), target.y()))

        def step(t, a=cur, b=target):
            self.pos_of[i] = a + (b - a) * float(t)
            self.update()
        glass.animate(self, 0.0, 1.0, glass.FAST + 50, step, attr=f"_g{i}")

    def mouseReleaseEvent(self, e):
        if self.drag is None:
            return
        k, _off, _s, moving = self.drag
        self.drag = None
        for i in range(self.count()):
            setattr(self, f"_t{i}", None)
        if moving:
            to = self.drop_index(e.position())
            if to != k:
                self.reordered.emit(k, to)
                return
        self.relayout()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    # ------------------------------------------------------------ painting

    def _remove_rect(self, k):
        r = self.rect_of(k)
        return QRectF(r.right() - 30, r.y() + 8, 22, 22)

    def paintEvent(self, _e):
        m = mode_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        n = self.count()
        # arrows first, under the cards
        for k in range(n - 1):
            self._arrow(p, self.rect_of(k), self.rect_of(k + 1))
        dragging = self.drag[0] if self.drag and self.drag[3] else None
        for k in range(n):
            if k != dragging:
                self._card(p, m, k)
        self._add_card(p, m, self.rect_of(n))
        if dragging is not None:
            self._card(p, m, dragging, lifted=True)
        p.end()

    def _arrow(self, p, a, b):
        if abs(a.y() - b.y()) < 2:  # same row: straight across
            s, t = QPointF(a.right() + 6, a.center().y()), QPointF(b.x() - 8, b.center().y())
            path = QPainterPath(s)
            path.lineTo(t)
        else:  # wraps to the next row: down from the card, round to the start of the row
            s, t = QPointF(a.center().x(), a.bottom() + 4), QPointF(b.center().x(), b.y() - 6)
            mid = (s.y() + t.y()) / 2
            path = QPainterPath(s)
            path.cubicTo(QPointF(s.x(), mid), QPointF(t.x(), mid), t)
        p.setPen(QPen(QColor(255, 196, 107, 210), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        ang = path.angleAtPercent(1.0)
        head = QPainterPath()
        head.moveTo(-8, -4.5)
        head.lineTo(0, 0)
        head.lineTo(-8, 4.5)
        p.save()
        p.translate(t)
        p.rotate(-ang)
        p.drawPath(head)
        p.restore()

    def _card(self, p, m, k, lifted=False):
        link = self.tab.chain["links"][k]
        r = self.rect_of(k)
        if lifted:
            r = r.translated(0, -4)
        state = self.state.get(k)
        entry = self.tab.entry_for(link["path"])
        missing = not os.path.isfile(link["path"])
        p.save()
        if missing:
            p.setOpacity(0.5)
        if lifted:
            shadow, pad = glass.shadow_pixmap(r.width(), r.height(), 18, 22, 0.45)
            p.drawPixmap(QPointF(r.x() - pad, r.y() - pad + 8), shadow)
        hover = self.hover == k and not lifted
        if state == "running":
            p.setPen(QPen(QColor(glass.ACCENT), 3))
        elif k == self.sel:  # selected: white, so it never looks like the running card
            p.setPen(QPen(QColor(255, 255, 255, 210) if m.dark else QColor(0, 0, 0, 150), 2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 90 if hover else 50), 1))
        base = QColor(34, 36, 60, 235) if m.dark else QColor(255, 255, 255, 235)
        if lifted or hover:
            base = base.lighter(112)
        p.setBrush(base)
        p.drawRoundedRect(r, 18, 18)
        # picture
        tr = QRectF(r.x() + 8, r.y() + 8, r.width() - 16, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(tr, 12, 12)
        p.save()
        p.setClipPath(clip)
        p.fillRect(tr, QColor(0, 0, 0, 80))
        pm = thumb_pixmap(self.tab.main.library.thumb_path(entry)) if entry and entry.get("thumb") else None
        if pm is not None:
            s = max(tr.width() / pm.width(), tr.height() / pm.height())
            w, h = pm.width() * s, pm.height() * s
            p.drawPixmap(QRectF(tr.center().x() - w / 2, tr.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
        else:
            p.setPen(QColor(255, 255, 255, 140))
            p.setFont(font(8.5))
            acts = ", ".join((entry or {}).get("actions", [])[:3]) or "Script"
            p.drawText(tr.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, acts)
        p.restore()
        # number, state
        nb = QRectF(tr.x() + 8, tr.y() + 8, 24, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush({"done": QColor(glass.GREEN), "failed": QColor(glass.RED),
                    "skipped": QColor(120, 120, 140)}.get(state, QColor(0, 0, 0, 150)))
        p.drawEllipse(nb)
        p.setPen(QColor("#ffffff"))
        p.setFont(font(9, QFont.Weight.Bold))
        mark = {"done": "✓", "failed": "!", "skipped": "–"}.get(state, str(k + 1))
        p.drawText(nb, Qt.AlignmentFlag.AlignCenter, mark)
        if hover and not self.tab.running():
            rr = self._remove_rect(k)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawEllipse(rr)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.6))
            c = rr.center()
            p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
            p.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))
        # text
        x, w = r.x() + 12, r.width() - 24
        f = font(10, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(m.text)
        name = (entry or {}).get("name") or chains.link_name(link)
        p.drawText(QRectF(x, tr.bottom() + 8, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetrics(f).elidedText(name, Qt.TextElideMode.ElideRight, int(w)))
        f2 = font(8.2)
        p.setFont(f2)
        p.setPen(m.detail)
        line = "File not found" if missing else chains.describe_link(link)
        p.drawText(QRectF(x, tr.bottom() + 28, w, 34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop |
                   Qt.TextFlag.TextWordWrap, line)
        p.restore()

    def _add_card(self, p, m, r):
        hover = self.hover == self.count()
        p.setPen(QPen(QColor(255, 255, 255, 120 if hover else 70), 1.5, Qt.PenStyle.DashLine))
        p.setBrush(QColor(255, 255, 255, 24 if hover else 10))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 18, 18)
        p.setPen(m.text if hover else m.detail)
        p.setFont(font(26, QFont.Weight.Light))
        p.drawText(QRectF(r.x(), r.y() + 30, r.width(), 50), Qt.AlignmentFlag.AlignCenter, "+")
        p.setFont(font(9.5, QFont.Weight.DemiBold))
        p.drawText(QRectF(r.x(), r.y() + 84, r.width(), 22), Qt.AlignmentFlag.AlignCenter, "Add a script")
        p.setFont(font(8.2))
        p.setPen(m.detail)
        p.drawText(QRectF(r.x() + 14, r.y() + 106, r.width() - 28, 40), Qt.AlignmentFlag.AlignCenter |
                   Qt.TextFlag.TextWordWrap, "from the Library")


class ChainsTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.chain = chains.new_chain()
        self.path = None
        self.dirty = False
        self._build()
        self._load_card(None)

    # ------------------------------------------------------------ layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(8)
        self.btn_start = GlassButton("Start", icon="play", kind="primary")
        self.btn_start.clicked.connect(self.toggle_run)
        bl.addWidget(self.btn_start)
        self.btn_pause = GlassButton("Pause", icon="pause")
        self.btn_pause.clicked.connect(self.main.toggle_pause)
        bl.addWidget(self.btn_pause)
        bl.addSpacing(8)
        for text, ic, cmd in (("New", "file-plus", self.new_chain), ("Open", "folder-open", self.open),
                              ("Save", "floppy-disk", self.save), ("Save As", None, lambda: self.save(True))):
            b = GlassButton(text, icon=ic)
            b.clicked.connect(cmd)
            bl.addWidget(b)
        bl.addStretch(1)
        bl.addWidget(QLabel("Name"))
        self.e_name = QLineEdit()
        self.e_name.setFixedWidth(200)
        self.e_name.textEdited.connect(self._name_changed)
        bl.addWidget(self.e_name)
        bl.addWidget(QLabel("Run the chain"))
        self.e_repeat = QLineEdit("1")
        self.e_repeat.setFixedWidth(52)
        self.e_repeat.setToolTip("0 = keep going until stopped")
        self.e_repeat.textEdited.connect(self._repeat_changed)
        bl.addWidget(self.e_repeat)
        bl.addWidget(QLabel("times"))
        root.addWidget(bar)

        panel = GlassPanel(radius=30)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(22, 18, 22, 18)
        pl.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(Caption("Chain"))
        self.lbl_info = QLabel("")
        self.lbl_info.setProperty("role", "detail")
        head.addWidget(self.lbl_info)
        head.addStretch(1)
        pl.addLayout(head)
        self.canvas = ChainCanvas(self)
        self.canvas.selected.connect(self._select)
        self.canvas.add_clicked.connect(self.add_link)
        self.canvas.reordered.connect(self.move_link)
        pl.addWidget(self.canvas, 1)
        root.addWidget(panel, 1)

        # the selected card's options
        self.opts = GlassPanel(radius=26)
        g = QGridLayout(self.opts)
        g.setContentsMargins(22, 14, 22, 14)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        self.lbl_card = QLabel("")
        self.lbl_card.setFont(font(10.5, QFont.Weight.DemiBold))
        g.addWidget(self.lbl_card, 0, 0, 1, 2)
        g.addWidget(QLabel("Runs"), 0, 2)
        self.e_times = QLineEdit("1")
        self.e_times.setFixedWidth(52)
        self.e_times.textEdited.connect(self._card_changed)
        g.addWidget(self.e_times, 0, 3)
        g.addWidget(QLabel("times, waiting"), 0, 4)
        self.e_pause = QLineEdit("0")
        self.e_pause.setFixedWidth(60)
        self.e_pause.textEdited.connect(self._card_changed)
        g.addWidget(self.e_pause, 0, 5)
        g.addWidget(QLabel("s before it.   If it fails:"), 0, 6)
        self.cb_fail = QComboBox()
        for key, text in chains.ON_FAIL:
            self.cb_fail.addItem(text, key)
        self.cb_fail.activated.connect(self._card_changed)
        g.addWidget(self.cb_fail, 0, 7)
        self.e_retries = QLineEdit("1")
        self.e_retries.setFixedWidth(44)
        self.e_retries.setToolTip("How many more tries")
        self.e_retries.textEdited.connect(self._card_changed)
        g.addWidget(self.e_retries, 0, 8)
        self.lbl_retries = QLabel("more tries")
        g.addWidget(self.lbl_retries, 0, 9)
        g.addWidget(QLabel("Only if"), 1, 2)
        self.e_only = QLineEdit()
        self.e_only.setPlaceholderText("always; or a check like {gold} < 500 or contains({status}, 'ready')")
        self.e_only.textEdited.connect(self._card_changed)
        g.addWidget(self.e_only, 1, 3, 1, 7)
        self.lbl_only = QLabel("")
        self.lbl_only.setProperty("role", "detail")
        g.addWidget(self.lbl_only, 1, 10, 1, 3)
        g.setColumnStretch(10, 1)
        b = GlassButton("Edit script", icon="list-bullets", small=True, tip="Open this script in Action Script")
        b.clicked.connect(self.edit_script)
        g.addWidget(b, 0, 11)
        b = GlassButton("Remove", icon="trash", small=True, kind="danger")
        b.clicked.connect(lambda: self.remove_link(self.canvas.sel))
        g.addWidget(b, 0, 12)
        root.addWidget(self.opts)
        self.hint = QLabel("Build small scripts that each do one job, then chain them here. Drag cards to change "
                           "the order. Variables set by one script carry on to the next.")
        self.hint.setProperty("role", "detail")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

    # ------------------------------------------------------------ chain editing

    def entry_for(self, path):
        e = self.main.library.entries.get(os.path.abspath(path))
        if e is None and os.path.isfile(path):
            e = self.main.library.touch_file(path, used=False)
        return e

    def changed(self):
        self.dirty = True
        self._refresh()
        self.main.update_title()

    def _refresh(self, animate=True):
        n = len(self.chain["links"])
        self.lbl_info.setText(f"{n} script{'s' if n != 1 else ''}" if n else "Empty: add a script to start")
        if not self.e_name.hasFocus():
            self.e_name.setText(self.chain["name"])
        if not self.e_repeat.hasFocus():
            self.e_repeat.setText(str(self.chain["repeat"]))
        self.canvas.relayout(animate)
        self.btn_start.setEnabled(bool(n) or self.running())

    def add_link(self):
        if self.running():
            return
        path = pick_script(self.main, "Add a script to the chain")
        if not path:
            return
        self.chain["links"].append(chains.new_link(path))
        k = len(self.chain["links"]) - 1
        self.canvas.pos_of[k] = self.canvas.slot(k)          # appears where the + card was
        self.canvas.pos_of[k + 1] = self.canvas.slot(k)      # and the + card glides on
        self.changed()
        self._select(k)

    def remove_link(self, k):
        if k is None or self.running() or not 0 <= k < len(self.chain["links"]):
            return
        del self.chain["links"][k]
        pos = self.canvas.pos_of
        self.canvas.pos_of = {i - (1 if i > k else 0): p for i, p in pos.items() if i != k}
        self.canvas.state.clear()
        self.changed()
        self._select(min(k, len(self.chain["links"]) - 1) if self.chain["links"] else None)

    def move_link(self, a, b):
        links = self.chain["links"]
        link = links.pop(a)
        links.insert(b, link)
        order = [i for i in range(len(links)) if i != a]
        order.insert(b, a)
        pos = dict(self.canvas.pos_of)
        self.canvas.pos_of = {new: pos.get(old, self.canvas.slot(new)) for new, old in enumerate(order)}
        self.canvas.pos_of[len(links)] = pos.get(len(links), self.canvas.slot(len(links)))
        self.canvas.state.clear()
        self.changed()
        self._select(b)

    def _select(self, k):
        self.canvas.sel = k
        self.canvas.update()
        self._load_card(k)

    def _load_card(self, k):
        on = k is not None and 0 <= k < len(self.chain["links"])
        for w in self.opts.findChildren(QWidget):
            w.setEnabled(on and not self.running())
        if not on:
            self.lbl_card.setText("Click a card to set its options")
            return
        link = self.chain["links"][k]
        e = self.entry_for(link["path"])
        self.lbl_card.setText(f"{k + 1}. {(e or {}).get('name') or chains.link_name(link)}")
        self.e_times.setText(str(link["repeat"]))
        self.e_pause.setText(f"{link['pause_s']:g}")
        self.cb_fail.setCurrentIndex(max(0, self.cb_fail.findData(link["on_fail"])))
        self.e_retries.setText(str(link["retries"]))
        if not self.e_only.hasFocus():
            self.e_only.setText(link.get("only_if", ""))
        self._check_only(link)
        retry = link["on_fail"] == "retry"
        self.e_retries.setVisible(retry)
        self.lbl_retries.setVisible(retry)

    def _card_changed(self, *_):
        k = self.canvas.sel
        if k is None or not 0 <= k < len(self.chain["links"]):
            return
        link = self.chain["links"][k]

        def num(edit, cast, lo, default):
            try:
                return max(lo, cast(edit.text().strip() or default))
            except ValueError:
                return None
        for key, val in (("repeat", num(self.e_times, int, 1, 1)), ("pause_s", num(self.e_pause, float, 0, 0)),
                         ("retries", num(self.e_retries, int, 1, 1))):
            if val is not None:
                link[key] = val
        link["on_fail"] = self.cb_fail.currentData()
        link["only_if"] = self.e_only.text().strip()
        self._check_only(link)
        retry = link["on_fail"] == "retry"
        self.e_retries.setVisible(retry)
        self.lbl_retries.setVisible(retry)
        self.changed()

    def _check_only(self, link):
        from .. import expr
        msg = ""
        if link.get("only_if"):
            try:
                expr.parse(link["only_if"])
            except expr.ExprError as e:
                msg = str(e)
        self.lbl_only.setText(msg)

    def _name_changed(self, text):
        self.chain["name"] = text.strip() or "Untitled chain"
        self.dirty = True
        self.main.update_title()

    def _repeat_changed(self, text):
        try:
            self.chain["repeat"] = max(0, int(text.strip() or 1))
            self.dirty = True
        except ValueError:
            pass

    def edit_script(self):
        k = self.canvas.sel
        if k is not None and 0 <= k < len(self.chain["links"]):
            self.main.show_tab("actions")
            self.main.action_tab.open_from_library(self.chain["links"][k]["path"])

    # ------------------------------------------------------------ files

    def confirm_discard(self, why):
        if not self.dirty or not self.chain["links"]:
            return True
        ans = QMessageBox.question(self, "Unsaved changes", f"Save the current chain before {why}?",
                                   QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                   QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if ans == QMessageBox.StandardButton.Save else True

    def set_chain(self, chain, path=None):
        self.chain, self.path, self.dirty = chains.normalize(chain), path, False
        self.canvas.pos_of, self.canvas.state, self.canvas.sel = {}, {}, None
        self._refresh(animate=False)
        self._load_card(0 if self.chain["links"] else None)
        if self.chain["links"]:
            self._select(0)
        self.main.update_title()

    def new_chain(self):
        if self.running() or not self.confirm_discard("starting a new one"):
            return
        self.set_chain(chains.new_chain())

    def open(self):
        self.main.open_library("chain")

    def browse(self):
        if self.running() or not self.confirm_discard("opening another"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open chain", "", f"Clicker chains (*{chains.EXT})")
        if path:
            self.open_path(path)

    def open_from_library(self, path):
        if not self.running() and self.confirm_discard("opening another"):
            self.open_path(path)

    def open_version(self, path, copy):
        if self.running() or not self.confirm_discard("going back to an earlier version"):
            return False
        try:
            chain = chains.load(copy)
        except Exception as e:
            QMessageBox.warning(self, "Could not open that version", str(e))
            return False
        self.set_chain(chain, path)
        self.dirty = True
        self.main.update_title()
        return True

    def open_path(self, path):
        try:
            chain = chains.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open chain", str(e))
            return
        self.set_chain(chain, path)
        self.main.remember(path, "chain", library.chain_info(self.chain))

    def save(self, save_as=False):
        path = self.path
        if save_as or not path:
            base = self.chain["name"] if self.chain["name"] != "Untitled chain" else "chain"
            path, _ = QFileDialog.getSaveFileName(self, "Save chain", f"{base}{chains.EXT}",
                                                  f"Clicker chain (*{chains.EXT})")
            if not path:
                return False
            if not path.lower().endswith(chains.EXT):
                path += chains.EXT
        if self.chain["name"] == "Untitled chain":
            self.chain["name"] = os.path.splitext(os.path.basename(path))[0]
        try:
            self.main.keep_version(path)
            chains.save(path, self.chain)
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return False
        self.path, self.dirty = path, False
        self._refresh(animate=False)
        self.main.update_title()
        self.main.set_status(f"Saved {os.path.basename(path)}")
        self.main.remember(path, "chain", library.chain_info(self.chain))
        return True

    def title_text(self):
        name = os.path.basename(self.path) if self.path else self.chain["name"]
        return name + (" *" if self.dirty else "")

    # ------------------------------------------------------------ running

    def running(self):
        return self.main.job_running_for(self)

    def toggle_run(self):
        if self.running():
            self.main.stop_job()
            return
        bad = chains.problems(self.chain)
        if bad:
            QMessageBox.warning(self, "Can't start the chain", "\n".join(bad))
            return
        inputs, seen = [], set()
        for link in self.chain["links"]:
            try:
                script, _a = storage.load_script(link["path"])
            except Exception as e:
                QMessageBox.warning(self, "Can't start the chain", f"{link['path']}: {e}")
                return
            for item in script.get("inputs") or []:
                if item["name"] not in seen:
                    seen.add(item["name"])
                    inputs.append(item)
        values = {}
        if inputs:
            values = dialogs.ask_inputs(self.main, inputs, self.main.last_inputs)
            if values is None:
                return
            self.main.last_inputs.update(values)
        job = chains.ChainJob(self.chain, self.main.emitter("script"), path=self.path, inputs_map=values,
                              save_log=self.main.settings.get("save_run_logs", True))
        self.canvas.state.clear()
        if self.main.start_job(job, self):
            self.main.set_status(f"Running the chain {self.chain['name']}")

    def on_job(self, kind, payload):
        st = self.canvas.state
        if kind == "chain" and payload.get("skipped"):
            st[payload["link"]] = "skipped"
            self.canvas.update()
        elif kind == "chain":
            i = payload["link"]
            for k in list(st):
                if st[k] == "running" and k != i:
                    st[k] = "done"
            st[i] = "running"
            self.canvas.update()
        elif kind == "run":
            st.clear()
            self.canvas.update()
        elif kind == "done":
            ok, _reason = payload
            for k in list(st):
                if st[k] == "running":
                    st[k] = "done" if ok else "failed"
            self.canvas.update()

    def update_state(self, running_mine, running_any, paused):
        self.btn_start.setText("Stop" if running_mine else "Start")
        self.btn_start.icon_name = "stop" if running_mine else "play"
        self.btn_start.set_kind("record" if running_mine else "primary")
        self.btn_start.setEnabled(running_mine or (not running_any and bool(self.chain["links"])))
        self.btn_start.updateGeometry()
        self.btn_pause.setEnabled(running_mine)
        self.btn_pause.setText("Resume" if (running_mine and paused) else "Pause")
        self.btn_pause.icon_name = "play" if (running_mine and paused) else "pause"
        self._load_card(self.canvas.sel)
