"""Recording edits: trim, delete, keep only, shorten pauses, and presses stay paired."""

from clicker import recedit


def ev(t, typ, **kw):
    return dict(t=t, type=typ, **kw)


REC = [
    ev(0.5, "mouse_down", x=1, y=1, button="left"), ev(0.6, "mouse_up", x=1, y=1, button="left"),
    ev(1.0, "key_down", key="shift"), ev(1.2, "key_down", char="a", vk=65), ev(1.3, "key_up", char="a", vk=65),
    ev(1.4, "key_up", key="shift"),
    ev(8.0, "move", x=5, y=5),                                    # after a 6.6 s pause
    ev(8.5, "mouse_down", x=5, y=5, button="left"), ev(9.0, "mouse_up", x=9, y=9, button="left"),
]


def test_trim_rebases_time_and_drops_split_presses():
    out = recedit.trim(REC, 1.1, 8.7)
    # shift press (1.0) and the final release (9.0) are outside, so their partners go too
    assert [(e["type"], e["t"]) for e in out] == [("key_down", 0.1), ("key_up", 0.2), ("move", 6.9)]


def test_delete_closes_the_gap():
    out = recedit.delete(REC, 2.0, 7.0)
    assert out[-1]["t"] == 4.0 and len(out) == len(REC)
    assert recedit.length(out) == recedit.length(REC) - 5.0


def test_delete_in_the_middle_of_a_hold_keeps_nothing_held():
    out = recedit.delete(REC, 1.1, 1.35)   # removes 'a' press/release and nothing else: still balanced
    assert [e["type"] for e in out][:4] == ["mouse_down", "mouse_up", "key_down", "key_up"]
    out = recedit.delete(REC, 0.55, 0.65)  # cuts only the release: the press goes too
    assert out[0]["type"] == "key_down"


def test_pauses_and_shorten():
    assert recedit.pauses(REC, 2.0) == [(1.4, 8.0)]
    out = recedit.shorten_pauses(REC, 2.0, 0.5)
    assert recedit.length(out) == 2.9
    assert [e["t"] for e in out][-3:] == [1.9, 2.4, 2.9]


def test_select_and_describe():
    assert recedit.select(REC, 1.0, 1.4) == (2, 6)
    assert recedit.describe(REC[3]) == ("Key press", "a")
    assert recedit.describe(REC[0])[0] == "Left press"
