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


def k(t, typ, **kw):
    return dict(t=t, type=typ, **kw)


def messy():
    ev = [k(0.2, "move", x=0, y=0), k(1.0, "move", x=5, y=5)]                  # dawdling before starting
    ev += [k(3.0, "mouse_down", x=10, y=10, button="left"), k(3.1, "mouse_up", x=10, y=10, button="left")]
    for n, ch in enumerate("hwllo"):                                             # a typo...
        ev += [k(4.0 + n * 0.2, "key_down", char=ch, vk=65), k(4.05 + n * 0.2, "key_up", char=ch, vk=65)]
    ev += [k(5.2, "key_down", key="backspace"), k(5.25, "key_up", key="backspace")]
    for t in range(300, 750):                                                    # wandering for 9 s, 50 a second
        ev.append(k(t / 50.0, "move", x=t // 2, y=(t // 2) % 7))
    ev += [k(15.2, "mouse_down", x=20, y=20, button="left"), k(15.3, "mouse_up", x=20, y=20, button="left")]
    ev += [k(19.0, "move", x=1, y=1)]                                            # idle at the end
    return ev


def test_suggestions_find_dead_time_gaps_typos_and_dense_paths():
    ids = {s["id"]: s for s in recedit.suggest(messy())}
    assert set(ids) == {"start", "end", "gaps", "typos", "moves"}
    assert round(ids["start"]["saves"], 1) == 2.7 and round(ids["end"]["saves"], 1) == 3.5
    assert "1 typing mistake" in ids["typos"]["title"]


def test_applying_all_suggestions_keeps_the_actions():
    ev = messy()
    out = recedit.apply_suggestions(ev, {"start", "end", "gaps", "typos", "moves"})
    acts = [e["type"] for e in out if e["type"] in recedit.ACTIVE]
    assert acts.count("mouse_down") == 2 and acts.count("mouse_up") == 2
    keys = [e.get("char") or e.get("key") for e in out if e["type"] == "key_down"]
    assert keys == ["h", "w", "l", "l"]  # the last 'o' and its backspace are gone
    assert recedit.length(out) < 6 < recedit.length(ev)
    downs = [e["t"] for e in out if e["type"] == "mouse_down"]
    assert downs[0] == 0.3 and downs[1] - downs[0] < 3.5   # starts with a short approach; the 9 s wander is gone


def test_tighten_keeps_the_approach_to_the_next_click():
    ev = [k(0.0, "mouse_down", x=0, y=0, button="left"), k(0.1, "mouse_up", x=0, y=0, button="left"),
          k(2.0, "move", x=50, y=50), k(9.8, "move", x=90, y=90),
          k(10.0, "mouse_down", x=100, y=100, button="left"), k(10.1, "mouse_up", x=100, y=100, button="left")]
    out = recedit.tighten_gaps(ev)
    assert [e["t"] for e in out] == [0.0, 0.1, 0.5, 0.7, 0.8]
