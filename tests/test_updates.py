import time

from clicker import updates


def test_parse_and_compare_versions():
    assert updates.parse_version("v2.10.1") == (2, 10, 1)
    assert updates.parse_version("2.1") == (2, 1, 0)
    assert updates.parse_version("junk") == (0, 0, 0)
    assert updates.is_newer("v2.10.0", "2.9.9")
    assert not updates.is_newer("v2.1.0", "2.1.0")
    assert not updates.is_newer("", "2.1.0")


def test_due_respects_setting_and_interval():
    now = time.time()
    assert updates.due({}, now)
    assert not updates.due({"check_updates": False}, now)
    assert not updates.due({"last_update_check": now - 60}, now)
    assert updates.due({"last_update_check": now - 2 * updates.CHECK_EVERY_S}, now)


def test_check_async_reports_errors_without_raising(monkeypatch):
    def boom(repo, timeout=6):
        raise OSError("offline")
    monkeypatch.setattr(updates, "latest_release", boom)
    got = []
    assert updates.check_async({}, got.append, force=True)
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.01)
    assert got == [{"error": "offline"}]


def test_check_async_flags_newer(monkeypatch):
    monkeypatch.setattr(updates, "latest_release", lambda repo, timeout=6: ("v99.0.0", "https://x", "notes"))
    got, settings = [], {}
    updates.check_async(settings, got.append, force=True)
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.01)
    assert got[0]["newer"] and got[0]["tag"] == "v99.0.0" and settings["last_update_check"] > 0
