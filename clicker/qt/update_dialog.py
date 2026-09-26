"""Update available: what's new, and Install and restart (download, check, run the installer)."""

import re
import threading
import webbrowser

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QTextBrowser, QWidget

from .. import model, updates
from . import dialogs, glass
from .widgets import GlassButton, mode_of


def detail(text):
    lab = QLabel(text)
    lab.setProperty("role", "detail")
    lab.setWordWrap(True)
    return lab


def tidy_notes(text):
    """GitHub's generated notes, without the "Full Changelog" link and pull request links."""
    text = re.sub(r"\*\*Full Changelog\*\*:.*", "", text or "")
    text = re.sub(r"(?m)^#+ What's Changed\s*$", "", text)
    text = re.sub(r" by @[\w-]+ in https://\S+", "", text)
    return text.strip() or "No notes for this version."


class ProgressBar(QWidget):
    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.setFixedHeight(6)

    def set_value(self, v):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(255, 255, 255, 40) if mode_of(self).dark else QColor(0, 0, 0, 30))
        p.drawRoundedRect(r, 3, 3)
        if self.value > 0:
            p.setBrush(glass.ACCENT)
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(6.0, r.width() * self.value), r.height()), 3, 3)
        p.end()


class UpdateDialog(dialogs.GlassDialog):
    progress = Signal(int, int)
    finished_download = Signal(object)   # the installer's path, or a DownloadFailed

    def __init__(self, main, release):
        super().__init__(main, "Update available")
        self.release = release
        self.how = updates.install_mode()  # not .mode: widgets read their colors from window().mode
        self.asset = updates.installer_asset(release)
        self.stop = threading.Event()
        self.installer = None
        tag = release.get("tag", "")
        self.body.addWidget(QLabel(f"Clicker {tag.lstrip('v')} is ready. You have {model.APP_VERSION}."))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(tidy_notes(release.get("notes")))
        notes.setMinimumSize(460, 180)
        notes.setMaximumHeight(280)
        notes.setStyleSheet("QTextBrowser { background: rgba(0,0,0,40); border: 1px solid rgba(255,255,255,30); "
                            "border-radius: 10px; padding: 6px; }")
        self.body.addWidget(notes)
        self.bar = ProgressBar()
        self.bar.hide()
        self.body.addWidget(self.bar)
        self.lbl = detail("")
        self.body.addWidget(self.lbl)

        self.btn_skip = GlassButton("Skip this version")
        self.btn_skip.clicked.connect(self._skip)
        self.buttons.insertWidget(0, self.btn_skip)
        self.btn_later = GlassButton("Later")
        self.btn_later.clicked.connect(self.reject)
        self.buttons.addWidget(self.btn_later)
        if updates.can_install(release, self.how):
            self.lbl.setText("Clicker closes, installs the update and opens again. Your scripts, rules and "
                             "settings stay as they are.")
            self.btn_go = GlassButton("Install and restart", icon="download-simple", kind="primary")
            self.btn_go.clicked.connect(self._install)
        else:
            self.lbl.setText("Download the new version from its release page." if self.how else
                             "This copy can't update itself (it isn't the installed Windows app), so download "
                             "the new version from its release page.")
            self.btn_go = GlassButton("Open download page", icon="download-simple", kind="primary")
            self.btn_go.clicked.connect(self._open_page)
        self.buttons.addWidget(self.btn_go)
        self.progress.connect(self._on_progress)
        self.finished_download.connect(self._on_downloaded)

    def _skip(self):
        self.main.settings["skip_update"] = self.release.get("tag")
        self.main.save_settings()
        self.main.btn_update.hide()
        self.reject()

    def _open_page(self):
        webbrowser.open(self.release.get("url") or f"https://github.com/{updates.DEFAULT_REPO}/releases")
        self.accept()

    def _install(self):
        self.btn_go.setEnabled(False)
        self.btn_skip.setEnabled(False)
        self.btn_later.setText("Cancel")
        self.bar.set_value(0)
        self.bar.show()
        self.lbl.setText("Downloading...")
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self):
        try:
            path = updates.download(self.asset, progress=lambda d, t: self.progress.emit(d, t), stop=self.stop)
        except updates.DownloadFailed as e:
            path = e
        self.finished_download.emit(path)

    def _on_progress(self, done, total):
        mb = 1024 * 1024
        if total:
            self.bar.set_value(done / total)
            self.lbl.setText(f"Downloading... {done / mb:.0f} of {total / mb:.0f} MB")
        else:
            self.lbl.setText(f"Downloading... {done / mb:.0f} MB")

    def _on_downloaded(self, result):
        if not self.isVisible():
            return
        if isinstance(result, Exception):
            self.bar.hide()
            self.lbl.setText(str(result))
            self.btn_go.setEnabled(True)
            self.btn_skip.setEnabled(True)
            self.btn_later.setText("Later")
            return
        self.bar.set_value(1)
        self.lbl.setText("Downloaded and checked. Closing Clicker to install...")
        self.installer = result
        self.accept()

    def done(self, result):
        if not self.installer:
            self.stop.set()      # closed while downloading: stop the download
        super().done(result)


def show_update(main, release):
    """Show the dialog; if the update was downloaded, close Clicker and run the installer."""
    d = UpdateDialog(main, release)
    d.exec()
    if d.installer:
        main.install_update(d.installer, d.how)
