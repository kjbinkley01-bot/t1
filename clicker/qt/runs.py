"""Running several scripts at once: the rule for what may run together, and the Runs panel."""

import os

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import glass
from .glass import font
from .widgets import Caption, GlassButton


def uses_real_input(job):
    """True when the job moves the real mouse and keyboard (whole screen, or a window in quick switch)."""
    t = getattr(job, "target", None)
    return t is None or t.get("method") == "quickswitch"


def can_run_alongside(new_job, running):
    """At most one of all the runs may use the real mouse and keyboard; the rest run in their own windows."""
    real = sum(1 for j in running if uses_real_input(j)) + (1 if uses_real_input(new_job) else 0)
    return real <= 1


def job_name(job):
    script = getattr(job, "script", None)
    if isinstance(script, dict) and script.get("name"):
        return script["name"]
    path = getattr(job, "path", None)
    return os.path.splitext(os.path.basename(path))[0] if path else getattr(job, "label", "Recording")


def job_line(job):
    script = getattr(job, "script", None)
    cur = getattr(job, "current", None)
    bits = []
    if isinstance(script, dict) and cur is not None and 0 <= cur < len(script["steps"]):
        bits.append(f"step {cur + 1}/{len(script['steps'])} · {script['steps'][cur]['action']}")
    t = getattr(job, "target", None)
    if t:
        from .. import target
        bits.append(target.describe(t))
    else:
        bits.append("real mouse and keyboard")
    return ("Paused · " if job.paused else "") + " · ".join(bits)


class RunsPanel(QFrame):
    """Pops up from the status bar: every running script with its own Pause and Stop."""

    def __init__(self, main):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.main = main
        self.setObjectName("runsPanel")
        self.setStyleSheet("#runsPanel { background: rgba(26,20,62,245); border: 1px solid rgba(255,255,255,70); "
                           "border-radius: 18px; }")
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 12, 12, 12)
        self.lay.setSpacing(8)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)

    def open_at(self, widget):
        self._sig = None
        self.refresh()
        self.adjustSize()
        p = widget.mapToGlobal(QPoint(widget.width() - self.width(), -self.height() - 8))
        self.move(p)
        glass.fade_in(self)
        self.show()
        QTimer.singleShot(0, self._fit)
        self.timer.start()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def refresh(self):
        runs = self.main.all_runs()
        sig = tuple((id(j), j.paused) for j, _m in runs)
        if sig == getattr(self, "_sig", None):
            for lab, job in getattr(self, "_lines", []):  # same runs: just update their step lines
                lab.setText(job_line(job))
            return
        self._sig = sig
        self._lines = []
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                _clear(it.layout())
        self.lay.addWidget(Caption("Running now"))
        if not runs:
            lab = QLabel("Nothing is running.")
            lab.setProperty("role", "detail")
            self.lay.addWidget(lab)
        for job, main_run in runs:
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(0)
            name = QLabel(job_name(job) + ("" if main_run else "  (alongside)"))
            name.setFont(font(10, font_weight_bold()))
            name.setStyleSheet("color: white;")
            line = QLabel(job_line(job))
            line.setStyleSheet("color: rgba(255,255,255,170);")
            self._lines.append((line, job))
            col.addWidget(name)
            col.addWidget(line)
            row.addLayout(col, 1)
            b = GlassButton("", icon="play" if job.paused else "pause", small=True, tip="Pause / resume")
            b.clicked.connect(lambda _=False, j=job: (j.toggle_pause(), QTimer.singleShot(50, self.refresh)))
            row.addWidget(b)
            b = GlassButton("Stop", icon="stop", kind="record", small=True)
            b.clicked.connect(lambda _=False, j=job: (j.stop(), QTimer.singleShot(300, self.refresh)))
            row.addWidget(b)
            holder = QWidget()
            holder.setLayout(row)
            self.lay.addWidget(holder)
        b = GlassButton("Run a script alongside...", icon="plus", small=True,
                        tip="Scripts that run in their own window (background mode) can run at the same time")
        b.clicked.connect(self._pick)
        self.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        note = QLabel("Only one run at a time may use the real mouse and keyboard; others must run in their own "
                      "window (Run in, background).")
        note.setWordWrap(True)
        note.setStyleSheet("color: rgba(255,255,255,150);")
        self.lay.addWidget(note)
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        bottom = self.geometry().bottom()
        self.adjustSize()
        if self.isVisible():  # keep it sitting just above the status bar as it grows
            self.move(self.x(), bottom - self.height() + 1)

    def _pick(self):
        self.hide()
        from .library_dialog import pick_script
        path = pick_script(self.main, "Run a script or chain alongside", chains=True)
        if path:
            self.main.run_script_hotkey(path, from_menu=True)


def font_weight_bold():
    from PySide6.QtGui import QFont
    return QFont.Weight.Bold


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())
