import pytest

from clicker import expr, model
from helpers import S, run, script

V = {"count": "5", "price": "19.99", "name": "kim", "big": "1,200", "empty": ""}


@pytest.mark.parametrize("src,want", [
    ("{count} * 2 + 1", "11"),
    ("{count} / 2", "2.5"),
    ("0.1 + 0.2", "0.3"),
    ("round({price} * 1.05, 2)", "20.99"),
    ("{big} + 1", "1201"),                       # "1,200" is a number
    ("upper({name}) + '!'", "KIM!"),
    ('"Hi " + {name}', "Hi kim"),
    ("len({name})", "3"),
    ("pad({count}, 3)", "005"),
    ("max({count}, 9, 2)", "9"),
    ("'yes' if {count} > 3 else 'no'", "yes"),
    ("contains({name}, 'K')", "true"),
    ("mid('abcdef', 2, 3)", "bcd"),
    ("right('abcdef', 2) + left('abcdef', 1)", "efa"),
    ("{count} // 2", "2"),
    ("-{count} % 3", "1"),
])
def test_expressions(src, want):
    assert expr.as_text(expr.evaluate(src, V)) == want


@pytest.mark.parametrize("src,bit", [
    ("{count} / 0", "division by zero"),
    ("{missing} + 1", "no variable called missing"),
    ("__import__('os')", "unknown function"),
    ("{name}.upper()", "can't do"),
    ("(1 + ", "can't read"),
    ("{name} * 3", "can't multiply"),
    ("round(1, 2, 3)", "wrong number"),
    ("2 ** 1000", "too big"),
    ("[1, 2]", "can't do"),
])
def test_errors_are_clear_and_nothing_else_is_reachable(src, bit):
    with pytest.raises(expr.ExprError) as e:
        expr.evaluate(src, V)
    assert bit in str(e.value)


def test_inline_spans_nest():
    t = "Total {= round({price} * 2, 1)} for {name} {= 1 + 1}"
    assert [s for _a, _b, s in expr.inline_spans(t)] == [" round({price} * 2, 1)", " 1 + 1"]
    assert expr.expand_inline(t, V) == "Total 40 for {name} 2"
    assert expr.expand_inline("unclosed {= 1 + ", V) == "unclosed {= 1 + "


def test_in_a_running_script(fake_inputs):
    sc = script(S("Set Variable", var="n", value="4"),
                S("Set Variable", var="n", value="= {n} * 3 + 1"),
                S("Set Variable", var="who", value="= upper('ann')"),
                S("Type Text", text="{who} has {n}, half is {= {n} / 2}"))
    r, _ = run(sc)
    assert r.result[0]
    assert ("type", "ANN has 13, half is 6.5") in fake_inputs.calls


def test_bad_expression_fails_the_step(fake_inputs):
    r, _ = run(script(S("Set Variable", var="n", value="= 1 / 0")))
    assert r.result == (False, "Step 1: division by zero")
    r, _ = run(script(S("Type Text", text="x {= nope}")))
    assert r.result[0] is False and "no variable called nope" in r.result[1]


def test_the_editor_catches_mistakes():
    assert "Expression" in model.check_step({"action": "Set Variable", "var": "a", "value": "= (1 +"})
    assert model.check_step({"action": "Set Variable", "var": "a", "value": "= 1 + 2"}) is None
    assert "{= " in model.check_step({"action": "Type Text", "text": "a {= foo(1)} b"})
