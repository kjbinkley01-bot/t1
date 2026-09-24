"""Macro Recorder tab in the Liquid Glass look: record, play back with variation, convert to a script."""

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, \
    QVBoxLayout, QWidget

from .. import model, storage, vision
from ..recorder import Player, Recorder, recording_to_steps
from ..storage import AssetStore
from .glass import GlassPanel, font
from .widgets import Caption, GlassButton, GlassSwitch


def num_field(value, width=64):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    e = QLineEdit(str(value))
    e.setFixedWidth(width)
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    return e


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    return lab


class Stat(QWidget):
    def __init__(self, caption):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = QLabel("0")
        self.value.setFont(font(26, QFont.Weight.DemiBold))
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap = detail(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.value)
        lay.addWidget(cap)


class RecorderTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.recorder = Recorder(main.hotkeys.is_hotkey)
        self.events = []
        self.path = None
        self.dirty = False
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)
        self._show_counts()

    # ------------------------------------------------------------ layout

    def _build(self):
        o = self.main.settings.get("recorder") or {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(8)
        for text, ic, cmd in (("New", "file-plus", self.new), ("Open", "folder-open", self.open),
                              ("Save", "floppy-disk", self.save), ("Save As", None, lambda: self.save(True))):
            b = GlassButton(text, icon=ic)
            b.clicked.connect(cmd)
            bl.addWidget(b)
        bl.addStretch(1)
        b = GlassButton("Convert to Action Script", icon="list-bullets")
        b.clicked.connect(self.convert)
        bl.addWidget(b)
        root.addWidget(bar)

        # record / play
        p = GlassPanel(radius=30)
        g = QGridLayout(p)
        g.setContentsMargins(26, 22, 26, 20)
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(14)
        self.btn_rec = GlassButton("Start Recording", icon="record", kind="record")
        self.btn_rec.setMinimumHeight(48)
        self.btn_rec.clicked.connect(lambda: self.toggle_record())
        self.btn_rec_stop = GlassButton("Stop Recording", icon="stop")
        self.btn_rec_stop.clicked.connect(lambda: self.stop_record())
        stats = QHBoxLayout()
        self.st_events, self.st_len = Stat("events"), Stat("length")
        stats.addWidget(self.st_events)
        stats.addWidget(self.st_len)
        g.addWidget(self.btn_rec, 0, 0)
        g.addWidget(self.btn_rec_stop, 0, 1)
        g.addLayout(stats, 0, 2)
        self.lbl_note = detail("Click Start Recording (or press the record hotkey), do the task, "
                               "then press the hotkey again to stop.")
        self.lbl_note.setWordWrap(True)
        g.addWidget(self.lbl_note, 1, 0, 1, 3)
        self.btn_play = GlassButton("Play Recording", icon="play", kind="primary")
        self.btn_play.clicked.connect(self.toggle_play)
        g.addWidget(self.btn_play, 2, 0)
        rp = QHBoxLayout()
        rp.setSpacing(8)
        self.e_repeat = num_field(o.get("repeat", 1), 56)
        rp.addWidget(QLabel("Repeat"))
        rp.addWidget(self.e_repeat)
        rp.addWidget(detail("0 = loop"))
        rp.addStretch(1)
        g.addLayout(rp, 2, 1)
        opts = QVBoxLayout()
        opts.setSpacing(6)
        self.sw_clicks = GlassSwitch("Record mouse clicks and scrolls")
        self.sw_moves = GlassSwitch("Record mouse movement")
        self.sw_keys = GlassSwitch("Record keyboard")
        for sw, key in ((self.sw_clicks, "clicks"), (self.sw_moves, "moves"), (self.sw_keys, "keys")):
            sw.setChecked(bool(o.get(key, True)))
            opts.addWidget(sw)
        g.addLayout(opts, 2, 2)
        for c in range(3):
            g.setColumnStretch(c, 1)
        root.addWidget(p)

        # variation
        p = GlassPanel(radius=30)
        vl = QVBoxLayout(p)
        vl.setContentsMargins(26, 20, 26, 20)
        vl.setSpacing(12)
        vl.addWidget(Caption("Playback variation"))
        self.e_smin, self.e_smax = num_field(o.get("speed_min", 100)), num_field(o.get("speed_max", 100))
        self.e_gmin, self.e_gmax = num_field(o.get("gap_min", 0)), num_field(o.get("gap_max", 0))
        self.cb_gunit = QComboBox()
        self.cb_gunit.addItems(["seconds", "minutes"])
        self.cb_gunit.setCurrentText(o.get("gap_unit", "seconds"))
        for label_text, a, mid, b, tail in (("Random playback speed between", self.e_smin, "and", self.e_smax, "%"),
                                            ("Random delay between playbacks", self.e_gmin, "to", self.e_gmax, None)):
            r = QHBoxLayout()
            r.setSpacing(8)
            lab = QLabel(label_text)
            lab.setFixedWidth(250)
            r.addWidget(lab)
            r.addWidget(a)
            r.addWidget(detail(mid))
            r.addWidget(b)
            r.addWidget(detail(tail) if tail else self.cb_gunit)
            r.addStretch(1)
            vl.addLayout(r)
        dev = QHBoxLayout()
        dev.setSpacing(14)
        self.dev = {}
        for axis, title in (("dx", "Horizontal mouse deviation"), ("dy", "Vertical mouse deviation")):
            box = GlassPanel(radius=22)
            bl2 = QVBoxLayout(box)
            bl2.setContentsMargins(18, 14, 18, 14)
            bl2.setSpacing(8)
            t = QLabel(title)
            t.setFont(font(10, QFont.Weight.DemiBold))
            bl2.addWidget(t)
            r = QHBoxLayout()
            r.setSpacing(8)
            emin, emax = num_field(o.get(f"{axis}_min", 0), 56), num_field(o.get(f"{axis}_max", 0), 56)
            for w in (QLabel("Min"), emin, QLabel("Max"), emax, detail("px")):
                r.addWidget(w)
            r.addStretch(1)
            bl2.addLayout(r)
            whole = GlassSwitch("Same offset for the whole playback")
            whole.setChecked(bool(o.get(f"{axis}_whole", True)))
            bl2.addWidget(whole)
            self.dev[axis] = (emin, emax, whole)
            dev.addWidget(box)
        vl.addLayout(dev)
        self.sw_settle = GlassSwitch("Wait for the screen to settle before each recorded click (max 10 s)")
        self.sw_settle.setChecked(bool(o.get("settle", False)))
        vl.addWidget(self.sw_settle)
        root.addWidget(p)

        tip = detail("Shortcut keys for recording and playback are in Settings (the gear icon).")
        root.addWidget(tip)
        root.addStretch(1)

    # ------------------------------------------------------------ state

    def _read_options(self):
        def num(edit, name, lo=None):
            try:
                v = float(edit.text() or 0)
            except ValueError:
                raise ValueError(f"{name} must be a number.")
            if lo is not None and v < lo:
                raise ValueError(f"{name} must be at least {lo:g}.")
            return v
        (hmin, hmax, hwhole), (vmin, vmax, vwhole) = self.dev["dx"], self.dev["dy"]
        o = {
            "repeat": int(num(self.e_repeat, "Repeat", 0)),
            "clicks": self.sw_clicks.isChecked(), "moves": self.sw_moves.isChecked(),
            "keys": self.sw_keys.isChecked(),
            "speed_min": num(self.e_smin, "Speed", 1), "speed_max": num(self.e_smax, "Speed", 1),
            "gap_min": num(self.e_gmin, "Delay", 0), "gap_max": num(self.e_gmax, "Delay", 0),
            "gap_unit": self.cb_gunit.currentText(),
            "dx_min": num(hmin, "Deviation"), "dx_max": num(hmax, "Deviation"),
            "dy_min": num(vmin, "Deviation"), "dy_max": num(vmax, "Deviation"),
            "dx_whole": hwhole.isChecked(), "dy_whole": vwhole.isChecked(),
            "settle": self.sw_settle.isChecked(),
        }
        self.main.settings["recorder"] = o
        self.main.save_settings()
        return o

    def _tick(self):
        if self.recorder.active:
            self.st_events.value.setText(str(self.recorder.count))
            secs = int(time.monotonic() - self.recorder.started)
            self.st_len.value.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _show_counts(self):
        self.st_events.value.setText(str(len(self.events)))
        secs = int(self.events[-1]["t"]) if self.events else 0
        self.st_len.value.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _note(self, text, role="detail"):
        self.lbl_note.setText(text)
        self.lbl_note.setProperty("role", role)
        self.lbl_note.style().unpolish(self.lbl_note)
        self.lbl_note.style().polish(self.lbl_note)

    def update_state(self, running_mine, running_any, paused):
        rec = self.recorder.active
        self.btn_rec.setEnabled(not rec and not running_any)
        self.btn_rec_stop.setEnabled(rec)
        self.btn_play.setEnabled(running_mine or (not running_any and not rec and bool(self.events)))
        self.btn_play.setText("Stop Playback" if running_mine else "Play Recording")
        self.btn_play.icon_name = "stop" if running_mine else "play"
        self.btn_play.set_kind("record" if running_mine else "primary")
        self.btn_play.updateGeometry()

    def title_text(self):
        name = os.path.basename(self.path) if self.path else "Untitled recording"
        return name + (" *" if self.dirty else "")

    # ------------------------------------------------------------ actions

    def toggle_record(self, from_hotkey=False):
        if self.recorder.active:
            self.stop_record(from_hotkey=from_hotkey)
            return
        if self.main.job_running():
            self.main.set_status("Stop the running job before recording.", error=True)
            return
        if self.dirty and self.events and not from_hotkey and QMessageBox.question(
                self, "Discard recording?", "The current recording is not saved. Record over it?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            o = self._read_options()
        except ValueError as e:
            self.main.set_status(str(e), error=True)
            return
        self.recorder.start(clicks=o["clicks"], moves=o["moves"], keys=o["keys"])
        self._note("Recording. Press the record hotkey to stop.", "error")
        self.main.set_status("Recording")
        self.main.refresh_states()

    def stop_record(self, from_hotkey=False):
        if not self.recorder.active:
            return
        self.events = self.recorder.stop(trim_last_click=not from_hotkey)
        self.path = None
        self.dirty = bool(self.events)
        self._show_counts()
        self._note(f"Recorded {len(self.events)} events. Save it, play it, or convert it to an Action Script.")
        self.main.set_status("Recording stopped")
        self.main.update_title()
        self.main.refresh_states()

    def toggle_play(self):
        if self.main.job_running_for(self):
            self.main.stop_job()
            return
        if self.main.job_running() or self.recorder.active:
            return
        if not self.events:
            self.main.set_status("Nothing to play. Record or open a recording first.", error=True)
            return
        try:
            o = self._read_options()
        except ValueError as e:
            self.main.set_status(str(e), error=True)
            return
        mult = 60.0 if o["gap_unit"] == "minutes" else 1.0
        job = Player(self.events, self.main.emitter("recording"), repeat=o["repeat"],
                     speed_min=o["speed_min"], speed_max=o["speed_max"],
                     dx_min=o["dx_min"], dx_max=o["dx_max"], dy_min=o["dy_min"], dy_max=o["dy_max"],
                     whole=o["dx_whole"] and o["dy_whole"],
                     gap_min=o["gap_min"] * mult, gap_max=o["gap_max"] * mult,
                     settle=o["settle"], start_delay=2.0)
        self.main.start_job(job, self)

    def on_job(self, kind, payload):
        if kind == "run":
            self._note(f"Playing run {payload}.")
        elif kind == "done":
            ok, reason = payload
            self._note(f"Playback {'finished' if ok else 'stopped'}. {'' if ok else reason}")

    def new(self):
        if self.recorder.active or self.main.job_running_for(self):
            return
        if self.dirty and self.events and QMessageBox.question(
                self, "Discard recording?", "The current recording is not saved. Discard it?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.events, self.path, self.dirty = [], None, False
        self._show_counts()
        self.main.update_title()

    def open(self):
        if self.recorder.active or self.main.job_running_for(self):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open recording", "", "Recordings (*.clkrec *.json);;All files (*)")
        if not path:
            return
        try:
            events, _options = storage.load_recording(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open recording", str(e))
            return
        self.events, self.path, self.dirty = events, path, False
        self._show_counts()
        self._note(f"Opened {os.path.basename(path)}.")
        self.main.update_title()

    def save(self, save_as=False):
        if not self.events:
            return
        path = self.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save recording", "recording.clkrec", "Recording (*.clkrec)")
            if not path:
                return
        try:
            storage.save_recording(path, self.events, self._read_options())
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return
        self.path, self.dirty = path, False
        self.main.update_title()
        self.main.set_status(f"Saved {os.path.basename(path)}")

    def convert(self):
        if not self.events:
            self.main.set_status("Record something first.", error=True)
            return
        steps = recording_to_steps(self.events)
        if not steps:
            self.main.set_status("The recording has no clicks or keys to convert.", error=True)
            return
        tab = self.main.action_tab
        if self.main.job_running_for(tab) or not tab.confirm_discard("converting"):
            return
        script = model.new_script("Converted recording")
        script["steps"] = steps
        script["screen"] = vision.display_info()
        tab.set_script(script, AssetStore())
        self.main.show_tab("actions")
        self.main.set_status(f"Converted {len(self.events)} events into {len(steps)} steps")
