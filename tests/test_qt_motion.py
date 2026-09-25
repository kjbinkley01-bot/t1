import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from clicker.qt import glass, motion  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    m = motion.install(app)
    yield app
    app.removeEventFilter(m)


def wheel(widget, dy, pixel=QPoint(0, 0)):
    e = QWheelEvent(QPointF(10, 10), QPointF(10, 10), pixel, QPoint(0, dy), Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, e)


def pump(app, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def make_area():
    area = QScrollArea()
    lab = QLabel("tall")
    lab.setMinimumHeight(4000)
    area.setWidget(lab)
    area.resize(300, 300)
    area.show()
    return area


def test_wheel_notch_glides_instead_of_jumping(qapp):
    glass.set_motion(True)
    area = make_area()
    qapp.processEvents()
    bar = area.verticalScrollBar()
    wheel(area.viewport(), -120)
    qapp.processEvents()
    first = bar.value()
    pump(qapp, motion.SCROLL_MS + 150)
    target = QApplication.wheelScrollLines() * max(bar.singleStep(), 20)
    assert 0 <= first < target            # still on its way after the first frame
    assert bar.value() == target          # and it arrives exactly
    wheel(area.viewport(), -120)          # notches in a row add up
    wheel(area.viewport(), -120)
    pump(qapp, motion.SCROLL_MS + 150)
    assert bar.value() == target * 3


def test_trackpad_and_reduced_motion_are_left_to_qt(qapp):
    area = make_area()
    qapp.processEvents()
    bar = area.verticalScrollBar()
    wheel(area.viewport(), -120, pixel=QPoint(0, -40))   # trackpads send pixel deltas: already smooth
    assert not hasattr(bar, "_clicker_glide")
    glass.set_motion(False)
    try:
        wheel(area.viewport(), -120)
        assert not hasattr(bar, "_clicker_glide")
    finally:
        glass.set_motion(True)
