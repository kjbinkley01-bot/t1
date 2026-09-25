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


def test_button_style_changes_cross_fade(qapp):
    from clicker.qt.widgets import GlassButton
    glass.set_motion(True)
    b = GlassButton("Start", icon="play", kind="primary")
    b.show()
    b.set_kind("record")
    qapp.processEvents()
    assert b._old_kind == "primary" and b._blend < 1.0   # both styles show, blending
    b.grab()                                               # and it paints mid blend
    pump(qapp, glass.BASE + 150)
    assert b._old_kind is None and b._blend == 1.0


def test_disabling_a_button_dims_it_gradually(qapp):
    from clicker.qt.widgets import GlassButton
    b = GlassButton("Stop")
    b.show()
    qapp.processEvents()
    b.setEnabled(False)
    qapp.processEvents()
    assert 0.55 < b._dim <= 1.0
    pump(qapp, glass.FAST + 150)
    assert b._dim == pytest.approx(0.55)


def test_scroll_to_jumps_become_glides(qapp):
    from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
    glass.set_motion(True)
    tree = QTreeWidget()
    for i in range(300):
        QTreeWidgetItem(tree, [str(i)])
    tree.resize(300, 300)
    tree.show()
    qapp.processEvents()
    bar = tree.verticalScrollBar()
    target = tree.topLevelItem(250)
    motion.smoothly(tree, lambda: tree.scrollToItem(target))
    assert bar.value() == 0                     # the jump itself is never shown
    pump(qapp, motion.SCROLL_MS + 150)
    assert bar.value() > 0
    rect = tree.visualItemRect(target)
    assert 0 <= rect.top() < tree.viewport().height()  # and it ends with the item in view


def test_text_boxes_scroll_the_usual_way(qapp):
    from PySide6.QtWidgets import QPlainTextEdit
    glass.set_motion(True)
    ed = QPlainTextEdit("\n".join(str(i) for i in range(500)))
    ed.resize(300, 200)
    ed.show()
    qapp.processEvents()
    wheel(ed.viewport(), -120)
    assert not hasattr(ed.verticalScrollBar(), "_clicker_glide")   # lines, not pixels: left to Qt
    assert ed.verticalScrollBar().value() <= 10                     # a notch moves a few lines


def test_reduced_motion_still_lands_on_the_end_value(qapp):
    from PySide6.QtWidgets import QWidget
    from clicker.qt.widgets import GlassButton, GlassSwitch
    glass.set_motion(False)
    try:
        seen = []
        assert glass.animate(QWidget(), 0.0, 1.0, 200, seen.append, done=lambda: seen.append("done")) is None
        assert seen == [1.0, "done"]
        s = GlassSwitch("x")
        s.show()
        s.toggle()
        assert s._pos == 1.0                          # the knob moves
        b = GlassButton("Stop")
        b.show()
        b.setEnabled(False)
        assert b._dim == pytest.approx(0.55)          # disabled buttons dim
        w = QWidget()
        w.show()
        glass.fade_in(w)
        assert w.windowOpacity() == pytest.approx(1.0)  # faded windows are visible
    finally:
        glass.set_motion(True)
