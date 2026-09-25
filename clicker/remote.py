"""Phone remote control through ntfy: send 'start Mining loop', 'stop', 'status' or 'screenshot' from the
ntfy app and Clicker answers on the same topic.

Safety: Clicker only listens on your own topic (make it long and random), can require a PIN in front of
every command, and only starts scripts you put on its allow list.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

from .alerts import _header_text, _request, ntfy_url

REPLY_TAG = "clicker-reply"
COMMANDS = {
    "help": "list the commands",
    "status": "what's running",
    "list": "scripts you can start",
    "start NAME": "start an allowed script (part of its name is enough)",
    "stop": "stop what's running",
    "pause": "pause the running script",
    "resume": "resume it",
    "screenshot": "a picture of the screen",
}


def help_text():
    return "Commands:\n" + "\n".join(f"{k} - {v}" for k, v in COMMANDS.items())


def parse(text, pin=""):
    """(command, argument) from a message, or (None, reason). The PIN, if set, must come first."""
    words = str(text or "").strip().split()
    if pin:
        if not words or words[0] != pin:
            return None, "wrong or missing PIN"
        words = words[1:]
    if not words:
        return None, "empty message"
    cmd = words[0].lower()
    arg = " ".join(words[1:]).strip()
    if cmd in ("run", "go"):
        cmd = "start"
    if cmd in ("shot", "screen", "ss"):
        cmd = "screenshot"
    if cmd == "?":
        cmd = "help"
    if cmd not in {c.split()[0] for c in COMMANDS}:
        return None, f"unknown command '{cmd}'. Send help for the list."
    if cmd == "start" and not arg:
        return None, "start what? Send list for the names."
    return cmd, arg


def match_script(name, paths):
    """The allowed script whose file name best matches name: exact, then starts with, then contains."""
    want = name.strip().lower()
    names = [(os.path.splitext(os.path.basename(p))[0].lower().replace("_", " "), p) for p in paths]
    for test in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n):
        hits = [p for n, p in names if test(n) or test(n.replace(" ", "_"))]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, "more than one script matches: " + ", ".join(
                os.path.splitext(os.path.basename(h))[0] for h in hits)
    return None, f"no allowed script called '{name}'. Send list for the names."


def reply(topic, title, text, image=None, request=_request):
    """Post an answer to the topic (tagged so the listener skips it)."""
    headers = {"Title": _header_text(title), "Tags": REPLY_TAG}
    if image is not None:
        headers.update({"Filename": "screen.png", "Message": _header_text(text)})
        return request(ntfy_url(topic), image, headers, method="PUT")
    return request(ntfy_url(topic), text.encode("utf-8"), headers)


class Listener:
    """Reads new messages from the topic on a background thread and hands them to on_message(text)."""

    def __init__(self, topic, on_message, on_state=None):
        self.topic = topic
        self.on_message = on_message
        self.on_state = on_state or (lambda s: None)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.since = str(int(time.time()))

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _url(self):
        return ntfy_url(self.topic).rstrip("/") + "/json?" + urllib.parse.urlencode({"since": self.since})

    def _run(self):
        delay = 3
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(self._url(), headers={"User-Agent": "Clicker-remote"})
                with urllib.request.urlopen(req, timeout=70) as r:  # noqa: S310 (the user's own topic)
                    self.on_state("listening")
                    delay = 3
                    for raw in r:
                        if self._stop.is_set():
                            return
                        self._handle(raw)
            except Exception as e:  # network trouble: try again, backing off
                if self._stop.is_set():
                    return
                self.on_state(f"reconnecting ({e.__class__.__name__})")
                self._stop.wait(delay)
                delay = min(60, delay * 2)

    def _handle(self, raw):
        try:
            ev = json.loads(raw.decode("utf-8"))
        except ValueError:
            return
        if ev.get("id"):
            self.since = ev["id"]
        if ev.get("event") != "message" or REPLY_TAG in (ev.get("tags") or []):
            return
        text = ev.get("message") or ""
        if text:
            self.on_message(text)
