"""Mouse glide: sliding the cursor to each spot instead of jumping there."""

import math

from clicker import glide
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, run, script


def off_line(pts, sx, sy, x, y):
    """How far the farthest point is from the straight line between start and end."""
    dx, dy = x - sx, y - sy
    n = math.hypot(dx, dy)
    return max(abs((px - sx) * dy - (py - sy) * dx) / n for px, py in pts)


def test_path_lands_exactly_eases_and_stays_straight():
    pts = glide.points(0, 0, 400, 0, 0.2)
    assert pts[-1] == (400, 0)
    assert len(pts) == 25                                            # 0.2 s / 8 ms
    steps = [b[0] - a[0] for a, b in zip(pts, pts[1:])]
    assert steps[0] < steps[len(steps) // 2] > steps[-1]             # slow, fast, slow
    assert all(y == 0 for _x, y in pts)                              # straight when not curved
    assert off_line(glide.points(10, 20, 310, 420, 0.3), 10, 20, 310, 420) <= 1
    assert len(glide.points(0, 0, 5, 5, 0)) == 2                     # at least 2 points
    assert len(glide.points(0, 0, 5, 5, 60)) == 600                  # at most 600


def test_curved_path_bows_out_but_still_lands():
    pts = glide.points(0, 0, 500, 0, 0.3, curve=True)
    assert pts[-1] == (500, 0)
    assert 0.08 * 500 <= off_line(pts, 0, 0, 500, 0) <= 0.2 * 500
    assert glide.points(0, 0, 10, 0, 0.3, curve=True)[-1] == (10, 0)  # short moves don't bend
    assert all(y == 0 for _x, y in glide.points(0, 0, 10, 0, 0.3, curve=True))


def test_zero_distance_is_harmless():
    pts = glide.points(50, 60, 50, 60, 0.1, curve=True)
    assert set(pts) == {(50, 60)}


def glides(fake_inputs):
    return [c for c in fake_inputs.calls if c[0] == "glide"]


def test_glide_off_jumps(fake_inputs):
    r, _ = run(script(S("Left Click", x=10, y=20), S("Move Mouse", x=30, y=40)))
    assert r.result[0] and glides(fake_inputs) == []


def test_glide_on_slides_clicks_moves_offsets_and_click_image(fake_inputs, screen):
    tpl = make_template()
    screen.paste(tpl, 200, 150)
    assets = AssetStore()
    assets.put_image("ok.png", tpl)
    sc = script(S("Left Click", x=10, y=20), S("Move Mouse", x=100, y=100),
                S("Move Mouse by Offset", x=5, y=-10), S("Click Image", image="ok", timeout_s=1),
                settings={"glide_ms": 300, "glide_curve": True})
    r, _ = run(sc, assets, speed=1)
    assert r.result[0]
    assert [c[1:3] for c in glides(fake_inputs)] == [(10, 20), (100, 100), (105, 90), (220, 162)]
    assert all(c[3] == 0.3 and c[4] is True for c in glides(fake_inputs))
    assert [c[4] for c in fake_inputs.clicks()] == [(10, 20), (220, 162)]   # clicks land where they should


def test_glide_follows_speed_and_is_capped():
    from clicker.runner import Runner
    fast = Runner(script(settings={"glide_ms": 400}), AssetStore(), lambda *a: None, speed=2)
    assert fast.glide_s == 0.4
    slow = Runner(script(settings={"glide_ms": 99999}), AssetStore(), lambda *a: None, speed=0.5)
    assert slow.glide_s == 5.0


def test_glide_duration_in_steps(fake_inputs):
    run(script(S("Move Mouse", x=1, y=1), settings={"glide_ms": 400}), speed=2)
    run(script(S("Move Mouse", x=2, y=2), settings={"glide_ms": 4000}), speed=0.5)
    assert [c[3] for c in glides(fake_inputs)] == [0.2, 5.0]
