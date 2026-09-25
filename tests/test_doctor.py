import os

from clicker import chains, doctor, library, storage
from clicker.storage import AssetStore
from helpers import S, script
from test_library import make_recording


def save(tmp_path, name, *steps):
    p = str(tmp_path / f"{name}.clk")
    storage.save_script(p, script(*steps, name=name), AssetStore())
    return p


def test_finds_what_would_stop_a_run(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    good = save(tmp_path, "good", S("Left Click", x=1, y=1))
    jump = save(tmp_path, "jump", S("Go to Step", goto="nowhere"))
    calls = save(tmp_path, "calls", S("Run Script File", file=str(tmp_path / "gone.clk")),
                 S("Run Script File", file="{folder}/any.clk"))           # variables can't be checked yet
    gone = save(tmp_path, "gone_later", S("Left Click"))
    rec = make_recording(tmp_path / "r.clkrec")
    ch = str(tmp_path / "c.clkchain")
    c = chains.new_chain("C")
    c["links"] = [chains.new_link(good), chains.new_link(jump)]
    chains.save(ch, c)
    for p in (good, jump, calls, gone, rec, ch):
        lib.touch_file(p)
    os.remove(gone)
    found, checked = doctor.check_all(lib, {"script_hotkeys": [{"path": str(tmp_path / "hotkey_gone.clk")}]})
    by = {}
    for f in found:
        by.setdefault(os.path.basename(f["path"]), []).append(f)
    assert checked == 7
    assert "good.clk" not in by and "r.clkrec" not in by
    assert "nowhere" in by["jump.clk"][0]["message"]
    assert len(by["calls.clk"]) == 1 and "gone.clk is missing" in by["calls.clk"][0]["message"]
    assert by["gone_later.clk"][0]["message"].startswith("The file is missing")
    assert by["hotkey_gone.clk"][0]["where"] == "Script hotkey"
    assert by["c.clkchain"][0]["level"] == "warn" and "Card 2" in by["c.clkchain"][0]["message"]
    assert found[0]["level"] == "error"                                  # errors first
    assert doctor.summary(found, checked) == "Checked 7 files: 5 need attention."


def test_all_clear_and_nothing_to_check(tmp_path):
    lib = library.Library(str(tmp_path / "data"))
    assert doctor.summary(*doctor.check_all(lib)).startswith("There's nothing to check")
    lib.touch_file(save(tmp_path, "ok", S("Left Click")))
    assert doctor.summary(*doctor.check_all(lib)) == "Checked 1 file: everything looks ready to run."
