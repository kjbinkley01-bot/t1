"""Backup: everything Clicker keeps (settings, hotkeys, trigger rules, snippets, history and the scripts your
hotkeys, schedule and recent list point to) in one .clkbackup file, to move to another PC or keep safe."""

import datetime
import json
import os
import zipfile

FORMAT = "clicker-backup"
DATA_FILES = ["settings.json", "triggers.clktrig", "history.jsonl"]


def _script_paths(settings):
    """Script files the settings point to: hotkeys, schedule, remote control allow list and recent list."""
    out = []
    for e in settings.get("script_hotkeys") or []:
        out.append(e.get("path"))
    for e in settings.get("schedule") or []:
        out.append(e.get("path"))
    for p in (settings.get("remote") or {}).get("allowed") or []:
        out.append(p)
    out += settings.get("recent") or []
    seen, keep = set(), []
    for p in out:
        if p and os.path.isfile(p) and os.path.abspath(p) not in seen:
            seen.add(os.path.abspath(p))
            keep.append(os.path.abspath(p))
    return keep


def export(path, data_dir, settings):
    """Write the backup. Returns a short summary."""
    scripts = _script_paths(settings)
    manifest = {"format": FORMAT, "version": 1, "made": datetime.datetime.now().isoformat(timespec="seconds"),
                "scripts": {}}
    n_snip = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data/settings.json", json.dumps(settings, indent=2))
        for name in DATA_FILES[1:]:
            p = os.path.join(data_dir, name)
            if os.path.isfile(p):
                z.write(p, f"data/{name}")
        snip = os.path.join(data_dir, "snippets")
        if os.path.isdir(snip):
            for f in sorted(os.listdir(snip)):
                if f.endswith(".json"):
                    z.write(os.path.join(snip, f), f"data/snippets/{f}")
                    n_snip += 1
        used = set()
        for p in scripts:
            base = os.path.basename(p)
            stem, ext = os.path.splitext(base)
            k = 2
            while base.lower() in used:
                base = f"{stem}_{k}{ext}"
                k += 1
            used.add(base.lower())
            z.write(p, f"scripts/{base}")
            manifest["scripts"][base] = p
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return f"{len(scripts)} script{'s' if len(scripts) != 1 else ''}, {n_snip} snippet{'s' if n_snip != 1 else ''}"


def read_manifest(path):
    with zipfile.ZipFile(path) as z:
        m = json.loads(z.read("manifest.json"))
    if m.get("format") != FORMAT:
        raise ValueError("Not a Clicker backup")
    return m


def restore(path, data_dir, scripts_dir):
    """Unpack a backup: data files into data_dir, scripts into scripts_dir, and point the settings at the
    restored scripts. Returns (settings, summary)."""
    m = read_manifest(path)
    moved = {}
    with zipfile.ZipFile(path) as z:
        os.makedirs(scripts_dir, exist_ok=True)
        for base, original in (m.get("scripts") or {}).items():
            safe = os.path.basename(base)
            dest = os.path.join(scripts_dir, safe)
            with open(dest, "wb") as f:
                f.write(z.read(f"scripts/{base}"))
            moved[os.path.abspath(original)] = dest
        names = z.namelist()
        for name in DATA_FILES[1:]:
            if f"data/{name}" in names:
                with open(os.path.join(data_dir, name), "wb") as f:
                    f.write(z.read(f"data/{name}"))
        snip = os.path.join(data_dir, "snippets")
        os.makedirs(snip, exist_ok=True)
        n_snip = 0
        for n in names:
            if n.startswith("data/snippets/") and n.endswith(".json"):
                with open(os.path.join(snip, os.path.basename(n)), "wb") as f:
                    f.write(z.read(n))
                n_snip += 1
        settings = json.loads(z.read("data/settings.json"))

    def fix(p):
        return moved.get(os.path.abspath(p), p) if p else p
    for e in settings.get("script_hotkeys") or []:
        e["path"] = fix(e.get("path"))
    for e in settings.get("schedule") or []:
        e["path"] = fix(e.get("path"))
    remote = settings.get("remote") or {}
    if remote.get("allowed"):
        remote["allowed"] = [fix(p) for p in remote["allowed"]]
    settings["recent"] = [fix(p) for p in settings.get("recent") or []]
    return settings, f"{len(moved)} script{'s' if len(moved) != 1 else ''}, {n_snip} snippet{'s' if n_snip != 1 else ''}"
