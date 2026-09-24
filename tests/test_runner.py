import os

import pytest

from clicker import vision
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, logs, run, script


def test_clicks_move_and_type(fake_inputs):
    sc = script(S("Left Click", x=10, y=20), S("Double Click", x=5, y=5), S("Type Text", text="hi {who}"))
    r, _ = run(sc, inputs_map={"who": "there"})
    assert r.result == (True, "Finished")
    assert fake_inputs.clicks() == [("click", "left", 1, (), (10, 20)), ("click", "left", 2, (), (5, 5))]
    assert ("type", "hi there") in fake_inputs.calls


def test_dry_run_does_not_click(fake_inputs):
    r, _ = run(script(S("Left Click", x=1, y=1)), dry_run=True)
    assert r.result[0] and not fake_inputs.clicks()


def test_counter_loop_with_label_and_if_variable(fake_inputs):
    sc = script(
        S("Set Variable", var="n", value="0"),
        S("Increment Variable", var="n", amount=1, label="top"),
        S("Left Click", x=1, y=1),
        S("If Variable", var="n", op="<", value="4", goto="top"),
        S("Type Text", text="done {n}"),
    )
    r, _ = run(sc)
    assert r.result[0]
    assert len(fake_inputs.clicks()) == 4
    assert ("type", "done 4") in fake_inputs.calls


def test_while_variable_loop(fake_inputs):
    sc = script(
        S("Set Variable", var="i", value="0"),
        S("While Variable", var="i", op="<", value="3"),
        S("Left Click"),
        S("Increment Variable", var="i", amount=1),
        S("End While"),
        S("Type Text", text="i={i}"),
    )
    r, _ = run(sc)
    assert r.result[0]
    assert len(fake_inputs.clicks()) == 3
    assert ("type", "i=3") in fake_inputs.calls


def test_nested_whiles(fake_inputs):
    sc = script(
        S("Set Variable", var="a", value="0"),
        S("While Variable", var="a", op="<", value="2"),
        S("Set Variable", var="b", value="0"),
        S("While Variable", var="b", op="<", value="3"),
        S("Left Click"),
        S("Increment Variable", var="b", amount=1),
        S("End While"),
        S("Increment Variable", var="a", amount=1),
        S("End While"),
    )
    r, _ = run(sc)
    assert r.result[0] and len(fake_inputs.clicks()) == 6


def test_while_max_loops_caps_an_endless_loop(fake_inputs):
    sc = script(S("While Variable", var="x", op="=", value="", max_loops=5), S("Left Click"), S("End While"))
    r, ev = run(sc)
    assert r.result[0]
    assert len(fake_inputs.clicks()) == 5
    assert any("after 5 loops" in m for m in logs(ev))


def test_while_image_found_stops_when_image_disappears(fake_inputs, screen):
    tpl = make_template()
    screen.paste(tpl, 100, 100)
    assets = AssetStore()
    assets.put_image("btn.png", tpl)
    count = {"n": 0}

    orig = fake_inputs.click

    def click_and_clear(*a, **k):
        orig(*a, **k)
        count["n"] += 1
        if count["n"] == 2:
            screen.clear()
    fake_inputs.click = click_and_clear
    try:
        sc = script(S("While Image Found", image="btn"), S("Left Click"), S("End While"))
        r, _ = run(sc, assets)
    finally:
        del fake_inputs.click
    assert r.result[0] and count["n"] == 2


def test_unbalanced_while_fails_cleanly():
    r, _ = run(script(S("While Variable", var="a", op="=", value="1"), S("Beep")))
    assert r.result[0] is False and "has no End While" in r.result[1]


def test_call_subroutine_and_return(fake_inputs):
    sc = script(
        S("Call Subroutine", goto="click_twice"),
        S("Type Text", text="between"),
        S("Call Subroutine", goto="click_twice"),
        S("Return"),  # end of the main part
        S("Left Click", label="click_twice"),
        S("Left Click"),
        S("Return"),
    )
    r, _ = run(sc)
    assert r.result[0]
    kinds = [c[0] for c in fake_inputs.calls if c[0] in ("click", "type")]
    assert kinds == ["click", "click", "type", "click", "click"]


def test_runaway_recursion_is_stopped():
    r, _ = run(script(S("Call Subroutine", goto=1)))
    assert not r.result[0] and "nested more than" in r.result[1]


def test_jump_to_missing_label_fails_with_message():
    r, _ = run(script(S("Go to Step", goto="nowhere")))
    assert not r.result[0] and "No step is labelled 'nowhere'" in r.result[1]


def test_click_image_finds_and_clicks_center(fake_inputs, screen):
    tpl = make_template()
    screen.paste(tpl, 200, 150)
    assets = AssetStore()
    assets.put_image("ok.png", tpl)
    r, _ = run(script(S("Click Image", image="ok", timeout_s=1)), assets)
    assert r.result[0]
    assert fake_inputs.clicks()[0][4] == (220, 162)


def test_retry_then_error_handler_runs_handler_and_saves_screenshot(fake_inputs, screen, tmp_path):
    assets = AssetStore()
    assets.put_image("never.png", make_template(seed=7))
    sc = script(
        S("Click Image", image="never", timeout_s=0,
          wait={"mode": "none", "on_timeout": "retry_handler", "retries": 2}),
        S("Stop Script"),
        S("Type Text", text="recovered", label="handler"),
        error_handler="handler",
    )
    r, ev = run(sc, assets, log_dir=str(tmp_path))
    assert r.result == (True, "Finished")
    assert ("type", "recovered") in fake_inputs.calls
    msgs = logs(ev)
    assert any("retry 1 of 2" in m for m in msgs) and any("retry 2 of 2" in m for m in msgs)
    run_dir = next(p for k, p in ev if k == "logfile")
    files = os.listdir(run_dir)
    assert "log.txt" in files and any(f.startswith("failure") and f.endswith(".png") for f in files)
    text = open(os.path.join(run_dir, "log.txt"), encoding="utf-8").read()
    assert "running error handler" in text


def test_plain_retry_gives_up_after_retries(screen):
    assets = AssetStore()
    assets.put_image("never.png", make_template(seed=3))
    sc = script(S("Wait for Image", image="never", timeout_s=0,
                  wait={"mode": "none", "on_timeout": "retry", "retries": 1}))
    r, _ = run(sc, assets)
    assert not r.result[0] and "after 1 retry" in r.result[1]


def test_restart_on_failure_recovers(fake_inputs, screen, tmp_path):
    assets = AssetStore()
    assets.put_image("never.png", make_template(seed=5))
    sc = script(
        S("Increment Variable", var="tries", amount=1),
        S("If Variable", var="tries", op=">=", value="3", goto="ok"),
        S("Wait for Image", image="never", timeout_s=0),
        S("Type Text", text="made it on try {tries}", label="ok"),
        settings={"restart_on_failure": 5, "restart_delay_s": 0},
    )
    r, ev = run(sc, assets, log_dir=str(tmp_path))
    assert r.result[0]
    assert ("type", "made it on try 3") in fake_inputs.calls
    assert sum("Restarting from step 1" in m for m in logs(ev)) == 2


def test_restart_limit_is_respected(screen):
    assets = AssetStore()
    assets.put_image("never.png", make_template(seed=5))
    sc = script(S("Wait for Image", image="never", timeout_s=0),
                settings={"restart_on_failure": 1, "restart_delay_s": 0})
    r, ev = run(sc, assets)
    assert not r.result[0]
    assert sum("Restarting" in m for m in logs(ev)) == 1


def test_stop_script_is_not_retried_by_restart():
    sc = script(S("Stop Script"), settings={"restart_on_failure": 3, "restart_delay_s": 0})
    r, ev = run(sc)
    assert r.result[1].startswith("Stop Script reached") and not any("Restarting" in m for m in logs(ev))


def test_increment_rejects_text():
    r, _ = run(script(S("Set Variable", var="v", value="abc"), S("Increment Variable", var="v", amount=1)))
    assert not r.result[0] and "not a number" in r.result[1]


@pytest.mark.parametrize("left,op,right,expected", [
    ("10", ">", "9", True),        # numeric, not text order
    ("1,200", "=", "1200", True),
    ("Apple", "=", "apple", True),
    ("Total: 5", "contains", "total", True),
    ("abc", "not contains", "z", True),
    ("2", "<=", "1", False),
])
def test_compare(left, op, right, expected):
    from clicker.runner import compare
    assert compare(left, op, right) is expected


@pytest.mark.skipif(vision.ocr_problem() is not None, reason="Tesseract not installed")
def test_read_text_into_variable(fake_inputs, screen):
    import cv2
    cv2.putText(screen.img, "Score 4821", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2, cv2.LINE_AA)
    sc = script(S("Read Text", region=[0, 20, 400, 60], var="score", mode="number"),
                S("If Variable", var="score", op="=", value="4821", else_goto="bad"),
                S("Type Text", text="ok {score}"), S("Return"),
                S("Type Text", text="bad {score}", label="bad"))
    r, _ = run(sc)
    assert r.result[0]
    assert ("type", "ok 4821") in fake_inputs.calls
