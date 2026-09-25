"""Check my scripts: look over every file in the Library (and the files hotkeys, the schedule and the phone
remote point to) for things that would stop them running: missing files and pictures, broken jumps, steps
with mistakes, Run Script File and chain cards pointing at files that are gone.
"""

import os

from . import chains, library, storage


def _fixed_path(v):
    """A path typed in a step, unless it uses {variables} (those can only be checked when running)."""
    v = str(v or "").strip()
    return v if v and "{" not in v else None


def check_script(path):
    out = []
    try:
        script, assets = storage.load_script(path)
    except Exception as e:
        return [("error", f"Can't be opened: {e}")]
    out += [(lvl, msg) for lvl, msg in storage.validate(script, assets) if lvl == "error"]
    for i, st in enumerate(script["steps"], 1):
        a = st.get("action")
        p = _fixed_path(st.get("file")) if a in ("Run Script File", "For Each Row") else None
        if p and not os.path.isfile(p):
            what = "script" if a == "Run Script File" else "data file"
            out.append(("error", f"Step {i} ({a}): the {what} {os.path.basename(p)} is missing "
                                 f"(it was in {os.path.dirname(p) or 'this folder'})"))
    return out


def check_recording(path):
    try:
        events, _o, _i, _s = storage.load_recording_full(path)
    except Exception as e:
        return [("error", f"Can't be opened: {e}")]
    return [] if events else [("warn", "The recording is empty")]


def check_chain(path):
    try:
        chain = chains.load(path)
    except Exception as e:
        return [("error", f"Can't be opened: {e}")]
    out = [("error", p) for p in chains.problems(chain)]
    for i, ln in enumerate(chain["links"], 1):
        if os.path.isfile(ln["path"]) and check_script(ln["path"]):
            out.append(("warn", f"Card {i}: {os.path.basename(ln['path'])} has problems of its own"))
    return out


CHECKS = {"script": check_script, "recording": check_recording, "chain": check_chain}


def check_file(path, kind=None):
    kind = kind or library.kind_of(path)
    if not os.path.isfile(path):
        return [("error", "The file is missing (moved, renamed or deleted)")]
    return CHECKS.get(kind, check_script)(path)


def settings_files(settings):
    """(where, path) for every file the settings point to."""
    out = [("Script hotkey", e.get("path")) for e in settings.get("script_hotkeys") or []]
    out += [("Schedule", e.get("path")) for e in settings.get("schedule") or []]
    out += [("Phone remote", p) for p in (settings.get("remote") or {}).get("allowed") or []]
    return [(w, p) for w, p in out if p]


def check_all(lib, settings=None, progress=None):
    """[{"path", "name", "kind", "where", "level", "message"}] for everything that needs attention, and
    the number of files looked at."""
    todo = {}
    for e in lib.entries.values():
        todo[os.path.abspath(e["path"])] = {"name": e.get("name") or os.path.basename(e["path"]),
                                            "kind": e.get("kind"), "where": "Library"}
    for where, p in settings_files(settings or {}):
        p = os.path.abspath(p)
        item = todo.setdefault(p, {"name": os.path.splitext(os.path.basename(p))[0], "kind": library.kind_of(p),
                                   "where": where})
        if item["where"] == "Library":
            item["where"] = f"Library, {where}"
    found = []
    for n, (path, item) in enumerate(sorted(todo.items(), key=lambda kv: kv[1]["name"].lower())):
        if progress:
            progress(n, len(todo))
        for level, msg in check_file(path, item["kind"]):
            found.append(dict(item, path=path, level=level, message=msg))
    found.sort(key=lambda f: (f["level"] != "error", f["name"].lower()))
    return found, len(todo)


def summary(found, checked):
    files = len({f["path"] for f in found})
    if not checked:
        return "There's nothing to check yet: open, save or add scripts to the Library first."
    if not found:
        return f"Checked {checked} file{'s' if checked != 1 else ''}: everything looks ready to run."
    return f"Checked {checked} file{'s' if checked != 1 else ''}: {files} need{'s' if files == 1 else ''} attention."
