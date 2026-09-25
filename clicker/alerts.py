"""Alerts: tell your phone or a Discord channel when a script finishes, fails or loses its window.

Destinations
* Discord (or any) webhook URL. Discord URLs get a rich message with the failure screenshot attached;
  any other https URL gets a small JSON body ({"title", "message", ...}) for your own tools.
* ntfy (https://ntfy.sh, free phone app): a topic name ("my-clicker-alerts") or a full ntfy URL for a
  self-hosted server. Anyone who knows the topic can read it, so pick something hard to guess.

Everything is sent straight from this PC on a background thread; a failed send never affects a run.
"""

import datetime
import io
import json
import os
import re
import threading
import time
import urllib.request
import uuid

DEFAULTS = {
    "on_finished": True, "on_failed": True, "on_window": True, "on_trigger": False,
    "discord": "", "ntfy": "",
    "screenshot": True, "log_lines": True,
    "quiet": False, "quiet_from": "23:00", "quiet_to": "07:00",
}
KIND_SETTING = {"finished": "on_finished", "failed": "on_failed", "window": "on_window", "trigger": "on_trigger"}
REPEAT_GAP_S = {"window": 600, "trigger": 60}  # the same alert of these kinds is sent at most this often
LOG_TAIL = 10
TIMEOUT_S = 12
_last = {}
_lock = threading.Lock()


def config(settings):
    c = dict(DEFAULTS)
    c.update((settings or {}).get("alerts") or {})
    return c


def configured(cfg):
    return bool(cfg.get("discord", "").strip() or cfg.get("ntfy", "").strip())


# ---------------------------------------------------------------- events

def run_event(job, ok, reason):
    """An alert event for a finished Runner (or Player). None when the run was stopped by the user."""
    stopped = not ok and str(reason).startswith("Stop") and getattr(job, "fail_step", None) is None
    if stopped:
        return None
    reason = str(reason)
    kind = "finished" if ok else ("window" if "not open" in reason or "Window" in reason else "failed")
    script = getattr(job, "script", None)
    name = (script or {}).get("name") if isinstance(script, dict) else None
    if not name:
        path = getattr(job, "path", None)
        name = os.path.splitext(os.path.basename(path))[0] if path else getattr(job, "label", "Recording")
    started = getattr(job, "started_at", None)
    ev = {"kind": kind, "script": name or "Script", "reason": reason,
          "seconds": (time.time() - started) if started else None,
          "passes": getattr(job, "run_number", None),
          "step": (job.fail_step[1] if getattr(job, "fail_step", None) else None),
          "window": None, "screenshot": None, "log": []}
    tgt = getattr(job, "target", None)
    if tgt:
        from . import target
        ev["window"] = target.describe(tgt)
    rl = getattr(job, "run_log", None)
    if rl is not None:
        if rl.screenshots:
            ev["screenshot"] = rl.screenshots[-1]
        ev["log"] = tail(rl.path)
    return ev


def trigger_event(rule_name, message):
    return {"kind": "trigger", "script": rule_name or "Trigger rule", "reason": message, "seconds": None,
            "passes": None, "step": None, "window": None, "screenshot": None, "log": []}


def test_event():
    return {"kind": "test", "script": "Test alert", "reason": "Alerts from Clicker are working.", "seconds": None,
            "passes": None, "step": None, "window": None, "screenshot": None, "log": []}


def tail(path, n=LOG_TAIL):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [ln.rstrip("\n") for ln in f.readlines()[-n:]]
    except OSError:
        return []


def _fmt_secs(s):
    from .history import fmt_duration
    return fmt_duration(s)


def title_of(ev):
    return {"finished": f"Finished: {ev['script']}", "failed": f"Script stopped: {ev['script']}",
            "window": f"Window lost: {ev['script']}", "trigger": f"Trigger fired: {ev['script']}",
            "test": "Clicker test alert"}.get(ev["kind"], ev["script"])


def body_of(ev, with_log=True):
    lines = []
    if ev.get("step"):
        lines.append(f"Step {ev['step']}")
    if ev["kind"] != "finished":
        lines.append(ev["reason"])
    bits = []
    if ev.get("seconds") is not None:
        bits.append(f"ran {_fmt_secs(ev['seconds'])}")
    if ev.get("passes"):
        bits.append(f"{ev['passes']} pass{'es' if ev['passes'] != 1 else ''}")
    if ev.get("window"):
        bits.append(ev["window"])
    if bits:
        lines.append(" · ".join(bits))
    if with_log and ev.get("log"):
        lines.append("")
        lines.extend(ev["log"])
    return "\n".join(lines) or ev["reason"]


# ---------------------------------------------------------------- deciding

def _minutes(hhmm):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(hhmm or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def in_quiet_hours(cfg, now=None):
    if not cfg.get("quiet"):
        return False
    a, b = _minutes(cfg.get("quiet_from")), _minutes(cfg.get("quiet_to"))
    if a is None or b is None or a == b:
        return False
    now = now or datetime.datetime.now()
    t = now.hour * 60 + now.minute
    return a <= t < b if a < b else (t >= a or t < b)


def should_send(cfg, ev, now=None):
    if ev is None or not configured(cfg):
        return False
    if ev["kind"] != "test":
        if not cfg.get(KIND_SETTING.get(ev["kind"], ""), False):
            return False
        if in_quiet_hours(cfg, now):
            return False
        gap = REPEAT_GAP_S.get(ev["kind"])
        if gap:
            key = (ev["kind"], ev["script"])
            t = time.monotonic()
            with _lock:
                if t - _last.get(key, -1e9) < gap:
                    return False
                _last[key] = t
    return True


# ---------------------------------------------------------------- sending

def _request(url, data=None, headers=None, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    req.add_header("User-Agent", "Clicker-alerts")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 (the user's own URL)
        return r.status


def is_discord(url):
    return bool(re.match(r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/", url.strip()))


def multipart(fields, files):
    """(body, content type) for form fields and (name, filename, bytes, type) files."""
    boundary = uuid.uuid4().hex
    buf = io.BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
                  f"Content-Type: application/json\r\n\r\n".encode())
        buf.write(value.encode("utf-8") + b"\r\n")
    for name, filename, data, ctype in files:
        buf.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                  f"Content-Type: {ctype}\r\n\r\n".encode())
        buf.write(data + b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


COLORS = {"finished": 0x4FA8FF, "failed": 0xFF5A64, "window": 0xFF9F0A, "trigger": 0xB07CFF, "test": 0x34C759}


def discord_payload(ev, cfg, shot_name=None):
    fields = []
    if ev.get("step"):
        fields.append({"name": "Step", "value": ev["step"][:1000], "inline": True})
    if ev["kind"] not in ("finished",):
        fields.append({"name": "Reason", "value": ev["reason"][:1000] or "-", "inline": True})
    if ev.get("seconds") is not None:
        ran = _fmt_secs(ev["seconds"]) + (f" · {ev['passes']} passes" if ev.get("passes") else "")
        fields.append({"name": "Ran for", "value": ran, "inline": True})
    if ev.get("window"):
        fields.append({"name": "Window", "value": ev["window"][:1000], "inline": True})
    embed = {"title": title_of(ev)[:250], "color": COLORS.get(ev["kind"], 0x888888), "fields": fields,
             "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if cfg.get("log_lines") and ev.get("log"):
        log = "\n".join(ev["log"])[-1800:].replace("```", "'''")
        embed["description"] = f"```\n{log}\n```"
    if shot_name:
        embed["image"] = {"url": f"attachment://{shot_name}"}
    return {"username": "Clicker", "embeds": [embed]}


def _read_shot(ev, cfg):
    if not cfg.get("screenshot") or not ev.get("screenshot"):
        return None
    try:
        with open(ev["screenshot"], "rb") as f:
            data = f.read()
        return data if len(data) < 8_000_000 else None
    except OSError:
        return None


def send_webhook(url, ev, cfg, request=_request):
    shot = _read_shot(ev, cfg)
    if is_discord(url):
        payload = discord_payload(ev, cfg, "screenshot.png" if shot else None)
        if shot:
            body, ctype = multipart({"payload_json": json.dumps(payload)},
                                    [("files[0]", "screenshot.png", shot, "image/png")])
            return request(url, body, {"Content-Type": ctype})
        return request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    payload = {"title": title_of(ev), "message": body_of(ev, cfg.get("log_lines")), "kind": ev["kind"],
               "script": ev["script"], "reason": ev["reason"], "step": ev.get("step"),
               "seconds": ev.get("seconds"), "window": ev.get("window")}
    return request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})


def ntfy_url(value):
    v = value.strip()
    if re.match(r"https?://", v):
        return v
    return "https://ntfy.sh/" + v.strip("/")


def _header_text(text):
    """HTTP headers must be Latin-1; keep what fits, swap the rest for close characters."""
    text = text.replace("·", "-").replace("—", "-").replace("“", '"').replace("”", '"').replace("\n", " ")
    return text.encode("latin-1", "replace").decode("latin-1")[:250]


def send_ntfy(value, ev, cfg, request=_request):
    url = ntfy_url(value)
    tags = {"finished": "white_check_mark", "failed": "rotating_light", "window": "warning",
            "trigger": "zap", "test": "tada"}.get(ev["kind"], "bell")
    headers = {"Title": _header_text(title_of(ev)), "Tags": tags,
               "Priority": "high" if ev["kind"] in ("failed", "window") else "default"}
    body_text = body_of(ev, cfg.get("log_lines"))
    shot = _read_shot(ev, cfg)
    if shot:
        headers.update({"Filename": "screenshot.png", "Message": _header_text(body_text.split("\n\n")[0])})
        return request(url, shot, headers, method="PUT")
    return request(url, body_text.encode("utf-8"), headers)


def send(cfg, ev, request=_request):
    """Send to every configured destination. Returns [(destination, error or None)]."""
    out = []
    for key, fn in (("discord", send_webhook), ("ntfy", send_ntfy)):
        dest = (cfg.get(key) or "").strip()
        if not dest:
            continue
        name = "Discord" if key == "discord" and is_discord(dest) else ("Webhook" if key == "discord" else "ntfy")
        try:
            fn(dest, ev, cfg, request)
            out.append((name, None))
        except Exception as e:
            out.append((name, str(e) or e.__class__.__name__))
    return out


def send_async(cfg, ev, done=None):
    """Send on a background thread; done(results) is called there when finished."""
    def work():
        res = send(cfg, ev)
        if done:
            try:
                done(res)
            except Exception:
                pass
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def notify(settings, ev, done=None):
    """Send ev if the settings ask for it. Returns True when a send was started."""
    cfg = config(settings)
    if not should_send(cfg, ev):
        return False
    send_async(cfg, ev, done)
    return True
