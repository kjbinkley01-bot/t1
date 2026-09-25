"""Snippets and backup."""

import os

from clicker import backup, snippets
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, script


def test_snippet_round_trip_with_images_and_jumps(tmp_path, monkeypatch):
    monkeypatch.setattr(snippets, "folder", lambda: str(tmp_path))
    a = AssetStore()
    a.put_image("btn.png", make_template())
    src = script(S("Beep"), S("Click Image", image="btn", label="go"), S("Go to Step", goto="go"), S("Beep"))
    snippets.save("Bank and return", src, a, [1, 2])
    assert snippets.names() == ["Bank and return"] and snippets.count("Bank and return") == 2
    dst = script(S("Beep"), S("Beep"))
    b = AssetStore()
    b.put_image("btn.png", make_template(seed=9))  # a different picture with the same name
    new = snippets.insert("Bank and return", dst, b, 1)
    assert new == [1, 2]
    ins = dst["steps"]
    assert ins[1]["action"] == "Click Image" and ins[1]["image"] != "btn.png" and b.has(ins[1]["image"])
    assert ins[2]["goto"] in ("go", 2)
    snippets.delete("Bank and return")
    assert snippets.names() == []


def test_backup_export_and_restore(tmp_path):
    data = tmp_path / "data"
    (data / "snippets").mkdir(parents=True)
    (data / "triggers.clktrig").write_bytes(b"zipdata")
    (data / "history.jsonl").write_text('{"ts": 1, "result": "finished"}\n')
    (data / "snippets" / "Log in.json").write_text("{}")
    scripts = tmp_path / "mine"
    scripts.mkdir()
    s1 = scripts / "Mining loop.clk"
    s1.write_bytes(b"script1")
    settings = {"script_hotkeys": [{"path": str(s1), "keys": "Ctrl+Alt+1"}], "recent": [str(s1), "/gone.clk"],
                "wallpaper": "dusk"}
    out = tmp_path / "b.clkbackup"
    assert backup.export(str(out), str(data), settings) == "1 script, 1 snippet"
    other = tmp_path / "other"
    other.mkdir()
    new_settings, summary = backup.restore(str(out), str(other), str(tmp_path / "restored"))
    assert summary == "1 script, 1 snippet"
    restored = str(tmp_path / "restored" / "Mining loop.clk")
    assert new_settings["script_hotkeys"][0]["path"] == restored and open(restored, "rb").read() == b"script1"
    assert new_settings["recent"][0] == restored and new_settings["wallpaper"] == "dusk"
    assert (other / "triggers.clktrig").read_bytes() == b"zipdata"
    assert os.path.exists(other / "snippets" / "Log in.json")
