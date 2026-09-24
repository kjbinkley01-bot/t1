"""Import Script tab in the Liquid Glass look: open a package, check it, dry run, run."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .. import model, storage, target
from ..runner import Runner
from ..storage import AssetStore
from . import dialogs, glass
from .glass import GlassPanel, font
from .runin import RunInButton
from .tab_triggers import pixmap_from_bgr
from .widgets import Caption, GlassButton, GlassSwitch, clear_layout


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    return lab


def chip(text, tone=None, dark=True):
    lab = QLabel(text)
    lab.setFont(font(9, QFont.Weight.Medium))
    if tone == "good":
        css = "color:#7fdcff; background: rgba(0,136,255,55);" if dark else "color:#0064b8; background: rgba(0,136,255,30);"
    elif tone == "bad":
        css = "color:#f7c14b; background: rgba(247,193,75,45);" if dark else "color:#a35f00; background: rgba(247,193,75,60);"
    else:
        css = "background: rgba(255,255,255,26);" if dark else "background: rgba(255,255,255,170);"
    lab.setStyleSheet(css + " border-radius: 11px; padding: 3px 11px;")
    return lab


def ask_text(main, title, prompt):
    d = dialogs.GlassDialog(main, title)
    lab = detail(prompt)
    lab.setWordWrap(True)
    box = QPlainTextEdit()
    box.setMinimumSize(620, 340)
    box.setFont(font(9.5))
    box.setStyleSheet("QPlainTextEdit { background: rgba(0,0,0,60); border: 1px solid rgba(255,255,255,30); "
                      "border-radius: 12px; padding: 8px; }")
    d.body.addWidget(lab)
    d.body.addWidget(box)
    d.add_buttons("Import")
    d.keyPressEvent = lambda e, d=d: QDialog.keyPressEvent(d, e)  # Enter makes new lines here
    return box.toPlainText() if d.exec() == QDialog.DialogCode.Accepted else None


def ask_choice(main, title, prompt, choices):
    d = dialogs.GlassDialog(main, title)
    d.body.addWidget(detail(prompt))
    cb = QComboBox()
    cb.addItems(choices)
    cb.setMinimumWidth(320)
    d.body.addWidget(cb)
    d.add_buttons()
    return cb.currentText() if d.exec() == QDialog.DialogCode.Accepted else None


class ImportTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.script = None
        self.assets = AssetStore()
        self.path = None
        self.input_edits = {}
        self.pending_real = False
        self.pending_values = {}
        self._build()
        self._show_empty()

    # ------------------------------------------------------------ layout

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 16, 8)
        bl.setSpacing(8)
        b = GlassButton("Open package", icon="folder-open", kind="primary")
        b.clicked.connect(self.open)
        bl.addWidget(b)
        b = GlassButton("Paste script text", icon="clipboard")
        b.clicked.connect(self.paste)
        bl.addWidget(b)
        self.cb_recent = QComboBox()
        self.cb_recent.setMinimumWidth(280)
        self.cb_recent.setPlaceholderText("Recent packages")
        self.cb_recent.activated.connect(self._open_recent)
        bl.addWidget(self.cb_recent)
        bl.addStretch(1)
        bl.addWidget(detail("Accepts .clkpkg / .clk (script plus images) or .json"))
        root.addWidget(bar)

        head = GlassPanel(radius=30)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(22, 16, 22, 16)
        hl.setSpacing(16)
        icon = QLabel()
        icon.setPixmap(glass.icon_pixmap("download-simple", "#7fdcff" if self.main.mode.dark else "#0064b8", 30,
                                         self.devicePixelRatioF()))
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background: rgba(0,136,255,45); border-radius: 26px;")
        hl.addWidget(icon)
        txt = QVBoxLayout()
        line = QHBoxLayout()
        self.lbl_name = QLabel("")
        self.lbl_name.setFont(font(14, QFont.Weight.Bold))
        self.lbl_desc = detail("")
        line.addWidget(self.lbl_name)
        line.addWidget(self.lbl_desc, 1)
        txt.addLayout(line)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        txt.addLayout(self.chips)
        hl.addLayout(txt, 1)
        self.btn_runin = RunInButton(self.main, tip="Run this script inside one window (it starts with the "
                                                    "window saved in the script, if any)")
        self.btn_runin.changed.connect(self._target_changed)
        hl.addWidget(self.btn_runin, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(head)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        sp = GlassPanel(radius=30)
        sl = QVBoxLayout(sp)
        sl.setContentsMargins(20, 16, 20, 14)
        h = QHBoxLayout()
        h.addWidget(Caption("Steps preview"))
        h.addStretch(1)
        h.addWidget(detail("blue steps wait on the screen instead of a fixed time"))
        sl.addLayout(h)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["#", "STEP", "WAITS FOR", "TIMEOUT"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(220)
        for i, w in enumerate((44, 200, 320, 90)):
            self.tree.setColumnWidth(i, w)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        sl.addWidget(self.tree, 1)
        mid.addWidget(sp, 1)

        side = QVBoxLayout()
        side.setSpacing(14)
        ip = GlassPanel(radius=26)
        self.inputs_box = QVBoxLayout(ip)
        self.inputs_box.setContentsMargins(18, 14, 18, 14)
        side.addWidget(ip)
        tp = GlassPanel(radius=26)
        tl = QVBoxLayout(tp)
        tl.setContentsMargins(18, 14, 18, 14)
        th = QHBoxLayout()
        th.addWidget(Caption("Image templates"))
        th.addStretch(1)
        b = GlassButton("Recapture", icon="camera", small=True)
        b.clicked.connect(self.recapture)
        th.addWidget(b)
        tl.addLayout(th)
        self.thumb_grid = QGridLayout()
        self.thumb_grid.setSpacing(8)
        tl.addLayout(self.thumb_grid)
        self.lbl_more = detail("")
        self.lbl_more.setWordWrap(True)
        tl.addWidget(self.lbl_more)
        side.addWidget(tp)
        cp = GlassPanel(radius=26)
        self.checks_box = QVBoxLayout(cp)
        self.checks_box.setContentsMargins(18, 14, 18, 14)
        side.addWidget(cp, 1)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(360)
        mid.addWidget(sw)
        root.addLayout(mid, 1)

        foot = GlassPanel(radius=26)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 8, 10, 8)
        self.sw_dry = GlassSwitch("Dry run first: find each target and highlight it without clicking")
        self.sw_dry.setChecked(True)
        fl.addWidget(self.sw_dry)
        fl.addStretch(1)
        b = GlassButton("Clear")
        b.clicked.connect(self.clear)
        fl.addWidget(b)
        self.btn_open = GlassButton("Open in Action Script", icon="list-bullets")
        self.btn_open.clicked.connect(self.to_actions)
        fl.addWidget(self.btn_open)
        self.btn_dry = GlassButton("Dry Run", icon="magnifying-glass")
        self.btn_dry.clicked.connect(self.run_dry)
        fl.addWidget(self.btn_dry)
        self.btn_run = GlassButton("Run", icon="play", kind="primary")
        self.btn_run.clicked.connect(self.run_real)
        fl.addWidget(self.btn_run)
        root.addWidget(foot)

    def _refresh_recent(self):
        self.cb_recent.clear()
        for p in self.main.settings.get("recent", []):
            if os.path.exists(p):
                self.cb_recent.addItem(os.path.basename(p), p)

    def _show_empty(self):
        self.lbl_name.setText("No script loaded")
        self.lbl_desc.setText("Open a package from Claude, or paste the script text.")
        self.btn_runin.set_target(None)
        clear_layout(self.chips)
        self.chips.addStretch(1)
        self.tree.clear()
        clear_layout(self.inputs_box)
        self.inputs_box.addWidget(Caption("Inputs to fill"))
        self.inputs_box.addWidget(detail("None"))
        clear_layout(self.thumb_grid)
        self.lbl_more.setText("")
        clear_layout(self.checks_box)
        self.checks_box.addWidget(Caption("Checks"))
        self.checks_box.addStretch(1)
        self._refresh_recent()

    # ------------------------------------------------------------ loading

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open script package", "",
                                              "Clicker packages (*.clkpkg *.clk *.json);;All files (*)")
        if path:
            self.load_path(path)

    def _open_recent(self, idx):
        p = self.cb_recent.itemData(idx)
        if p:
            self.load_path(p)

    def load_path(self, path):
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open package", str(e))
            return
        storage.add_recent(self.main.settings, path)
        self.main.save_settings()
        self.show(script, assets, path)

    def paste(self):
        text = ask_text(self.main, "Paste script",
                        "Paste the script JSON Claude gave you. Images can be added afterwards with Recapture.")
        if not text or not text.strip():
            return
        try:
            script = storage.parse_script_text(text)
        except Exception as e:
            QMessageBox.warning(self, "Could not read script", str(e))
            return
        self.show(script, AssetStore(), None)

    def show(self, script, assets, path):
        self.script, self.assets, self.path = script, assets, path
        name = script.get("name") or (os.path.splitext(os.path.basename(path))[0] if path else "Pasted script")
        self.lbl_name.setText(os.path.basename(path) if path else name)
        self.lbl_desc.setText(script.get("description") or name)
        self.btn_runin.set_target((script.get("settings") or {}).get("target"))
        self.refresh()
        self._refresh_recent()
        self.main.update_title()

    def refresh(self):
        s, a = self.script, self.assets
        dark = self.main.mode.dark
        clear_layout(self.chips)
        refs = model.referenced_images(s)
        for text in (f"{len(s['steps'])} steps", f"{len(refs)} image templates",
                     f"{len(s.get('inputs') or [])} inputs to fill"):
            self.chips.addWidget(chip(text, dark=dark))
        scr = s.get("screen")
        if scr:
            try:
                same = storage.screen_matches(s)
            except Exception:
                same = None
            txt = f"Built for {scr.get('width')} x {scr.get('height')} at {scr.get('scale', 100)}%"
            self.chips.addWidget(chip(txt + (", matches this screen" if same else ", differs from this screen"),
                                      "good" if same else "bad", dark))
        self.chips.addStretch(1)

        self.tree.clear()
        blue = QColor("#7fdcff") if dark else QColor("#0064b8")
        red = QColor("#ff7b7b") if dark else QColor("#c62a36")
        for i, st in enumerate(s["steps"]):
            lbl, waits, timeout = model.describe_for_import(st)
            it = QTreeWidgetItem([str(i + 1), lbl, waits, timeout])
            col = red if model.check_step(st, s["steps"]) else (blue if model.is_screen_step(st) else None)
            if col is not None:
                for c in range(4):
                    it.setForeground(c, QBrush(col))
            self.tree.addTopLevelItem(it)

        old = {k: e.text() for k, e in self.input_edits.items()}
        clear_layout(self.inputs_box)
        self.inputs_box.addWidget(Caption("Inputs to fill"))
        self.input_edits = {}
        if not s.get("inputs"):
            self.inputs_box.addWidget(detail("None"))
        for item in s.get("inputs") or []:
            self.inputs_box.addWidget(detail(item.get("label") or item["name"]))
            e = QLineEdit(old.get(item["name"], self.main.last_inputs.get(item["name"], item.get("default", ""))))
            self.inputs_box.addWidget(e)
            self.input_edits[item["name"]] = e
        self.sw_ask = GlassSwitch("Ask me for these each run")
        self.sw_ask.setChecked(True)
        if s.get("inputs"):
            self.inputs_box.addWidget(self.sw_ask)

        clear_layout(self.thumb_grid)
        shown = 0
        for name in refs[:4]:
            img = a.get(name)
            cell = QVBoxLayout()
            pic = QLabel()
            pic.setFixedHeight(62)
            pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if img is not None:
                pic.setPixmap(pixmap_from_bgr(img, 140, 56))
                pic.setStyleSheet("background: rgba(0,136,255,40); border-radius: 12px;")
            else:
                pic.setText("missing")
                pic.setStyleSheet(f"color: {red.name()}; background: rgba(255,80,80,40); border-radius: 12px;")
            cell.addWidget(pic)
            cell.addWidget(detail(model.image_stem(name)))
            self.thumb_grid.addLayout(cell, shown // 2, shown % 2)
            shown += 1
        extra = len(refs) - shown
        self.lbl_more.setText((f"+{extra} more. " if extra > 0 else "")
                              + ("Recapture any template that does not match your screen." if refs else
                                 "This script uses no images."))

        clear_layout(self.checks_box)
        self.checks_box.addWidget(Caption("Checks"))
        colors = {"ok": "#5ee08f" if dark else "#1e8e4a", "warn": "#f7c14b" if dark else "#a35f00",
                  "error": red.name()}
        for lvl, msg in storage.validate(s, a):
            row = QHBoxLayout()
            dot = QLabel()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(f"background: {colors[lvl]}; border-radius: 4px;")
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            lab = QLabel(msg)
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            self.checks_box.addLayout(row)
        self.checks_box.addStretch(1)
        self.main.refresh_states()

    def clear(self):
        if self.main.job_running_for(self):
            return
        self.script, self.assets, self.path = None, AssetStore(), None
        self.input_edits = {}
        self._show_empty()
        self.main.refresh_states()
        self.main.update_title()

    def recapture(self):
        if not self.script:
            return
        refs = model.referenced_images(self.script)
        if not refs:
            return
        missing = [n for n in refs if not self.assets.has(n)]
        choice = ask_choice(self.main, "Recapture template", "Which image do you want to capture again?",
                            missing + [n for n in refs if n not in missing])
        if not choice:
            return

        def done(region, img):
            if img is None:
                return
            self.assets.put_image(choice, img)
            self.refresh()
            self.main.set_status(f"Recaptured {choice}")
        dialogs.select_region(self.main, done, f"Drag around '{model.image_stem(choice)}'. Esc cancels.")

    def _target_changed(self, t):
        if not self.script:
            self.btn_runin.set_target(None)
            self.main.set_status("Open a script first.", error=True)
            return
        st = self.script.setdefault("settings", {})
        if t:
            st["target"] = t
        else:
            st.pop("target", None)
        self.main.set_status(f"This script will run in {target.describe(t)}. Its positions are measured from the "
                             "window's top left corner." if t else "This script will run on the whole screen.")

    def to_actions(self):
        if not self.script:
            return
        tab = self.main.action_tab
        if self.main.job_running_for(tab) or not tab.confirm_discard("opening the import"):
            return
        tab.set_script(self.script, self.assets.copy(), None)
        self.main.show_tab("actions")

    # ------------------------------------------------------------ running

    def _ready(self):
        if not self.script or self.main.job_running():
            return False
        errors = [m for lvl, m in storage.validate(self.script, self.assets) if lvl == "error"]
        if errors:
            QMessageBox.warning(self, "Fix these first", "\n".join(errors))
            return False
        return True

    def _values(self):
        values = {k: e.text() for k, e in self.input_edits.items()}
        if self.script.get("inputs") and self.sw_ask.isChecked():
            values = dialogs.ask_inputs(self.main, self.script["inputs"], values)
            if values is None:
                return None
            for k, v in values.items():
                if k in self.input_edits:
                    self.input_edits[k].setText(v)
        self.main.last_inputs.update(values)
        return values

    def _start(self, dry, values):
        st = self.script.get("settings") or {}
        job = Runner(self.script, self.assets, self.main.emitter("script"), inputs_map=values,
                     speed=st.get("speed", 1.0), repeat=1 if dry else st.get("repeat", 1),
                     random_delay_ms=st.get("random_delay_ms", 0), dry_run=dry, start_delay=2.0,
                     label="Dry run" if dry else "Imported script",
                     save_log=self.main.settings.get("save_run_logs", True))
        self.main.start_job(job, self, hide=not dry and self.main.action_tab.sw_hide.isChecked())

    def run_dry(self):
        if self._ready():
            values = self._values()
            if values is not None:
                self.pending_real = False
                self._start(True, values)

    def run_real(self):
        if not self._ready():
            return
        values = self._values()
        if values is None:
            return
        if self.sw_dry.isChecked():
            self.pending_real = True
            self.pending_values = values
            self._start(True, values)
        else:
            self._start(False, values)

    def on_job(self, kind, payload):
        if kind == "step" and 0 <= payload < self.tree.topLevelItemCount():
            it = self.tree.topLevelItem(payload)
            self.tree.setCurrentItem(it)
            self.tree.scrollToItem(it)
        elif kind == "done":
            ok, reason = payload
            if self.pending_real:
                self.pending_real = False
                if ok and QMessageBox.question(self, "Dry run finished",
                                               "Every target was found. Run the script for real now?") \
                        == QMessageBox.StandardButton.Yes:
                    QTimer.singleShot(100, lambda: self._start(False, self.pending_values))
                elif not ok:
                    QMessageBox.warning(self, "Dry run stopped", reason)

    def update_state(self, running_mine, running_any, paused):
        has = self.script is not None
        self.btn_run.setEnabled(has and not running_any)
        self.btn_dry.setEnabled(has and not running_any)
        self.btn_open.setEnabled(has)
        self.btn_runin.setEnabled(has and not running_mine)

    def title_text(self):
        return os.path.basename(self.path) if self.path else "Import script"
