"""Macro Recorder tab in the Liquid Glass look: record, play back with variation, convert to a script."""

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, \
    QVBoxLayout, QWidget

from .. import library, model, storage, target, vision
from ..recorder import Player, Recorder, recording_to_steps, to_window
from ..storage import AssetStore
from . import dialogs, glass
from .glass import GlassPanel, font
from .rec_timeline import RecordingEditor
from .runin import RunInButton
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
        self.images, self.snaps = {}, {}   # click pictures and screen snapshots of this recording
        self.path = None
        self.dirty = False
        self.recorded_in = None   # the window this recording's positions are measured from (None = screen)
        self._rec_window = None   # (target, origin, size) while recording in a window
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)
        self._show_counts()
        if self.btn_runin.target:
            self._note(self._where_note())

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
        self.btn_runin = RunInButton(self.main, tip="Record and play back inside one window, so playback "
                                                    "leaves your mouse and keyboard free")
        self.btn_runin.set_target(self.main.settings.get("recorder_target"))
        self.btn_runin.changed.connect(self._target_changed)
        bl.addWidget(self.btn_runin)
        root.addWidget(bar)

        # record (left) and play back (right) in one panel; the recording editor gets the rest
        p = GlassPanel(radius=30)
        g = QGridLayout(p)
        g.setContentsMargins(26, 20, 26, 18)
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(12)
        self.btn_rec = GlassButton("Start Recording", icon="record", kind="record")
        self.btn_rec.setMinimumHeight(44)
        self.btn_rec.clicked.connect(lambda: self.toggle_record())
        self.btn_rec_stop = GlassButton("Stop Recording", icon="stop")
        self.btn_rec_stop.setMinimumHeight(44)
        self.btn_rec_stop.clicked.connect(lambda: self.stop_record())
        rec_row = QHBoxLayout()
        rec_row.setSpacing(10)
        rec_row.addWidget(self.btn_rec, 1)
        rec_row.addWidget(self.btn_rec_stop, 1)
        g.addLayout(rec_row, 0, 0)
        self.btn_play = GlassButton("Play Recording", icon="play", kind="primary")
        self.btn_play.setMinimumHeight(44)
        self.btn_play.clicked.connect(self.toggle_play)
        play_row = QHBoxLayout()
        play_row.setSpacing(10)
        play_row.addWidget(self.btn_play, 1)
        stats = QHBoxLayout()
        self.st_events, self.st_len = Stat("events"), Stat("length")
        stats.addWidget(self.st_events)
        stats.addWidget(self.st_len)
        play_row.addLayout(stats)
        g.addLayout(play_row, 0, 1)
        self.lbl_note = detail("Click Start Recording (or press the record hotkey), do the task, "
                               "then press the hotkey again to stop.")
        self.lbl_note.setWordWrap(True)
        g.addWidget(self.lbl_note, 1, 0, 1, 2)

        rec = QVBoxLayout()
        rec.setSpacing(6)
        rec.addWidget(Caption("Record"))
        self.sw_clicks = GlassSwitch("Mouse clicks and scrolls")
        self.sw_moves = GlassSwitch("Mouse movement")
        self.sw_keys = GlassSwitch("Keyboard")
        self.sw_pics = GlassSwitch("A picture at each click")
        self.sw_pics.setToolTip("Lets Convert make Click Image steps, and playback find clicks that moved")
        self.sw_snaps = GlassSwitch("Screen snapshots for the timeline")
        self.sw_snaps.setToolTip("A small screenshot every half second, shown on the timeline (about 4 MB a minute)")
        for sw, key, default in ((self.sw_clicks, "clicks", True), (self.sw_moves, "moves", True),
                                 (self.sw_keys, "keys", True), (self.sw_pics, "pictures", True),
                                 (self.sw_snaps, "snapshots", False)):
            sw.setChecked(bool(o.get(key, default)))
            rec.addWidget(sw)
        rec.addStretch(1)
        g.addLayout(rec, 2, 0, Qt.AlignmentFlag.AlignTop)

        play = QVBoxLayout()
        play.setSpacing(8)
        play.addWidget(Caption("Play back"))
        self.e_repeat = num_field(o.get("repeat", 1), 56)
        self.e_smin, self.e_smax = num_field(o.get("speed_min", 100)), num_field(o.get("speed_max", 100))
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in (QLabel("Repeat"), self.e_repeat, detail("times (0 = loop)"), QLabel("   Speed"), self.e_smin,
                  detail("to"), self.e_smax, detail("%")):
            row.addWidget(w)
        row.addStretch(1)
        play.addLayout(row)
        self.sw_settle = GlassSwitch("Wait for the screen to settle before each click (max 10 s)")
        self.sw_settle.setChecked(bool(o.get("settle", False)))
        play.addWidget(self.sw_settle)
        self.sw_follow = GlassSwitch("Find each click by its picture, so moved windows and buttons still work")
        self.sw_follow.setChecked(bool(o.get("follow", False)))
        play.addWidget(self.sw_follow)

        # less used: behind a disclosure that slides open
        self.btn_more = GlassButton("More playback options", icon="caret-down", small=True,
                                    tip="Wait between repeats, and shift the mouse a little each playback")
        self.btn_more.clicked.connect(self._toggle_more)
        play.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignLeft)
        self.more = QWidget()
        ml = QVBoxLayout(self.more)
        ml.setContentsMargins(0, 2, 0, 0)
        ml.setSpacing(8)
        self.e_gmin, self.e_gmax = num_field(o.get("gap_min", 0)), num_field(o.get("gap_max", 0))
        self.cb_gunit = QComboBox()
        self.cb_gunit.addItems(["seconds", "minutes"])
        self.cb_gunit.setCurrentText(o.get("gap_unit", "seconds"))
        row = QHBoxLayout()
        row.setSpacing(8)
        for w in (QLabel("Wait between repeats"), self.e_gmin, detail("to"), self.e_gmax, self.cb_gunit):
            row.addWidget(w)
        row.addStretch(1)
        ml.addLayout(row)
        self.dev = {}
        for axis, title in (("dx", "Shift clicks sideways"), ("dy", "Shift clicks up/down")):
            row = QHBoxLayout()
            row.setSpacing(8)
            emin, emax = num_field(o.get(f"{axis}_min", 0), 56), num_field(o.get(f"{axis}_max", 0), 56)
            whole = GlassSwitch("same for the whole playback")
            whole.setChecked(bool(o.get(f"{axis}_whole", True)))
            for w in (QLabel(title), emin, detail("to"), emax, detail("px"), whole):
                row.addWidget(w)
            row.addStretch(1)
            ml.addLayout(row)
            self.dev[axis] = (emin, emax, whole)
        play.addWidget(self.more)
        self._more_open = bool(o.get("more_open", False)) or any(
            float(o.get(k, 0) or 0) for k in ("gap_min", "gap_max", "dx_min", "dx_max", "dy_min", "dy_max"))
        self.more.setVisible(self._more_open)
        self.btn_more.set_kind("on" if self._more_open else "glass")
        g.addLayout(play, 2, 1, Qt.AlignmentFlag.AlignTop)
        g.setColumnStretch(0, 2)
        g.setColumnStretch(1, 3)
        root.addWidget(p)

        self.editor = RecordingEditor(self)
        root.addWidget(self.editor)

        tip = detail("Shortcut keys for recording and playback are in Settings (the gear icon).")
        root.addWidget(tip)
        root.addStretch(1)

    # ------------------------------------------------------------ state

    def _toggle_more(self):
        """Slide the extra playback options open or closed."""
        self._more_open = not self._more_open
        self.btn_more.set_kind("on" if self._more_open else "glass")
        full = self.more.sizeHint().height()
        if not glass.motion_on() or not self.isVisible():
            self.more.setVisible(self._more_open)
            return
        self.more.setMaximumHeight(0 if self._more_open else full)
        self.more.setVisible(True)
        opening = self._more_open

        def done():
            self.more.setMaximumHeight(16777215)
            self.more.setVisible(opening)
        glass.animate(self, self.more.maximumHeight(), full if opening else 0, glass.BASE,
                      lambda v: self.more.setMaximumHeight(round(v)), curve=glass.GLIDE, attr="_more_anim",
                      done=done)

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
            "pictures": self.sw_pics.isChecked(), "snapshots": self.sw_snaps.isChecked(),
            "follow": self.sw_follow.isChecked(),
            "speed_min": num(self.e_smin, "Speed", 1), "speed_max": num(self.e_smax, "Speed", 1),
            "gap_min": num(self.e_gmin, "Delay", 0), "gap_max": num(self.e_gmax, "Delay", 0),
            "gap_unit": self.cb_gunit.currentText(),
            "dx_min": num(hmin, "Deviation"), "dx_max": num(hmax, "Deviation"),
            "dy_min": num(vmin, "Deviation"), "dy_max": num(vmax, "Deviation"),
            "dx_whole": hwhole.isChecked(), "dy_whole": vwhole.isChecked(),
            "settle": self.sw_settle.isChecked(), "more_open": self._more_open,
        }
        self.main.settings["recorder"] = o
        self.main.save_settings()
        return o

    def _target_changed(self, t):
        self.main.settings["recorder_target"] = t
        self.main.save_settings()
        self._note(self._where_note())

    def _where_note(self):
        t = self.btn_runin.target
        if not t:
            if self.recorded_in:
                return (f"This recording was made in {target.describe(self.recorded_in)}. It plays on the "
                        "whole screen at that window's current position.")
            return "Click Start Recording (or press the record hotkey), do the task, then press the hotkey again to stop."
        where = target.describe(t)
        text = (f"Recording and playback happen in {where}. Record by using that window normally; clicks "
                "outside it are left out. Playback goes to the window, so your mouse stays free.")
        if self.events and not self.recorded_in:
            text += " This recording was made on the whole screen; it plays as if the window is where it was then."
        return text

    def _tick(self):
        if self.recorder.active:
            self.st_events.value.setText(str(self.recorder.count))
            secs = int(time.monotonic() - self.recorder.started)
            self.st_len.value.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _show_counts(self):
        self.st_events.value.setText(str(sum(1 for e in self.events if e["type"] != "snap")))
        secs = int(self.events[-1]["t"]) if self.events else 0
        self.st_len.value.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _note(self, text, role="detail"):
        self.lbl_note.setText(text)
        self.lbl_note.setProperty("role", role)
        self.lbl_note.style().unpolish(self.lbl_note)
        self.lbl_note.style().polish(self.lbl_note)

    def replace_events(self, events):
        """An edit from the timeline."""
        self.events = events
        self.dirty = True
        self._show_counts()
        self.main.update_title()

    def play_events(self, events, note):
        if self.main.job_running() or self.recorder.active or not events:
            return
        try:
            o = self._read_options()
        except ValueError as e:
            self.main.set_status(str(e), error=True)
            return
        job = Player(events, self.main.emitter("recording"), repeat=1,
                     speed_min=o["speed_min"], speed_max=o["speed_max"], settle=o["settle"],
                     start_delay=0.5 if self.btn_runin.target else 2.0,
                     target=self.btn_runin.target, recorded_in=self.recorded_in,
                     images=self.images, follow=o["follow"])
        if self.main.start_job(job, self):
            self._note(note + ("" if self.btn_runin.target else ". Starting in 2 s."))

    def update_state(self, running_mine, running_any, paused):
        self.editor.setEnabled(not self.recorder.active and not running_mine)
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
        t = self.btn_runin.target
        self._rec_window = None
        if t:
            try:
                io = target.WindowIO(t)
                self._rec_window = (t, io.client_origin(), io.bounds()[2:])
            except Exception as e:
                self.main.set_status(f"{e}. Open it or choose Whole screen.", error=True)
                return
        self.recorder.start(clicks=o["clicks"], moves=o["moves"], keys=o["keys"], pictures=o["pictures"],
                            snapshots=o["snapshots"])
        self._note("Recording" + (f" in {target.describe(t)}" if t else "") + ". Press the record hotkey to stop.",
                   "error")
        self.main.set_status("Recording")
        self.main.refresh_states()

    def stop_record(self, from_hotkey=False):
        if not self.recorder.active:
            return
        self.events = self.recorder.stop(trim_last_click=not from_hotkey)
        self.images, self.snaps = dict(self.recorder.images), dict(self.recorder.snaps)
        dropped = 0
        self.recorded_in = None
        if self._rec_window:
            t, origin, size = self._rec_window
            self.events, dropped = to_window(self.events, origin, size)
            self.recorded_in = t
            self._rec_window = None
        self.path = None
        self.dirty = bool(self.events)
        self._show_counts()
        self.editor.load(self.events)
        self._note(f"Recorded {len(self.events)} events"
                   + (f" in {target.describe(self.recorded_in)} ({dropped} outside it left out)" if dropped else
                      f" in {target.describe(self.recorded_in)}" if self.recorded_in else "")
                   + ". Save it, play it, or convert it to an Action Script.")
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
                     settle=o["settle"], start_delay=0.5 if self.btn_runin.target else 2.0,
                     target=self.btn_runin.target, recorded_in=self.recorded_in,
                     images=self.images, follow=o["follow"])
        self.main.start_job(job, self)

    def on_job(self, kind, payload):
        if kind == "run":
            t = self.btn_runin.target
            self._note(f"Playing run {payload}" + (f" in {target.describe(t)}." if t else "."))
        elif kind == "done":
            ok, reason = payload
            self._note(f"Playback {'finished' if ok else 'stopped'}. {'' if ok else reason}")

    def _busy_or_keep(self):
        """True when the recording can't be replaced now (recording, playing, or unsaved and kept)."""
        if self.recorder.active or self.main.job_running_for(self):
            return True
        return bool(self.dirty and self.events and QMessageBox.question(
            self, "Discard recording?", "The current recording is not saved. Discard it?")
            != QMessageBox.StandardButton.Yes)

    def new(self):
        if self._busy_or_keep():
            return
        self.events, self.path, self.dirty, self.recorded_in = [], None, False, None
        self.images, self.snaps = {}, {}
        self._show_counts()
        self.editor.load(self.events)
        self._note(self._where_note())
        self.main.update_title()

    def open(self):
        self.main.open_library("recording")

    def browse(self):
        if self._busy_or_keep():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open recording", "", "Recordings (*.clkrec *.json);;All files (*)")
        if path:
            self.open_path(path)

    def open_from_library(self, path):
        if not self._busy_or_keep():
            self.open_path(path)

    def open_version(self, path, copy):
        if self._busy_or_keep():
            return False
        self.open_path(copy, remember=False)
        self.path, self.dirty = path, True
        self.main.update_title()
        return True

    def open_path(self, path, remember=True):
        try:
            events, options, images, snaps = storage.load_recording_full(path)
        except Exception as e:
            QMessageBox.warning(self, "Could not open recording", str(e))
            return
        self.events, self.path, self.dirty = events, path, False
        self.images, self.snaps = images, snaps
        self.recorded_in = target.normalize(options.get("recorded_in"))
        if self.recorded_in:  # it was made in a window: play it there unless the user picks otherwise
            self.btn_runin.set_target(self.recorded_in)
            self._target_changed(self.recorded_in)
        self._show_counts()
        self.editor.load(self.events)
        self._note(f"Opened {os.path.basename(path)}"
                   + (f", recorded in {target.describe(self.recorded_in)}." if self.recorded_in else "."))
        self.main.update_title()
        if remember:
            self.main.remember(path, "recording", library.recording_info(events, images, snaps))

    def save(self, save_as=False):
        if not self.events:
            return
        path = self.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save recording", "recording.clkrec", "Recording (*.clkrec)")
            if not path:
                return
        try:
            self.main.keep_version(path)
            used_i = {e.get("img") for e in self.events}
            used_s = {e.get("snap") for e in self.events}
            storage.save_recording(path, self.events, dict(self._read_options(), recorded_in=self.recorded_in),
                                   {k: v for k, v in self.images.items() if k in used_i},
                                   {k: v for k, v in self.snaps.items() if k in used_s})
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return
        self.path, self.dirty = path, False
        self.main.update_title()
        self.main.set_status(f"Saved {os.path.basename(path)}")
        self.main.remember(path, "recording", library.recording_info(self.events, self.images, self.snaps))

    def convert(self):
        if not self.events:
            self.main.set_status("Record something first.", error=True)
            return
        pics = sum(1 for e in self.events if e.get("img"))
        use_pics, smart = bool(pics), bool(pics)
        if pics:
            d = dialogs.GlassDialog(self.main, "Convert to Action Script")
            d.body.addWidget(detail(f"{pics} click{'s have' if pics != 1 else ' has'} a picture."))
            sw_pics = GlassSwitch("Click by picture where there is one (works when windows move)")
            sw_smart = GlassSwitch("Wait for each picture instead of the recorded pauses (faster, and fine "
                                   "on slow PCs)")
            for sw in (sw_pics, sw_smart):
                sw.setChecked(True)
                d.body.addWidget(sw)
            sw_pics.toggled.connect(sw_smart.setEnabled)
            d.add_buttons("Convert")
            if d.exec() != QDialog.DialogCode.Accepted:
                return
            use_pics, smart = sw_pics.isChecked(), sw_smart.isChecked()
        steps = recording_to_steps(self.events, use_pictures=use_pics, wait_for_pictures=smart)
        if not steps:
            self.main.set_status("The recording has no clicks or keys to convert.", error=True)
            return
        tab = self.main.action_tab
        if self.main.job_running_for(tab) or not tab.confirm_discard("converting"):
            return
        script = model.new_script("Converted recording")
        script["steps"] = steps
        script["screen"] = vision.display_info()
        if self.recorded_in:  # the positions are the window's, so the script runs in that window
            script["settings"]["target"] = dict(self.recorded_in)
        assets = AssetStore()
        for st in steps:
            name = st.get("image")
            if name and name in self.images:
                assets.put_image(name, self.images[name])
        tab.set_script(script, assets)
        self.main.show_tab("actions")
        pics = sum(1 for st in steps if st["action"] == "Click Image")
        self.main.set_status(f"Converted {len(self.events)} events into {len(steps)} steps"
                             + (f" ({pics} click{'s find' if pics != 1 else ' finds'} its picture)" if pics else ""))
