"""Pictures at clicks: choosing a unique patch, converting to Click Image, saving, and finding moved clicks."""

import queue
import threading
import time
from types import SimpleNamespace

import numpy as np

from clicker import recedit, recorder, storage
from conftest import make_template
from test_target import FakeWindow

WIN = {"title": "notepad"}


def desk():
    rng = np.random.default_rng(0)
    img = np.full((600, 800, 3), 235, np.uint8)
    img[100:124, 200:240] = make_template(seed=1)                      # a unique button
    for x in (400, 460, 520):                                         # three identical icons
        img[300:320, x:x + 24] = make_template(w=24, h=20, seed=2)
    img[500:560, 600:700] = rng.integers(0, 255, (60, 100, 3), dtype=np.uint8)
    return img


def test_pick_patch_finds_a_unique_textured_picture():
    screen = desk()
    patch, off = recorder.pick_patch(screen, 220, 112)
    assert patch.shape[:2] == (32, 48) and off == (0, 0)
    # a click on one of three identical icons needs a bigger picture that includes its surroundings
    hit = recorder.pick_patch(screen, 472, 310)
    assert hit is None or hit[0].shape[1] > 48
    # plain background has nothing to find
    assert recorder.pick_patch(screen, 50, 450) is None


def test_recorder_attaches_pictures_to_presses():
    screen = desk()
    r = recorder.Recorder(lambda k: False)
    r.opts = {"clicks": True, "moves": False, "keys": False, "pictures": True, "snapshots": False}
    r.started = time.monotonic()
    r._capture = lambda region: (screen, (0, 0))
    r._jobs, r._stop, r.images = queue.Queue(), threading.Event(), {}
    t = threading.Thread(target=r._picture_worker)
    t.start()
    left = SimpleNamespace(name="left")
    r._on_click(220, 112, left, True)
    r._on_click(220, 112, left, False)
    r._on_click(50, 450, left, True)
    r._stop.set()
    t.join(5)
    down1, _up, down2 = r.events
    assert down1["img"] in r.images and down1["img_off"] == [0, 0]
    assert "img" not in down2


def ev(t, typ, **kw):
    return dict(t=t, type=typ, **kw)


def test_convert_uses_click_image_only_where_there_is_a_picture():
    events = [ev(0.5, "mouse_down", x=220, y=112, button="left", img="click_001.png", img_off=[3, -2]),
              ev(0.55, "mouse_up", x=220, y=112, button="left"),
              ev(0.7, "mouse_down", x=220, y=112, button="left", img="click_002.png", img_off=[3, -2]),
              ev(0.75, "mouse_up", x=220, y=112, button="left"),
              ev(2.0, "mouse_down", x=50, y=450, button="left"), ev(2.1, "mouse_up", x=50, y=450, button="left")]
    steps = recorder.recording_to_steps(events)
    assert [s["action"] for s in steps] == ["Click Image", "Left Click"]
    assert steps[0]["image"] == "click_001.png" and steps[0]["button"] == "double"
    assert (steps[0]["x"], steps[0]["y"]) == (3, -2)
    assert [s["action"] for s in recorder.recording_to_steps(events, use_pictures=False)] == \
        ["Double Click", "Left Click"]


def test_recordings_with_pictures_and_snapshots_save_as_a_package(tmp_path):
    events = [ev(0.5, "mouse_down", x=1, y=1, button="left", img="click_001.png"),
              ev(0.6, "mouse_up", x=1, y=1, button="left"), ev(0.7, "snap", snap="snap_0001.jpg")]
    p = str(tmp_path / "r.clkrec")
    storage.save_recording(p, events, {"repeat": 1}, {"click_001.png": make_template()}, {"snap_0001.jpg": b"jpg"})
    got, opts, images, snaps = storage.load_recording_full(p)
    assert got == events and opts == {"repeat": 1}
    assert images["click_001.png"].shape == (24, 40, 3) and snaps == {"snap_0001.jpg": b"jpg"}
    plain = str(tmp_path / "plain.clkrec")
    storage.save_recording(plain, events[:2], {})
    assert storage.load_recording_full(plain)[0] == events[:2]
    assert open(plain, encoding="utf-8").read().lstrip().startswith("{")


def test_snapshots_are_not_activity_for_pauses():
    events = [ev(0.5, "mouse_down", x=1, y=1, button="left"), ev(0.6, "mouse_up", x=1, y=1, button="left"),
              ev(3.0, "snap", snap="a"), ev(6.0, "snap", snap="b"), ev(8.0, "key_down", key="enter"),
              ev(8.1, "key_up", key="enter")]
    assert recedit.pauses(events, 2.0) == [(0.6, 8.0)]
    out = recedit.shorten_pauses(events, 2.0, 0.5)
    assert out[-2]["t"] == 1.1 and all(e["t"] <= 1.1 for e in out if e["type"] == "snap")


def test_follow_clicks_where_the_picture_is_now(fake_inputs):
    win = FakeWindow()
    tpl = make_template(seed=4)
    win.img[150:174, 250:290] = tpl        # the button moved: recorded at (40, 30), now centered at (270, 162)
    events = [ev(0.0, "mouse_down", x=40, y=30, button="left", img="b.png", img_off=[2, 1]),
              ev(0.02, "mouse_up", x=40, y=30, button="left")]
    p = recorder.Player(events, lambda *a: None, target=WIN, recorded_in=WIN, target_backend=win,
                        images={"b.png": tpl}, follow=True)
    p._main()
    assert p.result[0], p.result
    assert [m[2] for m in win.mouse("down")] == [(272, 163)]
    assert [m[2] for m in win.mouse("up")] == [(272, 163)]


def test_smart_waits_replace_pauses_for_picture_clicks():
    events = [ev(4.0, "mouse_down", x=220, y=112, button="left", img="a.png", img_off=[0, 0]),
              ev(4.1, "mouse_up", x=220, y=112, button="left"),
              ev(9.0, "mouse_down", x=50, y=450, button="left"), ev(9.1, "mouse_up", x=50, y=450, button="left")]
    steps = recorder.recording_to_steps(events, wait_for_pictures=True)
    assert steps[0]["action"] == "Click Image" and steps[0]["delay_ms"] == 0 and steps[0]["timeout_s"] == 17
    assert steps[1]["action"] == "Left Click" and steps[1]["delay_ms"] == 4900
