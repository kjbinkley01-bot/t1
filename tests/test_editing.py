from clicker import editing, model
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, script


def names(sc):
    return [st.get("comment") for st in sc["steps"]]


def test_undo_redo_roundtrip():
    sc = script(S("Beep", comment="a"))
    h = editing.History()
    h.record(sc, [0])
    editing.insert(sc, 1, [S("Beep", comment="b")])
    assert names(sc) == ["a", "b"]
    assert h.undo(sc, [1]) == [0] and names(sc) == ["a"]
    assert h.redo(sc) == [1] and names(sc) == ["a", "b"]
    assert h.redo(sc) is None


def test_new_change_clears_redo():
    sc = script(S("Beep"))
    h = editing.History()
    h.record(sc)
    editing.delete(sc, [0])
    h.undo(sc)
    h.record(sc)
    assert not h.can_redo


def test_history_limit():
    sc = script(S("Beep"))
    h = editing.History(limit=3)
    for _ in range(10):
        h.record(sc)
    assert len(h.undo_stack) == 3


def test_move_block_keeps_jumps():
    sc = script(S("Beep", comment="a"), S("Beep", comment="b"), S("Beep", comment="c"),
                S("Go to Step", goto=1, comment="jump"))
    new = editing.move_to(sc, [0, 1], 2)
    assert names(sc) == ["c", "jump", "a", "b"] and new == [2, 3]
    assert sc["steps"][1]["goto"] == 3  # still points at "a"


def test_shift_up_down_and_edges():
    sc = script(S("Beep", comment="a"), S("Beep", comment="b"), S("Beep", comment="c"))
    assert editing.shift(sc, [2], -1) == [1] and names(sc) == ["a", "c", "b"]
    assert editing.shift(sc, [0], -1) == [0] and names(sc) == ["a", "c", "b"]
    assert editing.shift(sc, [0, 1], 1) == [1, 2] and names(sc) == ["b", "a", "c"]


def test_delete_multiple_returns_next_selection():
    sc = script(*(S("Beep", comment=c) for c in "abcd"))
    assert editing.delete(sc, [1, 2]) == 1 and names(sc) == ["a", "d"]
    assert editing.delete(sc, [0, 1]) is None and sc["steps"] == []


def test_duplicate_block_repoints_internal_jumps():
    sc = script(S("Beep", comment="a", label="top"), S("Loop Back", goto=1, times=2, comment="loop"),
                S("Beep", comment="end"))
    new = editing.duplicate(sc, [0, 1])
    assert new == [2, 3]
    assert names(sc) == ["a", "loop", "a", "loop", "end"]
    assert sc["steps"][1]["goto"] == 1          # original untouched
    assert sc["steps"][3]["goto"] == 3          # copy loops to the copy
    assert sc["steps"][2]["label"] == ""        # labels are not duplicated


def test_copy_paste_between_scripts_brings_images():
    src = script(S("Click Image", image="btn", comment="click"), S("Go to Step", goto=1))
    a = AssetStore()
    a.put_image("btn.png", make_template())
    text = editing.copy_payload(src, a, [0, 1])

    dst = script(S("Beep", comment="x"), S("Go to Step", goto=1))
    b = AssetStore()
    new = editing.paste(dst, b, text, 1)
    assert new == [1, 2]
    assert [st["action"] for st in dst["steps"]] == ["Beep", "Click Image", "Go to Step", "Go to Step"]
    assert dst["steps"][2]["goto"] == 2          # pasted jump points at pasted click
    assert dst["steps"][3]["goto"] == 1          # existing jump unaffected
    assert b.has("btn.png")


def test_paste_renames_clashing_image():
    src = script(S("Click Image", image="btn"))
    a = AssetStore()
    a.put_image("btn.png", make_template(seed=1))
    text = editing.copy_payload(src, a, [0])
    dst = script(S("Beep"))
    b = AssetStore()
    b.put_image("btn.png", make_template(seed=2))
    editing.paste(dst, b, text, 1)
    assert dst["steps"][1]["image"] == "btn_2.png" and b.has("btn_2.png")


def test_paste_accepts_plain_script_json_and_ignores_junk():
    dst = script(S("Beep"))
    assert editing.paste(dst, AssetStore(), "not json", 0) is None
    new = editing.paste(dst, AssetStore(), '{"steps": [{"action": "Left Click", "x": 1, "y": 2}]}', 0)
    assert new == [0] and dst["steps"][0]["x"] == 1


def test_pasted_steps_validate():
    src = script(S("Wait for Image", image="i", wait={"mode": "none", "on_timeout": "goto", "goto": 1}))
    a = AssetStore()
    a.put_image("i.png", make_template())
    text = editing.copy_payload(src, a, [0])
    dst = script(S("Beep"), S("Beep"))
    editing.paste(dst, a, text, 2)
    assert dst["steps"][2]["wait"]["goto"] == 3
    assert model.check_step(dst["steps"][2], dst["steps"]) is None


def test_coalesce_keeps_newest_of_each_kind_in_order():
    from clicker.core import coalesce
    batch = [("script", "step", 1), ("script", "log", "a"), ("script", "step", 2), ("script", "done", 1),
             ("script", "log", "b"), ("app", "cursor", 1), ("app", "cursor", 2)]
    assert coalesce(batch) == [("script", "step", 2), ("script", "done", 1), ("script", "log", "b"),
                               ("app", "cursor", 2)]
