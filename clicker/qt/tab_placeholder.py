"""Stand-in for tabs that haven't moved to the glass look yet."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .glass import GlassPanel, font
from .widgets import GlassButton


class PlaceholderTab(QWidget):
    def __init__(self, main, title):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        card = GlassPanel(radius=30)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(40, 40, 40, 40)
        cl.setSpacing(12)
        cl.addStretch(1)
        t = QLabel(title)
        t.setFont(font(18, QFont.Weight.Bold))
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d = QLabel("This tab moves to the Liquid Glass look in the next stage.\n"
                   "Until then it works as before in the Classic look.")
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setProperty("role", "detail")
        b = GlassButton("Open Classic look", icon="arrow-clockwise")
        b.clicked.connect(main.switch_to_classic)
        cl.addWidget(t)
        cl.addWidget(d)
        cl.addSpacing(8)
        cl.addWidget(b, 0, Qt.AlignmentFlag.AlignCenter)
        cl.addStretch(1)
        lay.addWidget(card)

    def update_state(self, *_a):
        pass

    def title_text(self):
        return ""
