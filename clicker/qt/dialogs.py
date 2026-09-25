"""Glass dialogs and overlays: region picker, prompts, script inputs, settings."""

import os

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QVBoxLayout, QWidget)

from .. import model, runlog, vision
from . import glass
from .glass import font, paint_glass, rounded
from .widgets import Caption, GlassButton, GlassSwitch


class GlassDialog(QDialog):
    """A frameless glass sheet over a frosted copy of what is behind it."""

    def __init__(self, main, title):
        super().__init__(main)
        self.main = main
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.outer = QVBoxLayout(self)
        self.outer.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)  # never smaller than the content
        self.outer.setContentsMargins(30, 26, 30, 24)
        self.outer.setSpacing(12)
        t = QLabel(title)
        t.setFont(font(14, QFont.Weight.Bold))
        self.outer.addWidget(t)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.outer.addLayout(self.body)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.outer.addSpacing(6)
        self.outer.addLayout(self.buttons)
        self._drag = None

    def add_buttons(self, ok="OK", cancel="Cancel"):
        if cancel:
            b = GlassButton(cancel)
            b.clicked.connect(self.reject)
            self.buttons.addWidget(b)
        b = GlassButton(ok, kind="primary")
        b.clicked.connect(self.accept)
        b.setDefault(True) if hasattr(b, "setDefault") else None
        self.buttons.addWidget(b)
        return b

    def fit(self):
        """Size to the content (adjustSize would cap tall dialogs at two thirds of the screen)."""
        scr = self.screen().availableGeometry() if self.screen() else None
        hint = self.sizeHint()
        h = min(hint.height(), scr.height() - 40) if scr else hint.height()
        self.resize(hint.width(), h)

    def showEvent(self, e):
        self.fit()
        g = self.main.geometry()
        self.move(g.center() - QPoint(self.width() // 2, self.height() // 2 + 40))
        glass.animate(self, 0.0, 1.0, 180, lambda v: self.setWindowOpacity(float(v)), attr="_fade")
        super().showEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not isinstance(self.focusWidget(), QComboBox):
            self.accept()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.main.mode
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        origin = self.main.centralWidget().mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
        paint_glass(p, r, 28, self.main.backdrop, origin, m, light=0.85, shadow=False,
                    tint=QColor(22, 24, 38, 214) if m.dark else QColor(255, 255, 255, 222))
        p.end()


def ask_string(main, title, prompt, default=""):
    d = GlassDialog(main, title)
    lab = QLabel(prompt)
    lab.setProperty("role", "detail")
    e = QLineEdit(default)
    e.setMinimumWidth(320)
    e.selectAll()
    d.body.addWidget(lab)
    d.body.addWidget(e)
    d.add_buttons()
    e.setFocus()
    return e.text() if d.exec() == QDialog.DialogCode.Accepted else None


def ask_inputs(main, inputs, current):
    d = GlassDialog(main, "Script inputs")
    lab = QLabel("Fill in the values this script needs.")
    lab.setProperty("role", "detail")
    d.body.addWidget(lab)
    form = QFormLayout()
    form.setVerticalSpacing(10)
    edits = {}
    for item in inputs:
        e = QLineEdit(current.get(item["name"], item.get("default", "")))
        e.setMinimumWidth(320)
        form.addRow(item.get("label") or item["name"], e)
        edits[item["name"]] = e
    d.body.addLayout(form)
    d.add_buttons("Run")
    if d.exec() != QDialog.DialogCode.Accepted:
        return None
    return {k: e.text() for k, e in edits.items()}


class RegionPicker(QWidget):
    """Freeze the screen, dim it, and let the user drag a box. Calls done(region, bgr image) or (None, None)."""

    def __init__(self, main, done, prompt):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.main, self.done_cb, self.prompt = main, done, prompt
        self.frame, (self.ox, self.oy) = vision.capture(None)
        import cv2
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        self.full = glass.np_to_pixmap(rgb)
        dim = (rgb.astype("float32") * 0.45).astype("uint8")
        self.dim = glass.np_to_pixmap(dim)
        h, w = self.frame.shape[:2]
        self.setGeometry(QRect(self.ox, self.oy, w, h))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = self.end = None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.dim)
        if self.start and self.end:
            r = QRect(self.start, self.end).normalized()
            p.drawPixmap(r, self.full, r)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(glass.ACCENT, 2))
            p.drawRect(r)
            p.setPen(QColor("#ffffff"))
            p.setFont(font(10, QFont.Weight.DemiBold))
            p.drawText(r.x(), max(16, r.y() - 8), f"{r.x() + self.ox}, {r.y() + self.oy}   {r.width()} x {r.height()}")
        # instruction pill
        scr = QGuiApplication.primaryScreen().geometry()
        pill = QRectF(scr.center().x() - self.ox - 230, 28 - self.oy + scr.y(), 460, 44)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 22, 36, 220))
        p.drawPath(rounded(pill, 22))
        p.setPen(QColor("#ffffff"))
        p.setFont(font(10.5, QFont.Weight.Medium))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.prompt)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._finish(None)
            return
        self.start = self.end = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):
        if self.start:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if not self.start:
            return
        r = QRect(self.start, e.position().toPoint()).normalized()
        if r.width() < 3 or r.height() < 3:
            self.start = None
            return
        self._finish([r.x() + self.ox, r.y() + self.oy, r.width(), r.height()])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._finish(None)

    def _finish(self, region):
        self.close()
        self.main.showNormal()
        self.main.raise_()
        self.main.activateWindow()
        if region is None:
            self.done_cb(None, None)
            return
        x, y, w, h = region
        crop = self.frame[y - self.oy:y - self.oy + h, x - self.ox:x - self.ox + w].copy()
        self.done_cb(region, crop)


def open_image(parent):
    """Ask for an image file. Returns (BGR image, file name without extension), or None."""
    path, _ = QFileDialog.getOpenFileName(parent, "Load image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return vision.decode_png(f.read()), os.path.splitext(os.path.basename(path))[0]
    except (OSError, ValueError) as e:
        QMessageBox.warning(parent, "Could not load image", str(e))
        return None


def select_region(main, done, prompt="Drag to select an area. Esc cancels."):
    main.showMinimized()

    def begin():
        try:
            main._picker = RegionPicker(main, done, prompt)
        except Exception:
            main.showNormal()
            done(None, None)
            return
        main._picker.show()
        main._picker.activateWindow()
        main._picker.setFocus()
    QTimer.singleShot(350, begin)


def countdown(main, seconds, title, on_done):
    def tick(n):
        if n <= 0:
            main.toast.hide_animated()
            on_done()
            return
        main.toast.show_msg(f"{title} in {n}", "Move the cursor to the target now.", 0, accent=glass.ACCENT)
        QTimer.singleShot(1000, lambda: tick(n - 1))
    tick(int(seconds))


class SettingsDialog(GlassDialog):
    def __init__(self, main):
        super().__init__(main, "Settings")
        s = main.settings
        sub = QLabel(f"{model.APP_NAME} {model.APP_VERSION}  ·  auto clicker, macro recorder, screen-aware scripts")
        sub.setProperty("role", "detail")
        self.body.addWidget(sub)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Run logs"))
        self.sw_logs = GlassSwitch("Save a log for every run, with a screenshot when it fails")
        self.sw_logs.setChecked(s.get("save_run_logs", True))
        self.body.addWidget(self.sw_logs)
        row = QHBoxLayout()
        b = GlassButton("Open Run Logs", icon="notebook", small=True)
        b.clicked.connect(lambda: runlog.open_folder(runlog.logs_dir()))
        row.addWidget(b)
        path = QLabel(runlog.logs_dir())
        path.setProperty("role", "detail")
        row.addWidget(path, 1)
        self.body.addLayout(row)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Alerts"))
        arow = QHBoxLayout()
        b = GlassButton("Alerts...", icon="lightning", small=True)
        b.clicked.connect(self._alerts)
        arow.addWidget(b)
        self.lbl_alerts = QLabel(self._alerts_text())
        self.lbl_alerts.setProperty("role", "detail")
        arow.addWidget(self.lbl_alerts, 1)
        self.body.addLayout(arow)
        rrow = QHBoxLayout()
        b = GlassButton("Phone remote control...", icon="lightning", small=True)
        b.clicked.connect(main.open_remote)
        rrow.addWidget(b)
        r = s.get("remote") or {}
        lab = QLabel(f"On · {len(r.get('allowed') or [])} scripts allowed · {main.remote_state}" if r.get("enabled")
                     else "Start, stop and check scripts from the ntfy app")
        lab.setProperty("role", "detail")
        rrow.addWidget(lab, 1)
        self.body.addLayout(rrow)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Backup"))
        brow = QHBoxLayout()
        for text, ic, cmd in (("Export everything...", "floppy-disk", self._export), ("Import backup...",
                                                                                       "download-simple", self._import)):
            b = GlassButton(text, icon=ic, small=True)
            b.clicked.connect(cmd)
            brow.addWidget(b)
        lab = QLabel("Settings, hotkeys, rules, snippets, history and your scripts, in one file")
        lab.setProperty("role", "detail")
        brow.addWidget(lab, 1)
        self.body.addLayout(brow)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Updates"))
        self.sw_upd = GlassSwitch("Check GitHub for a new version once a day")
        self.sw_upd.setChecked(s.get("check_updates", True))
        self.body.addWidget(self.sw_upd)
        b = GlassButton("Check now", icon="arrow-clockwise", small=True)
        b.clicked.connect(lambda: main.check_updates(force=True))
        self.body.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Shortcut keys (work anywhere, even when Clicker is hidden)"))
        grid = QFormLayout()
        grid.setVerticalSpacing(6)
        self._hk_fields = []
        for action, text in main.HOTKEY_NAMES.items():
            f = QLineEdit()
            f.setReadOnly(True)
            f.setFixedWidth(120)
            f.setAlignment(Qt.AlignmentFlag.AlignCenter)
            a = GlassButton("Assign", small=True)
            a.clicked.connect(lambda _=False, x=action: main.begin_assign(x))
            c = GlassButton("Clear", small=True)
            c.clicked.connect(lambda _=False, x=action: main.set_hotkey(x, ""))
            box = QHBoxLayout()
            box.setSpacing(6)
            box.addWidget(f)
            box.addWidget(a)
            box.addWidget(c)
            box.addStretch(1)
            grid.addRow(text, box)
            main.hotkey_displays.setdefault(action, []).append(f)
            self._hk_fields.append((action, f))
        self.body.addLayout(grid)
        srow = QHBoxLayout()
        b = GlassButton("Script hotkeys...", icon="keyboard", small=True)
        b.clicked.connect(main.open_script_hotkeys)
        srow.addWidget(b)
        n = len([e for e in (s.get("script_hotkeys") or []) if e.get("keys")])
        lab = QLabel(f"{n} script{'s' if n != 1 else ''} with {'their own keys' if n != 1 else 'its own keys'}"
                     if n else "Start any saved script with its own keys")
        lab.setProperty("role", "detail")
        srow.addWidget(lab, 1)
        self.body.addLayout(srow)
        crow = QHBoxLayout()
        b = GlassButton("Schedule...", icon="clock", small=True)
        b.clicked.connect(main.open_schedule)
        crow.addWidget(b)
        n = len([e for e in (s.get("schedule") or []) if e.get("enabled")])
        lab = QLabel(f"{n} scheduled run{'s' if n != 1 else ''} on" if n else
                     "Run scripts at set times, every N minutes, or when a window opens")
        lab.setProperty("role", "detail")
        crow.addWidget(lab, 1)
        self.body.addLayout(crow)
        main.refresh_hotkey_displays()
        self.finished.connect(self._forget_fields)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Mini status window"))
        from .ministatus import MODE_LABEL, MODES
        self.cb_mini = QComboBox()
        self.cb_mini.addItems([m[1] for m in MODES])
        self.cb_mini.setCurrentText(MODE_LABEL.get(s.get("mini_status", "hidden")))
        self.body.addWidget(self.cb_mini)
        self.body.addSpacing(6)
        self.body.addWidget(Caption("Motion"))
        self.sw_motion = GlassSwitch("Reduce motion (no sliding or fading)")
        self.sw_motion.setChecked(s.get("reduce_motion", False))
        self.body.addWidget(self.sw_motion)
        problem = vision.ocr_problem()
        ocr = QLabel("Read Text (OCR): " + ("ready" if not problem else problem))
        ocr.setWordWrap(True)
        ocr.setMaximumWidth(520)
        ocr.setProperty("role", "detail")
        self.body.addSpacing(6)
        self.body.addWidget(ocr)
        self.add_buttons("Save")

    def _export(self):
        import datetime

        from PySide6.QtWidgets import QFileDialog

        from .. import backup, storage
        name = f"clicker-{datetime.date.today():%Y-%m-%d}.clkbackup"
        path, _ = QFileDialog.getSaveFileName(self, "Export everything", name, "Clicker backup (*.clkbackup)")
        if not path:
            return
        self.main.save_settings()
        self.main.save_rules()
        try:
            summary = backup.export(path, storage.data_dir(), self.main.settings)
        except Exception as e:
            QMessageBox.warning(self, "Could not export", str(e))
            return
        self.main.set_status(f"Backup saved: {summary}")

    def _import(self):
        import os

        from PySide6.QtWidgets import QFileDialog

        from .. import backup, storage
        path, _ = QFileDialog.getOpenFileName(self, "Import backup", "", "Clicker backup (*.clkbackup)")
        if not path:
            return
        if QMessageBox.question(self, "Import backup?", "This replaces your settings, hotkeys, trigger rules, "
                                "snippets and history with the ones in the backup. Continue?") \
                != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "Where should the backed up scripts go?",
                                                  os.path.join(os.path.expanduser("~"), "Documents"))
        if not folder:
            return
        try:
            settings, summary = backup.restore(path, storage.data_dir(), os.path.join(folder, "Clicker scripts"))
        except Exception as e:
            QMessageBox.warning(self, "Could not import", str(e))
            return
        self.main.apply_imported(settings)
        QMessageBox.information(self, "Backup imported", f"Restored {summary}. The wallpaper and look change the "
                                "next time Clicker starts.")
        self.reject()

    def _alerts_text(self):
        from .. import alerts
        cfg = alerts.config(self.main.settings)
        where = [n for n, k in (("Discord", "discord"), ("phone", "ntfy")) if cfg.get(k, "").strip()]
        return ("Sending to " + " and ".join(where)) if where else "Phone or Discord messages when a run ends"

    def _alerts(self):
        from .alerts_dialog import open_alerts
        open_alerts(self.main)
        self.lbl_alerts.setText(self._alerts_text())

    def _forget_fields(self, *_):
        for action, f in self._hk_fields:
            fields = self.main.hotkey_displays.get(action, [])
            if f in fields:
                fields.remove(f)

    def accept(self):
        s = self.main.settings
        s["save_run_logs"] = self.sw_logs.isChecked()
        s["check_updates"] = self.sw_upd.isChecked()
        from .ministatus import MODE_ID
        s["mini_status"] = MODE_ID.get(self.cb_mini.currentText(), "hidden")
        self.main.set_reduce_motion(self.sw_motion.isChecked())
        self.main.save_settings()
        super().accept()

