"""Loop and jump overview: edges, lanes and unreachable steps."""

from clicker import flow
from helpers import S, script


def mining():
    return script(
        S("Show Notification", message="go", label="start"),
        S("Click Image", image="rock", label="mine"),
        S("While Image Found", image="ore"),
        S("If Pixel Color", x=1, y=1, color="#554433", goto="bank"),
        S("Delay", ms=600),
        S("End While"),
        S("Go to Step", goto="mine"),
        S("Click Image", image="bank_booth", label="bank"),
        S("Loop Back", goto="start", times=3),
        S("Stop Script"),
        S("Beep"),
    )


def test_edges_cover_whiles_ifs_gotos_and_loops():
    es = flow.edges(mining()["steps"])
    got = {(e["kind"], e["src"], e["dst"]) for e in es}
    assert got == {("while", 2, 5), ("if", 3, 7), ("goto", 6, 1), ("loop", 8, 0)}


def test_lanes_keep_overlapping_arrows_apart():
    es = flow.edges(mining()["steps"])
    ln = flow.lanes(es)
    for a in range(len(es)):
        for b in range(a + 1, len(es)):
            lo1, hi1 = sorted((es[a]["src"], es[a]["dst"]))
            lo2, hi2 = sorted((es[b]["src"], es[b]["dst"]))
            if not (hi1 < lo2 or hi2 < lo1):
                assert ln[a] != ln[b]


def test_unreachable_after_stop_but_loop_back_falls_through():
    # Loop Back runs its times and then carries on, so Stop Script (9) is reached; Beep (10) is not
    assert flow.unreachable(mining()) == [10]


def test_subroutines_and_error_handler_are_reachable():
    sc = script(S("Call Subroutine", goto="sub"), S("Stop Script"),
                S("Beep", label="sub"), S("Return"),
                S("Beep", label="oops"), S("Stop Script"),
                S("Beep"), error_handler="oops")
    assert flow.unreachable(sc) == [6]
