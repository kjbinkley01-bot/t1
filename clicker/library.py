"""The script library: scripts and recordings you've opened, saved or added, with favorites and search.

Each entry remembers what the library shows without opening the file again: a name, a line of detail
("12 steps", "0:42, 94 events"), when it was last used, and a small thumbnail (the script's first
picture, or a recording's first screen snapshot or click picture). Scripts without pictures keep their
first few actions and recordings keep their click times, so the window can draw a little diagram instead.
"""

import hashlib
import json
import os
import time

import cv2
import numpy as np

from . import model, storage, vision

SCRIPT_EXTS = (".clk", ".clkpkg", ".json")
RECORDING_EXTS = (".clkrec",)
CHAIN_EXTS = (".clkchain",)
MAX_RECENT = 60          # entries that aren't favorites are forgotten beyond this
THUMB_W, THUMB_H = 320, 180


def kind_of(path):
    p = path.lower()
    if p.endswith(RECORDING_EXTS):
        return "recording"
    if p.endswith(CHAIN_EXTS):
        return "chain"
    if p.endswith(SCRIPT_EXTS):
        return "script"
    return None


def _fmt_len(seconds):
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _thumb_image(img):
    """Fit a BGR picture into the thumbnail size (cover, centered) on a dark card."""
    if img is None or img.size == 0:
        return None
    ih, iw = img.shape[:2]
    k = max(THUMB_W / iw, THUMB_H / ih)
    if k > 3:  # a tiny template: show it whole and sharp in the middle rather than blown up
        k = min(THUMB_W / iw, THUMB_H / ih, 3.0)
        small = cv2.resize(img, (max(1, int(iw * k)), max(1, int(ih * k))), interpolation=cv2.INTER_NEAREST)
        out = np.full((THUMB_H, THUMB_W, 3), 32, np.uint8)
        y, x = (THUMB_H - small.shape[0]) // 2, (THUMB_W - small.shape[1]) // 2
        out[y:y + small.shape[0], x:x + small.shape[1]] = small[..., :3]
        return out
    big = cv2.resize(img, (max(THUMB_W, int(iw * k + 1)), max(THUMB_H, int(ih * k + 1))),
                     interpolation=cv2.INTER_AREA)
    y, x = (big.shape[0] - THUMB_H) // 2, (big.shape[1] - THUMB_W) // 2
    return np.ascontiguousarray(big[y:y + THUMB_H, x:x + THUMB_W, :3])


def script_info(script, assets):
    """(name, detail, thumbnail BGR or None, extra) for a script and its pictures."""
    steps = script.get("steps") or []
    n = len(steps)
    detail = f"{n} step{'s' if n != 1 else ''}"
    images = [nm for st in steps for nm in model.step_images(st)]
    if images:
        detail += f", {len(set(images))} picture{'s' if len(set(images)) != 1 else ''}"
    img = None
    for nm in images:
        img = assets.get(nm)
        if img is not None:
            break
    extra = {"actions": [st.get("action", "") for st in steps[:8]]}
    return script.get("name") or "", detail, _thumb_image(img), extra


def recording_info(events, images=None, snaps=None):
    """(name, detail, thumbnail BGR or None, extra) for a recording."""
    real = [e for e in events if e.get("type") != "snap"]
    length = events[-1]["t"] if events else 0.0
    detail = f"{_fmt_len(length)}, {len(real)} event{'s' if len(real) != 1 else ''}"
    img = None
    for e in events:
        if e.get("type") == "snap" and (snaps or {}).get(e.get("snap")):
            try:
                img = cv2.imdecode(np.frombuffer(snaps[e["snap"]], np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                img = None
            if img is not None:
                break
    if img is None:
        for e in events:
            pic = (images or {}).get(e.get("img")) if e.get("img") else None
            if pic is not None:
                img = pic if not isinstance(pic, bytes) else vision.decode_png(pic)
                break
    clicks = [round(e["t"] / length, 3) for e in events if e.get("type") == "mouse_down"][:60] if length else []
    keys = [round(e["t"] / length, 3) for e in events if e.get("type") == "key_down"][:60] if length else []
    return "", detail, _thumb_image(img), {"clicks": clicks, "keys": keys}


def chain_info(chain):
    """(name, detail, thumbnail, extra) for a chain: its cards' names make its picture."""
    names = [os.path.splitext(os.path.basename(ln["path"]))[0] for ln in chain.get("links", [])]
    n = len(names)
    detail = f"{n} script{'s' if n != 1 else ''}" + ("" if chain.get("repeat", 1) == 1 else
                                                      ", repeats" if chain.get("repeat") == 0
                                                      else f", {chain['repeat']} times")
    return chain.get("name") or "", detail, None, {"links": names[:8]}


class Library:
    """The index file (library.json in the data folder) and its thumbnails."""

    def __init__(self, folder=None):
        self.folder = folder or storage.data_dir()
        self.path = os.path.join(self.folder, "library.json")
        self.thumbs = os.path.join(self.folder, "library-thumbs")
        self.entries = {}
        self.load()

    # ------------------------------------------------------------ storage

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = {e["path"]: e for e in data.get("entries", []) if isinstance(e, dict) and e.get("path")}
        except (OSError, ValueError):
            self.entries = {}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"format": "clicker-library", "version": 1, "entries": list(self.entries.values())}, f,
                      indent=1)
        os.replace(tmp, self.path)

    def thumb_path(self, entry):
        return os.path.join(self.thumbs, entry["thumb"]) if entry.get("thumb") else None

    def _write_thumb(self, path, img):
        if img is None:
            return None
        os.makedirs(self.thumbs, exist_ok=True)
        name = hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:16] + ".jpg"
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        with open(os.path.join(self.thumbs, name), "wb") as f:
            f.write(buf.tobytes())
        return name

    # ------------------------------------------------------------ changes

    def touch(self, path, kind, info, used=True):
        """Remember a file with what script_info / recording_info said about it."""
        path = os.path.abspath(path)
        name, detail, img, extra = info
        old = self.entries.get(path, {})
        entry = {
            "path": path, "kind": kind,
            "name": name or os.path.splitext(os.path.basename(path))[0],
            "detail": detail, "favorite": bool(old.get("favorite")),
            "used": time.time() if used else old.get("used", 0), "added": old.get("added", time.time()),
            "thumb": self._write_thumb(path, img), **extra,
        }
        if entry["thumb"] is None and old.get("thumb"):
            self._remove_thumb(old)
        self.entries[path] = entry
        self._prune()
        return entry

    def touch_file(self, path, used=True):
        """Read a script or recording from disk and remember it. Returns the entry or None."""
        kind = kind_of(path)
        try:
            if kind == "script":
                script, assets = storage.load_script(path)
                return self.touch(path, kind, script_info(script, assets), used)
            if kind == "recording":
                events, _o, images, snaps = storage.load_recording_full(path)
                return self.touch(path, kind, recording_info(events, images, snaps), used)
            if kind == "chain":
                from . import chains
                return self.touch(path, kind, chain_info(chains.load(path)), used)
        except Exception:
            return None
        return None

    def add_folder(self, folder):
        """Add every script and recording in a folder (not its subfolders). Returns how many are new."""
        new = 0
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return 0
        for n in names:
            p = os.path.abspath(os.path.join(folder, n))
            if os.path.isfile(p) and kind_of(p) and p not in self.entries:
                if self.touch_file(p, used=False) is not None:
                    new += 1
        return new

    def set_favorite(self, path, on):
        e = self.entries.get(os.path.abspath(path))
        if e is not None:
            e["favorite"] = bool(on)

    def forget(self, path):
        e = self.entries.pop(os.path.abspath(path), None)
        if e is not None:
            self._remove_thumb(e)

    def _remove_thumb(self, e):
        p = self.thumb_path(e)
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    def _prune(self):
        rest = sorted((e for e in self.entries.values() if not e.get("favorite")),
                      key=lambda e: max(e.get("used", 0), e.get("added", 0)), reverse=True)
        for e in rest[MAX_RECENT:]:
            self.forget(e["path"])

    def import_recent(self, paths):
        """Bring in an older plain recent list (only files not known yet)."""
        for p in paths or []:
            p = os.path.abspath(p)
            if p not in self.entries and os.path.isfile(p):
                self.touch_file(p, used=False)

    # ------------------------------------------------------------ reading

    def list(self, query="", kind=None, favorites=False):
        """Entries matching every word of query, most recently used first (never used: newest added)."""
        words = query.lower().split()
        out = []
        for e in self.entries.values():
            if kind and e.get("kind") != kind:
                continue
            if favorites and not e.get("favorite"):
                continue
            hay = f"{e.get('name', '')} {os.path.basename(e['path'])} {e.get('detail', '')} " \
                  f"{' '.join(e.get('actions', []))} {' '.join(e.get('links', []))}".lower()
            if all(w in hay for w in words):
                out.append(dict(e, missing=not os.path.isfile(e["path"])))
        out.sort(key=lambda e: (max(e.get("used", 0), e.get("added", 0)), e["path"]), reverse=True)
        return out


def when_text(ts, now=None):
    """'just now', '5 min ago', 'yesterday', 'Mar 3'."""
    if not ts:
        return "added"
    d = (now or time.time()) - ts
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    if d < 2 * 86400:
        return "yesterday"
    if d < 7 * 86400:
        return f"{int(d // 86400)} days ago"
    return time.strftime("%b %d", time.localtime(ts)).replace(" 0", " ")
