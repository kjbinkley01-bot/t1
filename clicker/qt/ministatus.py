"""A small always-on-top status pill while a script runs: step, progress, time, Pause and Stop."""

import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import glass
from .glass import font
from .widgets import GlassButton

MODES = [("hidden", "While the main window is hidden"), ("always", "Always while a script runs"), ("never", "Never")]
MODE_LABEL = dict(MODES)
MODE_ID = {v: k for k, v in MODES}


class _Bar(QWidget):
    def __init__(self):
        super().__init__()
        self.frac = None
        self.setFixedHeight(6)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        r = QRectF(self.rect())
        p.drawRoundedRect(r, 3, 3)
        if self.frac is None:  # no timed wait: a soft glow sweeps across to show it's alive
            u = (time.monotonic() % 1.6) / 1.6
            u = u * u * (3 - 2 * u)                      # ease in and out of each sweep
            w = r.width() * 0.35
            x = -w + (r.width() + w) * u
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0.0, QColor(127, 220, 255, 0))
            g.setColorAt(0.5, QColor(127, 220, 255, 170))
            g.setColorAt(1.0, QColor(127, 220, 255, 0))
            p.setBrush(g)
            p.drawRoundedRect(r, 3, 3)
        else:
            p.setBrush(QColor("#0a84ff"))
            p.drawRoundedRect(QRectF(0, 0, max(6.0, r.width() * self.frac), r.height()), 3, 3)


class MiniStatus(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(360, 104)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 12, 12, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.lbl_name = QLabel("")
        self.lbl_name.setFont(font(10, QFont.Weight.Bold))
        self.lbl_name.setStyleSheet("color: white;")
        top.addWidget(self.lbl_name, 1)
        self.lbl_time = QLabel("")
        self.lbl_time.setStyleSheet("color: rgba(255,255,255,170);")
        top.addWidget(self.lbl_time)
        self.btn_pause = GlassButton("", icon="pause", small=True, tip="Pause / resume")
        self.btn_pause.clicked.connect(lambda: (self.main.all_runs()[0][0].toggle_pause()
                                                if self.main.all_runs() else None))
        self.btn_stop = GlassButton("", icon="stop", small=True, kind="record", tip="Stop")
        self.btn_stop.clicked.connect(main.stop_all)
        self.btn_open = GlassButton("", icon="arrow-up", small=True, tip="Open Clicker")
        self.btn_open.clicked.connect(main.show_from_tray)
        for b in (self.btn_pause, self.btn_stop, self.btn_open):
            top.addWidget(b)
        lay.addLayout(top)
        self.lbl_step = QLabel("")
        self.lbl_step.setStyleSheet("color: rgba(255,255,255,210);")
        lay.addWidget(self.lbl_step)
        self.bar = _Bar()
        lay.addWidget(self.bar)
        self.timer = QTimer(self)
        self.timer.setInterval(16)  # the bar moves every frame; the text only changes a few times a second
        self.timer.timeout.connect(self._frame)
        self._frames = 0
        self._drag = None
        self._started = None
        self._leaving = False

    # ------------------------------------------------------------ show / hide

    def wanted(self):
        mode = self.main.settings.get("mini_status", "hidden")
        if mode == "never" or not self.main.all_runs():
            return False
        if mode == "always":
            return True
        return self.main.isHidden() or self.main.isMinimized()

    def sync(self):
        if self.wanted():
            if not self.isVisible() or self._leaving:
                if not self.isVisible():
                    self._place()
                glass.fade_in(self, glass.BASE, start=self.windowOpacity() if self._leaving else 0.0)
                self._leaving = False
                self._started = self._started or time.monotonic()
                self.show()
                self.timer.start()
            self.tick()
        elif self.isVisible() and not self._leaving:
            self._leaving = True
            glass.animate(self, self.windowOpacity(), 0.0, glass.FAST, lambda v: self.setWindowOpacity(float(v)),
                          curve=glass.EXIT, attr="_fade", done=self._gone)
        if not self.main.all_runs():
            self._started = None

    def _gone(self):
        self._leaving = False
        self.hide()
        self.timer.stop()

    def _place(self):
        pos = self.main.settings.get("mini_status_pos")
        scr = self.main.screen().availableGeometry() if self.main.screen() else None
        if pos and scr and scr.contains(QPoint(*pos)):
            self.move(*pos)
        elif scr:
            self.move(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)

    # ------------------------------------------------------------ content

    def _frame(self):
        self._frames += 1
        if self._frames % 6 == 0:
            self.tick()
        else:
            self._update_bar()

    def _update_bar(self):
        tab = self.main.action_tab
        frac = None
        if self.main.job_owner is tab and tab.progress:
            pr = tab.progress
            frac = min(1.0, tab.progress_elapsed() / pr["duration"]) if pr["duration"] > 0 else None
        self.bar.frac = frac
        self.bar.update()

    def tick(self):
        runs = self.main.all_runs()
        if not runs:
            return
        job = runs[0][0]
        script = getattr(job, "script", None)
        name = script.get("name") if isinstance(script, dict) else None
        self.lbl_name.setText(name or getattr(job, "label", "Playback"))
        started = getattr(job, "started_at", None)
        secs = int(time.time() - started) if started else int(time.monotonic() - (self._started or time.monotonic()))
        self.lbl_time.setText(f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}" if secs >= 3600
                              else f"{secs // 60}:{secs % 60:02d}")
        paused = job.paused
        self.btn_pause.icon_name = "play" if paused else "pause"
        self.btn_pause.update()
        cur = getattr(job, "current", None)
        text = getattr(job, "status", "Running")
        if cur is not None and isinstance(script, dict) and 0 <= cur < len(script["steps"]):
            st = script["steps"][cur]
            text = f"Step {cur + 1} of {len(script['steps'])} · {st['action']}"
            if getattr(job, "run_number", 0) and getattr(job, "repeat", 1) != 1:
                text += f" · pass {job.run_number}" + (f"/{job.repeat}" if job.repeat else "")
        if paused:
            text = "Paused · " + text
        if len(runs) > 1:
            text += f"   (+{len(runs) - 1} more running)"
        self.lbl_step.setText(text)
        self._update_bar()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 22, 22)
        p.fillPath(path, QColor(24, 18, 60, 225))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        p.drawPath(path)

    # ------------------------------------------------------------ drag to move

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            self.main.settings["mini_status_pos"] = [self.x(), self.y()]
            self.main.save_settings()

    def mouseDoubleClickEvent(self, _e):
        self.main.show_from_tray()
