"""Phone remote control: parsing, matching, replies and the listener (against a local stand-in for ntfy)."""

import http.server
import json
import threading
import time

from clicker import remote


def test_parse_commands_and_pin():
    assert remote.parse("status") == ("status", "")
    assert remote.parse("Start mining loop") == ("start", "mining loop")
    assert remote.parse("run fishing") == ("start", "fishing")
    assert remote.parse("start")[0] is None
    assert remote.parse("dance")[0] is None
    assert remote.parse("4821 stop", pin="4821") == ("stop", "")
    assert remote.parse("stop", pin="4821") == (None, "wrong or missing PIN")


def test_match_script_by_name():
    paths = ["/s/Mining_loop.clk", "/s/Mining trip.clk", "/s/Fishing.clk"]
    assert remote.match_script("fishing", paths) == ("/s/Fishing.clk", None)
    assert remote.match_script("mining loop", paths) == ("/s/Mining_loop.clk", None)
    p, err = remote.match_script("mining", paths)
    assert p is None and "more than one" in err
    assert remote.match_script("cooking", paths)[0] is None


def test_reply_is_tagged_and_can_carry_a_picture():
    sent = []
    remote.reply("my-topic", "Clicker", "Idle", request=lambda *a, **k: sent.append((a, k)))
    remote.reply("my-topic", "Clicker", "Screen", image=b"png", request=lambda *a, **k: sent.append((a, k)))
    (url, body, headers), _ = sent[0]
    assert url == "https://ntfy.sh/my-topic" and headers["Tags"] == remote.REPLY_TAG and body == b"Idle"
    (_u, body, headers), k = sent[1]
    assert k["method"] == "PUT" and body == b"png" and headers["Filename"] == "screen.png"


def test_listener_passes_new_messages_and_skips_its_own_replies():
    lines = [{"id": "a1", "event": "open"},
             {"id": "a2", "event": "message", "message": "status"},
             {"id": "a3", "event": "message", "message": "Idle", "tags": [remote.REPLY_TAG]},
             {"id": "a4", "event": "keepalive"},
             {"id": "a5", "event": "message", "message": "stop"}]
    seen_paths = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen_paths.append(self.path)
            self.send_response(200)
            self.end_headers()
            for ln in lines:
                self.wfile.write((json.dumps(ln) + "\n").encode())
                self.wfile.flush()
            time.sleep(0.3)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    got = []
    lst = remote.Listener(f"http://127.0.0.1:{srv.server_address[1]}/topic", got.append).start()
    end = time.monotonic() + 5
    while len(got) < 2 and time.monotonic() < end:
        time.sleep(0.02)
    lst.stop()
    srv.shutdown()
    assert got[:2] == ["status", "stop"]
    assert seen_paths[0].startswith("/topic/json?since=")
    assert lst.since in ("a5",) or len(seen_paths) > 1
