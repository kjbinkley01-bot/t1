import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clicker.qt import glass  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_real_pixels_become_window_units_on_a_scaled_screen(qapp, monkeypatch):
    # a 3840 x 2160 monitor at 150%: Qt calls it 2560 x 1440 units, anchored at its real corner
    monkeypatch.setattr(glass, "screens", lambda: [(None, QRect(0, 0, 2560, 1440), (0, 0, 3840, 2160), 1.5),
                                                   (None, QRect(3840, 0, 1920, 1080), (3840, 0, 1920, 1080), 1.0)])
    assert glass.to_logical_rect(1500, 600, 300, 150) == QRect(1000, 400, 200, 100)
    assert glass.to_logical_rect(3940, 100, 50, 50) == QRect(3940, 100, 50, 50)   # the unscaled second monitor


def test_picker_shows_the_whole_screen_and_reports_real_pixels(qapp, monkeypatch):
    import numpy as np
    from clicker import vision
    from clicker.qt import dialogs
    from PySide6.QtCore import QPoint
    frame = np.zeros((2160, 3840, 3), np.uint8)
    monkeypatch.setattr(vision, "capture", lambda region=None: (frame, (0, 0)))
    monkeypatch.setattr(glass, "screens", lambda: [(None, QRect(0, 0, 2560, 1440), (0, 0, 3840, 2160), 1.5)])
    got = []
    group = dialogs.RegionPickers.__new__(dialogs.RegionPickers)
    group.frame, group.ox, group.oy = frame, 0, 0
    group.pickers = []
    group.finish = lambda region: got.append(region)
    pk = dialogs.RegionPicker(group, frame, QRect(0, 0, 2560, 1440), (0, 0, 3840, 2160), 1.5, "drag")
    group.pickers = [pk]
    assert pk.full.width() == 3840 and pk.full.deviceIndependentSize().width() == 2560   # nothing cut off
    assert pk.real(QPoint(1000, 400)) == (1500, 600)
