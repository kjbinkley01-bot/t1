"""Editor operations that don't need a window: undo history, clipboard, block moves.

Every change to the step list goes through model.reorder, so numeric jumps
keep pointing at the same steps however the list is rearranged.
"""

import base64
import copy
import json

from . import model

CLIP_FORMAT = "clicker-steps"


# ---------------------------------------------------------------- undo / redo

class History:
    """Undo and redo stacks of script snapshots (steps plus error handler)."""

    def __init__(self, limit=200):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []

    @staticmethod
    def snapshot(script, selection=()):
        return {"steps": copy.deepcopy(script["steps"]),
                "error_handler": script.get("error_handler"),
                "selection": list(selection)}

    @staticmethod
    def restore(script, snap):
        script["steps"] = copy.deepcopy(snap["steps"])
        script["error_handler"] = snap["error_handler"]
        return list(snap.get("selection") or [])

    def record(self, script, selection=()):
        """Call before changing the script."""
        self.undo_stack.append(self.snapshot(script, selection))
        if len(self.undo_stack) > self.limit:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def discard_last(self):
        """Drop the snapshot just recorded (the change did not happen)."""
        if self.undo_stack:
            self.undo_stack.pop()

    def undo(self, script, selection=()):
        """Restore the previous state. Returns the selection to show, or None."""
        if not self.undo_stack:
            return None
        self.redo_stack.append(self.snapshot(script, selection))
        return self.restore(script, self.undo_stack.pop())

    def redo(self, script, selection=()):
        if not self.redo_stack:
            return None
        self.undo_stack.append(self.snapshot(script, selection))
        return self.restore(script, self.redo_stack.pop())

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()

    @property
    def can_undo(self):
        return bool(self.undo_stack)

    @property
    def can_redo(self):
        return bool(self.redo_stack)


# ---------------------------------------------------------------- list edits

def insert(script, pos, new_steps):
    """Insert steps before pos. Returns the new steps' indexes."""
    n = len(script["steps"])
    pos = max(0, min(n, pos))
    new_steps = [copy.deepcopy(s) for s in new_steps]
    order = list(range(pos)) + new_steps + list(range(pos, n))
    model.reorder(script, order)
    return list(range(pos, pos + len(new_steps)))


def delete(script, indexes):
    """Remove steps. Returns the index to select afterwards (or None)."""
    gone = set(indexes)
    if not gone:
        return None
    n = len(script["steps"])
    model.reorder(script, [i for i in range(n) if i not in gone])
    left = len(script["steps"])
    return min(min(gone), left - 1) if left else None


def move_to(script, indexes, target):
    """Move the selected steps so the block starts at `target` (index in the final list).

    Returns the moved steps' new indexes.
    """
    sel = sorted(set(indexes))
    if not sel:
        return []
    n = len(script["steps"])
    rest = [i for i in range(n) if i not in set(sel)]
    target = max(0, min(len(rest), target))
    order = rest[:target] + sel + rest[target:]
    if order == list(range(n)):
        return sel
    model.reorder(script, order)
    return list(range(target, target + len(sel)))


def shift(script, indexes, delta):
    """Move the selection up (-1) or down (+1) one place."""
    sel = sorted(set(indexes))
    if not sel:
        return []
    n = len(script["steps"])
    if (delta < 0 and sel[0] == 0) or (delta > 0 and sel[-1] == n - 1):
        return sel
    return move_to(script, sel, sel[0] + delta)


def duplicate(script, indexes):
    """Copy the selected steps and place the copies right after the last one."""
    sel = sorted(set(indexes))
    if not sel:
        return []
    block = _relative_block(script["steps"], sel)
    new_idx = insert(script, sel[-1] + 1, _place_block(block, sel[-1] + 1))
    _finish_abs(script)
    return new_idx


# ---------------------------------------------------------------- clipboard

def _relative_block(steps, sel):
    """Deep copies of the selected steps, with jumps inside the block made relative.

    A numeric jump to another selected step becomes {"rel": k} (k = position in
    the block) so it can be re-pointed wherever the block is pasted. Labels on
    the copies are cleared so they don't clash with the originals.
    """
    where = {old: k for k, old in enumerate(sel)}
    out = []
    for i in sel:
        st = copy.deepcopy(steps[i])
        st["label"] = ""
        boxes = [(st, key) for key in model.TARGET_KEYS if key in st]
        if isinstance(st.get("wait"), dict) and "goto" in st["wait"]:
            boxes.append((st["wait"], "goto"))
        for box, key in boxes:
            v = box.get(key)
            if isinstance(v, int) and not isinstance(v, bool) and (v - 1) in where:
                box[key] = {"rel": where[v - 1]}
        out.append(st)
    return out


def _place_block(block, pos):
    """Turn relative jumps back into step numbers for a block inserted at pos.

    The step numbers are written as they will be after insertion; insert()
    then shifts only jumps that point past pos, and these point inside the block.
    """
    out = []
    for st in block:
        st = copy.deepcopy(st)
        boxes = [(st, key) for key in model.TARGET_KEYS if key in st]
        if isinstance(st.get("wait"), dict) and "goto" in st["wait"]:
            boxes.append((st["wait"], "goto"))
        for box, key in boxes:
            v = box.get(key)
            if isinstance(v, dict) and "rel" in v:
                box[key] = {"abs": pos + int(v["rel"]) + 1}
        out.append(st)
    return out


def _finish_abs(script):
    """Replace {"abs": n} markers left by _place_block with plain step numbers."""
    for st in script["steps"]:
        boxes = [(st, key) for key in model.TARGET_KEYS if key in st]
        if isinstance(st.get("wait"), dict) and "goto" in st["wait"]:
            boxes.append((st["wait"], "goto"))
        for box, key in boxes:
            v = box.get(key)
            if isinstance(v, dict) and "abs" in v:
                box[key] = int(v["abs"])


def copy_payload(script, assets, indexes):
    """Text for the system clipboard: the steps plus the images they use."""
    sel = sorted(set(i for i in indexes if 0 <= i < len(script["steps"])))
    block = _relative_block(script["steps"], sel)
    images = {}
    for name in model.referenced_images({"steps": block}):
        raw = assets.raw(name)
        if raw:
            images[name] = base64.b64encode(raw).decode("ascii")
    return json.dumps({"format": CLIP_FORMAT, "version": 1, "steps": block, "images": images})


def parse_payload(text):
    """Steps and images from clipboard text. Accepts our format or a plain script."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if isinstance(data, dict) and data.get("format") == CLIP_FORMAT and isinstance(data.get("steps"), list):
        images = {}
        for name, b64 in (data.get("images") or {}).items():
            try:
                images[name] = base64.b64decode(b64)
            except (TypeError, ValueError):
                continue
        return data["steps"], images
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        return model.normalize_script(data)["steps"], {}
    return None


def paste(script, assets, text, pos):
    """Insert clipboard steps at pos. Returns the new indexes, or None if nothing to paste.

    Images that clash with a different image of the same name are renamed.
    """
    parsed = parse_payload(text)
    if not parsed:
        return None
    steps, images = parsed
    rename = {}
    for name, raw in images.items():
        if assets.has(name) and assets.raw(name) == raw:
            continue
        new = name if not assets.has(name) else assets.unique_name(name)
        assets.add_bytes(new, raw)
        if new != name:
            rename[name] = new
    fixed = []
    for st in steps:
        st = copy.deepcopy(st)
        for holder in (st, st.get("wait") if isinstance(st.get("wait"), dict) else None):
            if holder and model.image_name(holder.get("image")) in rename:
                holder["image"] = rename[model.image_name(holder["image"])]
        if st.get("images"):
            st["images"] = [rename.get(model.image_name(n), n) for n in st["images"]]
        fixed.append(st)
    # check each step's shape the same way loading a file does, keeping the jump markers
    shells = model.normalize_script({"steps": _strip_markers(fixed)})["steps"]
    for shell, st in zip(shells, fixed):
        for key in model.TARGET_KEYS:
            if isinstance(st.get(key), dict):
                shell[key] = st[key]
        if isinstance(st.get("wait"), dict) and isinstance(st["wait"].get("goto"), dict):
            shell["wait"]["goto"] = st["wait"]["goto"]
    new_idx = insert(script, pos, _place_block(shells, pos))
    _finish_abs(script)
    return new_idx


def _strip_markers(steps):
    out = []
    for st in steps:
        st = copy.deepcopy(st)
        for key in model.TARGET_KEYS:
            if isinstance(st.get(key), dict):
                st[key] = None
        if isinstance(st.get("wait"), dict) and isinstance(st["wait"].get("goto"), dict):
            st["wait"]["goto"] = None
        out.append(st)
    return out
