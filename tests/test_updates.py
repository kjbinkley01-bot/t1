import hashlib
import io
import os
import time

import pytest

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
    rel = {"tag": "v99.0.0", "url": "https://x", "notes": "notes", "assets": []}
    monkeypatch.setattr(updates, "latest_release", lambda repo, timeout=6: rel)
    got, settings = [], {"skip_update": "v99.0.0"}
    updates.check_async(settings, got.append)
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.01)
    assert got[0]["newer"] and got[0]["tag"] == "v99.0.0" and settings["last_update_check"] > 0
    assert got[0]["skipped"]                           # the automatic check stays quiet about a skipped version


def asset(name="Clicker-Setup.exe", data=b"installer", digest=None):
    return {"name": name, "url": "https://example/" + name, "size": len(data),
            "digest": digest if digest is not None else "sha256:" + hashlib.sha256(data).hexdigest()}


def test_installer_asset_needs_a_checksum():
    rel = {"assets": [asset("Clicker-macos.dmg"), asset("Clicker-Setup.exe", digest="")]}
    assert updates.installer_asset(rel) is None                   # no digest: never installed blind
    good = asset()
    rel["assets"].append(good)
    assert updates.installer_asset(rel) is good


def test_install_mode_from_where_the_app_lives():
    env = {"LOCALAPPDATA": "/u/AppData/Local", "ProgramFiles": "/pf"}
    assert updates.install_mode("/u/AppData/Local/Programs/Clicker/Clicker.exe", env) == "user"
    assert updates.install_mode("/pf/Clicker/Clicker.exe", env) == "all"
    assert updates.install_mode("/u/Downloads/Clicker/Clicker.exe", env) is None      # a portable copy
    assert updates.install_mode("/pfx/Clicker.exe", env) is None
    assert updates.install_mode() is None                                               # tests run from source
    assert not updates.can_install({"assets": [asset()]})


def test_installer_runs_quietly_into_the_same_place():
    cmd = updates.installer_command("C:/t/Clicker-Setup.exe", "user")
    assert cmd[0] == "C:/t/Clicker-Setup.exe" and "/SILENT" in cmd and "/CURRENTUSER" in cmd
    assert "/ALLUSERS" in updates.installer_command("x", "all")


class FakeResp(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_checks_the_digest(monkeypatch, tmp_path):
    data = os.urandom(600 * 1024)
    monkeypatch.setattr(updates, "_get", lambda url, timeout: FakeResp(data))
    seen = []
    path = updates.download(asset(data=data), str(tmp_path), progress=lambda d, t: seen.append((d, t)))
    assert open(path, "rb").read() == data and seen[-1] == (len(data), len(data))
    with pytest.raises(updates.DownloadFailed, match="damaged"):
        updates.download(asset(name="Clicker-Setup2.exe", data=b"other"), str(tmp_path))
    assert sorted(os.listdir(tmp_path)) == ["Clicker-Setup.exe"]          # the bad download is gone


def test_download_can_be_cancelled(monkeypatch, tmp_path):
    import threading
    monkeypatch.setattr(updates, "_get", lambda url, timeout: FakeResp(b"x" * 10))
    stop = threading.Event()
    stop.set()
    with pytest.raises(updates.DownloadFailed, match="Cancelled"):
        updates.download(asset(data=b"x" * 10), str(tmp_path), stop=stop)
    assert os.listdir(tmp_path) == []
