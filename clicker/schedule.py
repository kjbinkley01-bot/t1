"""Scheduled runs: at a time of day on chosen weekdays, every N minutes, once, or when a window opens.

Pure timing logic; the window checks it every few seconds and starts the script. Runs only happen while
Clicker is open (or in the tray).
"""

import datetime
import uuid

KINDS = [("daily", "Every day at a time"), ("interval", "Every N minutes"), ("once", "Once, at a date and time"),
         ("window", "When a window opens")]
KIND_LABEL = dict(KINDS)
KIND_ID = {v: k for k, v in KINDS}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GRACE_MIN = 10   # a daily or one-time run that was missed by up to this much still happens


def new_entry(path):
    return {"id": uuid.uuid4().hex[:10], "path": path, "kind": "daily", "time": "09:00", "days": list(range(7)),
            "every_min": 30, "once_at": "", "window_title": "", "window_process": "", "enabled": True,
            "last_run": None}


def parse_hhmm(text):
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    raise ValueError("Times look like 09:00 or 17:30")


def parse_when(text):
    try:
        return datetime.datetime.strptime(str(text).strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Dates look like 2026-09-26 09:00")


def check(e):
    """An error message for an entry that can't run, or None."""
    k = e.get("kind")
    try:
        if k == "daily":
            parse_hhmm(e.get("time"))
            if not e.get("days"):
                return "Pick at least one day."
        elif k == "interval":
            if int(e.get("every_min") or 0) < 1:
                return "Every must be at least 1 minute."
        elif k == "once":
            parse_when(e.get("once_at"))
        elif k == "window":
            if not (str(e.get("window_title") or "").strip() or str(e.get("window_process") or "").strip()):
                return "Enter part of the window title or the program."
        else:
            return "Unknown schedule type."
    except ValueError as err:
        return str(err)
    return None


def _last(e):
    v = e.get("last_run")
    return datetime.datetime.fromtimestamp(v) if v else None


def next_run(e, now=None):
    """When it will run next (datetime), or None (disabled, done, or it waits for a window)."""
    now = now or datetime.datetime.now()
    if not e.get("enabled") or check(e):
        return None
    k = e["kind"]
    last = _last(e)
    if k == "interval":
        every = datetime.timedelta(minutes=int(e["every_min"]))
        return (last + every) if last else now
    if k == "once":
        at = parse_when(e["once_at"])
        return None if last and last >= at else at
    if k == "daily":
        h, m = parse_hhmm(e["time"])
        days = set(e.get("days") or [])
        for add in range(0, 8):
            d = (now + datetime.timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
            if d.weekday() not in days:
                continue
            if last and last >= d:
                continue
            if d + datetime.timedelta(minutes=GRACE_MIN) < now:
                continue
            return d
    return None


def due(e, now=None):
    """True when a time-based entry should start now."""
    now = now or datetime.datetime.now()
    if e.get("kind") == "window":
        return False
    at = next_run(e, now)
    return at is not None and at <= now


def describe(e):
    k = e.get("kind")
    if k == "daily":
        days = sorted(e.get("days") or [])
        if days == list(range(7)):
            when = "every day"
        elif days == list(range(5)):
            when = "weekdays"
        elif days == [5, 6]:
            when = "weekends"
        else:
            when = ", ".join(DAYS[d] for d in days)
        return f"{when} at {e.get('time')}"
    if k == "interval":
        n = int(e.get("every_min") or 0)
        return f"every {n} minute{'s' if n != 1 else ''}"
    if k == "once":
        return f"once at {e.get('once_at')}"
    if k == "window":
        who = " · ".join(v for v in (e.get("window_title"), e.get("window_process")) if v)
        return f"when {who} opens"
    return "?"


class WindowWatch:
    """Fires once each time a watched window appears (not while it stays open)."""

    def __init__(self):
        self.open = {}

    def appeared(self, e, is_open):
        was = self.open.get(e["id"], True)  # already-open windows at start don't count as appearing
        self.open[e["id"]] = is_open
        return is_open and not was
