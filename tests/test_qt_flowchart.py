import os
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from clicker import editing, model  # noqa: E402
from clicker.qt import glass  # noqa: E402
from clicker.qt.flowchart import FlowChart  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Tab:
    """Just what the chart reads from the Action Script tab."""

    def __init__(self, actions):
        self.script = model.new_script()
        self.script["steps"] = [model.new_step(a) for a in actions]
        self.main = SimpleNamespace(mode=glass.Mode(True))
        self.running_row = None

    def _selection(self):
        return []

    def move_steps_to(self, indexes, target):
        editing.move_to(self.script, indexes, target)
        self.chart.rebuild()


def pump(app, ms):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def make_chart(qapp, actions):
    tab = Tab(actions)
    tab.chart = FlowChart(tab)
    tab.chart.resize(420, 500)
    tab.chart.show()
    qapp.processEvents()
    return tab


def test_moved_boxes_glide_to_their_new_places(qapp):
    glass.set_motion(True)
    tab = make_chart(qapp, ["Left Click", "Type Text", "Delay"])
    chart = tab.chart
    first = chart.boxes[0].step
    y_top = chart.boxes[0].pos().y()
    y_last = chart.boxes[2].pos().y()
    tab.move_steps_to([0], 2)                      # the first step goes to the bottom
    moved = next(b for b in chart.boxes if b.step is first)
    assert moved.i == 2
    assert moved.pos().y() == pytest.approx(y_top)  # starts where it was...
    pump(qapp, glass.SLOW + 150)
    assert moved.pos().y() == pytest.approx(y_last)  # ...and ends in its new place


def test_nothing_glides_with_reduced_motion(qapp):
    glass.set_motion(False)
    try:
        tab = make_chart(qapp, ["Left Click", "Type Text"])
        first = tab.chart.boxes[0].step
        y_last = tab.chart.boxes[1].pos().y()
        tab.move_steps_to([0], 1)
        moved = next(b for b in tab.chart.boxes if b.step is first)
        assert moved.pos().y() == pytest.approx(y_last)
    finally:
        glass.set_motion(True)


def test_zoom_eases_to_its_target(qapp):
    tab = make_chart(qapp, ["Left Click"])
    chart = tab.chart
    chart._zoom_to = 1.5
    glass.animate(chart, chart.zoom, chart._zoom_to, glass.FAST, chart._set_zoom, attr="_zanim")
    qapp.processEvents()
    assert chart.zoom < 1.5
    pump(qapp, glass.FAST + 150)
    assert chart.zoom == pytest.approx(1.5)
    assert chart.transform().m11() == pytest.approx(1.5)
