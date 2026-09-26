import random

from clicker import glide
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, run, script


def test_points_end_exactly_on_target_and_ease():
    pts = glide.points(0, 0, 400, 0, 0.3)
    assert pts[-1] == (400, 0)
    assert all(py == 0 for _, py in pts)  # straight when not curved
    xs = [px for px, _ in pts]
    assert xs == sorted(xs)
    # eased: the first and last moves are small, the middle ones big
    assert xs[1] - xs[0] < xs[len(xs) // 2] - xs[len(xs) // 2 - 1]


def test_curved_path_leaves_the_straight_line_but_still_lands():
    pts = glide.points(0, 0, 400, 0, 0.3, curve=True, rng=random.Random(1))
    assert pts[-1] == (400, 0)
    assert max(abs(py) for _, py in pts) > 20


def test_zero_distance_is_harmless():
    assert glide.points(5, 5, 5, 5, 0.2, curve=True)[-1] == (5, 5)


def test_glide_off_jumps(fake_inputs):
    run(script(S("Left Click", x=10, y=20), S("Move Mouse", x=3, y=4)))
    assert not [c for c in fake_inputs.calls if c[0] == "glide"]


def test_glide_setting_slides_clicks_moves_and_click_image(fake_inputs, screen):
    tpl = make_template()
    screen.paste(tpl, 200, 150)
    assets = AssetStore()
    assets.put_image("ok.png", tpl)
    sc = script(S("Left Click", x=10, y=20), S("Move Mouse", x=3, y=4), S("Move Mouse by Offset", x=5, y=0),
                S("Click Image", image="ok", timeout_s=1),
                settings={"glide_ms": 300, "glide_curve": True})
    r, _ = run(sc, assets, speed=1)
    assert r.result[0]
    glides = [c for c in fake_inputs.calls if c[0] == "glide"]
    assert [(c[1], c[2]) for c in glides] == [(10, 20), (3, 4), (8, 4), (220, 162)]
    assert all(c[3] == 0.3 and c[4] is True for c in glides)
    assert [c[4] for c in fake_inputs.clicks()] == [(10, 20), (220, 162)]


def test_glide_follows_speed_and_is_capped(fake_inputs):
    run(script(S("Move Mouse", x=1, y=1), settings={"glide_ms": 400}), speed=2)
    assert [c[3] for c in fake_inputs.calls if c[0] == "glide"] == [0.2]
    fake_inputs.reset()
    run(script(S("Move Mouse", x=1, y=1), settings={"glide_ms": 99999}), speed=0.1)
    assert [c[3] for c in fake_inputs.calls if c[0] == "glide"] == [glide.MAX_MS / 1000.0]
