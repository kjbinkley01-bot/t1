import pytest

from clicker import formlogic, model


def has(names):
    return lambda n: model.image_name(n) in names


@pytest.mark.parametrize("step", [
    {"action": "Left Click", "x": 10, "y": 20, "cursor_back": True, "delay_ms": 50, "repeat": 2, "comment": "c",
     "label": "top", "wait": {"mode": "none"}},
    {"action": "Click Image", "x": None, "y": None, "cursor_back": False, "delay_ms": 0, "repeat": 1, "comment": "",
     "label": "", "image": "ok.png", "region": [1, 2, 30, 40], "confidence": 0.85, "button": "right",
     "timeout_s": 12,
     "wait": {"mode": "image_appears", "image": "ok.png", "confidence": 0.9, "timeout_s": 20, "poll_ms": 250,
              "on_timeout": "retry_handler", "retries": 2}},
    {"action": "If Variable", "x": None, "y": None, "cursor_back": False, "delay_ms": 0, "repeat": 1, "comment": "",
     "label": "", "var": "n", "op": "<", "value": "3", "goto": "top", "else_goto": None,
     "wait": {"mode": "pixel_is", "x": 5, "y": 6, "color": "#112233", "tolerance": 12, "timeout_s": 3,
              "poll_ms": 100, "on_timeout": "goto", "goto": 4}},
])
def test_round_trip(step):
    values, detail = formlogic.step_to_form(step)
    back = formlogic.form_to_step(values, detail, has({"ok.png"}))
    assert back == step


def test_errors_are_readable():
    with pytest.raises(ValueError, match="needs an image"):
        formlogic.form_to_step({"action": "Click Image"}, {"image": ""}, has(set()))
    with pytest.raises(ValueError, match="not in this script"):
        formlogic.form_to_step({"action": "Click Image"}, {"image": "x"}, has(set()))
    with pytest.raises(ValueError, match="X must be a whole number"):
        formlogic.form_to_step({"action": "Left Click", "x": "abc"}, {}, has(set()))
    with pytest.raises(ValueError, match="Capture the image to wait for"):
        formlogic.form_to_step({"action": "Beep", "wait_mode": model.WAIT_LABEL["image_appears"]}, {}, has(set()))
