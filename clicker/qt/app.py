"""The Liquid Glass window (Qt). Same engine, scripts, hotkeys and settings as Classic."""

import datetime
import json
import os
import queue
import sys
import threading
import traceback
import webbrowser

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import model, storage, updates, vision
from ..core import CursorSampler, Ctx, coalesce
from ..hotkeys import HotkeyManager
from ..triggers import TriggerEngine
from . import glass
from .glass import Backdrop, Mode, font, icon_pixmap, paint_glass, window_origin
from .widgets import GlassButton, SegmentedTabs, apply_style

TABS = [("actions", "Action Script"), ("recorder", "Macro Recorder"), ("triggers", "Screen Triggers"),
        ("import", "Import Script")]
AUTOSAVE_MS = 60_000


class Surface(QWidget):
    """The window's content area: paints the sharp wallpaper that the glass frosts."""

    def paintEvent(self, _e):
        bd = self.window().backdrop
        p = QPainter(self)
        if bd.sharp is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(self.rect(), bd.sharp)
        p.end()


class StatusPill(QWidget):
    """The bottom status bar as a slim glass capsule."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.window()
        paint_glass(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), (self.height() - 2) / 2, w.backdrop,
                    window_origin(self), w.mode, light=0.6, shadow=False)
        p.end()


class Toast(QWidget):
    """A glass notice that slides up in the corner of the screen."""

    def __init__(self, main):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        self.title = QLabel()
        self.title.setFont(font(10.5, QFont.Weight.DemiBold))
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setMaximumWidth(340)
        self.body.setProperty("role", "detail")
        lay.addWidget(self.title)
        lay.addWidget(self.body)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_animated)
        self._shot = None
        self.accent = None

    def show_msg(self, title, message, ms=5000, accent=None):
        self.accent = accent
        self.title.setText(title)
        self.body.setText(message or "")
        self.body.setVisible(bool(message))
        self.adjustSize()
        scr = QApplication.primaryScreen().availableGeometry()
        end = QPoint(scr.right() - self.width() - 24, scr.bottom() - self.height() - 24)
        # real glass: frost whatever is on screen behind the notice
        try:
            grab = QApplication.primaryScreen().grabWindow(0, end.x(), end.y(), self.width(), self.height())
            self._shot = glass.np_to_pixmap(_blur_pixmap(grab))
        except Exception:
            self._shot = None
        self.move(end + QPoint(0, 18))
        self.setWindowOpacity(0.0)
        self.show()
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(260 if glass.motion_on() else 0)
        a.setStartValue(end + QPoint(0, 18))
        a.setEndValue(end)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.start()
        glass.animate(self, 0.0, 1.0, 220, lambda v: self.setWindowOpacity(float(v)), attr="_fade")
        self._slide = a
        self._timer.start(ms) if ms else self._timer.stop()

    def hide_animated(self):
        glass.animate(self, self.windowOpacity(), 0.0, 180, lambda v: self.setWindowOpacity(float(v)),
                      done=self.hide, attr="_fade")

    def mousePressEvent(self, _e):
        self.hide_animated()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = glass.rounded(r, 22)
        if self._shot is not None:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(r, self._shot, QRectF(self._shot.rect()))
            p.restore()
        m = self.main.mode
        paint_glass(p, r, 22, None, QPoint(0, 0), m, light=0.8, shadow=False,
                    tint=QColor(20, 22, 36, 170) if m.dark else QColor(255, 255, 255, 200))
        if self.accent:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.accent))
            p.drawRoundedRect(QRectF(9, 16, 4, r.height() - 30), 2, 2)
        p.end()


def _blur_pixmap(pm):
    import cv2
    import numpy as np
    img = pm.toImage().convertToFormat(pm.toImage().Format.Format_RGB888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    arr = arr[:, :w * 3].reshape(h, w, 3).copy()
    return cv2.GaussianBlur(arr, (0, 0), 14)


class Highlight(QWidget):
    """One reusable outline that marks where a match was found."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._t = QTimer(self)
        self._t.setSingleShot(True)
        self._t.timeout.connect(self.hide)

    def flash(self, rect, ms=700):
        x, y, w, h = (int(v) for v in rect)
        self.setGeometry(QRect(x - 5, y - 5, w + 10, h + 10))
        self.show()
        self.update()
        self._t.start(ms)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(glass.ACCENT))
        pen = p.pen()
        pen.setWidthF(3)
        p.setPen(pen)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 8, 8)
        p.end()


class GlassApp(QMainWindow):
    def __init__(self):
        super().__init__()
        sys.setswitchinterval(0.001)  # see the Classic app: keeps the window smooth during busy scripts
        self.settings = storage.load_settings()
        glass.set_motion(not self.settings.get("reduce_motion", False))
        self.wallpaper = self.settings.get("wallpaper", "aurora")
        self.mode = Mode(glass.WALLPAPER_DARK.get(self.wallpaper, True)
                         if not self.settings.get("wallpaper_image") else self.settings.get("glass_dark", True))
        self.backdrop = Backdrop(self.wallpaper, self.settings.get("wallpaper_image"))
        self.backdrop.changed.connect(self._repaint_all)
        apply_style(QApplication.instance(), self.mode)

        self.q = queue.Queue()
        self.last_inputs = {}
        self.job = None
        self.job_owner = None
        self._held_job = None
        self.last_log_dir = None
        self.update_info = None
        self.current_tab = "actions"
        self.hotkey_displays = {}
        self.capture_action = None
        self.toast = Toast(self)
        self.highlight = Highlight()
        self._install_error_handlers()

        try:
            self.rules, self.trigger_assets = storage.load_triggers(storage.triggers_path())
        except Exception:
            self.rules, self.trigger_assets = [], storage.AssetStore()
        self.triggers = TriggerEngine(lambda: list(self.rules), self.trigger_assets, self.emitter("trigger"),
                                      Ctx(self))
        self.hotkeys = HotkeyManager(lambda kind, payload: self.post("hotkey", kind, payload),
                                     self.settings["hotkeys"])

        self.setWindowTitle(model.APP_NAME)
        icon_path = os.path.join(glass.ASSETS, "clicker.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._build()
        self._fit()

        self.hotkeys.start()
        self.sampler = CursorSampler(self.post)
        self.sampler.start()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(30)
        QTimer.singleShot(2500, self.check_updates)
        QTimer.singleShot(700, self._offer_recovery)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(AUTOSAVE_MS)
        self.refresh_states()

    # ------------------------------------------------------------ layout

    def _build(self):
        from .tab_actions import ActionTab
        from .tab_placeholder import PlaceholderTab
        surface = Surface()
        self.setCentralWidget(surface)
        outer = QVBoxLayout(surface)
        outer.setContentsMargins(22, 16, 22, 14)
        outer.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icon_pixmap("cursor-click", self.mode.text, 22, self.devicePixelRatioF()))
        name = QLabel(model.APP_NAME)
        name.setFont(font(13, QFont.Weight.Bold))
        top.addWidget(logo)
        top.addWidget(name)
        top.addStretch(1)
        self.tabbar = SegmentedTabs(TABS)
        self.tabbar.changed.connect(self.show_tab)
        top.addWidget(self.tabbar)
        top.addStretch(1)
        self.lbl_file = QLabel("")
        self.lbl_file.setProperty("role", "detail")
        top.addWidget(self.lbl_file)
        self.btn_update = GlassButton("", icon="download-simple", kind="primary", small=True)
        self.btn_update.clicked.connect(self.open_update)
        self.btn_update.hide()
        top.addWidget(self.btn_update)
        self.btn_style = GlassButton("", icon="drop", tip="Style and wallpaper")
        self.btn_style.clicked.connect(self.show_style_menu)
        top.addWidget(self.btn_style)
        self.btn_settings = GlassButton("", icon="gear", tip="Settings")
        self.btn_settings.clicked.connect(self.show_settings)
        top.addWidget(self.btn_settings)
        outer.addLayout(top)

        self.stack = QStackedWidget()
        self.action_tab = ActionTab(self)
        self.tabs = {"actions": self.action_tab}
        for key, text in TABS[1:]:
            self.tabs[key] = PlaceholderTab(self, text)
        self.pages = {}
        for key, _ in TABS:
            # each tab scrolls when the window is shorter than its content (small or scaled screens)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
            area.viewport().setAutoFillBackground(False)
            area.setWidget(self.tabs[key])
            area.verticalScrollBar().valueChanged.connect(lambda _v, a=area: a.widget().update())
            self.pages[key] = area
            self.stack.addWidget(area)
        outer.addWidget(self.stack, 1)

        self.status = StatusPill()
        self.status.setFixedHeight(38)
        sl = QHBoxLayout(self.status)
        sl.setContentsMargins(18, 0, 18, 0)
        sl.setSpacing(14)
        self.lbl_cursor = QLabel("")
        self.lbl_cursor.setFont(font(9.5))
        self.lbl_cursor.setMinimumWidth(150)
        self.swatch = QLabel()
        self.swatch.setFixedSize(12, 12)
        self.lbl_pixel = QLabel("")
        self.lbl_pixel.setMinimumWidth(70)
        self.lbl_pixel.setProperty("role", "detail")
        try:
            info = vision.display_info()
            scr = QLabel(f"Screen {info['width']} x {info['height']} at {info['scale']}%")
        except Exception:
            scr = QLabel("")
        scr.setProperty("role", "detail")
        self.lbl_msg = QLabel("")
        self.lbl_msg.setProperty("role", "detail")
        self.lbl_trig = QLabel("")
        self.lbl_trig.setProperty("role", "detail")
        self.lbl_state = QLabel("Ready")
        self.lbl_state.setFont(font(10, QFont.Weight.DemiBold))
        for w in (self.lbl_cursor, self.swatch, self.lbl_pixel, scr):
            sl.addWidget(w)
        sl.addStretch(1)
        for w in (self.lbl_msg, self.lbl_trig, self.lbl_state):
            sl.addWidget(w)
        outer.addWidget(self.status)
        self.tabbar.select("actions", animate_it=False)
        self.update_title()

    def _fit(self):
        """Open as large as the content likes, within the screen; smaller windows scroll."""
        want = self.action_tab.sizeHint()
        scr = QApplication.primaryScreen().availableGeometry()
        w = min(max(1360, want.width() + 60), scr.width() - 40)
        h = min(max(900, want.height() + 150), scr.height() - 40)
        self.setMinimumSize(min(1000, scr.width() - 40), min(560, scr.height() - 40))
        self.resize(w, h)

    def resizeEvent(self, e):
        self.backdrop.resize(self.centralWidget().size() if self.centralWidget() else e.size())
        super().resizeEvent(e)

    def _repaint_all(self):
        self.centralWidget().update()
        for w in self.centralWidget().findChildren(QWidget):
            w.update()

    def show_tab(self, key):
        if key not in self.tabs:
            return
        old = self.current_tab
        self.current_tab = key
        self.tabbar.select(key)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if glass.motion_on() and old != key:
            eff = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(eff)
            glass.animate(page, 0.0, 1.0, 220, lambda v: eff.setOpacity(float(v)), attr="_fade",
                          done=lambda: page.setGraphicsEffect(None))
        self.update_title()

    def update_title(self):
        t = getattr(self, "tabs", {}).get(self.current_tab)
        text = t.title_text() if t is not None else ""
        self.lbl_file.setText(text)
        self.setWindowTitle(f"{model.APP_NAME}  |  {text}")

    def set_status(self, msg, error=False):
        self.lbl_msg.setText(msg)
        self.lbl_msg.setProperty("role", "error" if error else "detail")
        self.lbl_msg.style().unpolish(self.lbl_msg)
        self.lbl_msg.style().polish(self.lbl_msg)
        QTimer.singleShot(6000, lambda m=msg: self.lbl_msg.text() == m and self.lbl_msg.setText(""))

    # ------------------------------------------------------------ style

    def show_style_menu(self):
        m = QMenu(self)
        grp = QActionGroup(m)
        cur = "image" if self.settings.get("wallpaper_image") else self.wallpaper
        for key, text, _dark in glass.WALLPAPERS:
            act = QAction(text, m, checkable=True, checked=(key == cur))
            act.triggered.connect(lambda _=False, k=key: self.set_wallpaper(k))
            grp.addAction(act)
            m.addAction(act)
        act = QAction("Your own picture...", m, checkable=True, checked=(cur == "image"))
        act.triggered.connect(self.pick_wallpaper_image)
        grp.addAction(act)
        m.addAction(act)
        m.addSeparator()
        if self.settings.get("wallpaper_image"):
            dark = QAction("Dark glass", m, checkable=True, checked=self.mode.dark)
            dark.triggered.connect(lambda on: self.set_glass_dark(on))
            m.addAction(dark)
        motion = QAction("Reduce motion", m, checkable=True, checked=not glass.motion_on())
        motion.triggered.connect(self.set_reduce_motion)
        m.addAction(motion)
        m.addSeparator()
        classic = QAction("Switch to Classic look", m)
        classic.triggered.connect(self.switch_to_classic)
        m.addAction(classic)
        m.exec(self.btn_style.mapToGlobal(QPoint(0, self.btn_style.height() + 6)))

    def _apply_mode(self, dark):
        self.mode = Mode(dark)
        apply_style(QApplication.instance(), self.mode)
        self._repaint_all()
        self.action_tab.restyle()

    def set_wallpaper(self, key):
        self.wallpaper = key
        self.settings["wallpaper"] = key
        self.settings.pop("wallpaper_image", None)
        self.save_settings()
        self.backdrop.set_scene(key)
        self._apply_mode(glass.WALLPAPER_DARK.get(key, True))

    def pick_wallpaper_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a wallpaper", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        self.settings["wallpaper_image"] = path
        self.save_settings()
        self.backdrop.set_scene(self.wallpaper, path)
        self._apply_mode(self.settings.get("glass_dark", True))

    def set_glass_dark(self, on):
        self.settings["glass_dark"] = bool(on)
        self.save_settings()
        self._apply_mode(bool(on))

    def set_reduce_motion(self, on):
        glass.set_motion(not on)
        self.settings["reduce_motion"] = bool(on)
        self.save_settings()

    def switch_to_classic(self):
        if QMessageBox.question(self, "Switch to Classic",
                                "Restart Clicker with the Classic look? Unsaved work will be offered back.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.settings["ui"] = "classic"
        self.save_settings()
        self._autosave(force=True)
        self._restart = True
        self.close()

    # ------------------------------------------------------------ jobs

    def post(self, source, kind, payload):
        self.q.put((source, kind, payload))

    def emitter(self, source):
        return lambda kind, payload=None: self.q.put((source, kind, payload))

    def job_running(self):
        return self.job is not None and self.job.running

    def job_running_for(self, owner):
        return self.job_running() and self.job_owner is owner

    def recording_active(self):
        rt = self.tabs.get("recorder")
        rec = getattr(rt, "recorder", None)
        return bool(rec and rec.active)

    def start_job(self, job, owner, hide=False):
        if self.job_running() or self.recording_active():
            self.set_status("Something is already running.", error=True)
            return False
        self.job, self.job_owner = job, owner
        self.triggers.reset_counts()
        job.start()
        if hide:
            self._hid = True
            self.showMinimized()
        self.refresh_states()
        return True

    def stop_job(self):
        if self.job_running():
            self.job.stop()

    def toggle_pause(self):
        if self.job_running():
            self.job.toggle_pause()
            self.refresh_states()

    def stop_all(self):
        self.stop_job()
        if self.triggers.running:
            self.triggers.stop()
        self.toast.show_msg("Stopped", "Everything was stopped.", 2500, accent=glass.RED)
        self.refresh_states()

    def refresh_states(self):
        running = self.job_running()
        paused = running and self.job.paused
        for t in self.tabs.values():
            t.update_state(running and self.job_owner is t, running, paused)
        if running:
            state = "Paused" if paused else getattr(self.job, "status", "Running")
        else:
            state = "Ready"
        self.lbl_state.setText(state)
        n = sum(1 for r in self.rules if r.get("enabled"))
        self.lbl_trig.setText(f"Monitoring {n} rule{'s' if n != 1 else ''}" if self.triggers.running
                              else "Monitoring off")

    def _poll(self):
        batch = []
        try:
            for _ in range(2000):
                batch.append(self.q.get_nowait())
        except queue.Empty:
            pass
        for source, kind, payload in coalesce(batch):
            try:
                self._dispatch(source, kind, payload)
            except Exception:
                self._report_error(*sys.exc_info())
        sig = (self.job_running(), self.job.paused if self.job else None, self.triggers.running)
        if batch or sig != getattr(self, "_sig", None):
            self._sig = sig
            self.refresh_states()

    def _dispatch(self, source, kind, payload):
        if source == "hotkey":
            if kind == "hotkey_captured":
                action, self.capture_action = self.capture_action, None
                if action:
                    self.set_hotkey(action, payload)
            elif kind == "hotkey":
                self._on_hotkey(payload)
            return
        if source == "app":
            if kind == "cursor":
                x, y, hexc = payload
                self.lbl_cursor.setText(f"X {x:>5}   Y {y:>5}")
                self.swatch.setStyleSheet(f"background:{hexc}; border-radius:6px; border:1px solid rgba(255,255,255,90);")
                self.lbl_pixel.setText(hexc)
            elif kind == "update":
                self._on_update_result(payload)
            elif kind == "stop_all":
                self.stop_all()
            elif kind == "run_script":
                self.set_status("Trigger rules that run scripts work in the Classic look for now.")
            return
        if kind == "notify":
            self.toast.show_msg("Clicker", str(payload))
            return
        if kind == "highlight":
            self.highlight.flash(payload)
            return
        if source == "trigger":
            return
        owner = self.job_owner
        if kind == "state" and self.job:
            self.job.status = "Running" if payload == "running" else ("Paused" if payload == "paused" else str(payload))
        elif kind == "run" and self.job:
            self.job.status = f"Running, pass {payload}"
        elif kind == "step" and self.job:
            self.job.status = f"Running step {payload + 1}"
        elif kind == "log":
            self.set_status(str(payload))
        elif kind == "logfile":
            self.last_log_dir = payload
        elif kind == "done":
            ok, reason = payload
            if getattr(self, "_hid", False):
                self._hid = False
                self.showNormal()
                self.activateWindow()
            if ok:
                self.set_status("Finished")
            else:
                self.set_status(reason, error=not reason.startswith("Stop"))
                if not reason.startswith("Stop"):
                    more = " The run log and a screenshot are in Run Logs." if self.last_log_dir else ""
                    self.toast.show_msg("Script stopped", reason + more, 9000, accent=glass.RED)
        if owner is not None and hasattr(owner, "on_job"):
            owner.on_job(kind, payload)

    # ------------------------------------------------------------ hotkeys

    HOTKEY_NAMES = {
        "add_action": "Add action at cursor", "script_toggle": "Start / stop script",
        "emergency": "Emergency stop", "rec_toggle": "Start / stop recording",
        "play_toggle": "Start / stop playback", "pause": "Pause / resume",
    }

    def _on_hotkey(self, action):
        if action == "emergency":
            self.stop_all()
        elif action == "pause":
            self.toggle_pause()
        elif action == "add_action":
            self.action_tab.add_at_cursor()
        elif action == "script_toggle":
            self.action_tab.toggle_run(from_hotkey=True)

    def begin_assign(self, action):
        self.capture_action = action
        self.hotkeys.capture_next()
        self.refresh_hotkey_displays()
        self.set_status(f"Press the new key for '{self.HOTKEY_NAMES[action]}' (Esc to clear)")

    def set_hotkey(self, action, label_text):
        if label_text:
            for other, val in self.settings["hotkeys"].items():
                if other != action and val and val.lower() == label_text.lower():
                    self.settings["hotkeys"][other] = ""
        self.settings["hotkeys"][action] = label_text
        self.hotkeys.bindings = dict(self.settings["hotkeys"])
        self.save_settings()
        self.refresh_hotkey_displays()

    def refresh_hotkey_displays(self):
        for action, fields in self.hotkey_displays.items():
            val = self.settings["hotkeys"].get(action) or "None"
            if self.capture_action == action:
                val = "Press keys..."
            for f in fields:
                f.setText(val)

    # ------------------------------------------------------------ settings and updates

    def save_settings(self):
        try:
            storage.save_settings(self.settings)
        except Exception:
            pass

    def show_settings(self):
        from .dialogs import SettingsDialog
        SettingsDialog(self).exec()

    def check_updates(self, force=False):
        if getattr(self, "_closed", False):
            return
        updates.check_async(self.settings, lambda r: self.post("app", "update", dict(r, force=force)), force=force)

    def _on_update_result(self, r):
        self.save_settings()
        if r.get("error"):
            if r.get("force"):
                self.set_status(f"Could not check for updates: {r['error']}", error=True)
            return
        if r.get("newer"):
            self.update_info = r
            self.btn_update.setText(f"Update {r['tag']}")
            self.btn_update.show()
            if r.get("force"):
                self.open_update()
        elif r.get("force"):
            self.set_status(f"Clicker {model.APP_VERSION} is up to date.")

    def open_update(self):
        r = self.update_info
        if r and QMessageBox.question(self, "Update available",
                                      f"Clicker {r['tag']} is available (you have {model.APP_VERSION}).\n\n"
                                      "Open the download page?") == QMessageBox.StandardButton.Yes:
            webbrowser.open(r["url"])

    # ------------------------------------------------------------ errors and recovery

    def _install_error_handlers(self):
        self._prev_hook = sys.excepthook

        def hook(exc, val, tb):
            self._report_error(exc, val, tb)
        sys.excepthook = hook
        try:
            import faulthandler
            self._fault_file = open(os.path.join(storage.data_dir(), "crash.log"), "a")
            faulthandler.enable(self._fault_file)
        except Exception:
            pass

    def _report_error(self, exc, val, tb):
        try:
            with open(os.path.join(storage.data_dir(), "errors.log"), "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} (Qt, Clicker {model.APP_VERSION})\n")
                f.write("".join(traceback.format_exception(exc, val, tb)) + "\n")
        except Exception:
            pass
        traceback.print_exception(exc, val, tb)
        try:
            self.set_status(f"Something went wrong ({val}). Details were saved to errors.log.", error=True)
        except Exception:
            pass

    def _autosave_paths(self):
        d = storage.data_dir()
        return os.path.join(d, "autosave.clk"), os.path.join(d, "autosave.json")

    def _autosave(self, force=False):
        a = self.action_tab
        if not (a.dirty and a.script["steps"]):
            return
        a.sync_settings()
        script, assets = model.copy_script(a.script), a.assets.copy()
        clk, meta = self._autosave_paths()
        info = {"path": a.path, "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "steps": len(script["steps"])}

        def work():
            try:
                storage.save_script(clk, script, assets)
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump(info, f)
            except Exception:
                pass
        if force:
            work()
        else:
            threading.Thread(target=work, daemon=True, name="autosave").start()

    def _clear_autosave(self):
        for p in self._autosave_paths():
            try:
                os.remove(p)
            except OSError:
                pass

    def _offer_recovery(self):
        if getattr(self, "_closed", False):
            return  # a window that already closed must not take the autosave meant for the next one
        clk, meta = self._autosave_paths()
        if not os.path.exists(clk):
            return
        try:
            with open(meta, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        name = os.path.basename(info.get("path") or "") or "an unsaved script"
        when = str(info.get("time", "")).replace("T", " ")
        if QMessageBox.question(self, "Recover unsaved work?",
                                f"Clicker closed without saving {name} ({info.get('steps', '?')} steps, last "
                                f"autosaved {when or 'recently'}).\n\nOpen the recovered copy?") \
                == QMessageBox.StandardButton.Yes:
            try:
                script, assets = storage.load_script(clk)
                self.action_tab.set_script(script, assets, None)
                self.action_tab.dirty = True
                self.update_title()
                self.set_status("Recovered your unsaved script. Save it to keep it.")
            except Exception as e:
                self.set_status(f"Could not recover the script: {e}", error=True)
        self._clear_autosave()

    def closeEvent(self, e):
        if not getattr(self, "_restart", False) and not self.action_tab.confirm_discard("closing"):
            e.ignore()
            return
        self._closed = True
        self._poll_timer.stop()
        self._autosave_timer.stop()
        self.stop_job()
        self.triggers.stop()
        self.hotkeys.stop()
        self.sampler.stop()
        self.toast.close()
        self.highlight.close()
        if not getattr(self, "_restart", False):
            self._clear_autosave()
        self.save_settings()
        e.accept()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(model.APP_NAME)
    glass.load_fonts()
    win = GlassApp()
    win.show()
    code = app.exec()
    if getattr(win, "_restart", False):
        from ..app import main as classic_main
        classic_main()
    return code

