import json

import pytest

from clicker import model, runlog, storage
from clicker.storage import AssetStore
from conftest import make_template
from helpers import S, script


def test_save_and_load_roundtrip_keeps_labels_images_and_settings(tmp_path):
    sc = script(S("Click Image", image="btn", label="start"), S("Go to Step", goto="start"),
                settings={"restart_on_failure": 2, "scale_search": True})
    assets = AssetStore()
    assets.put_image("btn.png", make_template())
    assets.put_image("unused.png", make_template(seed=2))
    path = tmp_path / "t.clk"
    storage.save_script(str(path), sc, assets)
    loaded, la = storage.load_script(str(path))
    assert loaded["steps"][0]["label"] == "start"
    assert loaded["steps"][1]["goto"] == "start"
    assert loaded["settings"]["restart_on_failure"] == 2 and loaded["settings"]["scale_search"] is True
    assert la.names() == ["btn.png"]  # unused images are not packed


def test_old_v2_scripts_still_load(tmp_path):
    old = {"format": "clicker-script", "version": 2, "name": "old",
           "steps": [{"action": "Left Click", "x": 1, "y": 2}, {"action": "Go to Step", "goto": "1"}]}
    p = tmp_path / "old.json"
    p.write_text(json.dumps(old))
    sc, _ = storage.load_script(str(p))
    assert sc["steps"][1]["goto"] == 1 and sc["steps"][0]["label"] == ""
    assert sc["settings"]["restart_on_failure"] == 0


def test_parse_script_text_strips_code_fence():
    sc = storage.parse_script_text('```json\n{"steps": [{"action": "Beep"}]}\n```')
    assert sc["steps"][0]["action"] == "Beep"


def _errors(sc, assets=None):
    return [m for lvl, m in storage.validate(sc, assets or AssetStore()) if lvl == "error"]


def test_validate_flags_duplicate_labels_and_bad_blocks():
    errs = _errors(script(S("Beep", label="a"), S("Beep", label="a"), S("End While")))
    assert any("already used by step 1" in e for e in errs)
    assert any("End While has no While" in e for e in errs)


def test_validate_flags_missing_label_target_and_handler():
    errs = _errors(script(S("Go to Step", goto="missing"), error_handler="nope"))
    assert any("No step is labelled 'missing'" in e for e in errs)
    assert any(e.startswith("Error handler") for e in errs)


def test_validate_accepts_good_script():
    assert _errors(script(S("Beep", label="top"), S("Loop Back", goto="top", times=2))) == []


def test_run_log_prunes_old_runs(tmp_path):
    for i in range(5):
        runlog.RunLog(f"run{i}", str(tmp_path), keep=3).close()
    assert len(list(tmp_path.iterdir())) == 3


def test_normalize_rejects_garbage():
    with pytest.raises(ValueError):
        model.normalize_script({"steps": [{"x": 1}]})


def test_run_log_caps_step_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "MAX_DETAIL_LINES", 5)
    log = runlog.RunLog("cap", str(tmp_path))
    for i in range(50):
        log.write(f"step {i}", detail=True)
    log.write("FAILED: boom")
    log.close()
    text = open(log.path, encoding="utf-8").read()
    import re
    assert len(re.findall(r"step \d", text)) == 5 and "stop here" in text and "FAILED: boom" in text
