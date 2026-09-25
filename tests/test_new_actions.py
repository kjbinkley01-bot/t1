"""Text, window, open, clipboard and screenshot steps."""

import os

import pytest

from clicker import clipboard, formlogic, model, runner, vision
from helpers import S, run, script


@pytest.fixture
def ocr(monkeypatch):
    """Read Text returns whatever the test puts in `seen` (one value per read; the last one repeats)."""
    seen = ["Loading..."]

    def fake(region=None, mode="text"):
        return seen.pop(0) if len(seen) > 1 else seen[0]
    monkeypatch.setattr(vision, "read_text", fake)
    return seen


def test_wait_for_text_until_it_matches(fake_inputs, screen, ocr):
    ocr[:] = ["Loading...", "Loading...", "Upload Complete"]
    sc = script(S("Wait for Text", op="contains", value="complete", var="status", timeout_s=3),
                S("Type Text", text="{status}"))
    r, _ = run(sc)
    assert r.result[0], r.result
    assert ("type", "Upload Complete") in fake_inputs.calls


def test_wait_for_text_times_out_with_what_it_saw(fake_inputs, screen, ocr):
    r, _ = run(script(S("Wait for Text", op="contains", value="Done", timeout_s=0.3)))
    assert not r.result[0] and "Loading" in r.result[1]


def test_if_text_compares_numbers(fake_inputs, screen, ocr):
    ocr[:] = ["27"]
    sc = script(S("If Text on Screen", mode="number", op="<", value="30", goto="low"),
                S("Stop Script"), S("Type Text", text="heal", label="low"))
    run(sc)
    assert ("type", "heal") in fake_inputs.calls


class Windows:
    def __init__(self, titles):
        self.titles = dict(titles)
        self.did = []

    def find_window(self, title, process):
        for h, (t, p) in self.titles.items():
            if (not title or title.lower() in t.lower()) and (not process or process.lower() == p):
                return h
        return None

    def focus(self, h):
        self.did.append(("focus", h))

    def move(self, h, x, y, w, hh):
        self.did.append(("move", h, x, y, w, hh))

    def close(self, h):
        self.did.append(("close", h))


def test_window_steps(fake_inputs, screen):
    wins = Windows({7: ("Untitled - Notepad", "notepad.exe")})
    sc = script(S("Wait for Window", process="notepad.exe", timeout_s=1),
                S("If Window Open", title="Excel", goto="x"),
                S("Focus Window", title="notepad"),
                S("Move Window", title="notepad", region=[10, 20, 800, 600]),
                S("Close Window", process="notepad.exe"),
                S("Stop Script"), S("Beep", label="x"))
    r, _ = run(sc, target_backend=wins)
    assert r.result[1].startswith("Stop Script"), r.result
    assert wins.did == [("focus", 7), ("move", 7, 10, 20, 800, 600), ("close", 7)]
    r, _ = run(script(S("Wait for Window", title="Paint", timeout_s=0.3)), target_backend=wins)
    assert not r.result[0] and "did not open" in r.result[1]


def test_open_and_wait_for_its_window(fake_inputs, screen, monkeypatch):
    opened = []
    wins = Windows({})

    def fake_open(what, args=""):
        opened.append((what, args))
        wins.titles[3] = ("Report.xlsx - Excel", "excel.exe")
    monkeypatch.setattr(runner, "open_target", fake_open)
    r, _ = run(script(S("Open", file="C:/r/{name}.xlsx", args="", title="Report", timeout_s=2)),
               target_backend=wins, inputs_map={"name": "Report"})
    assert r.result[0], r.result
    assert opened == [("C:/r/Report.xlsx", "")]


class Clip:
    text = "copied text"

    def get(self):
        return self.text

    def set(self, t):
        self.text = t


def test_clipboard_steps(fake_inputs, screen):
    clipboard.set_backend(Clip())
    try:
        sc = script(S("Copy Clipboard to Variable", var="c"), S("Set Clipboard", value="<{c}>"),
                    S("Copy Clipboard to Variable", var="d"), S("Type Text", text="{d}"))
        run(sc)
        assert ("type", "<copied text>") in fake_inputs.calls
    finally:
        clipboard.set_backend(None)


def test_save_screenshot(fake_inputs, screen, tmp_path):
    out = tmp_path / "shots"
    out.mkdir()
    sc = script(S("Save Screenshot", region=[0, 0, 50, 40], file=str(out)), S("Type Text", text="{last_screenshot}"))
    run(sc)
    files = os.listdir(out)
    assert len(files) == 1 and files[0].endswith(".png")
    assert vision.decode_png((out / files[0]).read_bytes()).shape == (40, 50, 3)
    assert runner.screenshot_path(str(tmp_path / "x")) == str(tmp_path / "x") + ".png"


def test_form_and_checks_for_new_actions():
    has = lambda n: True  # noqa: E731
    v, d = formlogic.step_to_form(model.normalize_script({"steps": [{"action": "If Text on Screen", "value": "OK",
                                                                    "op": "contains"}]})["steps"][0])
    step = formlogic.form_to_step(v, d, has)
    assert step["var"] == "" and step["op"] == "contains"
    assert "window title" in model.check_step({"action": "Focus Window", "title": "", "process": ""})
    assert model.check_step({"action": "Open", "file": ""})
    assert "notepad" in model.describe_action({"action": "Wait for Window", "title": "notepad", "timeout_s": 5})
