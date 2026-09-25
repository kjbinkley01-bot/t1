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


def test_picker_mode_lists_only_that_kind(qapp, tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    lib.touch_file(make_script(tmp_path / "a.clk", "Alpha"))
    lib.touch_file(make_recording(tmp_path / "walk.clkrec"))
    d = LibraryDialog(Main(lib), "script", pick=True, title="Choose a script")
    assert names(d) == ["Alpha"] and set(d.chips) == {"all", "favorites"}
    d.select_card(d.cards[0])
    d.accept()
    assert d.chosen["name"] == "Alpha"


def test_home_row_shows_scripts_favorites_first(qapp, tmp_path):
    from clicker.qt.library_dialog import LibraryHome
    lib = library.Library(str(tmp_path / "data"))
    a = make_script(tmp_path / "a.clk", "Alpha")
    lib.touch_file(a)
    lib.touch_file(make_script(tmp_path / "b.clk", "Beta"))
    lib.touch_file(make_recording(tmp_path / "walk.clkrec"))
    lib.set_favorite(a, True)
    home = LibraryHome(Main(lib))
    assert home.refresh() is True
    cards = [home.row.itemAt(i).widget() for i in range(home.row.count()) if home.row.itemAt(i).widget()]
    assert [c.entry["name"] for c in cards] == ["Alpha", "Beta"]
    opened = []
    home.opened.connect(opened.append)
    cards[1].clicked.emit(cards[1])
    assert opened[0]["name"] == "Beta"
    assert LibraryHome(Main(library.Library(str(tmp_path / "empty")))).refresh() is False


def test_versions_dialog_lists_kept_copies(qapp, tmp_path, monkeypatch):
    import time
    from clicker import versions
    from clicker.qt.library_dialog import VersionsDialog
    monkeypatch.setattr(versions.storage, "data_dir", lambda: str(tmp_path / "data"))
    p = make_script(tmp_path / "farm.clk", "Farm", pictures=False, n=2)
    versions.keep(p)
    time.sleep(0.01)
    make_script(tmp_path / "farm.clk", "Farm", pictures=False, n=5)
    versions.keep(p)
    d = VersionsDialog(Main(library.Library(str(tmp_path / "lib"))), p, "script")
    assert d.list.count() == 2 and "5 steps" in d.list.item(0).text() and "2 steps" in d.list.item(1).text()
    d.list.setCurrentRow(1)
    d.accept()
    assert d.chosen["file"] == versions.list_versions(p)[1]["file"]
