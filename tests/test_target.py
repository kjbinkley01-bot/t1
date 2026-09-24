"""Background mode against a fake window: input must go to the window, never the real mouse."""

import numpy as np
import pytest

from clicker import target
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, run, script


class FakeWindow:
    """A window at screen position (100, 200) with its own 400 x 300 picture."""

    def __init__(self, title="Notepad - notes.txt", process="notepad.exe", minimized=False):
        self.title, self.process, self.minimized = title, process, minimized
        self.img = np.full((300, 400, 3), 230, np.uint8)
        self.posts = []
        self.quick = []
        self.restored = False

    # backend API
    def find_window(self, title, process):
        if process and process.lower() != self.process:
            return None
        if title and title.lower() not in self.title.lower():
            return None
        return 42

    def is_window(self, hwnd):
        return hwnd == 42

    def is_minimized(self, hwnd):
        return self.minimized

    def restore_behind(self, hwnd):
        self.restored, self.minimized = True, False

    def client_origin(self, hwnd):
        return 100, 200

    def client_size(self, hwnd):
        return 400, 300

    def capture_client(self, hwnd):
        return self.img.copy()

    def post_mouse(self, hwnd, kind, pos, button, mods, dbl=False):
        self.posts.append(("mouse", kind, tuple(pos), button, tuple(mods), dbl))

    def post_wheel(self, hwnd, pos, dx, dy):
        self.posts.append(("wheel", tuple(pos), dx, dy))

    def post_focus(self, hwnd):
        self.posts.append(("focus",))

    def post_key(self, hwnd, vk, down):
        self.posts.append(("key", vk, down))

    def post_char(self, hwnd, ch):
        self.posts.append(("char", ch))

    def char_vk(self, ch):
        return ord(ch.upper()), ch.isupper()

    def quick_input(self, hwnd, actions):
        self.quick.append(actions)

    def mouse(self, kind=None):
        return [p for p in self.posts if p[0] == "mouse" and (kind is None or p[1] == kind)]


def targeted(*steps, method="messages", **tgt):
    t = {"title": "notepad", "method": method}
    t.update(tgt)
    return script(*steps, settings={"target": t})


def test_normalize_and_describe():
    assert target.normalize(None) is None
    assert target.normalize({"title": "  "}) is None
    t = target.normalize({"title": "Excel", "method": "bogus"})
    assert t["method"] == "messages" and t["restore_minimized"]
    assert target.describe(None) == "Whole screen"
    assert "Excel" in target.describe(t) and "background" in target.describe(t)


def test_clicks_go_to_the_window_not_the_mouse(fake_inputs):
    win = FakeWindow()
    r, _ = run(targeted(S("Left Click", x=10, y=20), S("Double Click", x=5, y=6)), target_backend=win)
    assert r.result == (True, "Finished"), r.result
    assert fake_inputs.clicks() == [] and not any(c[0] == "move" for c in fake_inputs.calls)
    downs = win.mouse("down")
    assert downs[0][2] == (10, 20) and downs[0][3] == "left"
    assert [d[5] for d in downs[1:]] == [False, True]  # the second press of a double click is a double click
    assert ("focus",) in win.posts


def test_image_checks_read_the_window_and_highlight_on_screen(fake_inputs, screen):
    win = FakeWindow()
    tpl = make_template()
    win.img[50:74, 60:100] = tpl          # visible only inside the window's own picture
    assets = AssetStore()
    assets.put_image("ok.png", tpl)
    r, ev = run(targeted(S("Click Image", image="ok", timeout_s=1)), assets, target_backend=win)
    assert r.result[0], r.result
    assert win.mouse("down")[0][2] == (80, 62)                  # center of the match, in window coordinates
    hl = [p for k, p in ev if k == "highlight"][0]
    assert tuple(hl[:2]) == (160, 250)                          # shown on screen at window origin + match


def test_pixel_checks_use_the_window(fake_inputs):
    win = FakeWindow()
    win.img[5, 7] = (0, 0, 255)  # BGR red
    sc = targeted(S("If Pixel Color", x=7, y=5, color="#FF0000", tolerance=5, goto="red"),
                  S("Stop Script"), S("Type Text", text="saw red", label="red"))
    r, _ = run(sc, target_backend=win)
    assert r.result[0] and [p[1] for p in win.posts if p[0] == "char"] == list("saw red")


def test_keys_and_text_are_posted_with_virtual_key_codes(fake_inputs):
    win = FakeWindow()
    r, _ = run(targeted(S("Hot Key", keys="ctrl+s"), S("Send Keystroke", keys="enter"), S("Type Text", text="Hi\n")),
               target_backend=win)
    assert r.result[0]
    keys = [p[1:] for p in win.posts if p[0] == "key"]
    assert keys[:4] == [(0x11, True), (ord("S"), True), (ord("S"), False), (0x11, False)]
    assert keys[4:6] == [(0x0D, True), (0x0D, False)]
    assert [p[1] for p in win.posts if p[0] == "char"] == ["H", "i"]
    assert keys[-2:] == [(0x0D, True), (0x0D, False)]     # the newline in the text becomes Enter
    assert fake_inputs.calls == []


def test_scroll_and_drag(fake_inputs):
    win = FakeWindow()
    sc = targeted(S("Scroll Down", x=30, y=40, amount=2), S("Begin Dragging", x=10, y=10),
                  S("End Dragging", x=90, y=10))
    r, _ = run(sc, target_backend=win)
    assert r.result[0]
    assert ("wheel", (30, 40), 0, -2) in win.posts
    assert win.mouse("down")[-1][2] == (10, 10) and win.mouse("up")[-1][2] == (90, 10)
    assert len(win.mouse("move")) >= 10  # the drag glides across


def test_missing_window_fails_with_a_clear_message():
    win = FakeWindow()
    r, _ = run(script(S("Left Click"), settings={"target": {"title": "Photoshop"}}), target_backend=win)
    assert not r.result[0] and "Target window 'Photoshop' is not open" in r.result[1]


def test_minimized_window_is_restored_behind_others():
    win = FakeWindow(minimized=True)
    r, _ = run(targeted(S("Left Click", x=1, y=1)), target_backend=win)
    assert r.result[0] and win.restored


def test_quick_switch_sends_real_input_through_the_backend(fake_inputs):
    win = FakeWindow()
    r, _ = run(targeted(S("Right Click", x=12, y=34), S("Hot Key", keys="ctrl+c"), method="quickswitch"),
               target_backend=win)
    assert r.result[0]
    assert win.quick[0] == [("click", (12, 34), "right", 1, ())]
    assert win.quick[1] == [("keys", [0x11, ord("C")])]
    assert win.posts == []


def test_process_name_targeting():
    win = FakeWindow()
    r, _ = run(script(S("Left Click", x=1, y=1), settings={"target": {"process": "notepad.exe"}}),
               target_backend=win)
    assert r.result[0]
    r, _ = run(script(S("Left Click", x=1, y=1), settings={"target": {"process": "excel.exe"}}),
               target_backend=win)
    assert not r.result[0]


@pytest.mark.parametrize("name,expected", [("enter", (0x0D, False)), ("F5", (0x74, False)), ("pgdn", (0x22, False)),
                                           ("a", (ord("A"), False)), ("A", (ord("A"), True)), ("vk65", (65, False))])
def test_key_names_to_virtual_keys(name, expected):
    assert target.key_to_vk(name) == expected


def test_screen_mode_is_unchanged(fake_inputs):
    r, _ = run(script(S("Left Click", x=3, y=4)))
    assert r.result[0] and fake_inputs.clicks()[0][4] == (3, 4)
