"""Snippets: groups of steps saved once and inserted into any script (with their images)."""

import json
import os
import re

from . import editing


def folder():
    from . import storage
    path = os.path.join(storage.data_dir(), "snippets")
    os.makedirs(path, exist_ok=True)
    return path


def _file(name):
    safe = re.sub(r"[^A-Za-z0-9 _\-]+", "_", str(name)).strip() or "snippet"
    return os.path.join(folder(), safe + ".json")


def names():
    try:
        return sorted((f[:-5] for f in os.listdir(folder()) if f.endswith(".json")), key=str.lower)
    except OSError:
        return []


def save(name, script, assets, indexes):
    """Save the chosen steps (and the images they use) under name. Returns the file path."""
    path = _file(name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(editing.copy_payload(script, assets, indexes))
    return path


def load(name):
    """The snippet as paste text (what editing.paste takes)."""
    with open(_file(name), "r", encoding="utf-8") as f:
        return f.read()


def count(name):
    try:
        return len(json.loads(load(name)).get("steps") or [])
    except (OSError, ValueError):
        return 0


def insert(name, script, assets, pos):
    """Insert a snippet at pos. Returns the new step indexes."""
    return editing.paste(script, assets, load(name), pos)


def delete(name):
    try:
        os.remove(_file(name))
    except OSError:
        pass
