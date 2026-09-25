"""Hotkey per script: start any saved script with its own keys, and the tray icon that keeps them alive."""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QSystemTrayIcon, QTreeWidget,
                               QTreeWidgetItem)

from .. import history, storage, target
from . import dialogs, glass
from .widgets import Caption, GlassButton, GlassSwitch


def entries(settings):
    """[{path, keys, toggle, ask}] from settings, dropping broken ones."""
    out = []
    for e in settings.get("script_hotkeys") or []:
        if isinstance(e, dict) and e.get("path"):
            out.append({"path": e["path"], "keys": e.get("keys", ""), "toggle": e.get("toggle", True),
                        "ask": e.get("ask", False)})
    return out


def bindings(settings):
    return {e["path"]: e["keys"] for e in entries(settings) if e["keys"]}


def script_name(path):
    return os.path.splitext(os.path.basename(path))[0]


def _script_target(path, cache={}):
    """'RuneLite · background' for a saved script's Run in window (cached by file time)."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return "file is missing"
    hit = cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        script, _a = storage.load_script(path)
        t = target.normalize((script.get("settings") or {}).get("target"))
        text = target.describe(t) if t else "Whole screen"
    except Exception:
        text = "can't be opened"
    cache[path] = (mt, text)
    return text


class ScriptHotkeysDialog(dialogs.GlassDialog):
    def __init__(self, main):
        super().__init__(main, "Script hotkeys")
        self.body.addWidget(self._detail("Give any saved script its own keys to start it from anywhere, even while "
                                         "Clicker is hidden or in the tray."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Script", "Runs in", "Hotkey", "Last run"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumSize(720, 200)
        for c, w in enumerate((200, 220, 130)):
            self.tree.setColumnWidth(c, w)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.itemDoubleClicked.connect(lambda *_: self._assign())
        self.body.addWidget(self.tree)
        row = QHBoxLayout()
        for text, ic, cmd in (("Add script...", "plus", self._add_file), ("Add the open script", "file-plus",
                                                                          self._add_open)):
            b = GlassButton(text, icon=ic, small=True)
            b.clicked.connect(cmd)
            row.addWidget(b)
        row.addStretch(1)
        self.btn_run = GlassButton("Run now", icon="play", small=True)
        self.btn_run.clicked.connect(self._run)
        self.btn_key = GlassButton("Set hotkey", icon="keyboard", small=True)
        self.btn_key.clicked.connect(self._assign)
        self.btn_rm = GlassButton("Remove", icon="trash", kind="danger", small=True)
        self.btn_rm.clicked.connect(self._remove)
        for b in (self.btn_run, self.btn_key, self.btn_rm):
            row.addWidget(b)
        self.body.addLayout(row)
        self.body.addWidget(Caption("For the selected script"))
        self.sw_toggle = GlassSwitch("Pressing its hotkey again stops it")
        self.sw_ask = GlassSwitch("Ask before starting")
        for sw in (self.sw_toggle, self.sw_ask):
            sw.toggled.connect(self._opts_changed)
            self.body.addWidget(sw)
        self.body.addWidget(Caption("Tray"))
        self.sw_tray = GlassSwitch("Keep Clicker running in the tray when I close the window")
        self.sw_tray.setChecked(bool(main.settings.get("tray_on_close", False)))
        self.sw_tray.toggled.connect(self._tray_changed)
        self.body.addWidget(self.sw_tray)
        self.body.addWidget(self._detail("Hotkeys work anywhere while Clicker is open or in the tray. They stop when "
                                         "you quit it (tray menu > Quit)."
                                         + ("" if QSystemTrayIcon.isSystemTrayAvailable() else
                                            " This desktop has no tray, so closing the window quits.")))
        self.msg = self._detail("")
        self.body.addWidget(self.msg)
        self.add_buttons("Done", None)
        main.script_hotkey_dialog = self
        self.finished.connect(self._closed)
        self.refresh()

    def _detail(self, text):
        lab = QLabel(text)
        lab.setProperty("role", "detail")
        lab.setWordWrap(True)
        return lab

    def _closed(self, *_):
        if getattr(self.main, "script_hotkey_dialog", None) is self:
            self.main.script_hotkey_dialog = None
        self.main.cancel_script_assign()

    def refresh(self, select=None):
        cur = select or self._path()
        self.tree.clear()
        last = {}
        for e in history.load():
            if e.get("path"):
                last[os.path.abspath(e["path"])] = e
        capturing = self.main.capture_action
        for e in entries(self.main.settings):
            keys = e["keys"] or "none"
            if capturing == ("script", e["path"]):
                keys = "Press keys..."
            h = last.get(os.path.abspath(e["path"]))
            when = f"{h['result']} · {history.fmt_duration(h.get('seconds'))}" if h else "never"
            it = QTreeWidgetItem([script_name(e["path"]), _script_target(e["path"]), keys, when])
            it.setToolTip(0, e["path"])
            it.setData(0, Qt.ItemDataRole.UserRole, e["path"])
            self.tree.addTopLevelItem(it)
            if e["path"] == cur:
                it.setSelected(True)
                self.tree.setCurrentItem(it)
        self._on_select()

    def _path(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None and it.isSelected() else None

    def _entry(self, path):
        for e in self.main.settings.setdefault("script_hotkeys", []):
            if e.get("path") == path:
                return e
        return None

    def _on_select(self):
        path = self._path()
        e = self._entry(path) if path else None
        for w in (self.btn_run, self.btn_key, self.btn_rm, self.sw_toggle, self.sw_ask):
            w.setEnabled(e is not None)
        if e is not None:
            for sw, key, default in ((self.sw_toggle, "toggle", True), (self.sw_ask, "ask", False)):
                sw.blockSignals(True)
                sw.setChecked(bool(e.get(key, default)))
                sw.blockSignals(False)

    def _opts_changed(self, *_):
        e = self._entry(self._path())
        if e is not None:
            e["toggle"] = self.sw_toggle.isChecked()
            e["ask"] = self.sw_ask.isChecked()
            self.main.save_settings()

    def _tray_changed(self, on):
        self.main.settings["tray_on_close"] = bool(on)
        self.main.save_settings()
        self.main.update_tray()

    def add_path(self, path):
        path = os.path.abspath(path)
        lst = self.main.settings.setdefault("script_hotkeys", [])
        if not any(os.path.abspath(e.get("path", "")) == path for e in lst):
            lst.append({"path": path, "keys": "", "toggle": True, "ask": False})
            self.main.save_settings()
        self.refresh(select=path)
        self._assign()

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a script", "", storage.SCRIPT_FILTER)
        if path:
            self.add_path(path)

    def _add_open(self):
        tab = self.main.action_tab
        if not tab.path:
            self.msg.setText("Save the open script first, so the hotkey has a file to run.")
            return
        self.add_path(tab.path)

    def _assign(self):
        path = self._path()
        if path:
            self.main.begin_assign_script(path)
            self.msg.setText(f"Press the keys for {script_name(path)} (Esc clears it). Use a combination like "
                             "Ctrl+Alt+1 so it doesn't clash with other apps.")
            self.refresh(select=path)

    def _remove(self):
        path = self._path()
        if path:
            self.main.settings["script_hotkeys"] = [e for e in entries(self.main.settings) if e["path"] != path]
            self.main.apply_script_hotkeys()
            self.refresh()

    def _run(self):
        path = self._path()
        if path:
            self.main.run_script_hotkey(path, from_menu=True)


class Tray:
    """The tray icon: open Clicker, see and stop what's running, run scripts that have hotkeys, quit."""

    def __init__(self, main):
        self.main = main
        self.icon = None

    def ensure(self):
        if self.icon is None and QSystemTrayIcon.isSystemTrayAvailable():
            path = os.path.join(glass.ASSETS, "clicker.png")
            self.icon = QSystemTrayIcon(QIcon(path) if os.path.exists(path) else self.main.windowIcon(), self.main)
            self.icon.setToolTip("Clicker")
            self.icon.activated.connect(self._activated)
            self.menu = QMenu()
            self.menu.aboutToShow.connect(self._fill)
            self.icon.setContextMenu(self.menu)
        if self.icon is not None:
            self.icon.show()
        return self.icon is not None

    def hide(self):
        if self.icon is not None:
            self.icon.hide()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.main.show_from_tray()

    def _fill(self):
        m, main = self.menu, self.main
        m.clear()
        if main.job_running():
            job = main.job
            name = (getattr(job, "script", None) or {}).get("name") if isinstance(getattr(job, "script", None),
                                                                                   dict) else None
            a = QAction(f"Running: {name or getattr(job, 'label', 'job')}", m)
            a.setEnabled(False)
            m.addAction(a)
            m.addAction("Stop", main.stop_all)
            m.addAction("Pause / resume", main.toggle_pause)
            m.addSeparator()
        for e in entries(main.settings):
            text = f"Run {script_name(e['path'])}" + (f"\t{e['keys']}" if e["keys"] else "")
            m.addAction(text, lambda p=e["path"]: main.run_script_hotkey(p, from_menu=True))
        if entries(main.settings):
            m.addSeparator()
        m.addAction("Open Clicker", main.show_from_tray)
        m.addAction("Script hotkeys...", lambda: (main.show_from_tray(), main.open_script_hotkeys()))
        m.addAction("Schedule...", lambda: (main.show_from_tray(), main.open_schedule()))
        m.addSeparator()
        m.addAction("Quit", main.quit_from_tray)

    def message(self, title, text):
        if self.icon is not None and self.icon.isVisible():
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 4000)

