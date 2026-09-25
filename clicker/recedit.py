"""Editing recordings: trim, delete a stretch, keep only a stretch, shorten long pauses.

Recordings are lists of events with a time "t" in seconds from the start (see recorder.py). Every edit
returns a new list with times re-based so playback stays continuous, and keeps presses and releases
paired so an edit never leaves a key or mouse button held down.
"""

PRESS = {"mouse_down": "mouse_up", "key_down": "key_up"}
RELEASE = {v: k for k, v in PRESS.items()}


def _key(ev):
    if ev["type"] in ("mouse_down", "mouse_up"):
        return ("mouse", ev.get("button"))
    return ("key", ev.get("key") or ev.get("vk") or ev.get("char"))


def balance(events):
    """Drop releases whose press was cut, and presses whose release was cut."""
    held = {}
    keep = [True] * len(events)
    for i, e in enumerate(events):
        t = e["type"]
        if t in PRESS:
            k = _key(e)
            if k in held:           # pressed again without a release in between: the first press loses its pair
                keep[held[k]] = False
            held[k] = i
        elif t in RELEASE:
            k = _key(e)
            if k in held:
                del held[k]
            else:
                keep[i] = False
    for i in held.values():
        keep[i] = False
    return [e for e, k in zip(events, keep) if k]


def _round(events):
    for e in events:
        e["t"] = round(max(0.0, e["t"]), 4)
    return events


def length(events):
    return events[-1]["t"] if events else 0.0


def trim(events, start, end):
    """Keep only events between start and end (seconds); the first kept moment becomes 0."""
    start, end = max(0.0, start), max(start, end)
    out = [dict(e, t=e["t"] - start) for e in events if start <= e["t"] <= end]
    return _round(balance(out))


keep_only = trim


def delete(events, start, end):
    """Remove the stretch between start and end and close the gap."""
    start, end = sorted((max(0.0, start), max(0.0, end)))
    gap = end - start
    out = []
    for e in events:
        if e["t"] < start:
            out.append(dict(e))
        elif e["t"] > end:
            out.append(dict(e, t=e["t"] - gap))
    return _round(balance(out))


def pauses(events, longer_than):
    """[(start, end)] of quiet stretches longer than `longer_than` seconds (mouse moves count as activity)."""
    out = []
    prev = 0.0
    for e in events:
        if e["type"] == "snap":  # screen snapshots aren't activity
            continue
        if e["t"] - prev > longer_than:
            out.append((prev, e["t"]))
        prev = e["t"]
    return out


def shorten_pauses(events, longer_than, to):
    """Make every pause longer than `longer_than` last `to` seconds instead."""
    to = max(0.0, min(to, longer_than))
    cuts = [(a, b - a - to) for a, b in pauses(events, longer_than)]
    out = []
    for e in events:
        shift = 0.0
        for a, cut in cuts:
            if e["t"] <= a:
                break
            shift += min(cut, e["t"] - a)  # a snapshot inside a pause moves with it
        out.append(dict(e, t=e["t"] - shift))
    return _round(out)


def select(events, start, end):
    """(first index, last index + 1) of events inside [start, end]."""
    idx = [i for i, e in enumerate(events) if start <= e["t"] <= end]
    return (idx[0], idx[-1] + 1) if idx else (0, 0)


def describe(e):
    """A short line for the event list: (kind, detail)."""
    from .recorder import key_text
    t = e["type"]
    if t == "move":
        return "Move", f"{e['x']}, {e['y']}"
    if t == "mouse_down":
        return f"{e.get('button', 'left').title()} press", f"{e['x']}, {e['y']}" + (" · picture" if e.get("img") else "")
    if t == "mouse_up":
        return f"{e.get('button', 'left').title()} release", f"{e['x']}, {e['y']}"
    if t == "scroll":
        return "Scroll", f"{e['x']}, {e['y']}  ({e.get('dx', 0)}, {e.get('dy', 0)})"
    if t == "key_down":
        return "Key press", key_text(e)
    if t == "key_up":
        return "Key release", key_text(e)
    return t, ""
