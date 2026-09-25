import os
import time

from clicker import versions


def test_keeps_old_copies_newest_first_and_skips_unchanged(tmp_path):
    root = str(tmp_path / "data")
    p = tmp_path / "farm.clk"
    assert versions.keep(str(p), root) is None           # nothing there yet
    p.write_bytes(b"v1")
    first = versions.keep(str(p), root)
    assert first and open(first, "rb").read() == b"v1"
    assert versions.keep(str(p), root) is None           # same content: no new copy
    p.write_bytes(b"v2")
    time.sleep(0.01)
    versions.keep(str(p), root)
    vs = versions.list_versions(str(p), root)
    assert [open(v["file"], "rb").read() for v in vs] == [b"v2", b"v1"]


def test_only_the_newest_ten_stay(tmp_path, monkeypatch):
    monkeypatch.setattr(versions, "MAX_KEEP", 3)
    root = str(tmp_path / "data")
    p = tmp_path / "s.clk"
    for i in range(6):
        p.write_bytes(f"v{i}".encode())
        versions.keep(str(p), root)
        time.sleep(0.01)
    vs = versions.list_versions(str(p), root)
    assert [open(v["file"], "rb").read() for v in vs] == [b"v5", b"v4", b"v3"]
    assert len(os.listdir(os.path.dirname(vs[0]["file"]))) == 4   # three copies and the index


def test_other_files_have_their_own_history(tmp_path):
    root = str(tmp_path / "data")
    a, b = tmp_path / "a.clk", tmp_path / "b.clk"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    versions.keep(str(a), root)
    assert versions.list_versions(str(b), root) == []


def test_when_text():
    import datetime
    now = datetime.datetime(2026, 3, 5, 18, 0)
    assert versions.when_text(datetime.datetime(2026, 3, 5, 9, 7), now) == "Today 09:07"
    assert versions.when_text(datetime.datetime(2026, 3, 4, 9, 7), now) == "Yesterday 09:07"
    assert versions.when_text(datetime.datetime(2026, 2, 1, 9, 7), now) == "Feb 1, 09:07"
