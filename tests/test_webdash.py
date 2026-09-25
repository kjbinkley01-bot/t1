"""Web dashboard: PIN login, lockout, local-only access and the API."""

import http.cookiejar
import json
import urllib.error
import urllib.request

import pytest

from clicker import webdash


@pytest.fixture
def dash():
    calls = []

    def call(cmd, args):
        calls.append((cmd, args))
        if cmd == "screenshot":
            return b"\x89PNG"
        if cmd == "status":
            return {"runs": [], "scripts": ["Mining loop"], "history": [], "machine": "pc"}
        return {"ok": True, "msg": f"{cmd} done"}
    d = webdash.Dashboard(0, "4821", call).start()
    d.calls = calls
    d.url = f"http://127.0.0.1:{d.server.server_address[1]}"
    yield d
    d.stop()


def opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.ProxyHandler({}))


def post(op, url, data, json_body=False):
    body = json.dumps(data).encode() if json_body else "&".join(f"{k}={v}" for k, v in data.items()).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json" if json_body else
                                                          "application/x-www-form-urlencoded"})
    return op.open(req, timeout=5)


def test_login_then_status_start_and_screenshot(dash):
    op = opener()
    assert b"Enter your PIN" in op.open(dash.url + "/", timeout=5).read()
    with pytest.raises(urllib.error.HTTPError) as e:
        op.open(dash.url + "/api/status", timeout=5)
    assert e.value.code == 401
    page = post(op, dash.url + "/login", {"pin": "4821"}).read()
    assert b"Running now" in page
    st = json.loads(op.open(dash.url + "/api/status", timeout=5).read())
    assert st["scripts"] == ["Mining loop"]
    r = json.loads(post(op, dash.url + "/api/start", {"name": "Mining loop"}, json_body=True).read())
    assert r["msg"] == "start done" and ("start", {"name": "Mining loop"}) in dash.calls
    assert op.open(dash.url + "/api/screenshot", timeout=5).read() == b"\x89PNG"


def test_wrong_pins_lock_out(dash):
    op = opener()
    for _ in range(webdash.MAX_TRIES):
        with pytest.raises(urllib.error.HTTPError) as e:
            post(op, dash.url + "/login", {"pin": "0000"})
        assert e.value.code == 401
    with pytest.raises(urllib.error.HTTPError) as e:
        post(op, dash.url + "/login", {"pin": "4821"})
    assert e.value.code == 429


def test_only_local_network(dash, monkeypatch):
    monkeypatch.setattr(webdash, "is_local", lambda ip: False)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener().open(dash.url + "/", timeout=5)
    assert e.value.code == 403
    assert not webdash.__dict__["ipaddress"].ip_address("8.8.8.8").is_private


def test_is_local():
    assert webdash.is_local("192.168.1.20") and webdash.is_local("10.0.0.5") and webdash.is_local("127.0.0.1")
    assert not webdash.is_local("8.8.8.8") and not webdash.is_local("nonsense")
