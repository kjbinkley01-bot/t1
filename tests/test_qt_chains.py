import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from clicker import chains, library  # noqa: E402
from clicker.qt import glass, tab_chains  # noqa: E402
from test_library import make_script  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Main(QWidget):
    def __init__(self, lib):
        super().__init__()
        self.library, self.mode, self.backdrop = lib, glass.Mode(True), None
        self.settings, self.remembered, self.status = {}, [], ""

    def job_running_for(self, _owner):
        return False

    def update_title(self):
        pass

    def set_status(self, text, error=False):
        self.status = text

    def remember(self, path, kind, info):
        self.remembered.append((path, kind))

    def toggle_pause(self):
        pass

    def keep_version(self, path):
        pass


def make_tab(tmp_path, n=3):
    lib = library.Library(str(tmp_path / "data"))
    main = Main(lib)
    tab = tab_chains.ChainsTab(main)
    paths = [make_script(tmp_path / f"s{i}.clk", f"Script {i}", pictures=False) for i in range(n)]
    c = chains.new_chain("Test")
    c["links"] = [chains.new_link(p) for p in paths]
    tab.set_chain(c)
    return tab, paths


def test_reorder_remove_and_add(qapp, tmp_path, monkeypatch):
    tab, paths = make_tab(tmp_path)
    tab.move_link(0, 2)
    assert [ln["path"] for ln in tab.chain["links"]] == [paths[1], paths[2], paths[0]]
    assert tab.canvas.sel == 2 and tab.dirty
    tab.remove_link(1)
    assert [ln["path"] for ln in tab.chain["links"]] == [paths[1], paths[0]]
    extra = make_script(tmp_path / "extra.clk", "Extra", pictures=False)
    monkeypatch.setattr(tab_chains, "pick_script", lambda *a, **k: extra)
    tab.add_link()
    assert tab.chain["links"][-1]["path"] == os.path.abspath(extra) and tab.canvas.sel == 2


def test_card_options_edit_the_selected_link(qapp, tmp_path):
    tab, _p = make_tab(tmp_path)
    tab._select(1)
    tab.e_times.setText("4")
    tab.e_pause.setText("2.5")
    tab.cb_fail.setCurrentIndex(tab.cb_fail.findData("retry"))
    tab.e_retries.setText("3")
    tab._card_changed()
    link = tab.chain["links"][1]
    assert (link["repeat"], link["pause_s"], link["on_fail"], link["retries"]) == (4, 2.5, "retry", 3)
    tab.e_times.setText("lots")         # not a number: the old value stays
    tab._card_changed()
    assert tab.chain["links"][1]["repeat"] == 4


def test_drop_index_and_save_round_trip(qapp, tmp_path, monkeypatch):
    tab, _p = make_tab(tmp_path)
    tab.canvas.resize(900, 400)
    tab.canvas.relayout(animate=False)
    last = tab.canvas.slot(2)
    assert tab.canvas.drop_index(QPointF(last.x() + 10, last.y() + 10)) == 2
    out = str(tmp_path / f"t{chains.EXT}")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (out, ""))
    assert tab.save() is True and not tab.dirty
    assert chains.load(out)["name"] == "Test" and tab.main.remembered[-1] == (out, "chain")


def test_progress_marks_cards(qapp, tmp_path):
    tab, _p = make_tab(tmp_path)
    tab.on_job("chain", {"link": 0, "step": None})
    tab.on_job("chain", {"link": 1, "step": 0})
    assert tab.canvas.state == {0: "done", 1: "running"}
    tab.on_job("done", (False, "Card 2 (s1): failed"))
    assert tab.canvas.state == {0: "done", 1: "failed"}
