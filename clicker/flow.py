"""Where a script's steps lead: loops, jumps and calls, and steps that can never run.

Used by the loop and jump overview beside the step list. Pure functions over the step list.
"""

from . import model

KINDS = ("while", "if", "goto", "loop", "call", "timeout")
LABEL = {"while": "While", "if": "If", "goto": "Go to", "loop": "Loop back", "call": "Call", "timeout": "On timeout"}
UNCONDITIONAL_END = {"Go to Step", "Return", "Stop Script"}


def _target(steps, value, labels):
    try:
        return model.resolve_target(steps, value, labels)
    except ValueError:
        return None


def edges(steps):
    """[{src, dst, kind, text}] for every loop and jump (0-based indexes).

    While blocks are one edge from the While to its End While (kind 'while').
    """
    labels = model.label_map(steps)
    pairs, _err = model.match_blocks(steps)
    out = []
    for i, st in enumerate(steps):
        if st.get("disabled"):
            continue
        a = st.get("action", "")
        if a in model.BLOCK_STARTS and i in pairs and pairs[i] > i:
            out.append({"src": i, "dst": pairs[i], "kind": "while", "text": _short_while(st)})
        if a.startswith("If "):
            t = _target(steps, st.get("goto"), labels)
            if t is not None:
                out.append({"src": i, "dst": t, "kind": "if", "text": f"{_short_if(st)}: yes → {_name(steps, t)}"})
            e = _target(steps, st.get("else_goto"), labels)
            if e is not None:
                out.append({"src": i, "dst": e, "kind": "if", "text": f"{_short_if(st)}: no → {_name(steps, e)}"})
        elif a in ("Go to Step", "Loop Back", "Call Subroutine"):
            t = _target(steps, st.get("goto"), labels)
            if t is not None:
                kind = {"Go to Step": "goto", "Loop Back": "loop", "Call Subroutine": "call"}[a]
                extra = f", {st.get('times', 1)} times" if a == "Loop Back" else ""
                out.append({"src": i, "dst": t, "kind": kind, "text": f"{LABEL[kind]} {_name(steps, t)}{extra}"})
        w = st.get("wait") or {}
        if w.get("mode", "none") != "none" and w.get("on_timeout") == "goto":
            t = _target(steps, w.get("goto"), labels)
            if t is not None:
                out.append({"src": i, "dst": t, "kind": "timeout", "text": f"Timed out → {_name(steps, t)}"})
    return out


def _name(steps, i):
    lab = steps[i].get("label")
    return lab if lab else f"step {i + 1}"


def _short_if(st):
    a = st.get("action", "")
    if a in ("If Image Found", "If Image Not Found"):
        return f"{model.image_stem(st.get('image')) or '?'} {'found' if a == 'If Image Found' else 'missing'}"
    if a == "If Pixel Color":
        return f"pixel {st.get('color')}"
    if a == "If Variable":
        return f"{{{st.get('var')}}} {st.get('op', '=')} {st.get('value', '')}"
    return a


def _short_while(st):
    a = st.get("action", "")
    if a in ("While Image Found", "While Image Not Found"):
        what = model.image_stem(st.get("image")) or "?"
        return f"While {what} is {'' if a == 'While Image Found' else 'not '}visible"
    if a == "While Pixel Color":
        return f"While pixel is {st.get('color')}"
    if a == "While Variable":
        return f"While {{{st.get('var')}}} {st.get('op', '=')} {st.get('value', '')}"
    if a == "For Each Row":
        name = str(st.get("file", "")).replace("\\", "/").split("/")[-1]
        return f"For each row of {name or '?'}"
    return a


def lanes(es):
    """Give each edge a lane (0 = nearest the list) so arrows spanning the same rows don't overlap."""
    order = sorted(range(len(es)), key=lambda k: abs(es[k]["dst"] - es[k]["src"]))
    used = []  # per lane: list of (lo, hi)
    out = [0] * len(es)
    for k in order:
        lo, hi = sorted((es[k]["src"], es[k]["dst"]))
        lane = 0
        while lane < len(used) and any(not (hi < a or lo > b) for a, b in used[lane]):
            lane += 1
        if lane == len(used):
            used.append([])
        used[lane].append((lo, hi))
        out[k] = lane
    return out


def unreachable(script):
    """0-based indexes of steps no path from step 1 (or the error handler) can reach."""
    steps = script.get("steps") or []
    n = len(steps)
    if not n:
        return []
    labels = model.label_map(steps)
    pairs, _err = model.match_blocks(steps)
    starts = [0]
    h = _target(steps, script.get("error_handler"), labels)
    if h is not None:
        starts.append(h)
    seen = set()
    todo = list(starts)
    while todo:
        i = todo.pop()
        if i in seen or not 0 <= i < n:
            continue
        seen.add(i)
        st = steps[i]
        a = st.get("action", "")
        nxt = []
        if st.get("disabled"):
            nxt.append(i + 1)
        elif a in model.BLOCK_STARTS:
            nxt.append(i + 1)
            if i in pairs:
                nxt.append(pairs[i] + 1)
        elif a in model.BLOCK_ENDS:
            if i in pairs:
                nxt.append(pairs[i])
        elif a.startswith("If "):
            for key in ("goto", "else_goto"):
                t = _target(steps, st.get(key), labels)
                nxt.append(i + 1 if t is None else t)
        elif a == "Go to Step":
            t = _target(steps, st.get("goto"), labels)
            nxt.append(i + 1 if t is None else t)
        elif a in ("Loop Back", "Call Subroutine"):
            t = _target(steps, st.get("goto"), labels)
            if t is not None:
                nxt.append(t)
            nxt.append(i + 1)
        elif a in ("Return", "Stop Script"):
            pass
        else:
            nxt.append(i + 1)
        w = st.get("wait") or {}
        if w.get("mode", "none") != "none" and w.get("on_timeout") == "goto":
            t = _target(steps, w.get("goto"), labels)
            if t is not None:
                nxt.append(t)
        todo.extend(nxt)
    return [i for i in range(n) if i not in seen]


def why_unreachable(steps, i):
    """A short reason for the first unreachable step in a run, from the step above it."""
    if i == 0:
        return ""
    prev = steps[i - 1].get("action", "")
    if prev in UNCONDITIONAL_END:
        return f"step {i} always {'jumps away' if prev == 'Go to Step' else 'ends there'}"
    return "nothing jumps to it"
