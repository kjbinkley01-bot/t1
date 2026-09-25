"""Command palette (Ctrl+K): type to find any command, tab, step type, step of the open script, or file
in the Library, and press Enter to do it."""

import os

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QFrame, QLineEdit, QListWidget, QListWidgetItem, QStyle,
                               QStyledItemDelegate, QVBoxLayout)

from .. import history, model, palette
from . import glass
from .glass import font, paint_glass

ROW_H = 40
ROWS = 9


def commands(main):
    """Everything the palette can do right now, as items for palette.rank."""
    a, r, t = main.action_tab, main.recorder_tab, main.triggers_tab
    items = []

    def add(title, group, run, hint="", keywords="", boost=0):
        items.append({"title": title, "group": group, "run": run, "hint": hint, "keywords": keywords,
                      "boost": boost})

    def on(tab_key, fn):
        return lambda: (main.show_tab(tab_key), fn())

    running = main.job_running_for(a)
    add("Stop the script" if running else "Start the script", "Action Script", on("actions", a.toggle_run),
        "F7", "run play go", boost=4)
    add("Open from the Library", "File", lambda: main.open_library(
        "recording" if main.current_tab == "recorder" else "script"), "Ctrl+O", "open load recent favorite", 3)
    add("New script", "Action Script", on("actions", a.new_script), keywords="blank empty")
    add("Save script", "Action Script", on("actions", a.save), "Ctrl+S")
    add("Save script as...", "Action Script", on("actions", lambda: a.save(True)))
    add("Test the selected step", "Action Script", on("actions", a.test_step), keywords="try one")
    add("Show every match of the selected step's picture", "Action Script", on("actions", a.show_matches),
        keywords="find image where search debug near miss highlight")
    add("Undo", "Action Script", on("actions", a.undo), "Ctrl+Z")
    add("Redo", "Action Script", on("actions", a.redo), "Ctrl+Y")
    add("Hide the chart" if a.chart_on else "Show the chart", "View", on("actions", lambda: a.set_chart_visible(
        not a.chart_on)), keywords="flow chart boxes arrows diagram")
    add("Hide the flow panel" if a.flow_on else "Show the flow panel", "View", on("actions", lambda: a.set_flow_visible(
        not a.flow_on)), keywords="loops jumps")
    add("Debug from the first step", "Action Script", on("actions", a.debug_start), "",
        "step through breakpoint")
    add("Clear breakpoints", "Action Script", on("actions", a.clear_breakpoints))
    add("Open run logs", "Action Script", a.open_logs, keywords="log folder screenshot failure")
    add("Check my scripts", "File", main.check_scripts, keywords="doctor health problems missing broken validate")
    for key, tab, kind in (("actions", a, "script"), ("recorder", r, "recording"),
                           ("chains", main.chains_tab, "chain")):
        if tab.path and main.current_tab == key:
            add("Earlier versions of this file", "File", lambda p=tab.path, k=kind: main.show_versions(p, k),
                keywords="history undo restore backup previous")
    add("Stop recording" if main.recording_active() else "Start recording", "Macro Recorder",
        on("recorder", r.toggle_record), "F9", "record macro")
    add("Play the recording", "Macro Recorder", on("recorder", r.toggle_play), "F10", "replay playback")
    add("New recording", "Macro Recorder", on("recorder", r.new))
    add("Convert the recording to an Action Script", "Macro Recorder", on("recorder", r.convert))
    add("Stop monitoring" if main.triggers.running else "Start monitoring", "Screen Triggers",
        main.toggle_monitoring, keywords="triggers rules watch")
    add("New trigger rule", "Screen Triggers", on("triggers", t.new_rule))
    ch = main.chains_tab
    add("Stop the chain" if main.job_running_for(ch) else "Start the chain", "Chains", on("chains", ch.toggle_run),
        keywords="run sequence scripts in order")
    add("New chain", "Chains", on("chains", ch.new_chain), keywords="sequence scripts in order")
    add("Add a script to the chain", "Chains", on("chains", ch.add_link), keywords="card link")
    add("Pause or resume", "Running", main.toggle_pause, "F11")
    add("Stop everything", "Running", main.stop_all, "F8", "emergency halt")
    add("Settings", "Clicker", main.show_settings, keywords="preferences options hotkeys shortcut keys")
    add("Script hotkeys", "Clicker", main.open_script_hotkeys, keywords="shortcut keys per script")
    add("Schedule", "Clicker", main.open_schedule, keywords="timer daily time later")
    add("Phone remote control and web page", "Clicker", main.open_remote, keywords="ntfy dashboard wifi")
    add("Style and wallpaper", "Clicker", main.show_style_menu, keywords="theme dark light look")
    add("Turn animations back on" if not glass.motion_on() else "Reduce motion", "Clicker",
        lambda: main.set_reduce_motion(glass.motion_on()), keywords="animations")
    add("Check for updates", "Clicker", lambda: main.check_updates(force=True), keywords="version new")
    from .app import TABS
    for key, name in TABS:
        add(f"Go to {name}", "Tab", lambda k=key: main.show_tab(k), keywords="tab page switch")
    for key, name, _c in glass.WALLPAPERS:
        add(f"Wallpaper: {name}", "Style", lambda k=key: main.set_wallpaper(k), keywords="background theme")
    for group, acts in model.ACTION_GROUPS:
        for act in acts:
            add(f"New step: {act}", "Step type", lambda x=act: a.start_new_step(x), group.lower(),
                "add action")
    for i, st in enumerate(a.script["steps"]):
        add(f"Step {history.step_title(st, i)}", "This script", lambda k=i: (main.show_tab("actions"),
                                                                                  a.select_step(k)),
            st.get("label") or "", f"{st.get('label', '')} {st.get('comment', '')} go to line")
    for e in main.library.list():
        if e.get("missing"):
            continue
        kind = e["kind"]
        tab_key = main.TAB_FOR.get(kind, "actions")
        add(f"Open {e['name']}", kind.capitalize(),
            lambda p=e["path"], k=tab_key: (main.show_tab(k), main.tabs[k].open_from_library(p)),
            e.get("detail", ""), f"{os.path.basename(e['path'])} file", boost=2 if e.get("favorite") else 0)
    return items


class _Row(QStyledItemDelegate):
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar

    def sizeHint(self, _opt, _index):
        return QSize(100, ROW_H)

    def paint(self, p, opt, index):
        it = index.data(Qt.ItemDataRole.UserRole)
        if it is None:
            return
        m = self.bar.main.mode
        r = QRectF(opt.rect).adjusted(6, 2, -6, -2)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if opt.state & QStyle.StateFlag.State_Selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(glass.ACCENT))
            p.drawRoundedRect(r, 10, 10)
            main_c, sub_c = QColor("#ffffff"), QColor(255, 255, 255, 200)
        else:
            main_c, sub_c = QColor(m.text), QColor(m.detail)
        group = it["group"]
        fg = font(8.5, QFont.Weight.DemiBold)
        gw = QFontMetrics(fg).horizontalAdvance(group) + 16
        hint = it.get("hint") or ""
        fh = font(8.5)
        hw = QFontMetrics(fh).horizontalAdvance(hint) + 12 if hint else 0
        f = font(10.5, QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(main_c)
        title = QFontMetrics(f).elidedText(it["title"], Qt.TextElideMode.ElideRight, int(r.width() - gw - hw - 30))
        p.drawText(r.adjusted(14, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        if hint:
            p.setFont(fh)
            p.setPen(sub_c)
            p.drawText(QRectF(r.right() - gw - hw - 10, r.y(), hw, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, hint)
        chip = QRectF(r.right() - gw - 6, r.center().y() - 10, gw, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 40) if opt.state & QStyle.StateFlag.State_Selected else
                   (QColor(255, 255, 255, 22) if m.dark else QColor(0, 0, 0, 16)))
        p.drawRoundedRect(chip, 10, 10)
        p.setFont(fg)
        p.setPen(sub_c)
        p.drawText(chip, Qt.AlignmentFlag.AlignCenter, group)
        p.restore()


class CommandBar(QFrame):
    """The palette window: a search field over a list of matches, near the top of Clicker's window."""

    def __init__(self, main):
        super().__init__(main, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a command, a step, or a script name...")
        self.search.setFont(font(13))
        self.search.setMinimumHeight(44)
        self.search.setStyleSheet("QLineEdit { border: none; background: transparent; padding: 0 6px; }")
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setItemDelegate(_Row(self))
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; outline: none; }")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda _i: self.run_selected())
        lay.addWidget(self.list)
        self.items = commands(main)
        self.setFixedWidth(min(720, max(520, main.width() - 200)))
        self.refresh()

    def refresh(self):
        found = palette.rank(self.search.text(), self.items, limit=60)
        self.list.clear()
        for it in found:
            li = QListWidgetItem()
            li.setData(Qt.ItemDataRole.UserRole, it)
            self.list.addItem(li)
        if found:
            self.list.setCurrentRow(0)
        rows = max(1, min(ROWS, len(found)))
        self.list.setFixedHeight(rows * ROW_H + 4 if found else 0)
        self.list.setVisible(bool(found))
        self.adjustSize()

    def run_selected(self):
        li = self.list.currentItem()
        if li is None:
            return
        it = li.data(Qt.ItemDataRole.UserRole)
        self.close()
        it["run"]()  # after closing, so whatever it opens appears on top

    def eventFilter(self, obj, e):
        if obj is self.search and e.type() == QEvent.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
                step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_PageDown: ROWS,
                        Qt.Key.Key_PageUp: -ROWS}[k]
                n = self.list.count()
                if n:
                    self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + step)))
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run_selected()
                return True
            if k == Qt.Key.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, e)

    def open(self):
        g = self.main.geometry()
        end = QPoint(g.center().x() - self.width() // 2, g.y() + 70)
        self.move(end - QPoint(0, 10))
        glass.fade_in(self, glass.FAST)
        self.show()
        glass.animate(self, -10.0, 0.0, glass.BASE, lambda v: self.move(end + QPoint(0, round(v))), attr="_drop")
        self.search.setFocus()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.main.mode
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        origin = self.main.centralWidget().mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
        paint_glass(p, r, 24, self.main.backdrop, origin, m, light=0.9, shadow=False,
                    tint=QColor(22, 24, 38, 226) if m.dark else QColor(255, 255, 255, 232))
        if self.list.isVisible():
            y = self.list.geometry().top() - 4
            p.setPen(QColor(255, 255, 255, 30) if m.dark else QColor(0, 0, 0, 24))
            p.drawLine(QPoint(18, y), QPoint(self.width() - 18, y))
        p.end()

    def moveEvent(self, e):
        self.update()
        super().moveEvent(e)


def open_palette(main):
    bar = CommandBar(main)
    bar.open()
    return bar

