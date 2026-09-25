"""If / Else If / Else / End If and Try / On Error / End Try."""

from clicker import flow, formlogic, model
from helpers import S, run, script


def typed(fake_inputs):
    return [c[1] for c in fake_inputs.calls if c[0] == "type"]


def ladder(n):
    return script(S("Set Variable", var="n", value=str(n)),
                  S("If", check="variable", var="n", op=">", value="10"),
                  S("Type Text", text="big"),
                  S("Else If", check="variable", var="n", op=">", value="5"),
                  S("Type Text", text="medium"),
                  S("Else"),
                  S("Type Text", text="small"),
                  S("End If"),
                  S("Type Text", text="after"))


def test_if_else_if_else_picks_one_branch(fake_inputs, screen):
    for n, want in ((20, "big"), (7, "medium"), (1, "small")):
        fake_inputs.reset()
        r, _ = run(ladder(n))
        assert r.result[0], r.result
        assert typed(fake_inputs) == [want, "after"]


def test_if_without_else_and_nested_blocks(fake_inputs, screen):
    sc = script(S("Set Variable", var="a", value="1"),
                S("If", check="variable", var="a", op="=", value="2"), S("Type Text", text="no"), S("End If"),
                S("If", check="variable", var="a", op="=", value="1"),
                S("If", check="variable", var="a", op="!=", value="1"), S("Type Text", text="inner"),
                S("Else"), S("Type Text", text="inner else"), S("End If"),
                S("End If"),
                S("Type Text", text="end"))
    run(sc)
    assert typed(fake_inputs) == ["inner else", "end"]


def test_try_catches_a_failed_step_and_keeps_going(fake_inputs, screen):
    sc = script(S("Try"),
                S("Type Text", text="before"),
                S("Wait for Image", image="missing", timeout_s=0.1),
                S("Type Text", text="never"),
                S("On Error"),
                S("Type Text", text="caught: {error}"),
                S("End Try"),
                S("Type Text", text="after"))
    r, _ = run(sc)
    assert r.result[0], r.result
    t = typed(fake_inputs)
    assert t[0] == "before" and t[1].startswith("caught: ") and "missing" in t[1] and t[2] == "after"


def test_try_that_succeeds_skips_on_error_and_try_without_on_error(fake_inputs, screen):
    run(script(S("Try"), S("Type Text", text="ok"), S("On Error"), S("Type Text", text="bad"), S("End Try"),
               S("Try"), S("Wait for Image", image="missing", timeout_s=0.1), S("End Try"), S("Type Text", text="z")))
    assert typed(fake_inputs) == ["ok", "z"]


def test_failures_outside_try_still_stop(fake_inputs, screen):
    r, _ = run(script(S("Try"), S("End Try"), S("Wait for Image", image="missing", timeout_s=0.1)))
    assert not r.result[0]


def test_structure_errors_and_depth():
    bad = script(S("If", check="variable", var="a", op="=", value="1"), S("Else"), S("Else If", check="variable",
                                                                                   var="a", op="=", value="2"),
                 S("End If"))["steps"]
    assert "after Else" in model.block_structure(bad)[1]
    assert "no End If" in model.block_structure(script(S("If", check="variable", var="a", value="1"))["steps"])[1]
    assert "no Try" in model.block_structure(script(S("On Error"))["steps"])[1]
    info, err = model.block_structure(ladder(1)["steps"])
    assert err is None and info["depth"] == [0, 0, 1, 0, 1, 0, 1, 0, 0]


def test_flow_and_unreachable_understand_blocks():
    steps = ladder(1)["steps"]
    kinds = {(e["kind"], e["src"], e["dst"]) for e in flow.edges(steps)}
    assert ("ifblock", 1, 7) in kinds
    assert flow.unreachable({"steps": steps}) == []
    sc = script(S("Try"), S("Beep"), S("On Error"), S("Beep"), S("End Try"))
    assert flow.unreachable(sc) == []


def test_form_shows_only_the_fields_the_check_needs():
    names = [f[0] for f in model.fields_for("If", {"check": "window open"})]
    assert names == ["check", "title", "process"]
    v, d = formlogic.step_to_form(model.normalize_script(
        {"steps": [{"action": "If", "check": "variable", "var": "x", "op": ">", "value": "3"}]})["steps"][0])
    step = formlogic.form_to_step(v, d, lambda n: True)
    assert step["check"] == "variable" and step["var"] == "x" and "title" not in step
    assert "{x} > \"3\"" in model.describe_action(step)
