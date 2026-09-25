import os

import pytest

from clicker import chains, storage
from clicker.storage import AssetStore
from helpers import S, script


def save(tmp_path, name, *steps, **top):
    p = str(tmp_path / f"{name}.clk")
    storage.save_script(p, script(*steps, name=name, **top), AssetStore())
    return p


def run_chain(chain, **kw):
    events = []
    job = chains.ChainJob(chain, lambda k, p=None: events.append((k, p)), save_log=False, **kw)
    job._main()
    return job, events


def test_links_run_in_order_with_repeats_and_shared_variables(tmp_path, fake_inputs):
    a = save(tmp_path, "login", S("Set Variable", var="user", value="kim"), S("Left Click", x=1, y=1))
    b = save(tmp_path, "farm", S("Type Text", text="hi {user}"))
    c = chains.new_chain("Daily")
    c["links"] = [chains.new_link(a), dict(chains.new_link(b), repeat=2)]
    job, events = run_chain(c)
    assert job.result == (True, "Finished")
    assert fake_inputs.clicks() == [("click", "left", 1, (), (1, 1))]
    assert [x for x in fake_inputs.calls if x[0] == "type"] == [("type", "hi kim")] * 2   # variables carry on
    assert [i for i, ok, _w in job.outcomes] == [0, 1, 1]
    assert ("done", (True, "Finished")) in events and sum(1 for k, _p in events if k == "done") == 1


def test_a_failing_card_stops_the_chain(tmp_path, fake_inputs):
    bad = save(tmp_path, "bad", S("Go to Step", goto="nowhere"))
    after = save(tmp_path, "after", S("Left Click", x=1, y=1))
    c = chains.new_chain()
    c["links"] = [chains.new_link(bad), chains.new_link(after)]
    job, _e = run_chain(c)
    assert job.result[0] is False and job.result[1].startswith("Card 1 (bad):")
    assert not fake_inputs.clicks()


def test_skip_and_retry(tmp_path, fake_inputs):
    bad = save(tmp_path, "bad", S("Go to Step", goto="nowhere"))
    after = save(tmp_path, "after", S("Left Click", x=1, y=1))
    c = chains.new_chain()
    c["links"] = [dict(chains.new_link(bad), on_fail="retry", retries=2), chains.new_link(after)]
    job, events = run_chain(c)
    assert job.result[0] is False and [i for i, _ok, _w in job.outcomes] == [0, 0, 0]   # 1 try + 2 retries
    c["links"][0]["on_fail"] = "skip"
    job, events = run_chain(c)
    assert job.result == (True, "Finished") and len(fake_inputs.clicks()) == 1
    assert any("Going on to the next card" in str(p) for k, p in events if k == "log")


def test_chain_repeats_and_steps_report_their_card(tmp_path, fake_inputs):
    a = save(tmp_path, "a", S("Left Click", x=1, y=1), S("Left Click", x=2, y=2))
    c = chains.new_chain()
    c["links"] = [chains.new_link(a)]
    c["repeat"] = 3
    job, events = run_chain(c)
    assert job.result[0] and len(fake_inputs.clicks()) == 6 and job.run_number == 3
    steps = [p for k, p in events if k == "chain" and p.get("step") is not None]
    assert steps and all(p["link"] == 0 for p in steps)


def test_stop_stops_the_running_script(tmp_path, fake_inputs):
    a = save(tmp_path, "slow", S("Delay", ms=5000))
    c = chains.new_chain()
    c["links"] = [chains.new_link(a), chains.new_link(a)]
    job = chains.ChainJob(c, lambda k, p=None: None, save_log=False)
    job.start()
    import time
    time.sleep(0.3)
    job.stop()
    job.thread.join(3)
    assert not job.running and job.result[0] is False and job.result[1].startswith("Stop")


def test_files_round_trip_and_problems(tmp_path):
    a = save(tmp_path, "a", S("Left Click"))
    c = chains.new_chain("Mine")
    c["links"] = [dict(chains.new_link(a), repeat=3, pause_s=1.5, on_fail="skip")]
    p = str(tmp_path / f"x{chains.EXT}")
    chains.save(p, c)
    back = chains.load(p)
    assert back["links"][0]["repeat"] == 3 and back["links"][0]["on_fail"] == "skip" and back["name"] == "Mine"
    assert chains.describe_link(back["links"][0]) == "wait 1.5 s, 3 times, skip if it fails"
    assert chains.problems(back) == []
    os.remove(a)
    assert "missing" in chains.problems(back)[0]
    assert chains.problems(chains.new_chain())[0].startswith("Add at least one")
    with pytest.raises(ValueError):
        chains.normalize({"format": "something-else"})
