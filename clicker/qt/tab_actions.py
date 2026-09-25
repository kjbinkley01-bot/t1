"""Action Script tab in the Liquid Glass look: build, edit and run step lists."""

import copy
import os

import time

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QKeySequence, QLinearGradient, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QStyledItemDelegate, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import editing, formlogic, inputs, model, runlog, storage, target, vision
from ..runner import Runner
from ..storage import AssetStore
from . import dialogs
from .glass import GlassPanel, font
from .thumbs import ImageStrip, step_icon
from .widgets import Caption, GlassButton, GlassSwitch, clear_layout

SPEEDS = ["0.25x", "0.5x", "0.75x", "1.0x", "1.5x", "2.0x", "3.0x"]
COLUMNS = [("#", 44), ("Label", 86), ("Action", 170), ("X", 64), ("Y", 64), ("Back", 54), ("Delay", 64),
           ("Rep", 46), ("Wait / Condition", 300), ("Comment", 160)]
def screen_fg(dark):
    return QColor("#7fdcff") if dark else QColor("#0064b8")


def error_fg(dark):
    return QColor("#ff7b7b") if dark else QColor("#c62a36")


def detail_label(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    return lab


def field(width=None, mono=False, placeholder=""):
    e = QLineEdit()
    if width:
        e.setFixedWidth(width)
    if placeholder:
        e.setPlaceholderText(placeholder)
    return e


DELAY_COL = 6


class StepProgress(QStyledItemDelegate):
    """Draws the running step's progress: a glass fill sweeping across its row, and the time left.

    Delays count down exactly. Screen waits show how much of their time limit has been used (they
    usually finish early, and the bar then simply disappears).
    """

    def __init__(self, tab):
        super().__init__(tab.tree)
        self.tab = tab

    def _state(self, row):
        pr = self.tab.progress
        if not pr or pr["step"] != row:
            return None
        elapsed = self.tab.progress_elapsed()
        frac = max(0.0, min(1.0, elapsed / pr["duration"])) if pr["duration"] > 0 else 1.0
        return frac, max(0.0, pr["duration"] - elapsed), pr["kind"]

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        st = self._state(index.row()) if index.column() == DELAY_COL else None
        if st:
            _f, left, kind = st
            option.text = f"{left:.1f}s" if kind == "delay" else f"≤{left:.0f}s"

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        st = self._state(index.row())
        if not st:
            return
        frac, _left, kind = st
        tree = self.tab.tree
        hdr = tree.header()
        x0 = hdr.sectionViewportPosition(0)
        total = sum(hdr.sectionSize(c) for c in range(hdr.count()))
        row = QRectF(x0, option.rect.y(), total, option.rect.height())
        edge = row.x() + row.width() * frac
        cell = QRectF(option.rect)
        fill = QRectF(cell.x(), cell.y(), max(0.0, min(cell.right(), edge) - cell.x()), cell.height())
        wait = kind == "wait"
        base = QColor(127, 220, 255) if wait else QColor(0, 136, 255)
        painter.save()
        if fill.width() > 0:
            g = QLinearGradient(row.x(), 0, edge, 0)
            c0, c1 = QColor(base), QColor(base)
            c0.setAlpha(18)
            c1.setAlpha(70)
            g.setColorAt(0, c0)
            g.setColorAt(1, c1)
            painter.fillRect(fill, g)
            bar = QRectF(fill.x(), cell.bottom() - 2.5, fill.width(), 2.5)
            painter.fillRect(bar, base)
        if cell.left() <= edge <= cell.right() and frac < 1:  # a soft glowing leading edge
            glow = QRectF(edge - 1.5, cell.y() + 3, 3, cell.height() - 6)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 170))
            painter.drawRoundedRect(glow, 1.5, 1.5)
        painter.restore()


class _DragFilter(QObject):
    """Drag rows of the step table to move them (keeps jump numbers pointing at the same steps)."""

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.row = None
        self.moved = False

    def eventFilter(self, obj, e):
        t = self.tab
        if e.type() == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
            if e.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                self.row = None
                return False
            item = t.tree.itemAt(e.position().toPoint())
            self.row = t.tree.indexOfTopLevelItem(item) if item else None
            self.moved = False
        elif e.type() == QEvent.Type.MouseMove and self.row is not None and e.buttons() & Qt.MouseButton.LeftButton:
            if t.main.job_running_for(t):
                return False
            item = t.tree.itemAt(e.position().toPoint())
            if item is None:
                return False
            target = t.tree.indexOfTopLevelItem(item)
            if target == self.row:
                return True
            if not self.moved:
                t.history.record(t.script, [self.row])
                self.moved = True
                t.tree.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            new = editing.move_to(t.script, [self.row], target)
            self.row = new[0]
            t.changed(new)
            return True
        elif e.type() == QEvent.Type.MouseButtonRelease and self.row is not None:
            if self.moved:
                t.tree.viewport().unsetCursor()
                t.main.set_status(f"Moved to step {self.row + 1}. Jumps were renumbered to match.")
            self.row = None
            moved, self.moved = self.moved, False
            return moved
        return False


class ActionTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.script = model.new_script()
        self.assets = AssetStore()
        self.path = None
        self.dirty = False
        self.history = editing.History()
        self.running_row = None
        self.progress = None
        self._held_since, self._held_total = None, 0.0
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(16)  # ~60 fps, repainting only the running row
        self._progress_timer.timeout.connect(self._progress_tick)
        self._rows = []
        self.detail_edits = {}
        self.detail_values = {}
        self._build()
        self._shortcuts()
        self._on_action_change()
        self._on_wait_mode()
        self.refresh_list()
        self._update_undo()

    # ------------------------------------------------------------ layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        # toolbar
        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 14, 8)
        bl.setSpacing(8)
        self.btn_start = GlassButton("Start", icon="play", kind="primary")
        self.btn_start.clicked.connect(lambda: self.toggle_run())
        self.btn_pause = GlassButton("Pause", icon="pause")
        self.btn_pause.clicked.connect(self.main.toggle_pause)
        self.btn_stop = GlassButton("Stop", icon="stop")
        self.btn_stop.clicked.connect(self.main.stop_job)
        for b in (self.btn_start, self.btn_pause, self.btn_stop):
            bl.addWidget(b)
        bl.addSpacing(10)
        for text, ic, cmd in (("New", "file-plus", self.new_script), ("Open", "folder-open", self.load),
                              ("Save", "floppy-disk", self.save), ("Save As", None, lambda: self.save(True))):
            b = GlassButton(text, icon=ic)
            b.clicked.connect(cmd)
            bl.addWidget(b)
        bl.addStretch(1)
        self.btn_runin = GlassButton("Run in: Whole screen", icon="cursor", tip="Run this script inside one window "
                                     "(background mode) or on the whole screen")
        self.btn_runin.clicked.connect(self.choose_target)
        bl.addWidget(self.btn_runin)
        self.e_repeat = field(48)
        self.e_repeat.setText("1")
        self.e_repeat.setToolTip("How many times to run the whole script. 0 repeats until stopped.")
        self.cb_speed = QComboBox()
        self.cb_speed.addItems(SPEEDS)
        self.cb_speed.setCurrentText("1.0x")
        self.e_rand = field(56)
        self.e_rand.setText("0")
        self.e_rand.setToolTip("Adds or subtracts up to this many milliseconds on every delay.")
        self.sw_hide = GlassSwitch("Hide while running")
        self.sw_hide.setChecked(bool(self.main.settings.get("hide_while_running", False)))
        self.sw_hide.toggled.connect(self._save_hide)
        root.addWidget(bar)

        # editor + wait panels
        top = QHBoxLayout()
        top.setSpacing(14)
        ed = GlassPanel(radius=30)
        el = QVBoxLayout(ed)
        el.setContentsMargins(24, 20, 24, 18)
        el.setSpacing(10)
        el.addWidget(Caption("Add / edit action"))
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        g.setColumnMinimumWidth(0, 96)
        self.cb_action = QComboBox()
        self.cb_action.setMaxVisibleItems(24)
        for group, acts in model.ACTION_GROUPS:
            self.cb_action.addItem(f"— {group} —")
            idx = self.cb_action.count() - 1
            self.cb_action.model().item(idx).setEnabled(False)
            for a in acts:
                self.cb_action.addItem(a)
        self.cb_action.setCurrentText("Left Click")
        self.cb_action.setMinimumWidth(240)
        self.cb_action.currentTextChanged.connect(self._on_action_change)
        self.lbl_group = detail_label("")
        g.addWidget(QLabel("Action"), 0, 0)
        g.addWidget(self.cb_action, 0, 1, 1, 3)
        g.addWidget(self.lbl_group, 0, 4)
        self.e_x, self.e_y = field(76), field(76)
        pick = GlassButton("Pick", icon="crosshair", small=True, tip="Pick a position with the cursor (3 s)")
        pick.clicked.connect(self.pick_position)
        g.addWidget(QLabel("X"), 1, 0)
        xy = QHBoxLayout()
        xy.setSpacing(8)
        xy.addWidget(self.e_x)
        xy.addWidget(QLabel("Y"))
        xy.addWidget(self.e_y)
        xy.addWidget(pick)
        xy.addWidget(detail_label("blank = wherever the cursor is"))
        xy.addStretch(1)
        g.addLayout(xy, 1, 1, 1, 4)
        g.setColumnStretch(4, 1)
        el.addLayout(g)
        self.details = QGridLayout()
        self.details.setHorizontalSpacing(10)
        self.details.setVerticalSpacing(10)
        self.details.setColumnMinimumWidth(0, 96)
        self.details.setColumnStretch(9, 1)
        el.addLayout(self.details)
        self.lbl_hint = detail_label("")
        self.lbl_hint.setWordWrap(True)
        el.addWidget(self.lbl_hint)
        r = QHBoxLayout()
        r.setSpacing(10)
        self.sw_back = GlassSwitch("Cursor back")
        self.e_delay, self.e_rep1 = field(70), field(52)
        self.e_delay.setText("100")
        self.e_rep1.setText("1")
        for w in (self.sw_back, 12, QLabel("Delay before"), self.e_delay, detail_label("ms"), 12, QLabel("Repeat"),
                  self.e_rep1):
            r.addSpacing(w) if isinstance(w, int) else r.addWidget(w)
        r.addStretch(1)
        el.addLayout(r)
        r = QHBoxLayout()
        r.setSpacing(10)
        self.e_label = field(130, placeholder="optional")
        self.e_comment = field(placeholder="what this step is for")
        lab = QLabel("Label")
        lab.setFixedWidth(96)
        r.addWidget(lab)
        r.addWidget(self.e_label)
        r.addWidget(QLabel("Comment"))
        r.addWidget(self.e_comment, 1)
        el.addLayout(r)
        r = QHBoxLayout()
        r.setSpacing(8)
        for text, ic, kind, cmd in (("Add", "plus", "primary", self.add_step), ("Update", "check", "glass", self.update_step),
                                    ("Insert Above", "arrow-up", "glass", self.insert_step)):
            b = GlassButton(text, icon=ic, kind=kind)
            b.clicked.connect(cmd)
            r.addWidget(b)
        self.lbl_form_msg = QLabel("")
        self.lbl_form_msg.setProperty("role", "error")
        r.addWidget(self.lbl_form_msg, 1)
        el.addLayout(r)
        el.addStretch(1)
        top.addWidget(ed, 1)

        wp = GlassPanel(radius=30)
        wp.setMinimumWidth(410)
        wp.setMaximumWidth(452)
        wl = QVBoxLayout(wp)
        wl.setContentsMargins(22, 20, 22, 18)
        wl.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(Caption("Wait / timing"))
        head.addStretch(1)
        self.badge = QLabel("SCREEN AWARE")
        self.badge.setFont(font(7.5, QFont.Weight.Bold))
        self._style_badge()
        head.addWidget(self.badge)
        wl.addLayout(head)
        wg = QGridLayout()
        wg.setHorizontalSpacing(8)
        wg.setVerticalSpacing(8)
        wg.setColumnMinimumWidth(0, 92)
        self.cb_wait = QComboBox()
        self.cb_wait.addItems([m[1] for m in model.WAIT_MODES])
        self.cb_wait.currentTextChanged.connect(self._on_wait_mode)
        wg.addWidget(QLabel("Run when"), 0, 0)
        wg.addWidget(self.cb_wait, 0, 1, 1, 3)
        self.cb_target = QComboBox()
        self.cb_target.setEditable(True)
        self.btn_target = GlassButton("Capture", icon="camera", small=True)
        self.btn_target.clicked.connect(self.capture_wait_target)
        wg.addWidget(QLabel("Watch for"), 1, 0)
        wg.addWidget(self.cb_target, 1, 1, 1, 2)
        wg.addWidget(self.btn_target, 1, 3)
        self.e_wtimeout, self.e_wpoll, self.e_wconf = field(50), field(56), field(44)
        self.e_wtimeout.setText("30")
        self.e_wpoll.setText("250")
        self.e_wconf.setText("90")
        tr = QHBoxLayout()
        tr.setSpacing(6)
        for w in (self.e_wtimeout, detail_label("s  every"), self.e_wpoll, detail_label("ms  match"), self.e_wconf,
                  detail_label("%")):
            tr.addWidget(w)
        tr.addStretch(1)
        wg.addWidget(QLabel("Timeout"), 2, 0)
        wg.addLayout(tr, 2, 1, 1, 3)
        self.cb_ontimeout = QComboBox()
        self.cb_ontimeout.addItems([m[1] for m in model.ON_TIMEOUT])
        wg.addWidget(QLabel("If timed out"), 3, 0)
        wg.addWidget(self.cb_ontimeout, 3, 1, 1, 3)
        self.e_retries, self.e_wgoto = field(44), field(110, placeholder="step or label")
        self.e_retries.setText(str(model.DEFAULT_RETRIES))
        rr = QHBoxLayout()
        rr.setSpacing(6)
        for w in (self.e_retries, detail_label("   go to"), self.e_wgoto):
            rr.addWidget(w)
        rr.addStretch(1)
        wg.addWidget(QLabel("Retries"), 4, 0)
        wg.addLayout(rr, 4, 1, 1, 3)
        wl.addLayout(wg)
        wl.addSpacing(4)
        wl.addWidget(Caption("Whole script"))
        sr = QHBoxLayout()
        sr.setSpacing(6)
        lab = QLabel("Repeat")
        lab.setFixedWidth(92)
        for w in (lab, self.e_repeat, detail_label("  speed"), self.cb_speed, detail_label("  ± ms"), self.e_rand):
            sr.addWidget(w)
        sr.addStretch(1)
        wl.addLayout(sr)
        hr = QHBoxLayout()
        hr.setSpacing(6)
        self.e_handler, self.e_restart = field(110, placeholder="step or label"), field(44)
        self.e_restart.setText("0")
        self.e_restart.setToolTip("If the script fails, start again from step 1 up to this many times.")
        lab = QLabel("Error handler")
        lab.setFixedWidth(92)
        for w in (lab, self.e_handler, detail_label("  restarts"), self.e_restart):
            hr.addWidget(w)
        hr.addStretch(1)
        wl.addLayout(hr)
        self.sw_scale = GlassSwitch("Find images at other display scales")
        self.sw_scale.toggled.connect(lambda _on: self._settings_changed())
        wl.addWidget(self.sw_scale)
        wl.addWidget(self.sw_hide)
        wl.addStretch(1)
        top.addWidget(wp)
        root.addLayout(top)

        # steps
        mid = QHBoxLayout()
        mid.setSpacing(14)
        sp = GlassPanel(radius=30)
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(20, 16, 20, 12)
        sl.setSpacing(8)
        h = QHBoxLayout()
        h.setSpacing(8)
        h.addWidget(Caption("Actions in sequence"))
        self.btn_undo = GlassButton("", icon="arrow-counter-clockwise", small=True, tip="Undo (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = GlassButton("", icon="arrow-clockwise", small=True, tip="Redo (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.redo)
        h.addSpacing(6)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        h.addSpacing(6)
        h.addWidget(detail_label("Drag rows to reorder · Ctrl+C / Ctrl+V copy and paste"))
        h.addStretch(1)
        self.lbl_count = detail_label("")
        h.addWidget(self.lbl_count)
        logs = GlassButton("Run Logs", icon="notebook", small=True)
        logs.clicked.connect(self.open_logs)
        h.addWidget(logs)
        sl.addLayout(h)
        self.tree = QTreeWidget()
        self.tree.setItemDelegate(StepProgress(self))
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels([c[0].upper() for c in COLUMNS])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(34, 20))  # image steps show their template
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setMinimumHeight(160)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(False)
        for i, (_n, w) in enumerate(COLUMNS):
            self.tree.setColumnWidth(i, w)
        hdr.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        hdr.setMinimumSectionSize(40)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self._drag = _DragFilter(self)
        self.tree.viewport().installEventFilter(self._drag)
        sl.addWidget(self.tree, 1)
        mid.addWidget(sp, 1)

        side = QVBoxLayout()
        side.setSpacing(6)
        self.btn_start2 = GlassButton("Start", icon="play", kind="primary")
        self.btn_start2.clicked.connect(lambda: self.toggle_run())
        side.addWidget(self.btn_start2)
        b = GlassButton("Test Step", icon="flask", small=True)
        b.clicked.connect(self.test_step)
        side.addWidget(b)
        side.addSpacing(6)
        for text, ic, cmd in (("Move Up", "arrow-up", lambda: self.move(-1)), ("Move Down", "arrow-down", lambda: self.move(1)),
                              ("Duplicate", "copy-simple", self.duplicate), ("Copy", "copy", self.copy_steps),
                              ("Paste", "clipboard", self.paste_steps)):
            b = GlassButton(text, icon=ic, small=True)
            b.clicked.connect(cmd)
            side.addWidget(b)
        side.addSpacing(6)
        for text, cmd in (("Delete", self.delete_step), ("Delete All", self.delete_all)):
            b = GlassButton(text, icon="trash", kind="danger", small=True)
            b.clicked.connect(cmd)
            side.addWidget(b)
        side.addStretch(1)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(150)
        mid.addWidget(sw)
        root.addLayout(mid, 1)

    def _style_badge(self):
        c = screen_fg(self.main.mode.dark).name()
        self.badge.setStyleSheet(f"color:{c}; background: rgba(0,136,255,{60 if self.main.mode.dark else 36}); "
                                 "border-radius: 8px; padding: 2px 8px;")

    def restyle(self):
        self._style_badge()
        self._rows = []
        self.refresh_list(self._selection())

    # ------------------------------------------------------------ form

    def _on_action_change(self, *_):
        action = self.cb_action.currentText()
        if action not in model.ACTION_GROUP:
            return
        self.lbl_group.setText(model.ACTION_GROUP.get(action, ""))
        for k, e in self.detail_edits.items():
            self.detail_values[k] = e.currentText() if isinstance(e, QComboBox) else e.text()
        clear_layout(self.details)
        self.detail_edits = {}
        spec = model.FIELD_SPECS.get(action, [])
        row, col = -1, 99
        for key, text, width, kind in spec:
            cost = 2 if kind in ("image", "region", "images") else 1
            if col + cost > 3:
                row, col = row + 1, 0
            lab = QLabel(text)
            self.details.addWidget(lab, row, col * 3)
            val = self.detail_values.get(key, model.DEFAULTS.get(key, ""))
            box = QHBoxLayout()
            box.setSpacing(6)
            if kind.startswith("choice:"):
                w = QComboBox()
                w.addItems(kind[7:].split(","))
                w.setCurrentText(val or kind[7:].split(",")[0])
            elif kind == "images":
                w = ImageStrip(self)
                w.setText(val)
                box.addWidget(w)
            elif kind == "image":
                w = QComboBox()
                w.setEditable(True)
                w.addItems(self.assets.names())
                w.setCurrentText(val)
                w.setMinimumWidth(170)
                box.addWidget(w)
                for t, ic, cb in (("Capture", "camera", lambda _=False, x=w: self.capture_image(x)),
                                  ("Load", "image", lambda _=False, x=w: self.load_image(x))):
                    b = GlassButton(t, icon=ic, small=True)
                    b.clicked.connect(cb)
                    box.addWidget(b)
            else:
                w = QLineEdit(val)
                w.setMinimumWidth(max(56, min(360, width * 9)))
                if kind in ("int", "sint", "percent"):
                    w.setMaximumWidth(max(64, width * 11))
            if kind not in ("image", "images"):
                box.addWidget(w)
            if kind == "region":
                b = GlassButton("Draw", icon="bounding-box", small=True)
                b.clicked.connect(lambda _=False, x=w: self.draw_region(x))
                box.addWidget(b)
            elif kind == "color":
                b = GlassButton("Grab", icon="eyedropper", small=True)
                b.clicked.connect(lambda _=False, x=w: self.grab_pixel(x))
                box.addWidget(b)
            elif kind == "file":
                b = GlassButton("Browse", icon="folder-open", small=True)
                b.clicked.connect(lambda _=False, x=w: self.browse_script(x))
                box.addWidget(b)
            box.addStretch(1)
            self.details.addLayout(box, row, col * 3 + 1, 1, cost * 3 - 1)
            self.detail_edits[key] = w
            col += cost
        self.lbl_hint.setText(model.ACTION_HINTS.get(action, ""))
        self.lbl_hint.setVisible(bool(self.lbl_hint.text()))
        if hasattr(self.main, "update_min_width"):
            self.main.update_min_width()  # some actions have wider forms

    def _on_wait_mode(self, *_):
        mode = model.WAIT_ID.get(self.cb_wait.currentText(), "none")
        btn, hint = formlogic.WAIT_HINTS[mode]
        self.btn_target.setText(btn)
        self.btn_target.icon_name = {"Capture": "camera", "Grab": "eyedropper", "Draw": "bounding-box"}[btn]
        self.btn_target.setEnabled(mode != "none")
        self.btn_target.updateGeometry()
        cur = self.cb_target.currentText()
        self.cb_target.clear()
        if mode.startswith("image"):
            self.cb_target.addItems(self.assets.names())
        self.cb_target.setCurrentText(cur)
        self.cb_target.setEnabled(mode != "none")
        self.cb_wait.setToolTip(hint + " The delay on the left still applies after it.")

    def _refresh_image_lists(self):
        names = self.assets.names()
        for w in list(self.detail_edits.values()) + [self.cb_target]:
            if isinstance(w, QComboBox) and w.isEditable():
                if w is self.cb_target and not model.WAIT_ID.get(self.cb_wait.currentText(), "").startswith("image"):
                    continue
                cur = w.currentText()
                w.clear()
                w.addItems(names)
                w.setCurrentText(cur)

    def _values(self):
        return {
            "x": self.e_x.text(), "y": self.e_y.text(), "action": self.cb_action.currentText(),
            "cursor_back": self.sw_back.isChecked(), "delay": self.e_delay.text(), "repeat": self.e_rep1.text(),
            "comment": self.e_comment.text(), "label": self.e_label.text(),
            "wait_mode": self.cb_wait.currentText(), "wait_target": self.cb_target.currentText(),
            "wait_timeout": self.e_wtimeout.text(), "wait_poll": self.e_wpoll.text(),
            "wait_conf": self.e_wconf.text(), "on_timeout": self.cb_ontimeout.currentText(),
            "wait_goto": self.e_wgoto.text(), "retries": self.e_retries.text(),
        }

    def _detail(self):
        return {k: (w.currentText() if isinstance(w, QComboBox) else w.text()) for k, w in self.detail_edits.items()}

    def form_step(self):
        try:
            step = formlogic.form_to_step(self._values(), self._detail(), self.assets.has)
        except ValueError as e:
            self.lbl_form_msg.setText(str(e))
            self.main.set_status(str(e), error=True)
            return None
        self.lbl_form_msg.setText("")
        return step

    def step_to_form(self, step):
        v, detail = formlogic.step_to_form(step)
        self.detail_values.update(detail)
        self.cb_action.blockSignals(True)
        self.cb_action.setCurrentText(v["action"])
        self.cb_action.blockSignals(False)
        self.detail_edits = {}
        self._on_action_change()
        for k, w in self.detail_edits.items():
            val = detail.get(k, "")
            w.setCurrentText(val) if isinstance(w, QComboBox) else w.setText(val)
        self.e_x.setText(v["x"])
        self.e_y.setText(v["y"])
        self.sw_back.setChecked(v["cursor_back"])
        self.e_delay.setText(v["delay"])
        self.e_rep1.setText(v["repeat"])
        self.e_comment.setText(v["comment"])
        self.e_label.setText(v["label"])
        self.cb_wait.setCurrentText(v["wait_mode"])
        self.cb_target.setCurrentText(v["wait_target"])
        self.e_wtimeout.setText(v["wait_timeout"])
        self.e_wpoll.setText(v["wait_poll"])
        self.e_wconf.setText(v["wait_conf"])
        self.cb_ontimeout.setCurrentText(v["on_timeout"])
        self.e_wgoto.setText(v["wait_goto"])
        self.e_retries.setText(v["retries"])
        self.lbl_form_msg.setText("")

    # ------------------------------------------------------------ list editing

    def _selection(self):
        n = len(self.script["steps"])
        return sorted(i for i in (self.tree.indexOfTopLevelItem(it) for it in self.tree.selectedItems()) if 0 <= i < n)

    def _selected(self):
        s = self._selection()
        return s[0] if s else None

    def _editable(self):
        if self.main.job_running_for(self):
            self.main.set_status("Stop the script before editing it.", error=True)
            return False
        return True

    def _record(self):
        self.history.record(self.script, self._selection())

    def changed(self, select=None, sync=True):
        self.dirty = True
        if sync:
            self.sync_settings()
        self.refresh_list(select)
        self._update_undo()

    def _settings_changed(self):
        self.dirty = True
        self.sync_settings()
        self.main.update_title()

    def _update_undo(self):
        self.btn_undo.setEnabled(self.history.can_undo)
        self.btn_redo.setEnabled(self.history.can_redo)

    def _label_free(self, step, ignore=None):
        lab = step.get("label")
        for i, other in enumerate(self.script["steps"]):
            if lab and i != ignore and other.get("label") == lab:
                self.lbl_form_msg.setText(f"Step {i + 1} already has the label '{lab}'.")
                return False
        return True

    def add_step(self):
        step = self.form_step()
        if step and self._editable() and self._label_free(step):
            self._record()
            self.script["steps"].append(step)
            self.changed(len(self.script["steps"]) - 1)

    def update_step(self):
        i = self._selected()
        if i is None:
            self.lbl_form_msg.setText("Select a step in the list to update.")
            return
        step = self.form_step()
        if step and self._editable() and self._label_free(step, ignore=i):
            self._record()
            self.script["steps"][i] = step
            self.changed(i)

    def insert_step(self):
        i = self._selected()
        step = self.form_step()
        if step and self._editable() and self._label_free(step):
            self._record()
            self.changed(editing.insert(self.script, 0 if i is None else i, [step]))

    def add_at_cursor(self):
        x, y = inputs.position()
        self.e_x.setText(str(x))
        self.e_y.setText(str(y))
        self.e_label.setText("")
        step = self.form_step()
        if step and self._editable():
            self._record()
            self.script["steps"].append(step)
            self.changed(len(self.script["steps"]) - 1)
            self.main.set_status(f"Added {step['action']} at {x}, {y}")

    def move(self, d):
        sel = self._selection()
        if not sel or not self._editable():
            return
        self._record()
        new = editing.shift(self.script, sel, d)
        if new == sel:
            self.history.discard_last()
            return
        self.changed(new)

    def duplicate(self):
        sel = self._selection()
        if sel and self._editable():
            self._record()
            self.changed(editing.duplicate(self.script, sel))

    def delete_step(self):
        sel = self._selection()
        if not sel or not self._editable():
            return
        self._record()
        self.changed(editing.delete(self.script, sel))
        self.main.set_status(f"Deleted {len(sel)} step{'s' if len(sel) != 1 else ''}. Ctrl+Z brings "
                             f"{'them' if len(sel) != 1 else 'it'} back.")

    def delete_all(self):
        if not self.script["steps"] or not self._editable():
            return
        if QMessageBox.question(self, "Delete all", "Remove every step from this script?") == \
                QMessageBox.StandardButton.Yes:
            self._record()
            self.script["steps"].clear()
            self.changed()

    def undo(self):
        if self._editable():
            sel = self.history.undo(self.script, self._selection())
            if sel is None:
                self.main.set_status("Nothing to undo.")
            else:
                self.e_handler.setText(str(self.script.get("error_handler") or ""))
                self.changed(sel, sync=False)

    def redo(self):
        if self._editable():
            sel = self.history.redo(self.script, self._selection())
            if sel is None:
                self.main.set_status("Nothing to redo.")
            else:
                self.e_handler.setText(str(self.script.get("error_handler") or ""))
                self.changed(sel, sync=False)

    def copy_steps(self, cut=False):
        sel = self._selection()
        if not sel:
            return
        QApplication.clipboard().setText(editing.copy_payload(self.script, self.assets, sel))
        if cut and self._editable():
            self._record()
            self.changed(editing.delete(self.script, sel))
        self.main.set_status(f"{'Cut' if cut else 'Copied'} {len(sel)} step{'s' if len(sel) != 1 else ''}")

    def paste_steps(self):
        if not self._editable():
            return
        sel = self._selection()
        pos = sel[-1] + 1 if sel else len(self.script["steps"])
        self._record()
        try:
            new = editing.paste(self.script, self.assets, QApplication.clipboard().text(), pos)
        except ValueError:
            new = None
        if not new:
            self.history.discard_last()
            self.main.set_status("The clipboard has no Clicker steps. Copy steps first.", error=True)
            return
        self._refresh_image_lists()
        self.changed(new)
        self.main.set_status(f"Pasted {len(new)} step{'s' if len(new) != 1 else ''}")

    def _shortcuts(self):
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut

        def on_tree(seq, fn):
            s = QShortcut(QKeySequence(seq), self.tree)
            s.setContext(Qt.ShortcutContext.WidgetShortcut)
            s.activated.connect(fn)
        on_tree("Ctrl+C", self.copy_steps)
        on_tree("Ctrl+X", lambda: self.copy_steps(cut=True))
        on_tree("Ctrl+V", self.paste_steps)
        on_tree("Ctrl+D", self.duplicate)
        on_tree("Delete", self.delete_step)
        on_tree("Alt+Up", lambda: self.move(-1))
        on_tree("Alt+Down", lambda: self.move(1))

        def not_typing(fn):
            def run():
                if not isinstance(QApplication.focusWidget(), QLineEdit):
                    fn()
            return run
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo)):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(ctx)
            s.activated.connect(not_typing(fn))

    def _on_select(self):
        i = self._selected()
        if i is not None and not self._drag.moved:
            self.step_to_form(self.script["steps"][i])

    def _row(self, i, s, labels):
        xt, yt, cond = model.describe_step(s)
        back = ("Yes" if s.get("cursor_back") else "No") if s["action"] in model.MOUSE_ACTIONS else ""
        texts = (str(i + 1), s.get("label", ""), s["action"], xt, yt, back, str(s.get("delay_ms", 0)),
                 str(s.get("repeat", 1)), cond, s.get("comment", ""))
        flag = "error" if model.check_step(s, self.script["steps"], labels) else (
            "screen" if model.is_screen_step(s) else "")
        return texts, flag

    def _paint_row(self, item, texts, flag, running):
        for c, t in enumerate(texts):
            item.setText(c, t)
        dark = self.main.mode.dark
        fg = error_fg(dark) if flag == "error" else (screen_fg(dark) if flag == "screen" else None)
        bg = QBrush(QColor(0, 136, 255, 70)) if running else QBrush()
        for c in range(len(texts)):
            item.setForeground(c, QBrush(fg) if fg else QBrush())
            item.setBackground(c, bg)
        f = item.font(0)
        f.setWeight(QFont.Weight.DemiBold if running else QFont.Weight.Normal)
        item.setFont(2, f)

    def refresh_list(self, select=None):
        steps = self.script["steps"]
        labels = model.label_map(steps)
        rows = [self._row(i, s, labels) for i, s in enumerate(steps)]
        tree = self.tree
        tree.blockSignals(True)
        while tree.topLevelItemCount() > len(rows):
            tree.takeTopLevelItem(tree.topLevelItemCount() - 1)
        for i, (texts, flag) in enumerate(rows):
            if i >= tree.topLevelItemCount():
                tree.addTopLevelItem(QTreeWidgetItem())
                old = None
            else:
                old = self._rows[i] if i < len(self._rows) else None
            if old != (texts, flag):
                item = tree.topLevelItem(i)
                self._paint_row(item, texts, flag, i == self.running_row)
                item.setIcon(2, step_icon(self.assets, steps[i], 34, 20, self.devicePixelRatioF())
                             if steps[i]["action"] in model.IMAGE_ACTIONS else QIcon())
        self._rows = rows
        tree.clearSelection()
        if select is not None:
            want = [select] if isinstance(select, int) else list(select)
            want = [i for i in want if 0 <= i < len(steps)]
            for i in want:
                tree.topLevelItem(i).setSelected(True)
            if want:
                tree.scrollToItem(tree.topLevelItem(want[-1]))
                tree.setCurrentItem(tree.topLevelItem(want[0]), 0,
                                    tree.selectionModel().SelectionFlag.NoUpdate)
        tree.blockSignals(False)
        n = len(steps)
        scr = self.script.get("screen")
        where = f" · built on {scr['width']} x {scr['height']}" if scr else ""
        self.lbl_count.setText(f"{n} action{'s' if n != 1 else ''}{where}")
        self.main.update_title()

    def select_step(self, i):
        """Select step i (0-based), scroll to it and load it into the editor."""
        if 0 <= i < len(self.script["steps"]):
            self.refresh_list(select=i)
            self._on_select()

    def mark_running(self, i):
        prev, self.running_row = self.running_row, i
        for idx in (prev, i):
            if idx is not None and idx < len(self._rows):
                texts, flag = self._rows[idx]
                self._paint_row(self.tree.topLevelItem(idx), texts, flag, idx == i)
        if i is not None and i < self.tree.topLevelItemCount():
            self.tree.scrollToItem(self.tree.topLevelItem(i))

    # ------------------------------------------------------------ background mode

    def _target(self):
        return target.normalize(self.script["settings"].get("target"))

    def choose_target(self):
        from .target_dialog import choose_target
        new = choose_target(self.main, self._target())
        if new == "unchanged":
            return
        if new is None:
            self.script["settings"].pop("target", None)
        else:
            self.script["settings"]["target"] = new
        self.dirty = True
        self._show_target()
        self.main.update_title()
        if new:
            self.main.set_status("Positions you Pick, Grab or Draw are now measured from that window's corner.")

    def _show_target(self):
        t = self._target()
        self.btn_runin.setText("Run in: " + (target.describe(t) if t else "Whole screen"))
        self.btn_runin.set_kind("on" if t else "glass")
        self.btn_runin.updateGeometry()

    def _window_offset(self):
        """(dx, dy) to turn screen positions into target window positions; (0, 0) on the whole screen."""
        t = self._target()
        if not t:
            return 0, 0
        try:
            return target.WindowIO(t).client_origin()
        except Exception as e:
            self.main.set_status(f"{e}. Using screen positions.", error=True)
            return 0, 0

    def _local(self, x, y):
        ox, oy = self._window_offset()
        return x - ox, y - oy

    def _local_region(self, region):
        ox, oy = self._window_offset()
        x, y, w, h = region
        return [x - ox, y - oy, w, h]

    # ------------------------------------------------------------ capture helpers

    def pick_position(self):
        def done():
            x, y = self._local(*inputs.position())
            self.e_x.setText(str(x))
            self.e_y.setText(str(y))
        dialogs.countdown(self.main, 3, "Picking position", done)

    def grab_pixel(self, color_edit):
        def done():
            sx, sy = inputs.position()
            x, y = self._local(sx, sy)
            self.e_x.setText(str(x))
            self.e_y.setText(str(y))
            color_edit.setText(vision.rgb_hex(vision.pixel(sx, sy)))
        dialogs.countdown(self.main, 3, "Grabbing pixel", done)

    def capture_image(self, combo):
        def done(region, img):
            if img is None:
                return
            base = self.e_comment.text() or model.image_stem(combo.currentText()) or "image"
            name = dialogs.ask_string(self.main, "Name this image", "Image name", base.lower().replace(" ", "_"))
            if name is None:
                return
            t = self._target()
            if t:
                # take the template from the window's own picture: that is what the script will search
                try:
                    io = target.WindowIO(t)
                    lx, ly, w, h = self._local_region(region)
                    shot = io.grab(lx, ly, w, h)
                    if float(shot.std()) > 1.0:
                        img = shot
                except Exception:
                    pass
            name = self.assets.add_image(img, name or "image")
            self._refresh_image_lists()
            combo.setCurrentText(name)
            self.dirty = True
            self.main.set_status(f"Captured {name} ({region[2]} x {region[3]})")
        dialogs.select_region(self.main, done, "Drag around the image to capture. Esc cancels.")

    def load_image(self, combo):
        path, _ = QFileDialog.getOpenFileName(self, "Load image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                img = vision.decode_png(f.read())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Could not load image", str(e))
            return
        name = self.assets.add_image(img, os.path.splitext(os.path.basename(path))[0])
        self._refresh_image_lists()
        combo.setCurrentText(name)
        self.dirty = True

    def draw_region(self, edit):
        def done(region, _img):
            if region:
                edit.setText(model.format_region(self._local_region(region)))
        dialogs.select_region(self.main, done, "Drag the area to search in. Esc cancels.")

    def browse_script(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "Script to run", "", "Clicker scripts (*.clk *.clkpkg *.json)")
        if path:
            edit.setText(path)

    def capture_wait_target(self):
        mode = model.WAIT_ID.get(self.cb_wait.currentText(), "none")
        if mode.startswith("image"):
            self.capture_image(self.cb_target)
        elif mode == "pixel_is":
            def done():
                sx, sy = inputs.position()
                x, y = self._local(sx, sy)
                self.cb_target.setCurrentText(f"{x}, {y}, {vision.rgb_hex(vision.pixel(sx, sy))}")
            dialogs.countdown(self.main, 3, "Grabbing pixel", done)
        elif mode == "region_stable":
            def got(region, _img):
                if region:
                    self.cb_target.setCurrentText(model.format_region(self._local_region(region)))
            dialogs.select_region(self.main, got, "Drag the area to watch. Esc cancels.")

    # ------------------------------------------------------------ files

    def sync_settings(self):
        st = self.script["settings"]
        try:
            st["repeat"] = int(self.e_repeat.text() or 1)
        except ValueError:
            pass
        st["speed"] = float(self.cb_speed.currentText().rstrip("x") or 1)
        try:
            st["random_delay_ms"] = int(self.e_rand.text() or 0)
        except ValueError:
            pass
        try:
            self.script["error_handler"] = model.parse_target(self.e_handler.text(), "Error handler")
        except ValueError:
            self.script["error_handler"] = None
        try:
            st["restart_on_failure"] = max(0, int(self.e_restart.text() or 0))
        except ValueError:
            pass
        st["scale_search"] = self.sw_scale.isChecked()

    def _save_hide(self, on):
        self.main.settings["hide_while_running"] = bool(on)
        self.main.save_settings()

    def confirm_discard(self, why="continuing"):
        if not self.dirty or not self.script["steps"]:
            return True
        ans = QMessageBox.question(self, "Unsaved changes", f"Save the current script before {why}?",
                                   QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                   QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Cancel:
            return False
        if ans == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def set_script(self, script, assets, path=None):
        self.script = model.copy_script(script)
        self.assets = assets
        self.path = path
        self.dirty = path is None and bool(script["steps"])
        st = self.script.get("settings") or {}
        self.e_repeat.setText(str(st.get("repeat", 1)))
        sp = float(st.get("speed", 1.0))
        txt = f"{sp:g}x" if f"{sp:g}x" in SPEEDS else f"{sp:.1f}x"
        if self.cb_speed.findText(txt) < 0:
            self.cb_speed.addItem(txt)
        self.cb_speed.setCurrentText(txt)
        self.e_rand.setText(str(st.get("random_delay_ms", 0)))
        self.e_handler.setText(str(self.script.get("error_handler") or ""))
        self.e_restart.setText(str(st.get("restart_on_failure", 0)))
        self.sw_scale.setChecked(bool(st.get("scale_search", False)))
        self._show_target()
        self.running_row = None
        self.history.clear()
        self._update_undo()
        self._refresh_image_lists()
        self._rows = []
        self.tree.clear()
        self.refresh_list(0 if self.script["steps"] else None)

    def new_script(self):
        if self.main.job_running_for(self) or not self.confirm_discard("starting a new one"):
            return
        self.set_script(model.new_script(), AssetStore())
        self.dirty = False
        self.main.update_title()

    def load(self):
        if self.main.job_running_for(self) or not self.confirm_discard("opening another"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open script", "",
                                              "Clicker scripts (*.clk *.clkpkg *.json);;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open script", str(e))
            return
        self.set_script(script, assets, path)
        self.dirty = False
        storage.add_recent(self.main.settings, path)
        self.main.save_settings()
        self.main.update_title()

    def save(self, save_as=False):
        self.sync_settings()
        path = self.path
        if save_as or not path or not path.lower().endswith((".clk", ".clkpkg")):
            base = os.path.splitext(os.path.basename(path))[0] if path else self.script.get("name", "script")
            path, _ = QFileDialog.getSaveFileName(self, "Save script", f"{base}.clk", "Clicker script (*.clk)")
            if not path:
                return False
            if not path.lower().endswith(".clk"):
                path += ".clk"
        if not self.script.get("screen"):
            self.script["screen"] = vision.display_info()
        if self.script.get("name") in (None, "", "Untitled"):
            self.script["name"] = os.path.splitext(os.path.basename(path))[0]
        try:
            storage.save_script(path, self.script, self.assets)
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return False
        self.path, self.dirty = path, False
        storage.add_recent(self.main.settings, path)
        self.main.save_settings()
        self.refresh_list(self._selection())
        self.main.set_status(f"Saved {os.path.basename(path)}")
        return True

    def open_logs(self):
        path = self.main.last_log_dir if self.main.last_log_dir and os.path.isdir(self.main.last_log_dir) \
            else runlog.logs_dir()
        if not runlog.open_folder(path):
            QMessageBox.information(self, "Run logs", f"Run logs are saved in:\n{path}")

    def title_text(self):
        name = os.path.basename(self.path) if self.path else (self.script.get("name") or "Untitled")
        return name + (" *" if self.dirty else "")

    # ------------------------------------------------------------ running

    def _runner(self, script, start_delay, dry=False, label_text="Script"):
        self.sync_settings()
        st = self.script["settings"]
        values = {}
        if script.get("inputs"):
            values = dialogs.ask_inputs(self.main, script["inputs"], self.main.last_inputs)
            if values is None:
                return None
            self.main.last_inputs.update(values)
        return Runner(script, self.assets, self.main.emitter("script"), inputs_map=values,
                      speed=st.get("speed", 1.0), repeat=st.get("repeat", 1),
                      random_delay_ms=st.get("random_delay_ms", 0), dry_run=dry, start_delay=start_delay,
                      label=label_text, save_log=self.main.settings.get("save_run_logs", True), path=self.path)

    def toggle_run(self, from_hotkey=False):
        if self.main.job_running_for(self):
            self.main.stop_job()
            return
        if not self.script["steps"]:
            self.main.set_status("Add some steps first.", error=True)
            return
        self.sync_settings()
        problems = [m for lvl, m in storage.validate(self.script, self.assets) if lvl == "error"]
        if problems:
            QMessageBox.warning(self, "Script has problems", "\n".join(problems))
            return
        job = self._runner(self.script, 0 if from_hotkey else 2)
        if job:
            self.main.start_job(job, self, hide=self.sw_hide.isChecked())

    def test_step(self):
        i = self._selected()
        if i is None or self.main.job_running():
            return
        one = model.copy_script(self.script)
        step = copy.deepcopy(one["steps"][i])
        if step["action"] in model.WHILE_ACTIONS or step["action"] in (
                "End While", "Go to Step", "Loop Back", "Call Subroutine", "Return"):
            self.main.set_status("Loops and jumps can only be tested by running the script.", error=True)
            return
        w = step.get("wait") or {}
        if w.get("on_timeout") in ("goto", "handler", "retry_handler"):
            w["on_timeout"] = "stop"
        for key in ("goto", "else_goto"):
            step.pop(key, None)
        step["repeat"] = 1
        one["steps"] = [step]
        one["settings"] = dict(one["settings"], repeat=1, restart_on_failure=0)
        one["error_handler"] = None
        job = self._runner(one, 1.5, label_text=f"Test step {i + 1}")
        if job:
            job.repeat = 1
            self.main.start_job(job, self)

    # ------------------------------------------------------------ step progress

    def progress_elapsed(self):
        """Seconds into the current pause, not counting time spent paused or held by a trigger."""
        pr = self.progress
        now = time.monotonic()
        job = self.main.job
        held = bool(job and (job.paused or getattr(job, "_holds", 0)))
        if held:
            if self._held_since is None:
                self._held_since = now
            return self._held_since - pr["start"] - self._held_total
        if self._held_since is not None:
            self._held_total += now - self._held_since
            self._held_since = None
        return now - pr["start"] - self._held_total

    def _set_progress(self, pr):
        old = self.progress
        self.progress = pr
        self._held_since, self._held_total = None, 0.0
        for p_ in (old, pr):
            if p_:
                self._repaint_row(p_["step"])
        if pr:
            self._progress_timer.start()
        else:
            self._progress_timer.stop()

    def _repaint_row(self, row):
        if 0 <= row < self.tree.topLevelItemCount():
            r = self.tree.visualItemRect(self.tree.topLevelItem(row))
            self.tree.viewport().update(QRect(0, r.y(), self.tree.viewport().width(), r.height()))

    def _progress_tick(self):
        pr = self.progress
        if not pr:
            self._progress_timer.stop()
            return
        self._repaint_row(pr["step"])
        if self.progress_elapsed() > pr["duration"] + 0.25:
            self._set_progress(None)

    def on_job(self, kind, payload):
        if kind == "step":
            if self.progress and self.progress["step"] != payload:
                self._set_progress(None)
            self.mark_running(payload)
        elif kind == "progress":
            if payload is not None and payload["step"] != self.running_row:
                self.mark_running(payload["step"])
            self._set_progress(payload)
        elif kind == "done":
            self._set_progress(None)
            self.mark_running(None)

    def update_state(self, running_mine, running_any, paused):
        for b in (self.btn_start, self.btn_start2):
            b.setText("Stop" if running_mine else "Start")
            b.icon_name = "stop" if running_mine else "play"
            b.set_kind("record" if running_mine else "primary")
            b.setEnabled(running_mine or not running_any)
            b.updateGeometry()
            b.update()
        self.btn_pause.setEnabled(running_mine)
        self.btn_pause.setText("Resume" if (running_mine and paused) else "Pause")
        self.btn_pause.icon_name = "play" if (running_mine and paused) else "pause"
        self.btn_stop.setEnabled(running_mine)

