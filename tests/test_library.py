import os
import time

import cv2
import numpy as np

from clicker import library, model, storage


def make_script(path, name="Farm", pictures=True, n=3):
    s = model.new_script(name)
    s["steps"] = [model.new_step("Left Click") for _ in range(n)]
    assets = storage.AssetStore()
    if pictures:
        img = np.zeros((40, 60, 3), np.uint8)
        img[:, :30] = (0, 0, 255)
        nm = assets.add_image(img, "button")
        st = model.new_step("Click Image")
        st["image"] = nm
        s["steps"].append(st)
    storage.save_script(str(path), s, assets)
    return str(path)


def make_recording(path, snap=True):
    events = [{"t": 0.5, "type": "move", "x": 1, "y": 2},
              {"t": 1.0, "type": "mouse_down", "x": 1, "y": 2, "button": "left"},
              {"t": 1.1, "type": "mouse_up", "x": 1, "y": 2, "button": "left"},
              {"t": 2.0, "type": "key_down", "key": "a"},
              {"t": 42.0, "type": "key_up", "key": "a"}]
    snaps = {}
    if snap:
        img = np.full((90, 160, 3), 200, np.uint8)
        snaps["s1.jpg"] = cv2.imencode(".jpg", img)[1].tobytes()
        events.insert(0, {"t": 0.1, "type": "snap", "snap": "s1.jpg"})
    storage.save_recording(str(path), events, {}, {}, snaps)
    return str(path)


def test_scripts_get_a_name_detail_and_their_first_picture(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    p = make_script(tmp_path / "farm.clk")
    e = lib.touch_file(p)
    assert e["kind"] == "script" and e["name"] == "Farm"
    assert e["detail"] == "4 steps, 1 picture"
    thumb = cv2.imread(lib.thumb_path(e))
    assert thumb.shape == (library.THUMB_H, library.THUMB_W, 3)
    assert e["actions"][0] == "Left Click"


def test_scripts_without_pictures_keep_their_actions_for_a_diagram(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    e = lib.touch_file(make_script(tmp_path / "plain.clk", pictures=False, n=12))
    assert e["thumb"] is None and len(e["actions"]) == 8 and e["detail"] == "12 steps"


def test_recordings_use_a_snapshot_and_keep_click_times(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    e = lib.touch_file(make_recording(tmp_path / "r.clkrec"))
    assert e["kind"] == "recording" and e["detail"] == "0:42, 5 events"
    assert e["thumb"] and os.path.exists(lib.thumb_path(e))
    assert e["clicks"] == [round(1.0 / 42.0, 3)]
    plain = lib.touch_file(make_recording(tmp_path / "plain.clkrec", snap=False))
    assert plain["thumb"] is None


def test_search_favorites_and_order(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    a = make_script(tmp_path / "mining.clk", "Mining loop")
    b = make_script(tmp_path / "fishing.clk", "Fishing")
    r = make_recording(tmp_path / "walk.clkrec")
    for p in (a, b, r):
        lib.touch_file(p)
        time.sleep(0.01)
    assert [e["path"] for e in lib.list()] == [r, b, a]       # most recent first
    assert [e["path"] for e in lib.list("loop MIN")] == [a]  # every word, any case
    assert [e["path"] for e in lib.list(kind="recording")] == [r]
    lib.set_favorite(a, True)
    assert [e["path"] for e in lib.list(favorites=True)] == [a]
    lib.save()
    again = library.Library(str(tmp_path / "data"))           # survives a restart
    assert again.entries[a]["favorite"] is True


def test_missing_files_are_marked_and_can_be_forgotten(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    p = make_script(tmp_path / "gone.clk")
    e = lib.touch_file(p)
    thumb = lib.thumb_path(e)
    os.remove(p)
    assert lib.list()[0]["missing"] is True
    lib.forget(p)
    assert lib.list() == [] and not os.path.exists(thumb)


def test_add_folder_and_old_recent_list(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    folder = tmp_path / "scripts"
    folder.mkdir()
    make_script(folder / "a.clk")
    make_recording(folder / "b.clkrec")
    (folder / "notes.txt").write_text("not a script")
    assert lib.add_folder(str(folder)) == 2
    assert lib.add_folder(str(folder)) == 0                   # already known
    other = make_script(tmp_path / "old.clk")
    lib.import_recent([other, str(tmp_path / "missing.clk")])
    assert set(e["path"] for e in lib.list()) == {str(folder / "a.clk"), str(folder / "b.clkrec"), other}


def test_recent_list_is_capped_but_favorites_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "MAX_RECENT", 3)
    lib = library.Library(str(tmp_path / "data"))
    paths = [make_script(tmp_path / f"s{i}.clk", pictures=False) for i in range(5)]
    lib.touch_file(paths[0])
    lib.set_favorite(paths[0], True)
    for p in paths[1:]:
        lib.touch_file(p)
        time.sleep(0.01)
    kept = {e["path"] for e in lib.list()}
    assert kept == {paths[0], paths[2], paths[3], paths[4]}


def test_when_text():
    now = 1_000_000.0
    assert library.when_text(now - 5, now) == "just now"
    assert library.when_text(now - 600, now) == "10 min ago"
    assert library.when_text(now - 7200, now) == "2 h ago"
    assert library.when_text(now - 90000, now) == "yesterday"
    assert library.when_text(0, now) == "added"


def test_chains_are_a_library_kind(tmp_path):
    from clicker import chains
    lib = library.Library(str(tmp_path / "data"))
    a = make_script(tmp_path / "login.clk", "Login", pictures=False)
    c = chains.new_chain("Daily")
    c["links"] = [chains.new_link(a), chains.new_link(a)]
    p = str(tmp_path / "daily.clkchain")
    chains.save(p, c)
    e = lib.touch_file(p)
    assert e["kind"] == "chain" and e["detail"] == "2 scripts" and e["links"] == ["login", "login"]
    assert [x["path"] for x in lib.list("login", kind="chain")] == [p]   # found by the scripts it runs
