"""Version history: before a save replaces a script, recording or chain, the old file is kept.

Copies live in the data folder (versions/<one folder per file>/), the newest MAX_KEEP of each. A save
that changed nothing doesn't add a copy.
"""

import datetime
import hashlib
import json
import os
import shutil

from . import storage

MAX_KEEP = 10


def _folder(path, root=None):
    key = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(root or storage.data_dir(), "versions", key)


def _digest(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def keep(path, root=None):
    """Copy the file that is about to be replaced. Returns the copy's path, or None (nothing to keep)."""
    if not os.path.isfile(path):
        return None
    folder = _folder(path, root)
    os.makedirs(folder, exist_ok=True)
    existing = list_versions(path, root)
    digest = _digest(path)
    if existing and existing[0]["digest"] == digest:
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = os.path.join(folder, stamp + os.path.splitext(path)[1])
    shutil.copy2(path, dest)
    index = os.path.join(folder, "index.json")
    try:
        with open(index, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {"path": os.path.abspath(path), "digests": {}}
    data["digests"][os.path.basename(dest)] = digest
    for old in existing[MAX_KEEP - 1:]:
        try:
            os.remove(old["file"])
        except OSError:
            pass
        data["digests"].pop(os.path.basename(old["file"]), None)
    with open(index, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return dest


def list_versions(path, root=None):
    """Earlier copies of a file, newest first: [{"file", "when" (datetime), "size", "digest"}]."""
    folder = _folder(path, root)
    try:
        with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
            digests = json.load(f).get("digests", {})
    except (OSError, ValueError):
        digests = {}
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for n in names:
        if n == "index.json":
            continue
        try:
            when = datetime.datetime.strptime(os.path.splitext(n)[0], "%Y%m%d-%H%M%S-%f")
        except ValueError:
            continue
        full = os.path.join(folder, n)
        out.append({"file": full, "when": when, "size": os.path.getsize(full), "digest": digests.get(n)})
    out.sort(key=lambda v: v["when"], reverse=True)
    return out


def when_text(when, now=None):
    now = now or datetime.datetime.now()
    if when.date() == now.date():
        return "Today " + when.strftime("%H:%M")
    if (now.date() - when.date()).days == 1:
        return "Yesterday " + when.strftime("%H:%M")
    return f"{when:%b} {when.day}, {when:%H:%M}"
