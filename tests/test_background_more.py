"""Background mode beyond the Action Script: recordings and screen triggers inside one window."""

import time

from clicker import recorder, target, triggers
from clicker.storage import AssetStore
from conftest import make_template
from test_target import FakeWindow

WIN = {"title": "notepad"}


def ev(t, typ, **kw):
    return dict(t=t, type=typ, **kw)


def play(events, **kw):
    out = []
    p = recorder.Player(events, lambda k, v=None: out.append((k, v)), **kw)
    p._main()
    return p, out


def test_recording_positions_become_window_positions():
    events = [ev(0.0, "move", x=150, y=260), ev(0.1, "mouse_down", x=150, y=260, button="left"),
              ev(0.2, "mouse_up", x=151, y=261, button="left"),
              ev(0.3, "mouse_down", x=900, y=900, button="left"),   # outside: the Stop click on Clicker
              ev(0.4, "mouse_up", x=900, y=900, button="left"),
              ev(0.5, "key_down", char="a", vk=65), ev(0.6, "key_up", char="a", vk=65)]
    out, dropped = recorder.to_window(events, (100, 200), (400, 300))
    assert dropped == 2
    assert [(e["type"], e.get("x"), e.get("y")) for e in out[:3]] == [
        ("move", 50, 60), ("mouse_down", 50, 60), ("mouse_up", 51, 61)]
    assert [e["type"] for e in out[3:]] == ["key_down", "key_up"]


def test_drag_that_ends_outside_is_kept_at_the_edge():
    events = [ev(0.0, "mouse_down", x=450, y=300, button="left"), ev(0.1, "mouse_up", x=700, y=300, button="left")]
    out, dropped = recorder.to_window(events, (100, 200), (400, 300))
    assert dropped == 0 and out[1]["x"] == 399


def test_window_recording_plays_into_the_window_not_the_mouse(fake_inputs):
    win = FakeWindow()
    events = [ev(0.0, "mouse_down", x=50, y=60, button="left"), ev(0.01, "mouse_up", x=50, y=60, button="left"),
              ev(0.02, "scroll", x=50, y=60, dx=0, dy=-2),
              ev(0.03, "key_down", key="enter"), ev(0.04, "key_up", key="enter")]
    p, out = play(events, target=WIN, recorded_in=WIN, target_backend=win)
    assert p.result == (True, "Finished"), p.result
    assert fake_inputs.calls == []
    assert [m[1:3] for m in win.mouse() if m[1] != "move"] == [("down", (50, 60)), ("up", (50, 60))]
    assert ("wheel", (50, 60), 0, -2) in win.posts
    keys = [p for p in win.posts if p[0] == "key"]
    assert keys == [("key", target.VK["enter"], True), ("key", target.VK["enter"], False)]


def test_screen_recording_played_in_a_window_is_shifted_to_its_corner(fake_inputs):
    win = FakeWindow()  # content area starts at (100, 200) on screen
    events = [ev(0.0, "mouse_down", x=130, y=240, button="right"), ev(0.01, "mouse_up", x=130, y=240, button="right")]
    p, _ = play(events, target=WIN, target_backend=win)
    assert p.result[0], p.result
    assert win.mouse("down")[0][2:4] == ((30, 40), "right")


def test_missing_window_stops_playback_with_a_clear_reason(fake_inputs):
    win = FakeWindow(process="other.exe")
    p, out = play([ev(0.0, "key_down", key="a")], target={"process": "notepad.exe"}, target_backend=win)
    assert p.result[0] is False and "not open" in p.result[1]


def test_held_keys_are_released_in_the_window_when_stopped(fake_inputs):
    win = FakeWindow()
    p = recorder.Player([ev(0.0, "key_down", key="shift"), ev(5.0, "key_up", key="shift")], lambda *a: None,
                        target=WIN, recorded_in=WIN, target_backend=win)
    p.start()
    deadline = time.monotonic() + 2
    while not any(x[0] == "key" for x in win.posts) and time.monotonic() < deadline:
        time.sleep(0.01)
    p.stop()
    p.thread.join(2)
    assert [x for x in win.posts if x[0] == "key"] == [("key", target.VK["shift"], True),
                                                         ("key", target.VK["shift"], False)]


class Ctx:
    def script_running(self):
        return False

    def hold(self):
        pass

    def release(self):
        pass


def test_trigger_watches_the_window_and_clicks_inside_it(fake_inputs, screen):
    win = FakeWindow()
    tpl = make_template()
    win.img[100:124, 200:240] = tpl  # only in the window's own picture, not on the screen
    assets = AssetStore()
    assets.put_image("btn.png", tpl)
    rule = triggers.new_rule("Press it")
    rule.update(active="always", hold_ms=0, check_ms=50, cooldown_s=60)
    rule["condition"]["image"] = "btn.png"
    events = []
    eng = triggers.TriggerEngine(lambda: [rule], assets, lambda k, p=None: events.append((k, p)), Ctx(),
                                 get_target=lambda: WIN, target_backend=win)
    eng.start()
    deadline = time.monotonic() + 5
    while not win.mouse("down") and time.monotonic() < deadline:
        time.sleep(0.02)
    eng.stop()
    eng.thread.join(2)
    assert win.mouse("down")[0][2] == (220, 112)       # match center, in window positions
    assert fake_inputs.clicks() == []
    hl = [p for k, p in events if k == "highlight"][0]
    assert tuple(hl[:2]) == (300, 300)                  # highlighted on screen at window corner + match


def test_trigger_test_button_reads_the_window(fake_inputs, screen):
    win = FakeWindow()
    tpl = make_template(seed=3)
    win.img[10:34, 10:50] = tpl
    assets = AssetStore()
    assets.put_image("x.png", tpl)
    rule = triggers.new_rule()
    rule["condition"]["image"] = "x.png"
    eng = triggers.TriggerEngine(lambda: [rule], assets, lambda *a: None, Ctx(),
                                 get_target=lambda: WIN, target_backend=win)
    ok, match = eng.test_rule(rule)
    assert ok and match.center == (30, 22)
    ok, _ = triggers.TriggerEngine(lambda: [rule], assets, lambda *a: None, Ctx()).test_rule(rule)
    assert not ok  # the screen itself doesn't show it


def test_trigger_waits_for_a_closed_window(fake_inputs, screen):
    win = FakeWindow(process="other.exe")
    events = []
    eng = triggers.TriggerEngine(lambda: [], AssetStore(), lambda k, p=None: events.append((k, p)), Ctx(),
                                 get_target=lambda: {"process": "notepad.exe"}, target_backend=win)
    eng.start()
    deadline = time.monotonic() + 2
    while not any("Waiting" in str(p) for _, p in events) and time.monotonic() < deadline:
        time.sleep(0.02)
    eng.stop()
    eng.thread.join(2)
    assert any("not open" in str(p) and "Waiting" in str(p) for _, p in events)


def test_trigger_rules_fire_on_any_of_their_images_and_keep_them_when_saved(fake_inputs, screen, tmp_path):
    from clicker import storage
    tpl_a, tpl_b = make_template(seed=11), make_template(seed=12)
    screen.paste(tpl_b, 300, 200)                      # only the alternate is showing
    assets = AssetStore()
    assets.put_image("a.png", tpl_a)
    assets.put_image("b.png", tpl_b)
    rule = triggers.new_rule()
    rule["condition"].update(image="a.png", images=["b.png"], image_mode="any of them")
    eng = triggers.TriggerEngine(lambda: [rule], assets, lambda *a: None, Ctx())
    ok, match = eng.test_rule(rule)
    assert ok and match.center == (320, 212)
    assert "+1" in triggers.describe_condition(rule["condition"])
    p = str(tmp_path / "r.clktrig")
    storage.save_triggers(p, [rule], assets)
    _rules, got = storage.load_triggers(p)
    assert got.has("b.png")
