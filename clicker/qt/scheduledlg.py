"""Schedule dialog: run saved scripts at times, every N minutes, once, or when a window opens."""

import copy
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QWidget)

from .. import schedule as sch
from . import dialogs
from .widgets import Caption, GlassButton


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    lab.setWordWrap(True)
    return lab


class ScheduleDialog(dialogs.GlassDialog):
    def __init__(self, main):
        super().__init__(main, "Schedule")
        self.entries = copy.deepcopy(main.settings.get("schedule") or [])
        self.body.addWidget(detail("Start saved scripts on their own. Runs happen while Clicker is open or in "
                                   "the tray; if another script is running then, that run is skipped."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["On", "Script", "When", "Next run"])
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumSize(700, 170)
        for c, w in enumerate((40, 190, 250)):
            self.tree.setColumnWidth(c, w)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.itemSelectionChanged.connect(self._load_form)
        self.tree.itemClicked.connect(self._clicked)
        self.body.addWidget(self.tree)
        row = QHBoxLayout()
        b = GlassButton("Add script...", icon="plus", small=True)
        b.clicked.connect(self._add)
        row.addWidget(b)
        self.btn_rm = GlassButton("Remove", icon="trash", kind="danger", small=True)
        self.btn_rm.clicked.connect(self._remove)
        row.addWidget(self.btn_rm)
        row.addStretch(1)
        self.body.addLayout(row)

        self.body.addWidget(Caption("When"))
        self.form = QWidget()
        g = QGridLayout(self.form)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.cb_kind = QComboBox()
        self.cb_kind.addItems([k[1] for k in sch.KINDS])
        self.cb_kind.currentTextChanged.connect(self._kind_changed)
        g.addWidget(QLabel("Run"), 0, 0)
        g.addWidget(self.cb_kind, 0, 1, 1, 3)
        self.e_time = QLineEdit()
        self.e_time.setPlaceholderText("09:00")
        self.e_time.setFixedWidth(80)
        self.day_sw = []
        days = QHBoxLayout()
        days.setSpacing(4)
        for k, d in enumerate(sch.DAYS):
            b = GlassButton(d, small=True)
            b.setCheckable(True) if hasattr(b, "setCheckable") else None
            b.clicked.connect(lambda _=False, x=k: self._toggle_day(x))
            self.day_sw.append(b)
            days.addWidget(b)
        days.addStretch(1)
        self.lab_time, self.lab_days = QLabel("At"), QLabel("On")
        g.addWidget(self.lab_time, 1, 0)
        g.addWidget(self.e_time, 1, 1)
        g.addWidget(self.lab_days, 2, 0)
        self.days_box = QWidget()
        self.days_box.setLayout(days)
        g.addWidget(self.days_box, 2, 1, 1, 3)
        self.lab_every = QLabel("Every")
        self.e_every = QLineEdit()
        self.e_every.setFixedWidth(80)
        self.lab_min = detail("minutes")
        g.addWidget(self.lab_every, 3, 0)
        g.addWidget(self.e_every, 3, 1)
        g.addWidget(self.lab_min, 3, 2)
        self.lab_once = QLabel("On")
        self.e_once = QLineEdit()
        self.e_once.setPlaceholderText("2026-09-26 09:00")
        g.addWidget(self.lab_once, 4, 0)
        g.addWidget(self.e_once, 4, 1, 1, 2)
        self.lab_win = QLabel("Window")
        self.e_wtitle, self.e_wproc = QLineEdit(), QLineEdit()
        self.e_wtitle.setPlaceholderText("title contains...")
        self.e_wproc.setPlaceholderText("program, e.g. EXCEL.EXE")
        wr = QHBoxLayout()
        wr.addWidget(self.e_wtitle, 1)
        wr.addWidget(self.e_wproc)
        self.win_box = QWidget()
        self.win_box.setLayout(wr)
        g.addWidget(self.lab_win, 5, 0)
        g.addWidget(self.win_box, 5, 1, 1, 3)
        self.body.addWidget(self.form)
        apply = GlassButton("Apply to the selected script", icon="check", small=True)
        apply.clicked.connect(self._apply_form)
        self.body.addWidget(apply, 0, Qt.AlignmentFlag.AlignLeft)
        self.msg = detail("")
        self.body.addWidget(self.msg)
        self._days = set()
        self.add_buttons("Save")
        self.refresh()
        self._load_form()

    # ------------------------------------------------------------ list

    def refresh(self, select=None):
        cur = select or self._sel_id()
        self.tree.blockSignals(True)
        self.tree.clear()
        for e in self.entries:
            nxt = sch.next_run(e)
            nxt_t = ("waiting for the window" if e["kind"] == "window" and e.get("enabled")
                     else nxt.strftime("%a %b %d, %H:%M") if nxt else ("off" if not e.get("enabled") else "done"))
            err = sch.check(e)
            it = QTreeWidgetItem(["●" if e.get("enabled") else "○", os.path.splitext(os.path.basename(e["path"]))[0],
                                  sch.describe(e), err or nxt_t])
            it.setToolTip(1, e["path"])
            it.setToolTip(0, "Click to turn on or off")
            it.setData(0, Qt.ItemDataRole.UserRole, e["id"])
            self.tree.addTopLevelItem(it)
            if e["id"] == cur:
                it.setSelected(True)
                self.tree.setCurrentItem(it)
        self.tree.blockSignals(False)
        self.btn_rm.setEnabled(self._sel() is not None)

    def _sel_id(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None and it.isSelected() else None

    def _sel(self):
        sid = self._sel_id()
        return next((e for e in self.entries if e["id"] == sid), None)

    def _clicked(self, item, col):
        if col == 0:
            sid = item.data(0, Qt.ItemDataRole.UserRole)
            e = next(e for e in self.entries if e["id"] == sid)
            e["enabled"] = not e.get("enabled")
            self.refresh(select=sid)

    def _add(self):
        from .library_dialog import pick_script
        path = pick_script(self.main, "Choose a script to schedule", parent=self)
        if not path:
            return
        e = sch.new_entry(os.path.abspath(path))
        self.entries.append(e)
        self.refresh(select=e["id"])
        self._load_form()

    def _remove(self):
        sid = self._sel_id()
        self.entries = [e for e in self.entries if e["id"] != sid]
        self.refresh()
        self._load_form()

    # ------------------------------------------------------------ form

    def _toggle_day(self, k):
        self._days ^= {k}
        self._show_days()

    def _show_days(self):
        for k, b in enumerate(self.day_sw):
            b.set_kind("on" if k in self._days else "glass")

    def _kind_changed(self, *_):
        k = sch.KIND_ID.get(self.cb_kind.currentText(), "daily")
        for w in (self.lab_time, self.e_time, self.lab_days, self.days_box):
            w.setVisible(k == "daily")
        for w in (self.lab_every, self.e_every, self.lab_min):
            w.setVisible(k == "interval")
        for w in (self.lab_once, self.e_once):
            w.setVisible(k == "once")
        for w in (self.lab_win, self.win_box):
            w.setVisible(k == "window")
        self.fit()

    def _load_form(self):
        e = self._sel()
        self.form.setEnabled(e is not None)
        self.btn_rm.setEnabled(e is not None)
        e = e or sch.new_entry("")
        self.cb_kind.setCurrentText(sch.KIND_LABEL[e["kind"]])
        self.e_time.setText(e.get("time", "09:00"))
        self._days = set(e.get("days") or [])
        self._show_days()
        self.e_every.setText(str(e.get("every_min", 30)))
        self.e_once.setText(e.get("once_at", ""))
        self.e_wtitle.setText(e.get("window_title", ""))
        self.e_wproc.setText(e.get("window_process", ""))
        self._kind_changed()

    def _apply_form(self):
        e = self._sel()
        if e is None:
            return
        new = dict(e, kind=sch.KIND_ID.get(self.cb_kind.currentText(), "daily"), time=self.e_time.text().strip(),
                   days=sorted(self._days), once_at=self.e_once.text().strip(),
                   window_title=self.e_wtitle.text().strip(), window_process=self.e_wproc.text().strip())
        try:
            new["every_min"] = int(self.e_every.text() or 0)
        except ValueError:
            new["every_min"] = 0
        err = sch.check(new)
        if err:
            self.msg.setText(err)
            return
        if new["kind"] != e["kind"] or new.get("time") != e.get("time") or new.get("once_at") != e.get("once_at"):
            new["last_run"] = None
        e.update(new)
        self.msg.setText(f"{os.path.splitext(os.path.basename(e['path']))[0]}: {sch.describe(e)}")
        self.refresh(select=e["id"])

    def accept(self):
        self._apply_form() if self._sel() is not None else None
        self.main.settings["schedule"] = self.entries
        self.main.save_settings()
        self.main.update_tray()
        n = sum(1 for e in self.entries if e.get("enabled"))
        self.main.set_status(f"{n} scheduled run{'s' if n != 1 else ''} on")
        super().accept()
