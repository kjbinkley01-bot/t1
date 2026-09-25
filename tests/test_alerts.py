"""Alerts: what gets sent, where, and when (with a local web server standing in for Discord/ntfy)."""

import datetime
import email
import http.server
import json
import threading

import pytest

from clicker import alerts
from helpers import S, run, script


@pytest.fixture
def server():
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def _take(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.append((self.command, self.path, dict(self.headers), self.rfile.read(n)))
            self.send_response(204)
            self.end_headers()

        do_POST = do_PUT = _take

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", got
    srv.shutdown()


@pytest.fixture(autouse=True)
def fresh():
    alerts._last.clear()


def failed_event(tmp_path):
    shot = tmp_path / "failure_1.png"
    shot.write_bytes(b"\x89PNG fake")
    return {"kind": "failed", "script": "Mining loop", "reason": "Image not found after 10 s", "seconds": 4320,
            "passes": 37, "step": '14 · Click Image "bank_booth"', "window": "RuneLite · background",
            "screenshot": str(shot), "log": ["12:00:01  Step 14", "12:00:11  FAILED"]}


def test_discord_gets_an_embed_with_the_screenshot_attached(tmp_path):
    sent = []
    cfg = dict(alerts.DEFAULTS, discord="https://discord.com/api/webhooks/1/abc")
    res = alerts.send(cfg, failed_event(tmp_path), request=lambda *a, **k: sent.append((a, k)))
    assert res == [("Discord", None)]
    (url, body, headers), _ = sent[0]
    assert headers["Content-Type"].startswith("multipart/form-data")
    msg = email.message_from_bytes(b"Content-Type: " + headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    parts = {p.get_param("name", header="content-disposition"): p for p in msg.get_payload()}
    payload = json.loads(parts["payload_json"].get_payload(decode=True))
    embed = payload["embeds"][0]
    assert embed["title"] == "Script stopped: Mining loop" and embed["image"]["url"] == "attachment://screenshot.png"
    names = {f["name"]: f["value"] for f in embed["fields"]}
    assert names["Step"].startswith("14") and names["Ran for"] == "1 h 12 m · 37 passes"
    assert "FAILED" in embed["description"]
    assert parts["files[0]"].get_payload(decode=True) == b"\x89PNG fake"


def test_ntfy_uploads_the_screenshot_with_title_and_message(server, tmp_path):
    base, got = server
    cfg = dict(alerts.DEFAULTS, ntfy=f"{base}/clicker-test")
    assert alerts.send(cfg, failed_event(tmp_path)) == [("ntfy", None)]
    method, path, headers, body = got[0]
    assert method == "PUT" and path == "/clicker-test" and body == b"\x89PNG fake"
    assert headers["Title"] == "Script stopped: Mining loop" and headers["Priority"] == "high"
    assert "Step 14 - Click Image" in headers["Message"] and headers["Filename"] == "screenshot.png"


def test_plain_webhook_gets_json_and_ntfy_topic_names_use_ntfy_sh(server, tmp_path):
    base, got = server
    ev = dict(failed_event(tmp_path), screenshot=None)
    alerts.send(dict(alerts.DEFAULTS, discord=f"{base}/hook"), ev)
    data = json.loads(got[0][3])
    assert data["title"] == "Script stopped: Mining loop" and data["step"].startswith("14")
    assert alerts.ntfy_url("my-topic") == "https://ntfy.sh/my-topic"


def test_errors_are_reported_not_raised():
    cfg = dict(alerts.DEFAULTS, ntfy="http://127.0.0.1:9/nothing-listens")
    [(name, err)] = alerts.send(cfg, alerts.test_event())
    assert name == "ntfy" and err


def test_should_send_follows_switches_quiet_hours_and_repeat_gap():
    cfg = dict(alerts.DEFAULTS, ntfy="topic", on_finished=False)
    ev = {"kind": "finished", "script": "A"}
    assert not alerts.should_send(cfg, ev)
    assert not alerts.should_send(dict(alerts.DEFAULTS), dict(ev, kind="failed"))  # nowhere to send
    cfg = dict(alerts.DEFAULTS, ntfy="topic", quiet=True, quiet_from="23:00", quiet_to="07:00")
    late = datetime.datetime(2026, 1, 1, 2, 30)
    noon = datetime.datetime(2026, 1, 1, 12, 0)
    assert not alerts.should_send(cfg, dict(ev, kind="failed"), late)
    assert alerts.should_send(cfg, dict(ev, kind="failed"), noon)
    w = {"kind": "window", "script": "A"}
    assert alerts.should_send(cfg, w, noon) and not alerts.should_send(cfg, w, noon)  # once per 10 minutes


def test_run_event_from_a_failed_run_has_step_screenshot_and_log(tmp_path, screen):
    r, _ = run(script(S("Wait for Image", image="missing", timeout_s=0.2), name="Waity"), log_dir=str(tmp_path))
    ev = alerts.run_event(r, *r.result)
    assert ev["kind"] == "failed" and ev["script"] == "Waity" and ev["step"].startswith("1 · Wait for Image")
    assert ev["screenshot"].endswith(".png") and any("FAILED" in ln for ln in ev["log"])


def test_user_stops_send_nothing(tmp_path, screen):
    from clicker.runner import Runner
    from clicker.storage import AssetStore
    r = Runner(script(S("Delay", ms=5000)), AssetStore(), lambda *a: None)
    threading.Timer(0.1, r.stop).start()
    r._main()
    assert alerts.run_event(r, *r.result) is None
