"""Run history: one line per script run, and the numbers the History tab shows.

Run log folders are pruned to the last few dozen runs, so history keeps its own small file
(history.jsonl in the data folder) with just the facts needed for stats.
"""

import datetime
import json
import os
import threading
import time
from collections import Counter

KEEP = 5000          # entries kept; older ones are dropped when the file is rewritten
_lock = threading.Lock()


def default_path():
    from . import storage
    return os.path.join(storage.data_dir(), "history.jsonl")


def step_title(step, index):
    """'14 · Click Image "bank_booth"' for a step (index is 0-based)."""
    from . import model
    name = step.get("action", "?")
    img = model.image_stem(step.get("image"))
    if img:
        imgs = [model.image_stem(i) for i in step.get("images") or [] if i]
        name += f' "{img}"' + (f" +{len(imgs)}" if imgs else "")
    elif step.get("label"):
        name += f" ({step['label']})"
    return f"{index + 1} · {name}"


def record(entry, path=None):
    """Append one run. Never raises: history must not break a run."""
    path = path or default_path()
    try:
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            if os.path.getsize(path) > 3_000_000:
                _trim(path)
    except Exception:
        pass


def _trim(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()[-KEEP:]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, path)


def load(path=None):
    path = path or default_path()
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and "ts" in e and "result" in e:
                    out.append(e)
    except OSError:
        pass
    out.sort(key=lambda e: e["ts"])
    return out


def clear(path=None):
    try:
        os.remove(path or default_path())
    except OSError:
        pass


def select(entries, days=None, script=None, now=None, dry_runs=False):
    """Entries in the last `days` days (None = all) for one script name (None = all), newest last."""
    now = now or time.time()
    since = now - days * 86400 if days else None
    return [e for e in entries
            if (since is None or e["ts"] >= since)
            and (script is None or e.get("script") == script)
            and (dry_runs or not e.get("dry_run"))]


def scripts(entries):
    """Script names, most recently run first."""
    seen = []
    for e in reversed(entries):
        s = e.get("script")
        if s and s not in seen:
            seen.append(s)
    return seen


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} m {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} m"


def stats(entries, days=14, now=None):
    """Summary numbers for the History tab. `entries` should already be filtered."""
    now = now or time.time()
    finished = [e for e in entries if e["result"] == "finished"]
    failed = [e for e in entries if e["result"] == "failed"]
    stopped = [e for e in entries if e["result"] == "stopped"]
    judged = len(finished) + len(failed)
    times = [e["seconds"] for e in finished if e.get("seconds") is not None]
    where = Counter()
    for e in failed:
        where[e.get("step_desc") or _reason_group(e.get("reason", ""))] += 1
    today = datetime.date.fromtimestamp(now)
    per_day = []
    for back in range(days - 1, -1, -1):
        d = today - datetime.timedelta(days=back)
        day = [e for e in entries if datetime.date.fromtimestamp(e["ts"]) == d]
        per_day.append((d, sum(1 for e in day if e["result"] == "finished"),
                        sum(1 for e in day if e["result"] == "failed")))
    top = where.most_common(1)[0] if where else None
    return {
        "runs": len(entries),
        "finished": len(finished),
        "failed": len(failed),
        "stopped": len(stopped),
        "success_rate": (len(finished) / judged) if judged else None,
        "avg_seconds": (sum(times) / len(times)) if times else None,
        "fastest_seconds": min(times) if times else None,
        "top_fail": top,             # (description, count) or None
        "where_failed": where.most_common(6),
        "per_day": per_day,          # [(date, finished, failed)] oldest first
    }


def _reason_group(reason):
    r = reason.lower()
    if "not open" in r or "window" in r:
        return "Window not found"
    if r.startswith("error"):
        return "Unexpected error"
    return reason[:40] or "Unknown"
