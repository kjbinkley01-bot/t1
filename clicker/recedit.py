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


# ---------------------------------------------------------------- auto-trim suggestions

ACTIVE = {"mouse_down", "mouse_up", "scroll", "key_down", "key_up"}  # what matters (not moves or snapshots)
GAP_LONGER = 2.0     # a quiet stretch longer than this is worth tightening
GAP_TO = 0.6         # ... to this long
APPROACH = 0.3       # the mouse travel kept just before the next click


def _active_times(events):
    return [e["t"] for e in events if e["type"] in ACTIVE]


def dead_start(events):
    ts = _active_times(events)
    return max(0.0, ts[0] - APPROACH) if ts and ts[0] > 0.8 else 0.0


def dead_end(events):
    ts = _active_times(events)
    if not ts:
        return 0.0
    extra = length(events) - ts[-1]
    return extra - 0.2 if extra > 0.5 else 0.0


def trim_dead_ends(events, start=True, end=True):
    """Cut the waiting before the first action and/or after the last one."""
    ts = _active_times(events)
    if not ts:
        return list(events)
    a = dead_start(events) if start else 0.0
    b = ts[-1] + 0.2 if (end and dead_end(events)) else length(events)
    return trim(events, a, b)


def quiet_gaps(events, longer_than=GAP_LONGER):
    """[(a, b)] stretches between actions longer than longer_than (mouse wandering counts as quiet)."""
    ts = _active_times(events)
    return [(a, b) for a, b in zip(ts, ts[1:]) if b - a > longer_than]


def tighten_gaps(events, longer_than=GAP_LONGER, to=GAP_TO, approach=APPROACH):
    """Shrink each quiet stretch to `to` seconds, keeping only the last bit of mouse travel before the
    next action (snapshots inside are squeezed along with it)."""
    gaps = quiet_gaps(events, longer_than)
    if not gaps:
        return list(events)
    out = []
    shift_before = 0.0
    k = 0
    for e in events:
        while k < len(gaps) and e["t"] > gaps[k][1]:
            a, b = gaps[k]
            shift_before += (b - a) - to
            k += 1
        t = e["t"]
        if k < len(gaps) and gaps[k][0] < t <= gaps[k][1]:
            a, b = gaps[k]
            if t > b - approach:          # the approach to the next action: keep it, at the end of the gap
                new_t = a + to - (b - t)
            elif e["type"] == "move":     # wandering: drop
                continue
            else:                          # a snapshot: squeeze it into the kept part
                new_t = a + (t - a) * (to - approach) / max(1e-6, (b - approach - a))
            out.append(dict(e, t=new_t - shift_before))
        else:
            out.append(dict(e, t=t - shift_before))
    return _round(out)


def typo_pairs(events):
    """Indexes to drop for characters that were typed and then backspaced right away."""
    from .recorder import key_text
    drop = set()
    typed = []  # indexes of char key_downs that are still 'on the line'
    for i, e in enumerate(events):
        if e["type"] != "key_down":
            continue
        name = key_text(e)
        if name == "backspace":
            if typed:
                j = typed.pop()
                drop.update({j, i})
        elif len(name) == 1 or name == "space":
            typed.append(i)
        elif name not in ("shift", "shift_l", "shift_r", "caps_lock"):
            typed = []  # enter, tab, clicks... start a new line of typing
        if e["type"] == "key_down" and name == "backspace" and i not in drop:
            typed = []
    # each dropped press takes its release with it
    out = set(drop)
    for i in drop:
        k = _key(events[i])
        for j in range(i + 1, len(events)):
            if events[j]["type"] == "key_up" and _key(events[j]) == k:
                out.add(j)
                break
    return out


def fix_typos(events):
    drop = typo_pairs(events)
    return [dict(e) for i, e in enumerate(events) if i not in drop]


def thin_moves(events, min_px=10, max_gap=0.12):
    """Keep the mouse path's shape with far fewer points (always keeps the move right before an action)."""
    out = []
    last = None
    for i, e in enumerate(events):
        if e["type"] != "move":
            out.append(dict(e))
            continue
        nxt = events[i + 1] if i + 1 < len(events) else None
        before_action = nxt is not None and nxt["type"] in ACTIVE
        if (last is None or before_action or abs(e["x"] - last["x"]) + abs(e["y"] - last["y"]) >= min_px
                or e["t"] - last["t"] >= max_gap):
            out.append(dict(e))
            last = e
    return out


def suggest(events):
    """What auto-trim would change: [{"id", "title", "saves"}], biggest time saving first."""
    out = []
    ds, de = dead_start(events), dead_end(events)
    if ds > 0.05:
        out.append({"id": "start", "title": f"Cut {ds:.1f} s of waiting before the first action", "saves": ds})
    if de > 0.05:
        out.append({"id": "end", "title": f"Cut {de:.1f} s after the last action", "saves": de})
    gaps = quiet_gaps(events)
    if gaps:
        saved = sum((b - a) - GAP_TO for a, b in gaps)
        n = len(gaps)
        out.append({"id": "gaps", "saves": saved,
                    "title": f"Shorten {n} quiet stretch{'es' if n != 1 else ''} (nothing clicked or typed for "
                             f"over {GAP_LONGER:g} s) to {GAP_TO:g} s each"})
    typos = len(typo_pairs(events)) // 4
    if typos:
        out.append({"id": "typos", "saves": 0.0,
                    "title": f"Remove {typos} typing mistake{'s' if typos != 1 else ''} (typed, then backspaced)"})
    moves = sum(1 for e in events if e["type"] == "move")
    kept = sum(1 for e in thin_moves(events) if e["type"] == "move")
    if moves - kept >= 50:
        out.append({"id": "moves", "saves": 0.0,
                    "title": f"Simplify mouse paths: {moves:,} points to {kept:,} (same route, smaller file)"})
    out.sort(key=lambda s: -s["saves"])
    return out


def apply_suggestions(events, ids):
    """Apply the chosen suggestions in a safe order."""
    ev = list(events)
    if "typos" in ids:
        ev = fix_typos(ev)
    if "moves" in ids:
        ev = thin_moves(ev)
    if "gaps" in ids:
        ev = tighten_gaps(ev)
    if "start" in ids or "end" in ids:
        ev = trim_dead_ends(ev, "start" in ids, "end" in ids)
    return _round(balance(ev))
