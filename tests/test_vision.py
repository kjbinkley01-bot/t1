import cv2
import numpy as np

from clicker import vision
from conftest import make_template


def test_exact_match_location_and_score():
    hay = np.full((300, 400, 3), 240, np.uint8)
    tpl = make_template()
    hay[50:74, 120:160] = tpl
    m = vision.match_in(hay, tpl, 0.9)
    assert (m.x, m.y, m.w, m.h) == (120, 50, 40, 24) and m.score > 0.99


def test_offsets_are_added():
    hay = np.full((100, 100, 3), 240, np.uint8)
    tpl = make_template(20, 12)
    hay[10:22, 30:50] = tpl
    m = vision.match_in(hay, tpl, 0.9, ox=1000, oy=500)
    assert (m.x, m.y) == (1030, 510)


def test_no_match_below_confidence():
    hay = np.full((200, 200, 3), 240, np.uint8)
    assert vision.match_in(hay, make_template(), 0.9) is None


def test_flat_template_matches_by_color():
    hay = np.full((100, 100, 3), 240, np.uint8)
    hay[40:50, 40:60] = (0, 0, 200)
    tpl = np.zeros((10, 20, 3), np.uint8)
    tpl[:] = (0, 0, 200)
    m = vision.match_in(hay, tpl, 0.95)
    assert (m.x, m.y) == (40, 40)


def _scaled_scene(factor):
    """A crisp, UI like template, and a screen where it appears resized by factor."""
    tpl = np.full((40, 120, 3), 250, np.uint8)
    cv2.rectangle(tpl, (2, 2), (117, 37), (60, 60, 60), 2)
    cv2.putText(tpl, "Save", (22, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2, cv2.LINE_AA)
    big = cv2.resize(tpl, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    hay = np.full((400, 600, 3), 250, np.uint8)
    h, w = big.shape[:2]
    hay[100:100 + h, 200:200 + w] = big
    return tpl, hay


def test_scaled_screen_needs_multiscale_search():
    tpl, hay = _scaled_scene(1.25)
    assert vision.match_in(hay, tpl, 0.85) is None
    m = vision.match_in(hay, tpl, 0.85, scales=vision.scale_candidates(1.0, search=True))
    assert m is not None and abs(m.x - 200) <= 3 and abs(m.y - 100) <= 3
    assert abs(m.w - 150) <= 2


def test_known_scale_factor_is_tried_first():
    tpl, hay = _scaled_scene(1.5)
    m = vision.match_in(hay, tpl, 0.85, scales=vision.scale_candidates(1.5))
    assert m is not None and abs(m.w - 180) <= 2


def test_scale_candidates_order():
    assert vision.scale_candidates(1.0) == [1.0]
    assert vision.scale_candidates(1.25) == [1.25, 1.0]
    band = vision.scale_candidates(1.0, search=True)
    assert band[0] == 1.0 and 1.25 in band and 0.8 in band and len(band) == len(set(band))


def test_checker_passes_scales_through(screen):
    tpl, hay = _scaled_scene(1.25)
    screen.img[:hay.shape[0], :hay.shape[1]] = hay
    cond = {"kind": "image_appears", "image": "t.png", "confidence": 0.85}
    get = {"t.png": tpl}.get
    assert vision.Checker(cond, get).check()[0] is False
    ok, m = vision.Checker(dict(cond, scales=vision.scale_candidates(1.0, True)), get).check()
    assert ok and m is not None


def test_region_stable_and_changes(screen):
    import time
    c = vision.Checker({"kind": "region_changes", "region": [0, 0, 100, 100]}, lambda n: None)
    assert c.check()[0] is False
    screen.img[10:60, 10:60] = 0
    assert c.check()[0] is True
    s = vision.Checker({"kind": "region_stable", "region": [0, 0, 100, 100], "stable_ms": 50}, lambda n: None)
    assert s.check()[0] is False
    time.sleep(0.08)
    assert s.check()[0] is True


def test_checker_searches_near_last_match_first(screen, monkeypatch):
    tpl = make_template()
    screen.paste(tpl, 500, 400)
    memory = {}
    cond = {"kind": "image_appears", "image": "t.png", "confidence": 0.9}
    ok, m = vision.Checker(cond, {"t.png": tpl}.get, memory).check()
    assert ok and (m.x, m.y) == (500, 400)
    regions = []
    real = vision.capture
    monkeypatch.setattr(vision, "capture", lambda region=None: (regions.append(region), real(region))[1])
    # a new checker for the same image (the next step) looks in a small box around the old spot
    screen.clear()
    screen.paste(tpl, 510, 405)
    ok, m = vision.Checker(cond, {"t.png": tpl}.get, memory).check()
    assert ok and (m.x, m.y) == (510, 405)
    assert regions[0] is not None and regions[0][2] < 200 and len(regions) == 1


def test_checker_falls_back_to_full_screen_when_image_moved_far(screen):
    tpl = make_template()
    memory = {}
    cond = {"kind": "image_appears", "image": "t.png", "confidence": 0.9}
    screen.paste(tpl, 50, 50)
    assert vision.Checker(cond, {"t.png": tpl}.get, memory).check()[0]
    screen.clear()
    screen.paste(tpl, 700, 500)
    ok, m = vision.Checker(cond, {"t.png": tpl}.get, memory).check()
    assert ok and (m.x, m.y) == (700, 500)
    screen.clear()
    assert vision.Checker(cond, {"t.png": tpl}.get, memory).check()[0] is False
