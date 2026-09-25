"""Run history: what each run records, and the numbers the History tab shows."""

import datetime
import time

from clicker import history
from helpers import S, run, script


def test_runs_are_recorded_with_result_and_failed_step(tmp_path, screen):
    run(script(S("Left Click", x=1, y=1), name="Clicky"), log_dir=str(tmp_path))
    run(script(S("Left Click", x=1, y=1), S("Wait for Image", image="missing", timeout_s=0.2), name="Waity"),
        log_dir=str(tmp_path))
    ents = history.load(str(tmp_path / "history.jsonl"))
    assert [e["result"] for e in ents] == ["finished", "failed"]
    assert ents[0]["script"] == "Clicky" and ents[0]["seconds"] >= 0 and ents[0]["step"] is None
    assert ents[1]["step"] == 2 and ents[1]["step_desc"].startswith('2 · Wait for Image "missing"')


def test_stopped_runs_are_not_failures(tmp_path, screen):
    import threading

    from clicker.runner import Runner
    from clicker.storage import AssetStore
    r = Runner(script(S("Delay", ms=5000), name="Long"), AssetStore(), lambda *a: None, log_dir=str(tmp_path))
    threading.Timer(0.2, r.stop).start()
    r._main()
    e = history.load(str(tmp_path / "history.jsonl"))[-1]
    assert e["result"] == "stopped" and e["step"] is None


def test_no_history_without_logs(tmp_path, screen, monkeypatch):
    monkeypatch.setattr(history, "default_path", lambda: str(tmp_path / "h.jsonl"))
    run(script(S("Left Click", x=1, y=1)))  # save_log is off
    assert history.load(str(tmp_path / "h.jsonl")) == []


def _e(days_ago, result, secs=60, step=None, script_name="A", now=None):
    now = now or time.time()
    return {"ts": now - days_ago * 86400, "script": script_name, "result": result, "seconds": secs,
            "step_desc": step, "reason": "x"}


def test_stats_success_rate_average_and_top_failure():
    now = time.time()
    ents = [_e(0, "finished", 100), _e(1, "finished", 200), _e(1, "failed", 5, "14 · Click Image"),
            _e(2, "failed", 5, "14 · Click Image"), _e(2, "failed", 5, "3 · Read Text"), _e(3, "stopped", 9)]
    st = history.stats(ents, days=7, now=now)
    assert st["runs"] == 6 and st["finished"] == 2 and st["failed"] == 3 and st["stopped"] == 1
    assert round(st["success_rate"], 2) == 0.4          # stopped-by-you runs don't count either way
    assert st["avg_seconds"] == 150 and st["fastest_seconds"] == 100
    assert st["top_fail"] == ("14 · Click Image", 2)
    assert len(st["per_day"]) == 7 and st["per_day"][-1][0] == datetime.date.fromtimestamp(now)
    assert st["per_day"][-2][1:] == (1, 1)


def test_select_filters_by_days_script_and_dry_runs():
    now = time.time()
    ents = [_e(1, "finished", now=now), _e(10, "finished", now=now), _e(1, "failed", script_name="B", now=now),
            dict(_e(0, "finished", now=now), dry_run=True)]
    assert len(history.select(ents, 7, None, now)) == 2
    assert len(history.select(ents, None, "A", now)) == 2
    assert history.scripts(ents) == ["A", "B"]


def test_file_is_trimmed_when_large(tmp_path, monkeypatch):
    p = str(tmp_path / "h.jsonl")
    monkeypatch.setattr(history, "KEEP", 10)
    with open(p, "w", encoding="utf-8") as f:
        f.write(("x" * 1000 + "\n") * 3100)
    history.record({"ts": 1, "result": "finished"}, p)
    with open(p, encoding="utf-8") as f:
        assert len(f.readlines()) == 10
