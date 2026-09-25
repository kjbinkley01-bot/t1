"""History tab in the Liquid Glass look: how runs went, from the run history file."""

import csv
import datetime
import os
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import history, runlog
from .glass import GlassPanel, font
from .widgets import Caption, GlassButton, mode_of

OK_COLOR = QColor("#4fa8ff")
FAIL_COLOR = QColor("#ff9f0a")
RANGES = [("7 days", 7), ("14 days", 14), ("30 days", 30), ("All", None)]


def detail(text=""):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    return lab


class Tile(GlassPanel):
    def __init__(self, caption):
        super().__init__(radius=24)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)
        lay.addWidget(Caption(caption))
        self.value = QLabel("-")
        self.value.setFont(font(20, QFont.Weight.Bold))
        self.sub = detail()
        self.sub.setWordWrap(True)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value, sub="", small=False):
        self.value.setFont(font(13 if small else 20, QFont.Weight.Bold))
        self.value.setText(value)
        self.sub.setText(sub)


class DayChart(QWidget):
    """Stacked bars: finished (blue) under failed (orange), one per day."""

    def __init__(self):
        super().__init__()
        self.days = []
        self.setMinimumHeight(170)

    def set_days(self, days):
        self.days = days
        self.update()

    def paintEvent(self, _e):
        m = mode_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = h - 22
        n = max(1, len(self.days))
        peak = max([ok + bad for _d, ok, bad in self.days] + [1])
        slot = w / n
        bw = max(4.0, min(28.0, slot * 0.62))
        p.setPen(m.line)
        p.drawLine(0, base, w, base)
        p.setFont(font(8))
        for i, (d, ok, bad) in enumerate(self.days):
            x = i * slot + (slot - bw) / 2
            total_h = (base - 6) * (ok + bad) / peak
            fail_h = (base - 6) * bad / peak
            p.setPen(Qt.PenStyle.NoPen)
            if ok + bad:
                p.setBrush(OK_COLOR)
                p.drawRoundedRect(QRectF(x, base - total_h, bw, total_h), 4, 4)
            if bad:
                p.setBrush(FAIL_COLOR)
                p.drawRoundedRect(QRectF(x, base - total_h, bw, fail_h), 4, 4)
            if i in (0, n // 2, n - 1):
                p.setPen(m.detail)
                p.drawText(QRectF(i * slot - 20, base + 4, slot + 40, 16), Qt.AlignmentFlag.AlignHCenter,
                           d.strftime("%b %d"))
        if not any(ok + bad for _d, ok, bad in self.days):
            p.setPen(m.detail)
            p.setFont(font(10))
            p.drawText(QRectF(0, 0, w, base), Qt.AlignmentFlag.AlignCenter, "No runs in this period")


class FailBars(QWidget):
    """Horizontal bars: where failed runs stopped."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(150)

    def set_rows(self, rows):
        self.rows = rows
        self.setMinimumHeight(max(60, 42 * len(rows)))
        self.update()

    def paintEvent(self, _e):
        m = mode_of(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        if not self.rows:
            p.setPen(m.detail)
            p.setFont(font(10))
            p.drawText(QRectF(0, 0, w, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "No failed runs. Nice.")
            return
        peak = max(c for _n, c in self.rows)
        y = 0
        for name, count in self.rows:
            p.setPen(m.text)
            p.setFont(font(9.5))
            fm = p.fontMetrics()
            p.drawText(QRectF(0, y, w - 30, 18), Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, int(w - 34)))
            p.drawText(QRectF(w - 30, y, 30, 18), Qt.AlignmentFlag.AlignRight, str(count))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(m.well)
            p.drawRoundedRect(QRectF(0, y + 21, w, 10), 5, 5)
            p.setBrush(FAIL_COLOR)
            p.drawRoundedRect(QRectF(0, y + 21, max(10.0, w * count / peak), 10), 5, 5)
            y += 42


class HistoryTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.days = 14
        self.entries = []
        self.shown = []
        self._build()
        self.reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        bar = GlassPanel(radius=26)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(8)
        self.cb_script = QComboBox()
        self.cb_script.setMinimumWidth(240)
        self.cb_script.currentIndexChanged.connect(lambda *_: self.refresh())
        bl.addWidget(self.cb_script)
        self.range_btns = []
        for text, days in RANGES:
            b = GlassButton(text, small=True)
            b.clicked.connect(lambda _=False, d=days: self.set_range(d))
            self.range_btns.append((b, days))
            bl.addWidget(b)
        bl.addStretch(1)
        for text, ic, cmd in (("Refresh", "arrow-clockwise", self.reload), ("Export CSV", "floppy-disk", self.export),
                              ("Open logs folder", "folder-open", lambda: runlog.open_folder(runlog.logs_dir())),
                              ("Clear", "trash", self.clear)):
            b = GlassButton(text, icon=ic)
            b.clicked.connect(cmd)
            bl.addWidget(b)
        root.addWidget(bar)

        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.t_runs, self.t_rate = Tile("Runs"), Tile("Success rate")
        self.t_avg, self.t_top = Tile("Average run"), Tile("Fails most at")
        for i, t in enumerate((self.t_runs, self.t_rate, self.t_avg, self.t_top)):
            tiles.addWidget(t, 0, i)
            tiles.setColumnStretch(i, 1)
        root.addLayout(tiles)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        chart = GlassPanel(radius=26)
        cl = QVBoxLayout(chart)
        cl.setContentsMargins(20, 14, 20, 14)
        head = QHBoxLayout()
        head.addWidget(Caption("Runs per day"))
        head.addStretch(1)
        for text, c in (("Finished", OK_COLOR), ("Failed", FAIL_COLOR)):
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background: {c.name()}; border-radius: 3px;")
            head.addWidget(sw)
            head.addWidget(detail(text))
        cl.addLayout(head)
        self.chart = DayChart()
        cl.addWidget(self.chart, 1)
        mid.addWidget(chart, 3)
        where = GlassPanel(radius=26)
        wl = QVBoxLayout(where)
        wl.setContentsMargins(20, 14, 20, 14)
        wl.setSpacing(10)
        wl.addWidget(Caption("Where failed runs stopped"))
        self.fails = FailBars()
        wl.addWidget(self.fails)
        wl.addStretch(1)
        self.btn_open_step = GlassButton("Open that step", icon="list-bullets", small=True)
        self.btn_open_step.clicked.connect(self.open_top_step)
        wl.addWidget(self.btn_open_step, 0, Qt.AlignmentFlag.AlignLeft)
        where.setMinimumWidth(360)
        mid.addWidget(where, 2)
        root.addLayout(mid)

        runs = GlassPanel(radius=26)
        rl = QVBoxLayout(runs)
        rl.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        head.addWidget(Caption("Recent runs"))
        head.addStretch(1)
        head.addWidget(detail("Double-click a run to open its log folder"))
        rl.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["When", "Script", "Result", "Time", "Reached", "Reason"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(220)
        hdr = self.tree.header()
        for c, wdt in enumerate((130, 200, 90, 90, 200)):
            self.tree.setColumnWidth(c, wdt)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._open_log)
        rl.addWidget(self.tree)
        root.addWidget(runs, 1)

    # ------------------------------------------------------------ data

    def set_range(self, days):
        self.days = days
        self.refresh()

    def reload(self):
        self.entries = history.load()
        cur = self.cb_script.currentData()
        self.cb_script.blockSignals(True)
        self.cb_script.clear()
        self.cb_script.addItem("All scripts", None)
        for name in history.scripts(self.entries):
            self.cb_script.addItem(name, name)
        i = self.cb_script.findData(cur)
        self.cb_script.setCurrentIndex(max(0, i))
        self.cb_script.blockSignals(False)
        self.refresh()

    def refresh(self):
        for b, d in self.range_btns:
            b.set_kind("on" if d == self.days else "glass")
        script = self.cb_script.currentData()
        self.shown = history.select(self.entries, self.days, script)
        st = history.stats(self.shown, days=self.days or 30)
        per_day = st["runs"] / max(1, self.days or max(1, len(st["per_day"])))
        self.t_runs.set(str(st["runs"]), f"about {per_day:.0f} a day" if st["runs"] else "none yet")
        if st["success_rate"] is None:
            self.t_rate.set("-", "no finished or failed runs")
        else:
            extra = f" · {st['stopped']} stopped by you" if st["stopped"] else ""
            self.t_rate.set(f"{st['success_rate'] * 100:.0f}%", f"{st['finished']} finished · {st['failed']} failed{extra}")
        self.t_avg.set(history.fmt_duration(st["avg_seconds"]),
                       f"fastest {history.fmt_duration(st['fastest_seconds'])}" if st["fastest_seconds"] else "")
        top = st["top_fail"]
        self.t_top.set(top[0] if top else "Nothing failed", f"{top[1]} of {st['failed']} failures" if top else "",
                       small=True)
        self.chart.set_days(st["per_day"])
        self.fails.set_rows(st["where_failed"])
        self._top = top
        self.btn_open_step.setVisible(bool(top and self._top_entry()))
        self.tree.clear()
        dark = self.main.mode.dark
        for e in reversed(self.shown[-300:]):
            when = datetime.datetime.fromtimestamp(e["ts"])
            today = datetime.date.today()
            day = "Today" if when.date() == today else (
                "Yesterday" if when.date() == today - datetime.timedelta(days=1) else when.strftime("%b %d"))
            res = e["result"].capitalize()
            reached = (f"step {e['step']}" if e.get("step") else
                       ("all steps" if e["result"] == "finished" else ""))
            it = QTreeWidgetItem([f"{day} {when:%H:%M}", e.get("script") or "", res,
                                  history.fmt_duration(e.get("seconds")), reached,
                                  "" if e["result"] == "finished" else (e.get("reason") or "")])
            color = {"finished": OK_COLOR if dark else QColor("#0064b8"),
                     "failed": FAIL_COLOR if dark else QColor("#b35c00")}.get(e["result"])
            if color is not None:
                it.setForeground(2, color)
            it.setData(0, Qt.ItemDataRole.UserRole, e.get("log_dir"))
            self.tree.addTopLevelItem(it)

    def _top_entry(self):
        top = getattr(self, "_top", None)
        if not top:
            return None
        for e in reversed(self.shown):
            if e.get("step_desc") == top[0] and e.get("path") and os.path.exists(e["path"]):
                return e
        return None

    def open_top_step(self):
        e = self._top_entry()
        if not e:
            return
        tab = self.main.action_tab
        if os.path.abspath(tab.path or "") != os.path.abspath(e["path"]):
            if self.main.job_running_for(tab) or not tab.confirm_discard("opening that script"):
                return
            tab.open_path(e["path"])
        tab.select_step(e["step"] - 1)
        self.main.show_tab("actions")

    def _open_log(self, item, _col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d and os.path.isdir(d):
            runlog.open_folder(d)
        else:
            self.main.set_status("That run's log folder was cleaned up (only the latest runs keep logs).",
                                 error=True)

    def export(self):
        if not self.shown:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export run history", "run_history.csv", "CSV (*.csv)")
        if not path:
            return
        cols = ["when", "script", "result", "seconds", "passes", "step", "step_desc", "reason", "window", "path"]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for e in self.shown:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"]))]
                               + [e.get(c, "") for c in cols[1:]])
        except OSError as err:
            QMessageBox.warning(self, "Could not export", str(err))
            return
        self.main.set_status(f"Exported {len(self.shown)} runs")

    def clear(self):
        if QMessageBox.question(self, "Clear run history?", "Forget every recorded run? Run log folders stay.") \
                != QMessageBox.StandardButton.Yes:
            return
        history.clear()
        self.reload()

    # ------------------------------------------------------------ tab protocol

    def on_job(self, kind, payload):
        pass

    def update_state(self, running_mine, running_any, paused):
        pass

    def title_text(self):
        return "Run history"
