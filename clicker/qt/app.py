"""The Clicker window (Qt, Liquid Glass look)."""

import datetime
import json
import os
import queue
import sys
import threading
import traceback
import webbrowser

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QRegion
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from .. import alerts, clipboard, model, storage, updates, vision
from . import motion, scripthotkeys
from ..core import PROGRESS_ONLY, CursorSampler, Ctx, coalesce
from ..hotkeys import HotkeyManager
from ..triggers import TriggerEngine
from . import glass
from .glass import Backdrop, Mode, font, icon_pixmap, paint_glass
from .widgets import GlassButton, SegmentedTabs, apply_style

TABS = [("actions", "Action Script"), ("recorder", "Macro Recorder"), ("triggers", "Screen Triggers"),
        ("import", "Import Script"), ("history", "History")]
AUTOSAVE_MS = 60_000


def _quiet(fn, *a):
    try:
        fn(*a)
    except Exception:
        pass


class QtClipboard:
    """Clipboard access for script steps: done on the interface thread, which Qt requires."""

    def __init__(self, win):
        self.win = win

    def _call(self, op, text=None):
        if threading.current_thread() is threading.main_thread():
            cb = QApplication.clipboard()
            return cb.setText(text) if op == "set" else cb.text()
        box, done = [], threading.Event()
        self.win.post("app", "clip", (op, text, box, done))
        if not done.wait(3.0):
            raise RuntimeError("the window did not answer")
        if box and isinstance(box[0], Exception):
            raise box[0]
        return box[0] if box else None

    def get(self):
        return self._call("get") or ""

    def set(self, text):
        self._call("set", text)


class Surface(QWidget):
    """The window's content area: paints the sharp wallpaper that the glass frosts."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)  # the wallpaper covers every pixel

    def paintEvent(self, _e):
        win = self.window()
        p = QPainter(self)
        win.backdrop.draw(p, QRectF(_e.rect()), QRectF(_e.rect()), smooth=not getattr(win, "live_resize", False))
        p.end()


class StatusPill(glass.GlassPanel):
    """The bottom status bar as a slim glass capsule."""

    def __init__(self):
        super().__init__(light=0.6)

    def glass_radius(self):
        return (self.height() - 2) / 2


_swatches = {}


def swatch_pixmap(hexc, dpr):
    """A small round color chip (cached; restyling a label with a style sheet 8 times a second is slow)."""
    pm = _swatches.get((hexc, dpr))
    if pm is None:
        pm = glass.clear_pixmap(12, 12, dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(255, 255, 255, 110))
        p.setBrush(QColor(hexc))
        p.drawEllipse(QRectF(0.5, 0.5, 11, 11))
        p.end()
        if len(_swatches) > 512:
            _swatches.clear()
        _swatches[(hexc, dpr)] = pm
    return pm


class PageTransition(QWidget):
    """Slides between tabs the way the tab bar reads: the new page comes in from the side of its tab.

    Only the page contents move; the wallpaper stays put. Both pages are snapshots with a transparent
    background, so each frame is the wallpaper plus two image copies.
    """

    DURATION = glass.SLOW  # the same time and curve as the tab bar's lens, so both arrive together
    SHIFT = 56

    def __init__(self, parent, rect, main, old_pm, direction):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # The wallpaper and snapshots cover every pixel, so Qt must not repaint the live page underneath.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(rect)
        self.main = main
        self.old_pm, self.new_pm, self.t, self.dir = old_pm, None, 0.0, direction
        self.show()
        self.raise_()

    def start(self, new_pm):
        self.new_pm = new_pm
        glass.animate(self, 0.0, 1.0, self.DURATION, self._step, done=self.finish, attr="_anim")

    def _step(self, v):
        self.t = float(v)
        self.update()

    def finish(self):
        """End the transition (safe to call more than once)."""
        if getattr(self, "_done", False):
            return
        self._done = True
        a, self._anim = getattr(self, "_anim", None), None
        if a is not None:
            try:
                a.stop()
            except RuntimeError:
                pass  # the animation already finished and was cleaned up
        self.hide()
        self.deleteLater()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect())
        self.main.backdrop.draw(p, r, QRectF(self.geometry()), smooth=False)
        t, d = self.t, self.dir * self.SHIFT
        p.setOpacity(max(0.0, 1.0 - t * 1.6))           # the old page is gone a little before the move ends
        p.drawPixmap(QPointF(-d * t, 0), self.old_pm)
        if self.new_pm is not None:
            p.setOpacity(min(1.0, t * 1.4))
            p.drawPixmap(QPointF(d * (1 - t), 0), self.new_pm)
        p.end()


class FadeAway(QWidget):
    """A snapshot of how the window looked, fading out over the new look (appearance changes)."""

    def __init__(self, parent, pm):
        super().__init__(parent)
        self.pm, self.t = pm, 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        glass.animate(self, 1.0, 0.0, glass.SLOW, self._step, curve=glass.GLIDE, done=self.deleteLater)

    def _step(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setOpacity(self.t)
        p.drawPixmap(0, 0, self.pm)
        p.end()


def page_snapshot(area):
    """The page's contents on a transparent background (no wallpaper), for sliding transitions."""
    dpr = area.devicePixelRatioF()
    pm = glass.clear_pixmap(area.width(), area.height(), dpr)
    area.render(pm, QPoint(0, 0), QRegion(area.rect()), QWidget.RenderFlag.DrawChildren)
    return pm


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
        if self.isVisible() and self.windowOpacity() > 0.5:
            self.move(end)  # a notice replacing one still showing: just change the words, no flicker
            glass.fade_in(self, glass.FAST, start=self.windowOpacity())
        else:
            self.move(end + QPoint(0, 18))
            self.setWindowOpacity(0.0)
            self.show()
            glass.animate(self, 18.0, 0.0, glass.BASE, lambda v: self.move(end + QPoint(0, round(v))),
                          attr="_slide")
            glass.fade_in(self, glass.BASE)
        self._timer.start(ms) if ms else self._timer.stop()

    def hide_animated(self):
        glass.animate(self, self.windowOpacity(), 0.0, glass.FAST, lambda v: self.setWindowOpacity(float(v)),
                      curve=glass.EXIT, done=self.hide, attr="_fade")

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
        self._t.timeout.connect(lambda: glass.animate(self, 1.0, 0.0, glass.BASE,
                                                      lambda v: self.setWindowOpacity(float(v)),
                                                      curve=glass.EXIT, attr="_fade", done=self.hide))

    def flash(self, rect, ms=700):
        x, y, w, h = (int(v) for v in rect)
        self.setGeometry(QRect(x - 5, y - 5, w + 10, h + 10))
        a = getattr(self, "_fade", None)
        if a is not None:
            a.stop()
        self.setWindowOpacity(1.0)
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
        sys.setswitchinterval(0.001)  # short thread slices keep the window smooth during busy scripts
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
        self.triggers = TriggerEngine(self.get_rules, self.trigger_assets, self.emitter("trigger"), Ctx(self),
                                      get_target=lambda: self.settings.get("triggers_target"))
        self.hotkeys = HotkeyManager(lambda kind, payload: self.post("hotkey", kind, payload),
                                     self.settings["hotkeys"], scripthotkeys.bindings(self.settings))
        self.script_hotkey_dialog = None
        self.side_jobs = {}   # scripts running alongside the main run: id -> {job, name}
        self._side_seq = 0
        from .ministatus import MiniStatus
        self.mini = MiniStatus(self)
        clipboard.set_backend(QtClipboard(self))
        self.tray = scripthotkeys.Tray(self)
        self._quitting = False

        self.setWindowTitle(model.APP_NAME)
        icon_path = os.path.join(glass.ASSETS, "clicker.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._build()
        self._fit()

        self.hotkeys.start()
        self.update_tray()
        from .. import schedule as sch
        self._window_watch = sch.WindowWatch()
        self._sched_timer = QTimer(self)
        self._sched_timer.setInterval(10_000)
        self._sched_timer.timeout.connect(self.check_schedule)
        self._sched_timer.start()
        self.remote_listener = None
        self.remote_state = "off"
        self.apply_remote()
        self.web = None
        self.web_state = "off"
        self.apply_web()
        self.sampler = CursorSampler(self.post)
        self.sampler.start()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(30)
        QTimer.singleShot(2500, self.check_updates)
        QTimer.singleShot(400, self._warm_pages)
        QTimer.singleShot(700, self._offer_recovery)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(AUTOSAVE_MS)
        self.refresh_states()

    # ------------------------------------------------------------ layout

    def _build(self):
        from .tab_actions import ActionTab
        from .tab_history import HistoryTab
        from .tab_import import ImportTab
        from .tab_recorder import RecorderTab
        from .tab_triggers import TriggersTab
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
        self.recorder_tab = RecorderTab(self)
        self.triggers_tab = TriggersTab(self)
        self.import_tab = ImportTab(self)
        self.history_tab = HistoryTab(self)
        self.tabs = {"actions": self.action_tab, "recorder": self.recorder_tab,
                     "triggers": self.triggers_tab, "import": self.import_tab, "history": self.history_tab}
        self.pages = {}
        for key, _ in TABS:
            # each tab scrolls when the window is shorter than its content (small or scaled screens)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            # never crop: the window keeps its minimum width, and only a screen too small for that scrolls
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        self.btn_runs = GlassButton("", icon="play", small=True, tip="Everything running now")
        self.btn_runs.clicked.connect(self.open_runs)
        self.btn_runs.hide()
        for w in (self.lbl_msg, self.lbl_trig, self.btn_runs, self.lbl_state):
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
        self.update_min_width()
        self.setMinimumHeight(min(560, scr.height() - 40))
        self.resize(max(w, self.minimumWidth()), h)

    def update_min_width(self):
        """The window may not get narrower than its widest tab needs, so nothing is cut off on the right."""
        if not hasattr(self, "tabs"):
            return
        need = max(t.minimumSizeHint().width() for t in self.tabs.values())
        m = self.centralWidget().layout().contentsMargins()
        need += m.left() + m.right() + 12  # room for a vertical scroll bar
        scr = QApplication.primaryScreen().availableGeometry()
        self.setMinimumWidth(min(need, scr.width() - 40))

    def resizeEvent(self, e):
        if self.isVisible() and self.backdrop.base_sharp is not None:
            self.live_resize = True  # panels draw lighter glass until the size settles
        self.backdrop.resize(self.centralWidget().size() if self.centralWidget() else e.size())
        super().resizeEvent(e)

    def _repaint_all(self):
        self.live_resize = False
        self.centralWidget().update()
        for w in self.centralWidget().findChildren(QWidget):
            w.update()

    def show_tab(self, key):
        if key not in self.tabs:
            return
        old = self.current_tab
        self.current_tab = key
        if key == "history" and old != key:
            self.history_tab.reload()
        self.tabbar.select(key)
        page = self.pages[key]
        if not glass.motion_on() or old == key or not self.isVisible():
            self.stack.setCurrentWidget(page)
            self.update_title()
            return
        # Animate between two snapshots instead of the live pages: every frame is then the wallpaper and
        # two image copies, however many glass panels and controls the pages hold.
        keys = [k for k, _ in TABS]
        direction = 1 if keys.index(key) > keys.index(old) else -1
        area = self.stack.geometry()
        surface = self.centralWidget()
        old_pm = page_snapshot(self.pages[old])
        tr = getattr(self, "_transition", None)
        if tr is not None:
            try:
                tr.finish()
            except RuntimeError:
                pass  # already deleted
        tr = PageTransition(surface, area, self, old_pm, direction)
        self._transition = tr

        def swap():
            if self._transition is not tr:
                return
            self.stack.setCurrentWidget(page)
            tr.start(page_snapshot(page))
        QTimer.singleShot(0, swap)  # render the new page on the next frame, not in the same one
        self.update_title()

    def _warm_pages(self):
        """Lay out and draw every tab once, off screen, so the first visit to each isn't slower."""
        size = self.stack.size()
        for key, area in self.pages.items():
            if area is self.stack.currentWidget():
                continue
            area.resize(size)
            area.widget().adjustSize()
            area.ensurePolished()
            area.grab()

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
        m.exec(self.btn_style.mapToGlobal(QPoint(0, self.btn_style.height() + 6)))

    def _cross_fade(self, change):
        """Make an appearance change (wallpaper, light or dark glass) fade in instead of snapping."""
        surface = self.centralWidget()
        before = surface.grab() if glass.motion_on() and self.isVisible() else None
        change()
        if before is not None:
            FadeAway(surface, before)

    def _apply_mode(self, dark):
        self.mode = Mode(dark)
        apply_style(QApplication.instance(), self.mode)
        self._repaint_all()
        self.action_tab.restyle()
        self.triggers_tab.refresh_rules()
        if self.import_tab.script is not None:
            self.import_tab.refresh()

    def set_wallpaper(self, key):
        self.wallpaper = key
        self.settings["wallpaper"] = key
        self.settings.pop("wallpaper_image", None)
        self.save_settings()
        self._cross_fade(lambda: (self.backdrop.set_scene(key),
                                  self._apply_mode(glass.WALLPAPER_DARK.get(key, True))))

    def pick_wallpaper_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a wallpaper", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        self.settings["wallpaper_image"] = path
        self.save_settings()
        self._cross_fade(lambda: (self.backdrop.set_scene(self.wallpaper, path),
                                  self._apply_mode(self.settings.get("glass_dark", True))))

    def set_glass_dark(self, on):
        self.settings["glass_dark"] = bool(on)
        self.save_settings()
        self._cross_fade(lambda: self._apply_mode(bool(on)))

    def set_reduce_motion(self, on):
        glass.set_motion(not on)
        self.settings["reduce_motion"] = bool(on)
        self.save_settings()

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
        for run in list(self.side_jobs.values()):
            run["job"].stop()
        if self.recording_active():
            self.recorder_tab.stop_record(from_hotkey=True)
        if self.triggers.running:
            self.triggers.stop()
        self.toast.show_msg("Stopped", "Everything was stopped.", 2500, accent=glass.RED)
        self.refresh_states()

    def refresh_states(self):
        running = self.job_running()
        paused = running and self.job.paused
        for t in self.tabs.values():
            t.update_state(running and self.job_owner is t, running, paused)
        self._refresh_state_text()
        n_runs = len(self.all_runs())
        self.btn_runs.setVisible(n_runs > 0)
        self.btn_runs.setText(f"{n_runs} running")
        self.btn_runs.updateGeometry()
        if hasattr(self, "mini"):
            self.mini.sync()
        n = sum(1 for r in self.rules if r.get("enabled"))
        self.lbl_trig.setText(f"Monitoring {n} rule{'s' if n != 1 else ''}" if self.triggers.running
                              else "Monitoring off")

    def _refresh_state_text(self):
        running = self.job_running()
        state = ("Paused" if self.job.paused else getattr(self.job, "status", "Running")) if running else "Ready"
        if self.lbl_state.text() != state:
            self.lbl_state.setText(state)

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
        sig = (self.job_running(), self.job.paused if self.job else None, self.triggers.running,
               tuple((id(j), j.paused) for j, _m in self.all_runs()))
        # progress events arrive ~30 times a second while a script runs; relaying out every toolbar for
        # each one made the window stutter, so only real changes refresh the buttons and status bar
        if sig != getattr(self, "_sig", None) or any((src, kind) not in PROGRESS_ONLY for src, kind, _p in batch):
            self._sig = sig
            self.refresh_states()
        elif batch:
            self._refresh_state_text()

    def _dispatch(self, source, kind, payload):
        if source == "hotkey":
            if kind == "hotkey_captured":
                action, self.capture_action = self.capture_action, None
                if isinstance(action, tuple):
                    self.set_script_hotkey(action[1], payload)
                elif action:
                    self.set_hotkey(action, payload)
            elif kind == "hotkey":
                self._on_hotkey(payload)
            elif kind == "script_hotkey":
                self.run_script_hotkey(payload)
            return
        if source == "app":
            if kind == "cursor":
                x, y, hexc = payload
                self.lbl_cursor.setText(f"X {x:>5}   Y {y:>5}")
                self.swatch.setPixmap(swatch_pixmap(hexc, self.devicePixelRatioF()))
                self.lbl_pixel.setText(hexc)
            elif kind == "update":
                self._on_update_result(payload)
            elif kind == "stop_all":
                self.stop_all()
            elif kind == "run_script":
                self._run_script_from_trigger(payload)
            elif kind == "remote":
                self.handle_remote(payload)
            elif kind == "web":
                cmd, args, box, done = payload
                try:
                    box.append(self._web_command(cmd, args))
                except Exception as e:
                    box.append({"ok": False, "msg": str(e)})
                done.set()
            elif kind == "remote_state":
                self.remote_state = payload
            elif kind == "clip":
                op, text, box, done = payload
                try:
                    cb = QApplication.clipboard()
                    if op == "set":
                        cb.setText(text)
                    else:
                        box.append(cb.text())
                except Exception as e:
                    box.append(e)
                done.set()
            return
        if kind == "notify":
            self.toast.show_msg("Clicker", str(payload))
            return
        if kind == "highlight":
            self.highlight.flash(payload)
            return
        if source.startswith("side:"):
            self._side_event(source, kind, payload)
            return
        if source == "trigger":
            if kind == "log":
                rule, msg, hit = payload
                self.triggers_tab.add_log(rule, msg, hit)
                if hit:
                    alerts.notify(self.settings, alerts.trigger_event(rule, msg))
                elif "Waiting for it" in str(msg):
                    alerts.notify(self.settings, dict(alerts.trigger_event("Screen Triggers", msg), kind="window"))
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
            if self.job is not None:
                alerts.notify(self.settings, alerts.run_event(self.job, ok, reason))
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
        if kind == "done" and source == "script" and self.current_tab == "history":
            QTimer.singleShot(200, self.history_tab.reload)

    # ------------------------------------------------------------ trigger rules

    def get_rules(self):
        return list(self.rules)

    def replace_rule(self, rule):
        for i, r in enumerate(self.rules):
            if r["id"] == rule["id"]:
                self.rules[i] = rule
                break
        else:
            self.rules.append(rule)
        self.save_rules()

    def save_rules(self):
        try:
            storage.save_triggers(storage.triggers_path(), self.rules, self.trigger_assets)
        except Exception as e:
            self.set_status(f"Could not save rules: {e}", error=True)

    def toggle_monitoring(self):
        if self.triggers.running:
            self.triggers.stop()
        else:
            if not any(r.get("enabled") for r in self.rules):
                self.set_status("Turn on at least one rule first.", error=True)
                return
            self.triggers.start()
        QTimer.singleShot(100, self.refresh_states)

    def _run_script_from_trigger(self, path):
        if self.job_running():
            self.triggers_tab.add_log("Run script", "Skipped: a job is already running", False)
            return
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            self.triggers_tab.add_log("Run script", f"Could not open {path}: {e}", False)
            return
        from ..runner import Runner
        st = script.get("settings") or {}
        job = Runner(script, assets, self.emitter("script"), inputs_map=dict(self.last_inputs),
                     speed=st.get("speed", 1.0), repeat=st.get("repeat", 1),
                     random_delay_ms=st.get("random_delay_ms", 0), label=path,
                     save_log=self.settings.get("save_run_logs", True), path=path)
        self.start_job(job, self.import_tab)

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
        elif action == "rec_toggle":
            self.recorder_tab.toggle_record(from_hotkey=True)
        elif action == "play_toggle":
            self.recorder_tab.toggle_play()

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

    # ------------------------------------------------------------ script hotkeys and tray

    def open_script_hotkeys(self):
        if self.script_hotkey_dialog is not None:
            self.script_hotkey_dialog.raise_()
            return
        scripthotkeys.ScriptHotkeysDialog(self).exec()

    def begin_assign_script(self, path):
        self.capture_action = ("script", path)
        self.hotkeys.capture_next()

    def cancel_script_assign(self):
        if isinstance(self.capture_action, tuple):
            self.capture_action = None
            self.hotkeys.cancel_capture()

    def apply_script_hotkeys(self):
        self.hotkeys.script_bindings = scripthotkeys.bindings(self.settings)
        self.save_settings()
        self.update_tray()

    def set_script_hotkey(self, path, combo):
        dlg = self.script_hotkey_dialog
        if combo:
            for action, val in self.settings["hotkeys"].items():
                if val and val.lower() == combo.lower():
                    msg = f"{combo} is already '{self.HOTKEY_NAMES.get(action, action)}'. Pick other keys."
                    if dlg is not None:
                        dlg.msg.setText(msg)
                        dlg.refresh(select=path)
                    self.set_status(msg, error=True)
                    return
            if "+" not in combo and not combo.upper().startswith("F"):
                msg = f"{combo} alone would fire while you type. Add Ctrl or Alt, or use an F key."
                if dlg is not None:
                    dlg.msg.setText(msg)
                    dlg.refresh(select=path)
                return
        moved = None
        for e in self.settings.setdefault("script_hotkeys", []):
            if e.get("path") == path:
                e["keys"] = combo
            elif combo and (e.get("keys") or "").lower() == combo.lower():
                e["keys"] = ""
                moved = scripthotkeys.script_name(e["path"])
        self.apply_script_hotkeys()
        name = scripthotkeys.script_name(path)
        text = (f"{combo} now starts {name}" + (f" (taken from {moved})" if moved else "") + "."
                if combo else f"{name} has no hotkey now.")
        self.set_status(text)
        if dlg is not None:
            dlg.msg.setText(text)
            dlg.refresh(select=path)

    # ------------------------------------------------------------ runs alongside the main one

    def all_runs(self):
        """[(job, is_main_run)] for everything running now."""
        out = [(self.job, True)] if self.job_running() else []
        out += [(r["job"], False) for r in self.side_jobs.values() if r["job"].running]
        return out

    def start_side_job(self, job, name):
        from .runs import can_run_alongside
        if self.recording_active() or not can_run_alongside(job, [j for j, _m in self.all_runs()]):
            return False
        self._side_seq += 1
        sid = f"side:{self._side_seq}"
        job.emit = self.emitter(sid)
        self.side_jobs[sid] = {"job": job, "name": name}
        job.start()
        self.refresh_states()
        return True

    def _side_event(self, sid, kind, payload):
        run = self.side_jobs.get(sid)
        if run is None:
            return
        name = run["name"]
        if kind == "log":
            self.set_status(f"{name}: {payload}")
        elif kind == "done":
            ok, reason = payload
            alerts.notify(self.settings, alerts.run_event(run["job"], ok, reason))
            self.side_jobs.pop(sid, None)
            if ok:
                self.set_status(f"{name} finished")
            else:
                self.set_status(f"{name}: {reason}", error=not reason.startswith("Stop"))
                if not reason.startswith("Stop"):
                    self.toast.show_msg(f"{name} stopped", reason, 9000, accent=glass.RED)
            if self.current_tab == "history":
                QTimer.singleShot(200, self.history_tab.reload)
            self.refresh_states()

    def open_runs(self):
        from .runs import RunsPanel
        if not hasattr(self, "_runs_panel"):
            self._runs_panel = RunsPanel(self)
        self._runs_panel.open_at(self.btn_runs)

    def run_script_hotkey(self, path, from_menu=False):
        entry = next((e for e in scripthotkeys.entries(self.settings) if e["path"] == path), None)
        name = scripthotkeys.script_name(path)
        same = [j for j, _m in self.all_runs() if getattr(j, "path", None) == path]
        if same:
            if from_menu or not entry or entry.get("toggle", True):
                for j in same:
                    j.stop()
                self.set_status(f"Stopped {name}")
                self.tray.message("Clicker", f"Stopped {name}")
            else:
                self.set_status(f"{name} is already running.", error=True)
            return
        if not os.path.exists(path):
            self.set_status(f"{name}: the file is gone ({path})", error=True)
            return
        if entry and entry.get("ask") and not from_menu:
            if QMessageBox.question(self, "Start script?", f"Start {name}?") != QMessageBox.StandardButton.Yes:
                return
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            self.set_status(f"Could not open {name}: {e}", error=True)
            return
        values = {i["name"]: self.last_inputs.get(i["name"], i.get("default", "")) for i in script.get("inputs") or []}
        from ..runner import Runner
        st = script.get("settings") or {}
        job = Runner(script, assets, self.emitter("script"), inputs_map=values, speed=st.get("speed", 1.0),
                     repeat=st.get("repeat", 1), random_delay_ms=st.get("random_delay_ms", 0), label=name,
                     save_log=self.settings.get("save_run_logs", True), path=path)
        if not (self.job_running() or self.recording_active()):
            if self.start_job(job, None):
                self.set_status(f"Started {name}")
                self.tray.message("Clicker", f"Started {name}")
            return
        if self.start_side_job(job, name):
            self.set_status(f"Started {name} alongside")
            self.tray.message("Clicker", f"Started {name} alongside the running script")
        else:
            msg = (f"Can't start {name} now: it would share the real mouse and keyboard with a running script. "
                   "Give one of them a Run in window (background) to run both.")
            self.set_status(msg, error=True)
            self.tray.message("Clicker", msg)

    def apply_imported(self, settings):
        """Use settings (and the rule file) from an imported backup without restarting."""
        self.settings.clear()
        self.settings.update(storage.load_settings())
        self.settings.update(settings)
        self.save_settings()
        self.hotkeys.bindings = dict(self.settings["hotkeys"])
        self.apply_script_hotkeys()
        try:
            rules, assets = storage.load_triggers(storage.triggers_path())
        except Exception:
            rules, assets = [], storage.AssetStore()
        self.rules[:] = rules
        for n in self.trigger_assets.names():
            self.trigger_assets.remove(n)
        for n in assets.names():
            self.trigger_assets.add_bytes(n, assets.raw(n))
        self.triggers_tab.refresh_rules()
        self.history_tab.reload()
        self.import_tab._refresh_recent()

    # ------------------------------------------------------------ phone remote control

    def open_remote(self):
        from .remote_dialog import RemoteDialog
        RemoteDialog(self).exec()

    def apply_remote(self):
        from .. import remote
        if self.remote_listener is not None:
            self.remote_listener.stop()
            self.remote_listener = None
        cfg = self.settings.get("remote") or {}
        if cfg.get("enabled") and cfg.get("topic"):
            self.remote_listener = remote.Listener(
                cfg["topic"], lambda text: self.post("app", "remote", text),
                lambda st: self.post("app", "remote_state", st)).start()
            self.remote_state = "connecting"
        else:
            self.remote_state = "off"
        self.update_tray()

    def apply_web(self):
        """Start or stop the Wi-Fi dashboard to match the settings."""
        from .. import webdash
        if self.web is not None:
            self.web.stop()
            self.web = None
        cfg = self.settings.get("web") or {}
        if not (cfg.get("enabled") and len(str(cfg.get("pin") or "")) >= 4):
            self.web_state = "off"
            return
        try:
            self.web = webdash.Dashboard(int(cfg.get("port") or 8765), cfg["pin"], self.web_call).start()
            self.web_state = "on at " + ", ".join(f"http://{ip}:{self.web.port}" for ip in webdash.lan_addresses())
        except OSError as e:
            self.web_state = f"could not start ({e})"
        self.update_tray()

    def web_call(self, cmd, args):
        """From a web request thread: run a dashboard command on the window thread and wait for it."""
        box, done = [], threading.Event()
        self.post("app", "web", (cmd, args, box, done))
        if not done.wait(8.0):
            return {"ok": False, "msg": "Clicker is busy; try again"}
        return box[0]

    def _web_command(self, cmd, args):
        import platform

        from .. import history, remote
        from .runs import job_line, job_name
        allowed = [p for p in (self.settings.get("remote") or {}).get("allowed") or [] if os.path.exists(p)]
        runs = self.all_runs()
        if cmd == "status":
            hist = []
            for e in reversed(history.load()[-6:]):
                import datetime as _dt
                hist.append({"script": e.get("script"), "result": e["result"],
                             "when": _dt.datetime.fromtimestamp(e["ts"]).strftime("%b %d %H:%M"),
                             "time": history.fmt_duration(e.get("seconds"))})
            return {"machine": platform.node(), "history": hist,
                    "runs": [{"id": str(id(j)), "name": job_name(j), "line": job_line(j), "paused": j.paused,
                              "main": m} for j, m in runs],
                    "scripts": [os.path.splitext(os.path.basename(p))[0] for p in allowed]}
        if cmd == "start":
            path, err = remote.match_script(str(args.get("name", "")), allowed)
            if err:
                return {"ok": False, "msg": err}
            self.run_script_hotkey(path, from_menu=True)
            ok = any(getattr(j, "path", None) == path for j, _m in self.all_runs())
            name = os.path.splitext(os.path.basename(path))[0]
            return {"ok": ok, "msg": f"Started {name}." if ok else f"Could not start {name} now."}
        if cmd in ("stop", "pause"):
            want = str(args.get("id", ""))
            if cmd == "stop" and want == "all":
                self.stop_all()
                return {"ok": True, "msg": "Stopped everything."}
            for j, _m in runs:
                if str(id(j)) == want:
                    j.stop() if cmd == "stop" else j.toggle_pause()
                    return {"ok": True, "msg": f"{'Stopped' if cmd == 'stop' else 'Paused or resumed'} {job_name(j)}."}
            return {"ok": False, "msg": "That run has already ended."}
        if cmd == "screenshot":
            img, _o = vision.capture(None)
            return vision.encode_png(img)
        return {"ok": False, "msg": "unknown command"}

    def remote_reply(self, title, text, image=None, topic=None):
        from .. import remote
        topic = topic or (self.settings.get("remote") or {}).get("topic")
        if topic:
            threading.Thread(target=lambda: _quiet(remote.reply, topic, title, text, image), daemon=True).start()

    def handle_remote(self, text):
        """A command from the phone (runs on the window thread)."""
        from .. import history, remote
        cfg = self.settings.get("remote") or {}
        cmd, arg = remote.parse(text, cfg.get("pin", ""))
        if cmd is None:
            if arg != "wrong or missing PIN":  # stay quiet to strangers
                self.remote_reply("Clicker", arg)
            return
        allowed = [p for p in cfg.get("allowed") or [] if os.path.exists(p)]
        job = self.job if self.job_running() else None
        if cmd == "help":
            self.remote_reply("Clicker", remote.help_text())
        elif cmd == "list":
            names = [os.path.splitext(os.path.basename(p))[0] for p in allowed]
            self.remote_reply("Clicker", ("You can start: " + ", ".join(names)) if names else
                              "No scripts are allowed yet (Settings > Phone remote control).")
        elif cmd == "status":
            runs = self.all_runs()
            if runs:
                self.remote_reply("Clicker", "\n".join(self._job_summary(j) for j, _m in runs))
            elif job is None:
                last = history.load()[-1:] if history.load() else []
                extra = (f" Last run: {last[0].get('script')} {last[0]['result']}, "
                         f"{history.fmt_duration(last[0].get('seconds'))}.") if last else ""
                self.remote_reply("Clicker", "Idle." + extra)
            else:
                self.remote_reply("Clicker", self._job_summary(job))
        elif cmd == "start":
            path, err = remote.match_script(arg, allowed)
            if err:
                self.remote_reply("Clicker", err)
            else:
                name = os.path.splitext(os.path.basename(path))[0]
                if any(getattr(j, "path", None) == path for j, _m in self.all_runs()):
                    self.remote_reply("Clicker", f"{name} is already running.")
                else:
                    self.run_script_hotkey(path, from_menu=True)
                    ok = any(getattr(j, "path", None) == path for j, _m in self.all_runs())
                    self.remote_reply("Clicker", f"Started {name}." if ok else
                                      f"Could not start {name}: it would share the mouse with a running script.")
        elif cmd == "stop":
            had = bool(self.all_runs())
            self.stop_all()
            self.remote_reply("Clicker", "Stopped." if had else "Nothing was running.")
        elif cmd in ("pause", "resume"):
            if job is None:
                self.remote_reply("Clicker", "Nothing is running.")
            else:
                if job.paused != (cmd == "pause"):
                    self.toggle_pause()
                self.remote_reply("Clicker", "Paused." if cmd == "pause" else "Resumed.")
        elif cmd == "screenshot":
            try:
                img, _o = vision.capture(None)
                self.remote_reply("Clicker screenshot", self._job_summary(job) if job else "Idle.",
                                  vision.encode_png(img))
            except Exception as e:
                self.remote_reply("Clicker", f"Could not take a screenshot: {e}")
        self.set_status(f"Phone: {text.strip()[:40]}")

    def _job_summary(self, job):
        script = getattr(job, "script", None)
        name = script.get("name") if isinstance(script, dict) else getattr(job, "label", "a recording")
        cur = getattr(job, "current", None)
        where = f", step {cur + 1} of {len(script['steps'])}" if isinstance(script, dict) and cur is not None else ""
        started = getattr(job, "started_at", None)
        import time as _t
        ran = f", running {int((_t.time() - started) // 60)} min" if started else ""
        return f"{'Paused' if job.paused else 'Running'} {name}{where}{ran}."

    def open_schedule(self):
        from .scheduledlg import ScheduleDialog
        ScheduleDialog(self).exec()

    def check_schedule(self):
        """Start scheduled scripts that are due (every 10 s)."""
        import time as _time

        from .. import schedule as sch
        from .. import target as tgt
        changed = False
        for e in self.settings.get("schedule") or []:
            if not e.get("enabled") or sch.check(e):
                continue
            if e["kind"] == "window":
                try:
                    is_open = bool(tgt.find_window(e.get("window_title", ""), e.get("window_process", "")))
                except tgt.WindowNotFound:
                    continue
                fire = self._window_watch.appeared(e, is_open)
            else:
                fire = sch.due(e)
            if not fire:
                continue
            e["last_run"] = _time.time()
            changed = True
            name = os.path.splitext(os.path.basename(e["path"]))[0]
            self.run_script_hotkey(e["path"], from_menu=True)
            if not any(getattr(j, "path", None) == e["path"] for j, _m in self.all_runs()):
                self.set_status(f"Skipped scheduled {name}: couldn't start alongside what's running", error=True)
        if changed:
            self.save_settings()

    def update_tray(self):
        if (self.settings.get("tray_on_close") or scripthotkeys.bindings(self.settings)
                or any(e.get("enabled") for e in self.settings.get("schedule") or [])
                or (self.settings.get("remote") or {}).get("enabled")
                or (self.settings.get("web") or {}).get("enabled")):
            self.tray.ensure()
        else:
            self.tray.hide()

    def show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self):
        self._quitting = True
        self.show_from_tray()
        self.close()

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

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and hasattr(self, "mini"):
            QTimer.singleShot(0, self.mini.sync)

    def hideEvent(self, e):
        super().hideEvent(e)
        if hasattr(self, "mini"):
            QTimer.singleShot(0, self.mini.sync)

    def showEvent(self, e):
        super().showEvent(e)
        if hasattr(self, "mini"):
            QTimer.singleShot(0, self.mini.sync)

    def closeEvent(self, e):
        if (not self._quitting and self.settings.get("tray_on_close")
                and self.tray.ensure()):
            e.ignore()
            self.hide()
            if not self.settings.get("tray_told"):
                self.settings["tray_told"] = True
                self.save_settings()
                self.tray.message("Clicker is still running",
                                  "Script hotkeys keep working. Right-click the tray icon to quit.")
            return
        if not self.action_tab.confirm_discard("closing"):
            self._quitting = False
            e.ignore()
            return
        self.tray.hide()
        self._closed = True
        self._poll_timer.stop()
        self._autosave_timer.stop()
        self._sched_timer.stop()
        if self.web is not None:
            self.web.stop()
        if self.remote_listener is not None:
            self.remote_listener.stop()
        self.stop_job()
        self.triggers.stop()
        self.hotkeys.stop()
        self.sampler.stop()
        self.toast.close()
        self.highlight.close()
        self.mini.close()
        if self.recording_active():
            self.recorder_tab.recorder.stop()
        self._clear_autosave()
        self.save_rules()
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
    motion.install(app)
    win = GlassApp()
    win.show()
    return app.exec()

