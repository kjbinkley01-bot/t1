"""Smarter image matching: any/all of several images, and counting matches."""

from clicker import formlogic, model, vision
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, run, script


def assets_with(**imgs):
    a = AssetStore()
    for name, img in imgs.items():
        a.put_image(name + ".png", img)
    return a


def test_click_image_clicks_whichever_alternate_is_showing(fake_inputs, screen):
    normal, hover = make_template(seed=1), make_template(seed=2)
    screen.paste(hover, 300, 200)  # only the hover version is on screen
    a = assets_with(btn=normal, btn_hover=hover)
    r, _ = run(script(S("Click Image", image="btn", images=["btn_hover"], timeout_s=1)), a)
    assert r.result[0], r.result
    assert fake_inputs.clicks()[0][4] == (320, 212)


def test_all_of_them_needs_every_image(fake_inputs, screen):
    one, two = make_template(seed=1), make_template(seed=2)
    screen.paste(one, 50, 50)
    a = assets_with(one=one, two=two)
    sc = script(S("If Image Found", image="one", images=["two"], image_mode="all of them", goto="yes"),
                S("Stop Script"), S("Type Text", text="both", label="yes"))
    run(sc, a)
    assert not any(c[0] == "type" for c in fake_inputs.calls)
    screen.paste(two, 400, 300)
    run(sc, a)
    assert ("type", "both") in fake_inputs.calls


def test_count_image_saves_how_many_it_found(fake_inputs, screen):
    ore = make_template(w=30, h=20, seed=5)
    for x, y in ((20, 20), (200, 40), (420, 300), (600, 500)):
        screen.paste(ore, x, y)
    a = assets_with(ore=ore)
    sc = script(S("Count Image", image="ore", var="ores"),
                S("If Variable", var="ores", op=">=", value="4", goto="many"),
                S("Stop Script"), S("Type Text", text="{ores} ores", label="many"))
    r, ev = run(sc, a)
    assert r.result[0], r.result
    assert ("type", "4 ores") in fake_inputs.calls
    assert any("found 4" in str(p) for k, p in ev if k == "log")


def test_find_all_does_not_count_one_match_twice(screen):
    tpl = make_template(seed=9)
    screen.paste(tpl, 100, 100)
    screen.paste(tpl, 101, 300)
    hits = vision.find_all(tpl, None, 0.9)
    assert sorted((m.x, m.y) for m in hits) == [(100, 100), (101, 300)]


def test_form_round_trips_alternates_and_checks_they_exist():
    a = assets_with(btn=make_template(), btn_hover=make_template(seed=2))
    v, d = formlogic.step_to_form(model.normalize_script(
        {"steps": [{"action": "Click Image", "image": "btn.png", "images": ["btn_hover.png"]}]})["steps"][0])
    assert d["images"] == "btn_hover"
    step = formlogic.form_to_step(v, d, a.has)
    assert step["images"] == ["btn_hover.png"] and step["image_mode"] == "any of them"
    d["images"] = "btn_hover, nope"
    try:
        formlogic.form_to_step(v, d, a.has)
        raise AssertionError("missing image accepted")
    except ValueError as e:
        assert "nope" in str(e)


def test_packages_keep_alternate_images(tmp_path):
    from clicker import storage
    a = assets_with(btn=make_template(), btn_hover=make_template(seed=2))
    sc = script(S("Click Image", image="btn", images=["btn_hover"]))
    path = str(tmp_path / "s.clk")
    storage.save_script(path, sc, a)
    _s, a2 = storage.load_script(path)
    assert a2.has("btn_hover.png")
    assert model.describe_action(sc["steps"][0]).startswith("Find btn +1")
