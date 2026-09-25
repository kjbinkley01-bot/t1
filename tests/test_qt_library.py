import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from clicker import library  # noqa: E402
from clicker.qt import glass  # noqa: E402
from clicker.qt.library_dialog import LibraryDialog  # noqa: E402
from test_library import make_recording, make_script  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Main(QWidget):
    def __init__(self, lib):
        super().__init__()
        self.library, self.mode, self.backdrop = lib, glass.Mode(True), None


def names(d):
    return [c.entry["name"] for c in d.cards]


def test_filters_search_and_favorites(qapp, tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    a = make_script(tmp_path / "mine.clk", "Mining")
    lib.touch_file(a)
    lib.touch_file(make_recording(tmp_path / "walk.clkrec"))
    d = LibraryDialog(Main(lib), "script")
    assert names(d) == ["Mining"]                      # opened from a script tab: scripts first
    d.set_filter("all")
    assert len(d.cards) == 2
    d.search.setText("walk")
    assert names(d) == ["walk"]
    d.search.setText("")
    d.toggle_star(lib.list(kind="script")[0])
    assert lib.entries[a]["favorite"]
    d.set_filter("favorites")
    assert names(d) == ["Mining"]
    d.set_filter("all")
    d.select_card(d.cards[0])
    d.accept()                                         # Open picks the highlighted card
    assert d.chosen["path"] == a


def test_missing_files_and_browse(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    lib = library.Library(str(tmp_path / "data"))
    p = make_script(tmp_path / "gone.clk")
    lib.touch_file(p)
    os.remove(p)
    d = LibraryDialog(Main(lib), None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    d.open_entry(d.cards[0].entry)                     # missing: offer to remove instead of opening
    assert d.chosen is None and lib.list() == [] and d.cards == []
    d._browse()
    assert d.browse is True
