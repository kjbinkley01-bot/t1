"""Choose the window a script runs in (background mode)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem

from .. import inputs, target
from . import dialogs
from .tab_triggers import pixmap_from_bgr
from .widgets import Caption, GlassButton, GlassSwitch


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    lab.setWordWrap(True)
    return lab


class TargetDialog(dialogs.GlassDialog):
    """Pick a window from the list or by clicking it, choose how input reaches it, and test the capture."""

    def __init__(self, main, current):
        super().__init__(main, "Run in a window")
        self.result_target = "unchanged"
        cur = target.normalize(current) or dict(target.DEFAULT_TARGET)
        self.body.addWidget(detail(
            "Clicker sends this script's clicks and keys to one window and reads that window's picture for "
            "image and pixel checks, so you can keep using your mouse and computer. Positions are measured "
            "from the window's top left corner."))
        if not target.available():
            self.body.addWidget(detail("Background mode runs on Windows. You can set it up here; it takes "
                                       "effect when the script runs on a Windows PC."))

        self.body.addWidget(Caption("Open windows"))
        self.lst = QListWidget()
        self.lst.setMinimumSize(560, 130)
        self.lst.itemClicked.connect(self._choose)
        self.body.addWidget(self.lst)
        row = QHBoxLayout()
        b = GlassButton("Refresh", icon="arrow-clockwise", small=True)
        b.clicked.connect(self._fill)
        row.addWidget(b)
        b = GlassButton("Pick by clicking it", icon="crosshair", small=True)
        b.clicked.connect(self._pick)
        row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)

        self.body.addWidget(Caption("Match the window by"))
        r = QHBoxLayout()
        self.e_title = QLineEdit(cur["title"])
        self.e_title.setPlaceholderText("title contains...")
        self.e_proc = QLineEdit(cur["process"])
        self.e_proc.setPlaceholderText("program, e.g. notepad.exe")
        self.e_proc.setFixedWidth(200)
        r.addWidget(self.e_title, 1)
        r.addWidget(self.e_proc)
        self.body.addLayout(r)
        self.body.addWidget(detail("Leave the title blank to match any window of that program. Titles that "
                                   "change (like a document name) work best with just the stable part."))

        self.body.addWidget(Caption("How input reaches it"))
        self.cb_method = QComboBox()
        self.cb_method.addItems([m[1] for m in target.METHODS])
        self.cb_method.setCurrentText(target.METHOD_LABEL[cur["method"]])
        self.body.addWidget(self.cb_method)
        self.body.addWidget(detail("Background messages work with most apps; ones that read the physical mouse "
                                   "(many games) ignore them. Quick switch works with almost everything."))
        self.sw_restore = GlassSwitch("If it's minimized, restore it behind my other windows")
        self.sw_restore.setChecked(cur["restore_minimized"])
        self.sw_focus = GlassSwitch("Tell the window it's active before input (helps many apps)")
        self.sw_focus.setChecked(cur["focus_messages"])
        self.body.addWidget(self.sw_restore)
        self.body.addWidget(self.sw_focus)

        r = QHBoxLayout()
        b = GlassButton("Test capture", icon="camera", small=True)
        b.clicked.connect(self._test)
        r.addWidget(b)
        self.preview = QLabel("")
        self.preview.setMinimumHeight(10)
        self.test_msg = detail("Shows what Clicker sees in the window, even if it's covered.")
        r.addWidget(self.test_msg, 1)
        self.body.addLayout(r)
        self.body.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)

        whole = GlassButton("Use whole screen")
        whole.clicked.connect(self._whole)
        self.buttons.addWidget(whole)
        self.add_buttons("Use this window")
        self._fill()

    def _fill(self):
        self.lst.clear()
        for hwnd, title, proc in target.list_windows():
            if title == self.main.windowTitle():
                continue
            it = QListWidgetItem(f"{title}    ·    {proc}" if proc else title)
            it.setData(Qt.ItemDataRole.UserRole, (title, proc))
            self.lst.addItem(it)
        if not self.lst.count():
            self.lst.addItem("No windows found" if target.available() else "Window list is available on Windows")

    def _choose(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            title, proc = data
            self.e_title.setText(title)
            self.e_proc.setText(proc)

    def _pick(self):
        self.hide()

        def done():
            x, y = inputs.position()
            hit = target.window_at(x, y)
            if hit:
                _h, title, proc = hit
                self.e_title.setText(title)
                self.e_proc.setText(proc)
            self.show()
        dialogs.countdown(self.main, 3, "Pick the window under the cursor", done)

    def _values(self):
        return target.normalize({"title": self.e_title.text(), "process": self.e_proc.text(),
                                 "method": target.METHOD_ID.get(self.cb_method.currentText(), "messages"),
                                 "restore_minimized": self.sw_restore.isChecked(),
                                 "focus_messages": self.sw_focus.isChecked()})

    def _test(self):
        t = self._values()
        if not t:
            self.test_msg.setText("Choose a window first.")
            return
        try:
            io = target.WindowIO(t)
            img = io.grab(*io.bounds())
        except Exception as e:
            self.test_msg.setText(f"Could not capture it: {e}")
            self.preview.clear()
            return
        blank = float(img.std()) < 2.0
        self.test_msg.setText("The capture is blank: this app may not support background capture. Try Quick "
                              "switch, or keep the window visible." if blank else
                              f"Capture works ({img.shape[1]} x {img.shape[0]}).")
        self.preview.setPixmap(pixmap_from_bgr(img, 360, 130))
        self.fit()

    def _whole(self):
        self.result_target = None
        super().accept()

    def accept(self):
        t = self._values()
        if t is None:
            self.test_msg.setText("Enter part of the window title or the program name, or pick a window.")
            return
        self.result_target = t
        super().accept()


def choose_target(main, current):
    """Returns the new target dict, None for whole screen, or 'unchanged' if cancelled."""
    d = TargetDialog(main, current)
    d.exec()
    return d.result_target
