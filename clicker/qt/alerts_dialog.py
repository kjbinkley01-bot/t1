"""Alerts settings: which events send a message, and where to."""

import secrets
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit

from .. import alerts
from . import dialogs
from .widgets import Caption, GlassButton, GlassSwitch


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    lab.setWordWrap(True)
    return lab


class AlertsDialog(dialogs.GlassDialog):
    def __init__(self, main):
        super().__init__(main, "Alerts")
        cfg = alerts.config(main.settings)
        self.body.addWidget(detail("Get a message on your phone or in Discord when something needs you, so you "
                                   "don't have to watch the script. Clicker sends it straight from this PC."))
        self.body.addWidget(Caption("Send an alert when"))
        self.sw = {}
        for key, text in (("on_finished", "A script finishes"),
                          ("on_failed", "A script stops with an error"),
                          ("on_window", "Background mode can't find its window"),
                          ("on_trigger", "A trigger rule fires")):
            sw = GlassSwitch(text)
            sw.setChecked(bool(cfg.get(key)))
            self.sw[key] = sw
            self.body.addWidget(sw)

        self.body.addWidget(Caption("Send it to"))
        self.e_discord = QLineEdit(cfg.get("discord", ""))
        self.e_discord.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.e_discord.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.e_discord.setMinimumWidth(380)
        self._dest_row("Discord webhook", self.e_discord, "discord")
        self.body.addWidget(detail("In Discord: Server Settings > Integrations > Webhooks > New Webhook > Copy "
                                   "Webhook URL. Other https webhooks get a small JSON message."))
        self.e_ntfy = QLineEdit(cfg.get("ntfy", ""))
        self.e_ntfy.setPlaceholderText("a topic name, e.g. clicker-7f3k9q2m")
        make = GlassButton("Make one up", small=True)
        make.clicked.connect(lambda: self.e_ntfy.setText("clicker-" + secrets.token_hex(5)))
        self._dest_row("Phone (ntfy)", self.e_ntfy, "ntfy", make)
        self.body.addWidget(detail("Install the free ntfy app, tap + and subscribe to the same topic. Anyone who "
                                   "knows the topic can read it, so keep it hard to guess."))

        self.body.addWidget(Caption("Include"))
        self.sw_shot = GlassSwitch("The screenshot from the run log (when a run fails)")
        self.sw_shot.setChecked(bool(cfg.get("screenshot")))
        self.sw_log = GlassSwitch(f"The last {alerts.LOG_TAIL} log lines")
        self.sw_log.setChecked(bool(cfg.get("log_lines")))
        self.body.addWidget(self.sw_shot)
        self.body.addWidget(self.sw_log)
        q = QHBoxLayout()
        self.sw_quiet = GlassSwitch("Quiet hours: no alerts from")
        self.sw_quiet.setChecked(bool(cfg.get("quiet")))
        self.e_from = QLineEdit(cfg.get("quiet_from", "23:00"))
        self.e_to = QLineEdit(cfg.get("quiet_to", "07:00"))
        for e in (self.e_from, self.e_to):
            e.setFixedWidth(64)
        q.addWidget(self.sw_quiet)
        q.addWidget(self.e_from)
        q.addWidget(QLabel("to"))
        q.addWidget(self.e_to)
        q.addStretch(1)
        self.body.addLayout(q)
        self.msg = detail("")
        self.body.addWidget(self.msg)
        self.add_buttons("Save")
        self._pending = None
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check_test)

    def _dest_row(self, label, edit, key, extra=None):
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setFixedWidth(120)
        row.addWidget(lab)
        row.addWidget(edit, 1)
        if extra is not None:
            row.addWidget(extra)
        b = GlassButton("Send test", small=True)
        b.clicked.connect(lambda: self._test(key))
        row.addWidget(b)
        self.body.addLayout(row)

    def _values(self):
        v = {k: sw.isChecked() for k, sw in self.sw.items()}
        v.update(discord=self.e_discord.text().strip(), ntfy=self.e_ntfy.text().strip(),
                 screenshot=self.sw_shot.isChecked(), log_lines=self.sw_log.isChecked(),
                 quiet=self.sw_quiet.isChecked(), quiet_from=self.e_from.text().strip() or "23:00",
                 quiet_to=self.e_to.text().strip() or "07:00")
        return v

    def _test(self, key):
        cfg = dict(alerts.DEFAULTS, **self._values())
        other = "ntfy" if key == "discord" else "discord"
        cfg[other] = ""
        if not cfg[key]:
            self.msg.setText("Enter a webhook URL or ntfy topic first.")
            return
        self.msg.setText("Sending...")
        box = []
        threading.Thread(target=lambda: box.append(alerts.send(cfg, alerts.test_event())), daemon=True).start()
        self._pending = box
        self._poll.start(150)

    def _check_test(self):
        if not self._pending:
            return
        res = self._pending[0]
        self._poll.stop()
        self._pending = None
        name, err = res[0]
        self.msg.setText(f"{name}: sent. Check your phone or channel." if err is None else f"{name}: {err}")

    def accept(self):
        v = self._values()
        for e in (v["quiet_from"], v["quiet_to"]):
            if alerts._minutes(e) is None:
                self.msg.setText("Quiet hours need times like 23:00.")
                return
        self.main.settings["alerts"] = v
        self.main.save_settings()
        self.main.set_status("Alerts saved" + ("" if alerts.configured(v) else " (no destination yet)"))
        super().accept()


def open_alerts(main):
    AlertsDialog(main).exec()
