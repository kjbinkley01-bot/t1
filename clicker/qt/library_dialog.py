"""The Library: open scripts and recordings from cards instead of a file dialog.

Recently used files come first, favorites (the star) have their own row, and the search box filters as
you type. Enter opens the highlighted card; arrow keys move between cards.
"""

import math
import os

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import library, runlog
from . import dialogs, glass
from .flowchart import group_color
from .glass import font, icon_pixmap
from .widgets import Caption, GlassButton, mode_of

CARD_W, CARD_H = 216, 196
THUMB_H = 118
FILTERS = [("all", "All"), ("script", "Scripts"), ("recording", "Recordings"), ("favorites", "Favorites")]
_pixmaps = {}


def thumb_pixmap(path):
    """A saved thumbnail, cached until the file changes."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return None
    hit = _pixmaps.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    pm = QPixmap(path)
    if pm.isNull():
        return None
    if len(_pixmaps) > 300:
        _pixmaps.clear()
    _pixmaps[path] = (stamp, pm)
    return pm


def star_path(cx, cy, r):
    path = QPainterPath()
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.45
        pt = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
        path.moveTo(pt) if k == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


class LibraryCard(QWidget):
    opened = Signal(dict)
    starred = Signal(dict)
    menu = Signal(dict, object)

    def __init__(self, lib, entry):
        super().__init__()
        self.lib, self.entry = lib, entry
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.selected = False
        self._hover = 0.0
        tip = entry["path"] + ("\n(file not found)" if entry.get("missing") else "")
        self.setToolTip(tip)

    def _star_rect(self):
        return QRectF(CARD_W - 40, 14, 26, 26)

    def enterEvent(self, e):
        glass.animate(self, self._hover, 1.0, glass.FAST, self._set_hover, attr="_hanim")
        super().enterEvent(e)

    def leaveEvent(self, e):
        glass.animate(self, self._hover, 0.0, glass.BASE, self._set_hover, attr="_hanim")
        super().leaveEvent(e)

    def _set_hover(self, v):
        self._hover = float(v)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.menu.emit(self.entry, e.globalPosition().toPoint())
        elif self._star_rect().contains(e.position()):
            self.starred.emit(self.entry)
        else:
            self.window().select_card(self)

    def mouseDoubleClickEvent(self, e):
        if not self._star_rect().contains(e.position()):
            self.opened.emit(self.entry)

    def paintEvent(self, _e):
        m = mode_of(self)
        e = self.entry
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if e.get("missing"):
            p.setOpacity(0.45)
        lift = self._hover
        card = QRectF(4, 4 - 2 * lift, CARD_W - 8, CARD_H - 8)
        p.setPen(QPen(QColor(glass.ACCENT), 2) if self.selected else
                 QPen(QColor(255, 255, 255, int(40 + 50 * lift)), 1))
        p.setBrush(QColor(255, 255, 255, int(14 + 16 * lift) if m.dark else int(120 + 60 * lift)))
        p.drawRoundedRect(card, 18, 18)
        # thumbnail
        tr = QRectF(card.x() + 8, card.y() + 8, card.width() - 16, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(tr, 12, 12)
        p.save()
        p.setClipPath(clip)
        p.fillRect(tr, QColor(0, 0, 0, 70))
        pm = thumb_pixmap(self.lib.thumb_path(e)) if e.get("thumb") else None
        if pm is not None:
            k = max(tr.width() / pm.width(), tr.height() / pm.height())
            w, h = pm.width() * k, pm.height() * k
            p.drawPixmap(QRectF(tr.center().x() - w / 2, tr.center().y() - h / 2, w, h), pm, QRectF(pm.rect()))
        elif e.get("kind") == "recording":
            self._paint_timeline(p, tr, e)
        else:
            self._paint_steps(p, tr, e)
        p.restore()
        # kind badge and star
        badge = "Recording" if e.get("kind") == "recording" else "Script"
        p.setFont(font(7.5, QFont.Weight.DemiBold))
        bw = QFontMetrics(p.font()).horizontalAdvance(badge) + 14
        br = QRectF(tr.x() + 8, tr.bottom() - 26, bw, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(br, 9, 9)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)
        fav = bool(e.get("favorite"))
        if fav or lift > 0.01:
            sr = self._star_rect().translated(0, -2 * lift)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(120 * (1 if fav else lift))))
            p.drawEllipse(sr)
            star = star_path(sr.center().x(), sr.center().y() + 0.5, 8)
            if fav:
                p.setBrush(QColor("#ffd60a"))
                p.drawPath(star)
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, int(220 * lift)), 1.4))
                p.drawPath(star)
        # text
        x, y, w = card.x() + 12, tr.bottom() + 10, card.width() - 24
        p.setPen(m.text)
        f = font(10, QFont.Weight.DemiBold)
        p.setFont(f)
        name = QFontMetrics(f).elidedText(e.get("name") or os.path.basename(e["path"]),
                                          Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QRectF(x, y, w, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        f2 = font(8.5)
        p.setFont(f2)
        p.setPen(m.detail)
        line = "File not found" if e.get("missing") else f"{e.get('detail', '')} · {library.when_text(e.get('used'))}"
        line = QFontMetrics(f2).elidedText(line, Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QRectF(x, y + 21, w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)
        p.end()

    def _paint_steps(self, p, r, e):
        """No picture: the first few steps as a tiny flow of colored pills."""
        acts = e.get("actions") or []
        if not acts:
            p.setPen(QColor(255, 255, 255, 120))
            p.setFont(font(8.5))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Empty script")
            return
        rows = acts[:4]
        h, gap = 14, 7
        area = r.height() - 34  # keep clear of the badge in the bottom corner
        top = r.y() + 6 + (area - (len(rows) * h + (len(rows) - 1) * gap)) / 2
        for k, a in enumerate(rows):
            c = QColor(group_color(a))
            y = top + k * (h + gap)
            w = r.width() * (0.62 - 0.05 * (k % 3))
            box = QRectF(r.x() + 22 + (k % 2) * 10, y, w, h)
            c.setAlpha(200)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(20, 20, 40, 220))
            p.setFont(font(6.5, QFont.Weight.DemiBold))
            p.drawText(box.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, a)

    def _paint_timeline(self, p, r, e):
        """No picture: the recording as a little timeline of clicks and key presses."""
        mid = r.y() + r.height() * 0.42
        x0, x1 = r.x() + 16, r.right() - 16
        p.setPen(QPen(QColor(255, 255, 255, 60), 2))
        p.drawLine(QPointF(x0, mid), QPointF(x1, mid))
        for t in e.get("clicks") or []:
            x = x0 + (x1 - x0) * t
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(90, 160, 255, 230))
            p.drawEllipse(QPointF(x, mid), 4, 4)
        for t in e.get("keys") or []:
            x = x0 + (x1 - x0) * t
            p.setBrush(QColor(170, 130, 255, 210))
            p.drawRoundedRect(QRectF(x - 2, mid + 10, 4, 10), 2, 2)


class LibraryDialog(dialogs.GlassDialog):
    """Pick a script or recording. After exec: .chosen (an entry), or .browse is True, or neither."""

    def __init__(self, main, kind=None):
        super().__init__(main, "Library")
        self.lib = main.library
        self.chosen, self.browse = None, False
        self.filter = kind if kind in ("script", "recording") else "all"
        self.browse_kind = kind or "script"
        self.cards, self.sel = [], None
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search scripts and recordings")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(300)
        self.search.addAction(QIcon(icon_pixmap("magnifying-glass", main.mode.detail, 16,
                                                      self.devicePixelRatioF())),
                              QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.search.installEventFilter(self)
        top.addWidget(self.search, 1)
        self.chips = {}
        for key, text in FILTERS:
            b = GlassButton(text, small=True, kind="on" if key == self.filter else "glass")
            b.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.chips[key] = b
            top.addWidget(b)
        top.addSpacing(10)
        b = GlassButton("Add folder...", icon="folder-open", small=True,
                        tip="Add every script and recording in a folder")
        b.clicked.connect(self.add_folder)
        top.addWidget(b)
        b = GlassButton("Browse files...", icon="file-plus", small=True, tip="Open a file that isn't in the Library")
        b.clicked.connect(self._browse)
        top.addWidget(b)
        self.body.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumSize(4 * CARD_W + 40, 2 * CARD_H + 90)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.holder = QWidget()
        self.grid = QVBoxLayout(self.holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.scroll.setWidget(self.holder)
        self.body.addWidget(self.scroll, 1)
        self.hint = QLabel("Double-click a card (or press Enter) to open it. Right-click for more.")
        self.hint.setProperty("role", "detail")
        self.body.addWidget(self.hint)
        self.add_buttons("Open", "Close")
        self.refresh()
        self.search.setFocus()

    # ------------------------------------------------------------ content

    def set_filter(self, key):
        self.filter = key
        for k, b in self.chips.items():
            b.set_kind("on" if k == key else "glass")
        self.refresh()

    def refresh(self):
        q = self.search.text()
        kind = self.filter if self.filter in ("script", "recording") else None
        entries = self.lib.list(q, kind=kind, favorites=self.filter == "favorites")
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()  # gone now, not when Qt gets round to deleting it
                w.deleteLater()
        self.cards, self.sel = [], None
        if not entries:
            msg = ("Nothing matches your search." if q else
                   "No favorites yet: click the star on a card." if self.filter == "favorites" else
                   "Scripts and recordings you open or save show up here.\n"
                   "Use Add folder... to bring in a whole folder at once.")
            lab = QLabel(msg)
            lab.setProperty("role", "detail")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(lab, 1)
            return
        if not q and self.filter != "favorites":
            favs = [e for e in entries if e.get("favorite")]
            rest = [e for e in entries if not e.get("favorite")]
            if favs:
                self._section("Favorites", favs)
            if rest:
                self._section("Recent" if favs else "", rest)
        else:
            self._section("", entries)
        self.grid.addStretch(1)
        if self.cards:
            self.select_card(self.cards[0])

    def _section(self, title, entries):
        if title:
            self.grid.addWidget(Caption(title))
        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        for i, e in enumerate(entries):
            card = LibraryCard(self.lib, e)
            card.opened.connect(self.open_entry)
            card.starred.connect(self.toggle_star)
            card.menu.connect(self.card_menu)
            g.addWidget(card, i // 4, i % 4, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.cards.append(card)
        g.setColumnStretch(4, 1)
        self.grid.addWidget(box)

    def select_card(self, card):
        if self.sel is not None and self.sel in self.cards:
            self.sel.selected = False
            self.sel.update()
        self.sel = card
        card.selected = True
        card.update()
        self.scroll.ensureWidgetVisible(card, 10, 10)

    # ------------------------------------------------------------ actions

    def open_entry(self, e):
        if e.get("missing"):
            if QMessageBox.question(self, "File not found", f"{e['path']}\n\nis missing. Remove it from the Library?") \
                    == QMessageBox.StandardButton.Yes:
                self.lib.forget(e["path"])
                self.lib.save()
                self.refresh()
            return
        self.chosen = e
        super().accept()

    def accept(self):  # the Open button
        if self.sel is not None:
            self.open_entry(self.sel.entry)

    def toggle_star(self, e):
        self.lib.set_favorite(e["path"], not e.get("favorite"))
        self.lib.save()
        self.refresh()

    def card_menu(self, e, pos):
        m = QMenu(self)
        m.addAction("Open", lambda: self.open_entry(e))
        if e.get("kind") == "script" and not e.get("missing"):
            m.addAction("Run now", lambda: (self.main.run_script_hotkey(e["path"], from_menu=True), self.reject()))
        m.addAction("Remove star" if e.get("favorite") else "Add to favorites", lambda: self.toggle_star(e))
        m.addAction("Show in folder", lambda: runlog.open_folder(os.path.dirname(e["path"])))
        m.addSeparator()
        m.addAction("Remove from Library", lambda: self._forget(e))
        m.exec(pos)

    def _forget(self, e):
        self.lib.forget(e["path"])
        self.lib.save()
        self.refresh()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add a folder to the Library")
        if not folder:
            return
        n = self.lib.add_folder(folder)
        self.lib.save()
        self.hint.setText(f"Added {n} file{'s' if n != 1 else ''} from {os.path.basename(folder) or folder}."
                          if n else "No new scripts or recordings in that folder.")
        self.refresh()

    def _browse(self):
        self.browse = True
        super().accept()

    # ------------------------------------------------------------ keys

    def eventFilter(self, obj, e):
        if obj is self.search and e.type() == QEvent.Type.KeyPress and self.cards:
            k = e.key()
            moves = {Qt.Key.Key_Right: 1, Qt.Key.Key_Left: -1, Qt.Key.Key_Down: 4, Qt.Key.Key_Up: -4}
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up) or (k in moves and not self.search.text()):
                i = self.cards.index(self.sel) if self.sel in self.cards else 0
                self.select_card(self.cards[max(0, min(len(self.cards) - 1, i + moves[k]))])
                return True
        return super().eventFilter(obj, e)

    def sizeHint(self):
        return QSize(4 * CARD_W + 120, 2 * CARD_H + 260)
