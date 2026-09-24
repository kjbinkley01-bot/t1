import pytest

from clicker import model
from helpers import S, script


def test_parse_target_numbers_labels_and_blank():
    assert model.parse_target("3") == 3
    assert model.parse_target(" top ") == "top"
    assert model.parse_target("") is None
    with pytest.raises(ValueError):
        model.parse_target("0")
    with pytest.raises(ValueError):
        model.parse_target("has space")


def test_resolve_target_by_number_and_label():
    steps = script(S("Beep"), S("Beep", label="again"), S("Beep"))["steps"]
    assert model.resolve_target(steps, 1) == 0
    assert model.resolve_target(steps, "again") == 1
    assert model.resolve_target(steps, None) is None
    with pytest.raises(ValueError, match="does not exist"):
        model.resolve_target(steps, 9)
    with pytest.raises(ValueError, match="No step is labelled"):
        model.resolve_target(steps, "nope")


def test_normalize_converts_numeric_strings_and_keeps_labels():
    sc = script(S("Go to Step", goto="2"), S("Beep", label=" end "), error_handler="2")
    assert sc["steps"][0]["goto"] == 2
    assert sc["steps"][1]["label"] == "end"
    assert sc["error_handler"] == 2


def _gotos(sc):
    return [st.get("goto") for st in sc["steps"]]


def test_moving_a_step_keeps_numeric_jumps_on_the_same_step():
    sc = script(S("Beep"), S("Beep"), S("Beep", comment="target"), S("Go to Step", goto=3))
    # move step 3 (index 2) to the top
    model.reorder(sc, [2, 0, 1, 3])
    assert sc["steps"][0]["comment"] == "target"
    assert _gotos(sc)[3] == 1


def test_deleting_a_target_moves_jump_to_next_survivor():
    sc = script(S("Beep"), S("Beep", comment="gone"), S("Beep", comment="next"),
                S("Go to Step", goto=2), error_handler=2)
    model.reorder(sc, [0, 2, 3])
    assert sc["steps"][1]["comment"] == "next"
    assert sc["steps"][2]["goto"] == 2
    assert sc["error_handler"] == 2


def test_inserting_steps_shifts_jumps_and_timeout_gotos():
    sc = script(S("Beep"), S("Wait for Image", image="a", wait={"mode": "none", "on_timeout": "goto", "goto": 1}),
                S("If Variable", var="n", op="=", value="1", goto=2, else_goto="lab"))
    model.reorder(sc, [model.new_step("Beep"), 0, 1, 2])
    assert sc["steps"][2]["wait"]["goto"] == 2
    assert sc["steps"][3]["goto"] == 3
    assert sc["steps"][3]["else_goto"] == "lab"  # labels never need renumbering


def test_match_blocks_pairs_nested_whiles():
    steps = script(S("While Variable", var="a", op="<", value="3"),
                   S("While Variable", var="b", op="<", value="3"),
                   S("End While"), S("End While"))["steps"]
    pairs, err = model.match_blocks(steps)
    assert err is None
    assert pairs == {0: 3, 3: 0, 1: 2, 2: 1}


@pytest.mark.parametrize("steps,msg", [
    ([S("End While")], "no While above"),
    ([S("While Variable", var="a", op="=", value="1")], "has no End While"),
])
def test_match_blocks_reports_unbalanced(steps, msg):
    _, err = model.match_blocks(script(*steps)["steps"])
    assert msg in err


def test_check_step_catches_bad_labels_vars_and_missing_targets():
    steps = script(S("Beep"), S("Go to Step", goto="missing"))["steps"]
    assert "No step is labelled" in model.check_step(steps[1], steps)
    assert model.check_step(S("Beep", label="123")) is not None
    assert "variable name" in model.check_step(S("Set Variable", var="1bad", value="x"))
    assert model.check_step(S("Set Variable", var="ok_name", value="x")) is None


def test_describe_new_actions():
    assert model.describe_action(S("Call Subroutine", goto="login")) == "Call 'login'"
    assert model.describe_action(S("Increment Variable", var="n", amount=-2)) == "{n} - 2"
    assert "max 5 loops" in model.describe_action(S("While Image Found", image="x", max_loops=5))
