"""Phone remote control settings."""

import os
import secrets

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem

from . import dialogs
from .widgets import Caption, GlassButton, GlassSwitch


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    lab.setWordWrap(True)
    return lab


class RemoteDialog(dialogs.GlassDialog):
    def __init__(self, main):
        super().__init__(main, "Phone remote control")
        cfg = dict(main.settings.get("remote") or {})
        self.body.addWidget(detail("Control Clicker from the free ntfy phone app: send start, stop, status or "
                                   "screenshot to your topic and Clicker answers there. It works while Clicker is "
                                   "open or in the tray."))
        self.sw_on = GlassSwitch("Listen for commands from my phone")
        self.sw_on.setChecked(bool(cfg.get("enabled")))
        self.body.addWidget(self.sw_on)
        self.body.addWidget(Caption("Your topic"))
        row = QHBoxLayout()
        self.e_topic = QLineEdit(cfg.get("topic", ""))
        self.e_topic.setPlaceholderText("a long random name, e.g. clicker-remote-8f3k2q9x1m")
        self.e_topic.setMinimumWidth(360)
        row.addWidget(self.e_topic, 1)
        b = GlassButton("Make one up", small=True)
        b.clicked.connect(lambda: self.e_topic.setText("clicker-remote-" + secrets.token_hex(6)))
        row.addWidget(b)
        self.body.addLayout(row)
        self.body.addWidget(detail("Anyone who knows the topic can send commands, so keep it long and random and "
                                   "don't use your alerts topic. In the ntfy app tap +, subscribe to this topic, "
                                   "then send messages from it."))
        prow = QHBoxLayout()
        prow.addWidget(QLabel("PIN (optional)"))
        self.e_pin = QLineEdit(cfg.get("pin", ""))
        self.e_pin.setPlaceholderText("e.g. 4821")
        self.e_pin.setFixedWidth(110)
        prow.addWidget(self.e_pin)
        prow.addWidget(detail("then commands start with it: 4821 start mining"), 1)
        self.body.addLayout(prow)
        self.body.addWidget(Caption("Scripts your phone may start"))
        self.lst = QListWidget()
        self.lst.setMinimumHeight(110)
        for p in cfg.get("allowed") or []:
            self._add_item(p)
        self.body.addWidget(self.lst)
        arow = QHBoxLayout()
        for text, cmd in (("Add script...", self._add), ("Add the open script", self._add_open), ("Remove", self._rm)):
            b = GlassButton(text, small=True, kind="danger" if text == "Remove" else "glass")
            b.clicked.connect(cmd)
            arow.addWidget(b)
        arow.addStretch(1)
        self.body.addLayout(arow)
        self.body.addWidget(Caption("Web page on your Wi-Fi"))
        web = dict(main.settings.get("web") or {})
        self.sw_web = GlassSwitch("Show a control page to phones and PCs on my home network")
        self.sw_web.setChecked(bool(web.get("enabled")))
        self.body.addWidget(self.sw_web)
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("PIN"))
        self.e_wpin = QLineEdit(web.get("pin", ""))
        self.e_wpin.setPlaceholderText("at least 4 digits")
        self.e_wpin.setFixedWidth(130)
        wrow.addWidget(self.e_wpin)
        wrow.addWidget(QLabel("Port"))
        self.e_port = QLineEdit(str(web.get("port", 8765)))
        self.e_port.setFixedWidth(80)
        wrow.addWidget(self.e_port)
        wrow.addStretch(1)
        self.body.addLayout(wrow)
        self.body.addWidget(detail("Open the address below in your phone's browser while it's on the same Wi-Fi. "
                                   "Only local devices can connect, and it asks for the PIN. Windows may ask to "
                                   "allow Clicker through the firewall the first time: allow Private networks. "
                                   f"Now: {main.web_state}."))
        self.msg = detail("Commands: help, status, list, start NAME, stop, pause, resume, screenshot.")
        self.body.addWidget(self.msg)
        test = GlassButton("Send a test message", small=True)
        test.clicked.connect(self._test)
        self.body.addWidget(test, 0, Qt.AlignmentFlag.AlignLeft)
        self.add_buttons("Save")

    def _add_item(self, path):
        it = QListWidgetItem(f"{os.path.splitext(os.path.basename(path))[0]}    ·    {path}")
        it.setData(256, path)
        self.lst.addItem(it)

    def _paths(self):
        return [self.lst.item(k).data(256) for k in range(self.lst.count())]

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a script", "", "Clicker scripts (*.clk *.clkpkg *.json)")
        if path and os.path.abspath(path) not in self._paths():
            self._add_item(os.path.abspath(path))

    def _add_open(self):
        p = self.main.action_tab.path
        if not p:
            self.msg.setText("Save the open script first.")
        elif os.path.abspath(p) not in self._paths():
            self._add_item(os.path.abspath(p))

    def _rm(self):
        for it in self.lst.selectedItems():
            self.lst.takeItem(self.lst.row(it))

    def _test(self):
        topic = self.e_topic.text().strip()
        if not topic:
            self.msg.setText("Enter a topic first.")
            return
        self.main.remote_reply("Clicker remote control", "Connected. Send help for the commands.", topic=topic)
        self.msg.setText("Sent. It should show in the ntfy app under this topic.")

    def accept(self):
        topic = self.e_topic.text().strip()
        if self.sw_on.isChecked() and len(topic) < 12:
            self.msg.setText("Use a topic of at least 12 characters (Make one up makes a safe one).")
            return
        alerts_topic = ((self.main.settings.get("alerts") or {}).get("ntfy") or "").strip()
        if topic and topic == alerts_topic:
            self.msg.setText("Use a different topic from your alerts topic.")
            return
        wpin = self.e_wpin.text().strip()
        if self.sw_web.isChecked() and (len(wpin) < 4 or not wpin.isdigit()):
            self.msg.setText("The web page needs a PIN of at least 4 digits.")
            return
        try:
            port = int(self.e_port.text() or 8765)
            if not 1024 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.msg.setText("The port must be a number from 1024 to 65535.")
            return
        self.main.settings["remote"] = {"enabled": self.sw_on.isChecked(), "topic": topic,
                                        "pin": self.e_pin.text().strip(), "allowed": self._paths()}
        self.main.settings["web"] = {"enabled": self.sw_web.isChecked(), "pin": wpin, "port": port}
        self.main.save_settings()
        self.main.apply_remote()
        self.main.apply_web()
        if self.sw_web.isChecked():
            self.main.set_status(f"Web dashboard: {self.main.web_state}")
        super().accept()
