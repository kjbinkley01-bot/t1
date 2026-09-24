"""Screen Triggers tab in the Liquid Glass look: WHEN something shows on screen, THEN do things."""

import copy
import datetime
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPlainTextEdit, QSlider, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .. import inputs, model, storage, triggers, vision
from . import dialogs, glass
from .glass import GlassPanel, font
from .widgets import Caption, GlassButton, GlassSwitch


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    return lab


def field(width=None, placeholder=""):
    e = QLineEdit()
    if width:
        e.setFixedWidth(width)
    if placeholder:
        e.setPlaceholderText(placeholder)
    return e


def pixmap_from_bgr(img, max_w, max_h):
    import cv2
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    k = min(1.0, max_w / w, max_h / h)
    if k < 1:
        rgb = cv2.resize(rgb, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    return glass.np_to_pixmap(rgb)


class OutputDialog(dialogs.GlassDialog):
    """Edit one THEN output of a rule."""

    def __init__(self, main, output=None):
        super().__init__(main, "Trigger output")
        output = dict(output or {"type": "click_match", "value": "left"})
        self.cb = QComboBox()
        self.cb.addItems([t[1] for t in triggers.OUTPUT_TYPES])
        self.cb.setCurrentText(triggers.OUTPUT_LABEL.get(output.get("type"), triggers.OUTPUT_TYPES[0][1]))
        self.cb.setMinimumWidth(320)
        self.body.addWidget(QLabel("Do this"))
        self.body.addWidget(self.cb)
        self.body.addWidget(QLabel("Value"))
        row = QHBoxLayout()
        self.value = QLineEdit(str(output.get("value") or ""))
        self.grab = GlassButton("Grab", icon="crosshair", small=True)
        self.grab.clicked.connect(self._grab)
        row.addWidget(self.value, 1)
        row.addWidget(self.grab)
        self.body.addLayout(row)
        self.hint = detail("")
        self.body.addWidget(self.hint)
        self.cb.currentTextChanged.connect(self._refresh)
        self._refresh()
        self.add_buttons()
        self.result_output = None

    def _tid(self):
        return triggers.OUTPUT_ID.get(self.cb.currentText())

    def _refresh(self, *_):
        tid = self._tid()
        self.grab.setEnabled(tid == "click_at")
        self.value.setEnabled(tid not in triggers.NO_VALUE)
        self.hint.setText("No value needed." if tid in triggers.NO_VALUE else triggers.OUTPUT_HINT.get(tid, ""))

    def _grab(self):
        self.hide()

        def done():
            x, y = inputs.position()
            parts = [p.strip() for p in self.value.text().split(",")]
            extra = f", {parts[2]}" if len(parts) > 2 and parts[2] else ""
            self.value.setText(f"{x}, {y}{extra}")
            self.show()
        dialogs.countdown(self.main, 3, "Grabbing position", done)

    def accept(self):
        tid = self._tid()
        val = "" if tid in triggers.NO_VALUE else self.value.text().strip()
        if tid == "click_at":
            parts = [p.strip() for p in val.split(",")]
            if len(parts) < 2 or not all(p.lstrip("-").isdigit() for p in parts[:2]):
                self.hint.setText("Enter a position like 640, 410")
                return
        if tid in ("wait_ms", "wait_vanish", "rewind"):
            try:
                float(val or "0")
            except ValueError:
                self.hint.setText("Enter a number")
                return
        if tid in ("press_keys", "type_text", "run_script") and not val:
            self.hint.setText("This output needs a value")
            return
        self.result_output = {"type": tid, "value": val}
        super().accept()


def edit_output(main, output=None):
    d = OutputDialog(main, output)
    return d.result_output if d.exec() == QDialog.DialogCode.Accepted else None


class TriggersTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.sel_id = None
        self.outputs = []
        self._build()
        self.refresh_rules()
        if main.rules:
            self.select_rule(main.rules[0]["id"])
        else:
            self.lbl_msg.setText("Click New Rule to make your first rule.")

    # ------------------------------------------------------------ layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 16, 8)
        bl.setSpacing(8)
        self.btn_monitor = GlassButton("Monitoring off", icon="lightning")
        self.btn_monitor.clicked.connect(self.main.toggle_monitoring)
        bl.addWidget(self.btn_monitor)
        bl.addSpacing(10)
        for text, ic, cmd in (("New Rule", "plus", self.new_rule), ("Duplicate", "copy-simple", self.duplicate),
                              ("Delete", "trash", self.delete), ("Import", "download-simple", self.import_rules),
                              ("Export", "floppy-disk", self.export_rules)):
            b = GlassButton(text, icon=ic, kind="danger" if text == "Delete" else "glass")
            b.clicked.connect(cmd)
            bl.addWidget(b)
        bl.addStretch(1)
        self.lbl_info = detail("")
        bl.addWidget(self.lbl_info)
        root.addWidget(bar)

        body = QHBoxLayout()
        body.setSpacing(14)
        left = GlassPanel(radius=30)
        left.setFixedWidth(320)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(18, 16, 18, 16)
        ll.setSpacing(8)
        h = QHBoxLayout()
        h.addWidget(Caption("Rules"))
        h.addStretch(1)
        h.addWidget(detail("click the icon to turn a rule on or off"))
        ll.addLayout(h)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 34)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemSelectionChanged.connect(self._on_select)
        ll.addWidget(self.tree, 1)
        self.lbl_summary = detail("")
        self.lbl_summary.setWordWrap(True)
        ll.addWidget(self.lbl_summary)
        body.addWidget(left)

        ed = GlassPanel(radius=30)
        el = QVBoxLayout(ed)
        el.setContentsMargins(24, 18, 24, 18)
        el.setSpacing(10)
        r = QHBoxLayout()
        lab = QLabel("Rule name")
        lab.setFont(font(10, QFont.Weight.DemiBold))
        lab.setFixedWidth(100)
        self.e_name = field()
        r.addWidget(lab)
        r.addWidget(self.e_name, 1)
        el.addLayout(r)

        # WHEN
        when = GlassPanel(radius=22)
        wl = QVBoxLayout(when)
        wl.setContentsMargins(18, 14, 18, 14)
        wl.setSpacing(8)
        wl.addLayout(self._section_head("WHEN", "this is true on screen"))
        top = QHBoxLayout()
        top.setSpacing(14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnMinimumWidth(0, 100)
        self.cb_kind = QComboBox()
        self.cb_kind.addItems([k[1] for k in model.CONDITION_KINDS])
        self.cb_kind.currentTextChanged.connect(self._on_kind)
        grid.addWidget(QLabel("Condition"), 0, 0)
        grid.addWidget(self.cb_kind, 0, 1, 1, 3)
        # image rows
        self.cb_image = QComboBox()
        self.cb_image.setEditable(True)
        self.cb_image.currentTextChanged.connect(lambda _t: self._show_thumb())
        self.lab_image = QLabel("Image")
        grid.addWidget(self.lab_image, 1, 0)
        grid.addWidget(self.cb_image, 1, 1, 1, 3)
        self.lab_match = QLabel("Match")
        self.sl_conf = QSlider(Qt.Orientation.Horizontal)
        self.sl_conf.setRange(50, 100)
        self.sl_conf.setValue(90)
        self.lbl_conf = detail("90%")
        self.sl_conf.valueChanged.connect(lambda v: self.lbl_conf.setText(f"{v}%"))
        self.sw_gray = GlassSwitch("Grayscale")
        grid.addWidget(self.lab_match, 2, 0)
        grid.addWidget(self.sl_conf, 2, 1)
        grid.addWidget(self.lbl_conf, 2, 2)
        grid.addWidget(self.sw_gray, 2, 3)
        # pixel rows
        self.lab_px = QLabel("Pixel")
        self.e_px, self.e_py, self.e_color, self.e_tol = field(64), field(64), field(96, "#RRGGBB"), field(50)
        self.px_box = QWidget()
        pb = QHBoxLayout(self.px_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(6)
        grab = GlassButton("Grab", icon="eyedropper", small=True)
        grab.clicked.connect(self.grab_pixel)
        for w in (detail("X"), self.e_px, detail("Y"), self.e_py, detail("color"), self.e_color, detail("tol"),
                  self.e_tol, grab):
            pb.addWidget(w)
        pb.addStretch(1)
        grid.addWidget(self.lab_px, 3, 0)
        grid.addWidget(self.px_box, 3, 1, 1, 3)
        # region + stable
        self.lab_region = QLabel("Search region")
        self.e_region = field(placeholder="blank = whole screen")
        draw = GlassButton("Draw", icon="bounding-box", small=True)
        draw.clicked.connect(self.draw_region)
        self.region_box = QWidget()
        rb = QHBoxLayout(self.region_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(6)
        rb.addWidget(self.e_region, 1)
        rb.addWidget(draw)
        grid.addWidget(self.lab_region, 4, 0)
        grid.addWidget(self.region_box, 4, 1, 1, 3)
        self.lab_stable = QLabel("Still for")
        self.e_stable = field(70)
        self.stable_box = QWidget()
        sb = QHBoxLayout(self.stable_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.addWidget(self.e_stable)
        sb.addWidget(detail("ms"))
        sb.addStretch(1)
        grid.addWidget(self.lab_stable, 5, 0)
        grid.addWidget(self.stable_box, 5, 1, 1, 3)
        self.e_every, self.e_hold = field(64), field(64)
        tr = QHBoxLayout()
        tr.setSpacing(6)
        for w in (self.e_every, detail("ms   must stay true for"), self.e_hold, detail("ms")):
            tr.addWidget(w)
        tr.addStretch(1)
        grid.addWidget(QLabel("Check every"), 6, 0)
        grid.addLayout(tr, 6, 1, 1, 3)
        grid.setColumnStretch(1, 1)
        top.addLayout(grid, 1)
        thumb_col = QVBoxLayout()
        self.thumb = QLabel("No image yet")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(200, 96)
        self.thumb.setStyleSheet("border: 1.5px dashed rgba(127,220,255,140); border-radius: 14px; color: #7fdcff;")
        thumb_col.addWidget(self.thumb)
        tb = QHBoxLayout()
        for t, ic, cb in (("Capture", "camera", self.capture_image), ("Load", "image", self.load_image)):
            b = GlassButton(t, icon=ic, small=True)
            b.clicked.connect(cb)
            tb.addWidget(b)
        thumb_col.addLayout(tb)
        thumb_col.addStretch(1)
        self.thumb_col = QWidget()
        self.thumb_col.setLayout(thumb_col)
        top.addWidget(self.thumb_col)
        wl.addLayout(top)
        el.addWidget(when)

        # THEN
        then = GlassPanel(radius=22)
        tl = QVBoxLayout(then)
        tl.setContentsMargins(18, 14, 18, 14)
        tl.setSpacing(8)
        tl.addLayout(self._section_head("THEN", "do these in order"))
        orow = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setMinimumHeight(110)
        self.lst.setStyleSheet("QListWidget { background: transparent; border: none; } "
                               "QListWidget::item { padding: 6px 8px; border-radius: 8px; }")
        self.lst.doubleClicked.connect(lambda _i: self.edit_output())
        orow.addWidget(self.lst, 1)
        ob = QVBoxLayout()
        ob.setSpacing(6)
        for t, ic, cb in (("Add", "plus", self.add_output), ("Edit", None, self.edit_output),
                          ("Remove", "trash", self.remove_output), ("Up", "arrow-up", lambda: self.move_output(-1)),
                          ("Down", "arrow-down", lambda: self.move_output(1))):
            b = GlassButton(t, icon=ic, small=True, kind="danger" if t == "Remove" else "glass")
            b.clicked.connect(cb)
            ob.addWidget(b)
        ob.addStretch(1)
        orow.addLayout(ob)
        tl.addLayout(orow)
        el.addWidget(then)

        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(8)
        self.e_cool, self.e_max = field(64), field(64)
        self.cb_active = QComboBox()
        self.cb_active.addItems([a[1] for a in triggers.ACTIVE_MODES])
        self.sw_pause = GlassSwitch("Pause the running script while this fires")
        g2.addWidget(QLabel("Cooldown"), 0, 0)
        c = QHBoxLayout()
        c.addWidget(self.e_cool)
        c.addWidget(detail("s"))
        c.addStretch(1)
        g2.addLayout(c, 0, 1)
        g2.addWidget(QLabel("Max fires per run"), 0, 2)
        m = QHBoxLayout()
        m.addWidget(self.e_max)
        m.addWidget(detail("0 = unlimited"))
        m.addStretch(1)
        g2.addLayout(m, 0, 3)
        g2.addWidget(QLabel("Active"), 1, 0)
        g2.addWidget(self.cb_active, 1, 1)
        g2.addWidget(self.sw_pause, 1, 2, 1, 2)
        el.addLayout(g2)

        br = QHBoxLayout()
        self.lbl_msg = detail("")
        self.lbl_msg.setWordWrap(True)
        br.addWidget(self.lbl_msg, 1)
        for t, ic, kind, cb in (("Test now", "flask", "glass", lambda: self.test(False)),
                                ("Show match", "magnifying-glass", "glass", lambda: self.test(True)),
                                ("Save rule", "check", "primary", self.save_rule)):
            b = GlassButton(t, icon=ic, kind=kind)
            b.clicked.connect(cb)
            br.addWidget(b)
        el.addLayout(br)
        body.addWidget(ed, 1)
        root.addLayout(body)

        lp = GlassPanel(radius=26)
        lpl = QVBoxLayout(lp)
        lpl.setContentsMargins(20, 12, 20, 12)
        h = QHBoxLayout()
        h.addWidget(Caption("Monitor log"))
        h.addStretch(1)
        b = GlassButton("Clear", small=True)
        b.clicked.connect(self.clear_log)
        h.addWidget(b)
        lpl.addLayout(h)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(110)
        self.log.setMaximumBlockCount(400)
        self.log.setFont(font(9.5))
        self.log.setStyleSheet("QPlainTextEdit { background: transparent; border: none; }")
        lpl.addWidget(self.log)
        root.addWidget(lp)
        self._on_kind()

    def _section_head(self, word, sub):
        h = QHBoxLayout()
        w = QLabel(word)
        w.setFont(font(10, QFont.Weight.Bold))
        w.setStyleSheet(f"color: {glass.ACCENT.name()};" if not self.main.mode.dark else "color: #7fdcff;")
        h.addWidget(w)
        h.addWidget(detail(sub))
        h.addStretch(1)
        return h

    def restyle(self):
        pass

    def _on_kind(self, *_):
        kind = model.CONDITION_ID.get(self.cb_kind.currentText(), "image_appears")
        img = kind.startswith("image")
        px = kind.startswith("pixel")
        for w in (self.lab_image, self.cb_image, self.lab_match, self.sl_conf, self.lbl_conf, self.sw_gray,
                  self.thumb_col):
            w.setVisible(img)
        self.lab_px.setVisible(px)
        self.px_box.setVisible(px)
        self.e_color.setEnabled(kind == "pixel_is")
        self.lab_region.setVisible(not px)
        self.region_box.setVisible(not px)
        self.lab_stable.setVisible(kind == "region_stable")
        self.stable_box.setVisible(kind == "region_stable")

    # ------------------------------------------------------------ list

    def _rule(self, rid):
        return next((r for r in self.main.rules if r["id"] == rid), None)

    def refresh_rules(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for r in self.main.rules:
            it = QTreeWidgetItem(["", r.get("name") or "Rule"])
            it.setData(0, Qt.ItemDataRole.UserRole, r["id"])
            on = r.get("enabled")
            it.setIcon(0, glass.qicon("check" if on else "x", glass.GREEN if on else self.main.mode.faint, 16))
            if not on:
                it.setForeground(1, self.main.mode.detail)
            self.tree.addTopLevelItem(it)
            if r["id"] == self.sel_id:
                it.setSelected(True)
        self.tree.blockSignals(False)
        self.update_info()

    def update_info(self):
        n = sum(1 for r in self.main.rules if r.get("enabled"))
        self.lbl_info.setText(f"{n} of {len(self.main.rules)} rules on")
        r = self._rule(self.sel_id)
        self.lbl_summary.setText(triggers.describe_rule(r) if r else "")

    def _on_click(self, item, column):
        if column != 0:
            return
        r = self._rule(item.data(0, Qt.ItemDataRole.UserRole))
        if r:
            self.main.replace_rule(dict(r, enabled=not r.get("enabled")))
            self.refresh_rules()

    def _on_select(self):
        items = self.tree.selectedItems()
        if items:
            rid = items[0].data(0, Qt.ItemDataRole.UserRole)
            if rid != self.sel_id:
                self.select_rule(rid)

    def select_rule(self, rid):
        r = self._rule(rid)
        if not r:
            return
        self.sel_id = rid
        c = r.get("condition") or {}
        self.e_name.setText(r.get("name", ""))
        self.cb_kind.setCurrentText(model.CONDITION_LABEL.get(c.get("kind"), model.CONDITION_KINDS[0][1]))
        self.cb_image.clear()
        self.cb_image.addItems(self.main.trigger_assets.names())
        self.cb_image.setCurrentText(c.get("image") or "")
        self.e_region.setText(model.format_region(c.get("region")))
        self.sl_conf.setValue(int(round(float(c.get("confidence") or 0.9) * 100)))
        self.sw_gray.setChecked(bool(c.get("grayscale")))
        self.e_px.setText("" if c.get("x") is None else str(c.get("x")))
        self.e_py.setText("" if c.get("y") is None else str(c.get("y")))
        self.e_color.setText(c.get("color") or "")
        self.e_tol.setText(str(c.get("tolerance", 12)))
        self.e_stable.setText(str(c.get("stable_ms", 800)))
        self.e_every.setText(str(r.get("check_ms", 250)))
        self.e_hold.setText(str(r.get("hold_ms", 300)))
        self.e_cool.setText(str(r.get("cooldown_s", 5)))
        self.e_max.setText(str(r.get("max_fires", 0)))
        self.cb_active.setCurrentText(triggers.ACTIVE_LABEL.get(r.get("active", "script")))
        self.sw_pause.setChecked(bool(r.get("pause_script", True)))
        self.outputs = copy.deepcopy(r.get("outputs") or [])
        self._refresh_outputs()
        self._show_thumb()
        self.lbl_msg.setText("")
        self.refresh_rules()

    def _show_thumb(self):
        name = self.cb_image.currentText().strip()
        img = self.main.trigger_assets.get(name) if name else None
        if img is None:
            self.thumb.clear()
            self.thumb.setText("No image yet")
            return
        self.thumb.setText("")
        self.thumb.setPixmap(pixmap_from_bgr(img, 190, 86))

    def _refresh_outputs(self):
        cur = self.lst.currentRow()
        self.lst.clear()
        for i, o in enumerate(self.outputs, 1):
            self.lst.addItem(f"{i}.  {triggers.describe_output(o)}")
        if 0 <= cur < self.lst.count():
            self.lst.setCurrentRow(cur)

    # ------------------------------------------------------------ editing

    def form_to_rule(self):
        base = self._rule(self.sel_id) or triggers.new_rule()
        kind = model.CONDITION_ID.get(self.cb_kind.currentText(), "image_appears")
        c = {"kind": kind, "image": model.image_name(self.cb_image.currentText()),
             "region": model.parse_region(self.e_region.text(), "Search region"),
             "confidence": self.sl_conf.value() / 100.0, "grayscale": self.sw_gray.isChecked(),
             "x": model.parse_int(self.e_px.text(), "Pixel X", allow_blank=True),
             "y": model.parse_int(self.e_py.text(), "Pixel Y", allow_blank=True),
             "color": model.parse_color(self.e_color.text()) if self.e_color.text().strip() else "",
             "tolerance": model.parse_int(self.e_tol.text() or "12", "Tolerance", 0, 255),
             "stable_ms": model.parse_int(self.e_stable.text() or "800", "Still for", 50)}
        rule = dict(base)
        rule.update({
            "name": self.e_name.text().strip() or "Rule",
            "condition": c,
            "check_ms": model.parse_int(self.e_every.text(), "Check every", 50),
            "hold_ms": model.parse_int(self.e_hold.text() or "0", "Must stay true", 0),
            "outputs": copy.deepcopy(self.outputs),
            "cooldown_s": model.parse_int(self.e_cool.text() or "0", "Cooldown", 0),
            "max_fires": model.parse_int(self.e_max.text() or "0", "Max fires", 0),
            "active": triggers.ACTIVE_ID.get(self.cb_active.currentText(), "script"),
            "pause_script": self.sw_pause.isChecked(),
        })
        err = triggers.check_rule(rule, self.main.trigger_assets)
        if err:
            raise ValueError(err)
        return rule

    def _msg(self, text, tone="detail"):
        self.lbl_msg.setText(text)
        if tone == "ok":
            self.lbl_msg.setStyleSheet("color: #5ee08f;" if self.main.mode.dark else "color: #1e8e4a;")
        elif tone == "warn":
            self.lbl_msg.setStyleSheet("color: #f7c14b;" if self.main.mode.dark else "color: #a35f00;")
        elif tone == "error":
            self.lbl_msg.setStyleSheet("color: #ff7b7b;" if self.main.mode.dark else "color: #c62a36;")
        else:
            self.lbl_msg.setStyleSheet("")

    def save_rule(self):
        try:
            rule = self.form_to_rule()
        except ValueError as e:
            self._msg(str(e), "error")
            return None
        is_new = self._rule(rule["id"]) is None
        self.main.replace_rule(rule)
        self.sel_id = rule["id"]
        self.refresh_rules()
        tip = "" if self.main.triggers.running else " Turn Monitoring on to use it."
        if rule.get("active") == "script" and not self.main.job_running():
            tip += " It only runs while a script is running (see Active)."
        self._msg(("Rule created." if is_new else "Saved.") + tip, "ok")
        return rule

    def new_rule(self):
        r = triggers.new_rule(f"Rule {len(self.main.rules) + 1}")
        self.main.rules.append(r)
        self.main.save_rules()
        self.sel_id = None
        self.select_rule(r["id"])

    def duplicate(self):
        r = self._rule(self.sel_id)
        if not r:
            return
        new = copy.deepcopy(r)
        new["id"] = triggers.new_rule()["id"]
        new["name"] = (r.get("name") or "Rule") + " copy"
        self.main.rules.insert(self.main.rules.index(r) + 1, new)
        self.main.save_rules()
        self.select_rule(new["id"])

    def delete(self):
        r = self._rule(self.sel_id)
        if not r or QMessageBox.question(self, "Delete rule", f"Delete '{r.get('name')}'?") \
                != QMessageBox.StandardButton.Yes:
            return
        idx = self.main.rules.index(r)
        self.main.rules.remove(r)
        self.main.save_rules()
        self.sel_id = None
        if self.main.rules:
            self.select_rule(self.main.rules[min(idx, len(self.main.rules) - 1)]["id"])
        else:
            self.outputs = []
            self._refresh_outputs()
            self.refresh_rules()

    def add_output(self):
        o = edit_output(self.main)
        if o:
            self.outputs.append(o)
            self._refresh_outputs()

    def edit_output(self):
        i = self.lst.currentRow()
        if i < 0:
            return
        o = edit_output(self.main, self.outputs[i])
        if o:
            self.outputs[i] = o
            self._refresh_outputs()

    def remove_output(self):
        i = self.lst.currentRow()
        if i >= 0:
            del self.outputs[i]
            self._refresh_outputs()

    def move_output(self, d):
        i = self.lst.currentRow()
        if i < 0 or not 0 <= i + d < len(self.outputs):
            return
        self.outputs[i], self.outputs[i + d] = self.outputs[i + d], self.outputs[i]
        self._refresh_outputs()
        self.lst.setCurrentRow(i + d)

    def capture_image(self):
        def done(region, img):
            if img is None:
                return
            base = self.e_name.text() or "trigger"
            name = dialogs.ask_string(self.main, "Name this image", "Image name", base.lower().replace(" ", "_"))
            if name is None:
                return
            name = self.main.trigger_assets.add_image(img, name or "trigger")
            self.cb_image.clear()
            self.cb_image.addItems(self.main.trigger_assets.names())
            self.cb_image.setCurrentText(name)
            if not self.e_region.text().strip():
                pad = 150
                x, y, w, h = region
                self.e_region.setText(model.format_region([x - pad, y - pad, w + pad * 2, h + pad * 2]))
            self._msg("Captured. The search region is set around it; clear it to search everywhere.")
        dialogs.select_region(self.main, done, "Drag around the image this rule should look for. Esc cancels.")

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                img = vision.decode_png(f.read())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Could not load image", str(e))
            return
        name = self.main.trigger_assets.add_image(img, os.path.splitext(os.path.basename(path))[0])
        self.cb_image.clear()
        self.cb_image.addItems(self.main.trigger_assets.names())
        self.cb_image.setCurrentText(name)

    def draw_region(self):
        def done(region, _img):
            if region:
                self.e_region.setText(model.format_region(region))
        dialogs.select_region(self.main, done, "Drag the area this rule should watch. Esc cancels.")

    def grab_pixel(self):
        def done():
            x, y = inputs.position()
            self.e_px.setText(str(x))
            self.e_py.setText(str(y))
            self.e_color.setText(vision.rgb_hex(vision.pixel(x, y)))
        dialogs.countdown(self.main, 3, "Grabbing pixel", done)

    def test(self, show):
        try:
            rule = self.form_to_rule()
        except ValueError as e:
            self._msg(str(e), "error")
            return
        try:
            ok, match = self.main.triggers.test_rule(rule)
        except Exception as e:
            self._msg(f"Check failed: {e}", "error")
            return
        extra = ""
        if match and rule["condition"]["kind"].startswith("image"):
            extra = f" at {match.center[0]}, {match.center[1]} ({int(match.score * 100)}%)"
        self._msg(("Condition is TRUE" if ok else "Condition is false") + extra, "ok" if ok else "warn")
        if show and match:
            self.main.highlight.flash(match.rect, 1500)
        elif show and rule["condition"].get("region"):
            self.main.highlight.flash(rule["condition"]["region"], 1500)

    # ------------------------------------------------------------ import / export

    def export_rules(self):
        if not self.main.rules:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export rules", "rules.clktrig", "Trigger rules (*.clktrig)")
        if path:
            try:
                storage.save_triggers(path, self.main.rules, self.main.trigger_assets)
                self.main.set_status(f"Exported {len(self.main.rules)} rules")
            except Exception as e:
                QMessageBox.warning(self, "Could not export", str(e))

    def import_rules(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import rules", "", "Trigger rules (*.clktrig)")
        if not path:
            return
        try:
            rules, assets = storage.load_triggers(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not import", str(e))
            return
        rename = {}
        for name in assets.names():
            new = self.main.trigger_assets.unique_name(name) if self.main.trigger_assets.has(name) else name
            self.main.trigger_assets.put_image(new, assets.get(name))
            rename[name] = new
        for r in rules:
            base = triggers.new_rule()
            base.update(r)
            base["id"] = triggers.new_rule()["id"]
            base["enabled"] = False
            img = model.image_name(base["condition"].get("image"))
            if img in rename:
                base["condition"]["image"] = rename[img]
            self.main.rules.append(base)
        self.main.save_rules()
        self.refresh_rules()
        self.main.set_status(f"Imported {len(rules)} rules (turned off until you turn them on)")

    # ------------------------------------------------------------ log / state

    def add_log(self, rule, message, hit):
        stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cur = self.log.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        fmt = QTextCharFormat()
        fmt.setForeground(self.main.mode.faint)
        cur.insertText(f"{stamp}  ", fmt)
        fmt.setForeground(self.main.mode.text)
        cur.insertText(f"{str(rule)[:28]:<30}", fmt)
        fmt.setForeground(QColor("#7fdcff") if hit and self.main.mode.dark else
                          (glass.ACCENT if hit else self.main.mode.detail))
        cur.insertText(f"{message}\n", fmt)

    def clear_log(self):
        self.log.clear()

    def update_state(self, running_mine, running_any, paused):
        on = self.main.triggers.running
        self.btn_monitor.setText("Monitoring on" if on else "Monitoring off")
        self.btn_monitor.set_kind("on" if on else "glass")
        self.btn_monitor.updateGeometry()
        self.update_info()

    def title_text(self):
        return "Screen triggers"
