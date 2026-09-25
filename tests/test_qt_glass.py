"""Glass rendering checks. They run without a display (Qt's offscreen platform)."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRectF, QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clicker.qt import glass  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_tokens_from_the_kit_are_bundled():
    assert glass.TOKENS["materials"]["regular"]["light_angle"] == 315
    assert glass.TOKENS["color"]["accent/blue"] == "#0088ff"


@pytest.mark.parametrize("scene", [k for k, _, _ in glass.WALLPAPERS])
def test_wallpapers_render_and_match_their_mode(scene):
    img = glass.render_scene(scene, 320, 200)
    assert img.shape == (200, 320, 3)
    brightness = img.mean()
    assert (brightness < 150) == glass.WALLPAPER_DARK[scene]


def test_backdrop_builds_sharp_and_frosted_copies(qapp):
    b = glass.Backdrop("aurora")
    b.resize(QSize(400, 300))
    assert b.sharp.width() == 400 and b.frost.height() == 300


def test_glass_brightens_its_rim_from_the_top_left(qapp):
    b = glass.Backdrop("dusk")
    b.resize(QSize(300, 200))
    img = QImage(300, 200, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    glass.paint_glass(p, QRectF(20, 20, 260, 160), 30, b, QPoint(0, 0), glass.Mode(True), shadow=False)
    p.end()
    top_left = QColor(img.pixel(40, 21)).lightness()
    bottom_right = QColor(img.pixel(260, 178)).lightness()
    middle = QColor(img.pixel(150, 100)).lightness()
    assert top_left > bottom_right > 0 and top_left > middle


def test_icons_are_tinted(qapp):
    pm = glass.icon_pixmap("play", "#ff0000", 24)
    img = pm.toImage()
    c = QColor(img.pixel(12, 12))
    assert c.red() > 200 and c.green() < 60


def test_bundled_font_loads(qapp):
    assert glass.load_fonts()


def test_surface_cache_draws_once_per_key(qapp):
    calls = []
    cache = glass.SurfaceCache()
    for _ in range(5):
        cache.get(("a", 10), 40, 20, 1.0, lambda p: calls.append(1))
    assert len(calls) == 1
    cache.get(("b", 10), 40, 20, 1.0, lambda p: calls.append(1))
    assert len(calls) == 2


def test_fast_glass_skips_the_depth_band(qapp):
    img = QImage(200, 120, QImage.Format.Format_ARGB32)
    for fast in (False, True):
        img.fill(QColor(0, 0, 0))
        p = QPainter(img)
        glass.paint_glass(p, QRectF(10, 10, 180, 100), 26, None, QPoint(0, 0), glass.Mode(True), shadow=False,
                          fast=fast)
        p.end()
        inner = QColor(img.pixel(12, 60)).lightness()  # just inside the left edge, where the band sits
        if not fast:
            full = inner
    assert full > inner


def test_running_step_shows_its_countdown(qapp):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem

    from clicker.qt import tab_actions

    tree = QTreeWidget()
    tree.setColumnCount(8)
    for _ in range(2):
        tree.addTopLevelItem(QTreeWidgetItem([""] * 6 + ["100", "1"]))
    tab = SimpleNamespace(tree=tree, progress={"step": 1, "start": 0.0, "duration": 3.0, "kind": "delay"},
                          progress_elapsed=lambda: 1.2)
    d = tab_actions.StepProgress(tab)

    def text(row):
        opt = QStyleOptionViewItem()
        d.initStyleOption(opt, tree.model().index(row, tab_actions.DELAY_COL))
        return opt.text

    assert text(1) == "1.8s" and text(0) == "100"
    tab.progress = dict(tab.progress, kind="wait", duration=10.0)
    assert text(1) == "≤9s"
    tab.progress = None
    assert text(1) == "100"


def test_script_hotkey_entries_and_bindings(qapp):
    from clicker.qt import scripthotkeys
    s = {"script_hotkeys": [{"path": "/a.clk", "keys": "Ctrl+Alt+1"}, {"path": "/b.clk", "keys": ""},
                            {"keys": "F9"}, "junk"]}
    assert [e["path"] for e in scripthotkeys.entries(s)] == ["/a.clk", "/b.clk"]
    assert scripthotkeys.entries(s)[0]["toggle"] is True
    assert scripthotkeys.bindings(s) == {"/a.clk": "Ctrl+Alt+1"}


def test_only_one_run_may_use_the_real_mouse(qapp):
    from types import SimpleNamespace

    from clicker.qt import runs
    screen_job = SimpleNamespace(target=None)
    bg = SimpleNamespace(target={"title": "A", "method": "messages"})
    quick = SimpleNamespace(target={"title": "B", "method": "quickswitch"})
    assert runs.can_run_alongside(bg, [screen_job])
    assert runs.can_run_alongside(bg, [bg, screen_job])
    assert not runs.can_run_alongside(screen_job, [bg, screen_job])
    assert not runs.can_run_alongside(quick, [screen_job])
