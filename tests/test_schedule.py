"""Scheduler timing."""

import datetime

from clicker import schedule as sch

MON_0859 = datetime.datetime(2026, 9, 28, 8, 59)  # a Monday


def ts(d):
    return d.timestamp()


def test_daily_runs_once_per_day_on_chosen_days():
    e = dict(sch.new_entry("/a.clk"), time="09:00", days=[0, 1, 2, 3, 4])
    assert not sch.due(e, MON_0859)
    at = MON_0859 + datetime.timedelta(minutes=1)
    assert sch.due(e, at)
    e["last_run"] = ts(at)
    assert not sch.due(e, at + datetime.timedelta(minutes=5))
    assert sch.next_run(e, at) == datetime.datetime(2026, 9, 29, 9, 0)
    fri = datetime.datetime(2026, 10, 2, 9, 30)
    e["last_run"] = ts(fri)
    assert sch.next_run(e, fri) == datetime.datetime(2026, 10, 5, 9, 0)  # skips the weekend


def test_missed_by_more_than_grace_waits_for_next_day():
    e = dict(sch.new_entry("/a.clk"), time="09:00")
    late = datetime.datetime(2026, 9, 28, 9, 30)
    assert not sch.due(e, late) and sch.next_run(e, late).day == 29
    assert sch.due(e, datetime.datetime(2026, 9, 28, 9, 8))


def test_interval_and_once():
    e = dict(sch.new_entry("/a.clk"), kind="interval", every_min=30)
    assert sch.due(e, MON_0859)
    e["last_run"] = ts(MON_0859)
    assert not sch.due(e, MON_0859 + datetime.timedelta(minutes=29))
    assert sch.due(e, MON_0859 + datetime.timedelta(minutes=30))
    o = dict(sch.new_entry("/a.clk"), kind="once", once_at="2026-09-28 10:00")
    assert not sch.due(o, MON_0859) and sch.due(o, datetime.datetime(2026, 9, 28, 10, 1))
    o["last_run"] = ts(datetime.datetime(2026, 9, 28, 10, 1))
    assert sch.next_run(o) is None


def test_checks_and_descriptions():
    e = sch.new_entry("/a.clk")
    assert sch.describe(dict(e, days=[0, 1, 2, 3, 4])) == "weekdays at 09:00"
    assert sch.check(dict(e, time="9am")) and sch.check(dict(e, days=[]))
    assert sch.check(dict(e, kind="window")) and not sch.check(dict(e, kind="window", window_process="x.exe"))
    assert not sch.due(dict(e, enabled=False), datetime.datetime(2026, 9, 28, 9, 1))


def test_window_watch_fires_on_appearance_only():
    w = sch.WindowWatch()
    e = {"id": "x"}
    assert not w.appeared(e, True)      # open when Clicker started
    assert not w.appeared(e, False)
    assert w.appeared(e, True)
    assert not w.appeared(e, True)
