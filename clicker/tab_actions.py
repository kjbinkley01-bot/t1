"""Action Script tab: build, edit and run step lists."""

import copy
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from . import editing, inputs, model, runlog, storage, ui, vision
from .runner import Runner
from .storage import AssetStore
from .theme import (C, F, Button, cap, check, combo, entry, frame, label, panel,
                    scrolled_tree, vsep, px)

SPEEDS = ["0.25x", "0.5x", "0.75x", "1.0x", "1.5x", "2.0x", "3.0x"]
LEFT_W = 13


class ActionTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.script = model.new_script()
        self.assets = AssetStore()
        self.path = None
        self.dirty = False
        self.history = editing.History()
        self._drag = None
        self.running_row = None
        self.detail_vars = {}
        self.detail_widgets = []
        self.image_combos = []

        sv = lambda v="": tk.StringVar(value=v)  # noqa: E731
        self.v_x, self.v_y = sv(), sv()
        self.v_action = sv("Left Click")
        self.v_delay, self.v_repeat, self.v_comment, self.v_label = sv("100"), sv("1"), sv(), sv()
        self.v_back = tk.BooleanVar(value=False)
        self.v_wait_mode = sv(model.WAIT_LABEL["none"])
        self.v_wait_target = sv()
        self.v_wait_timeout, self.v_wait_poll, self.v_wait_conf = sv("30"), sv("250"), sv("90")
        self.v_on_timeout = sv(model.ON_TIMEOUT_LABEL["stop"])
        self.v_wait_goto, self.v_handler, self.v_retries = sv(), sv(), sv(str(model.DEFAULT_RETRIES))
        self.v_restart = sv("0")
        self.v_scale_search = tk.BooleanVar(value=False)
        self.v_script_repeat, self.v_speed, self.v_rand = sv("1"), sv("1.0x"), sv("0")
        self.v_hide = tk.BooleanVar(value=bool(app.settings.get("hide_while_running", False)))

        self._build_toolbar()
        self._build_editor()
        self._build_list()
        self._build_hotkeys()
        self._bind_keys()
        self.v_action.trace_add("write", self._on_action_change)
        self.v_wait_mode.trace_add("write", self._on_wait_mode)
        self._on_action_change()
        self._on_wait_mode()
        self.refresh_list()
        self._update_undo_buttons()

    # ------------------------------------------------------------ layout

    def _build_toolbar(self):
        bar = frame(self)
        bar.pack(fill="x", padx=14, pady=(12, 10))
        self.btn_start = Button(bar, "Start", self.toggle_run, kind="primary")
        self.btn_start.pack(side="left")
        self.btn_pause = Button(bar, "Pause", self.app.toggle_pause)
        self.btn_pause.pack(side="left", padx=(6, 0))
        self.btn_stop = Button(bar, "Stop", self.app.stop_job)
        self.btn_stop.pack(side="left", padx=(6, 0))
        vsep(bar).pack(side="left", padx=12)
        for text, cmd in (("New", self.new_script), ("Load", self.load), ("Save", self.save),
                          ("Save As", lambda: self.save(True))):
            Button(bar, text, cmd).pack(side="left", padx=(0, 6))

        check(bar, "Hide while running", self.v_hide, command=self._save_hide).pack(side="right")
        vsep(bar).pack(side="right", padx=12)
        entry(bar, self.v_rand, 5, mono=True, justify="right").pack(side="right")
        label(bar, "Random delay ms", muted=True).pack(side="right", padx=(12, 6))
        combo(bar, self.v_speed, SPEEDS, width=6).pack(side="right")
        label(bar, "Speed", muted=True).pack(side="right", padx=(12, 6))
        entry(bar, self.v_script_repeat, 4, mono=True, justify="right").pack(side="right")
        label(bar, "Repeat (0 = loop)", muted=True).pack(side="right", padx=(0, 6))

    def _row(self, parent, pady=(0, 8)):
        r = frame(parent, bg=C["panel"])
        r.pack(fill="x", pady=pady)
        return r

    def _lbl(self, parent, text, width=None):
        w = label(parent, text, bg=C["panel"], anchor="w")
        if width:
            w.configure(width=width)
        return w

    def _build_editor(self):
        row = frame(self)
        row.pack(fill="x", padx=14)

        # left: add / edit
        p = panel(row)
        p.pack(side="left", fill="both", expand=True)
        inner = frame(p, bg=C["panel"])
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        cap(inner, "Add / Edit Action", bg=C["panel"]).pack(anchor="w", pady=(0, 10))

        r = self._row(inner)
        self._lbl(r, "X", LEFT_W).pack(side="left")
        entry(r, self.v_x, 7, mono=True).pack(side="left")
        self._lbl(r, "Y").pack(side="left", padx=(12, 6))
        entry(r, self.v_y, 7, mono=True).pack(side="left")
        Button(r, "Pick", self.pick_position).pack(side="left", padx=(10, 0))
        label(r, "blank = wherever the cursor is", bg=C["panel"], muted=True, font=F.small).pack(side="left", padx=10)

        r = self._row(inner)
        self._lbl(r, "Action type", LEFT_W).pack(side="left")
        self.cb_action = combo(r, self.v_action, model.ALL_ACTIONS, width=28)
        self.cb_action.pack(side="left")
        self.lbl_group = label(r, "", bg=C["panel"], muted=True, font=F.small)
        self.lbl_group.pack(side="left", padx=10)

        self.details = frame(inner, bg=C["panel"])
        self.details.pack(fill="x")
        self.lbl_hint = label(inner, "", bg=C["panel"], muted=True, font=F.small, anchor="w", justify="left")
        self.lbl_hint.pack(fill="x", pady=(0, 8))

        r = self._row(inner)
        check(r, "Cursor back", self.v_back, bg=C["panel"]).pack(side="left")
        self._lbl(r, "Delay before").pack(side="left", padx=(18, 6))
        entry(r, self.v_delay, 7, mono=True).pack(side="left")
        self._lbl(r, "ms").pack(side="left", padx=(4, 18))
        self._lbl(r, "Repeat").pack(side="left", padx=(0, 6))
        entry(r, self.v_repeat, 5, mono=True).pack(side="left")

        r = self._row(inner)
        self._lbl(r, "Label", LEFT_W).pack(side="left")
        entry(r, self.v_label, 12).pack(side="left")
        self._lbl(r, "Comment").pack(side="left", padx=(12, 6))
        entry(r, self.v_comment, 28).pack(side="left", fill="x", expand=True)

        r = self._row(inner, pady=(4, 0))
        Button(r, "Add", self.add_step, kind="primary").pack(side="left")
        Button(r, "Update", self.update_step).pack(side="left", padx=(6, 0))
        Button(r, "Insert Above", self.insert_step).pack(side="left", padx=(6, 0))
        self.lbl_form_msg = label(r, "", bg=C["panel"], fg=C["err"], font=F.small)
        self.lbl_form_msg.pack(side="left", padx=12)

        # right: wait / timing
        q = panel(row, width=px(410))
        q.pack(side="right", fill="y", padx=(12, 0), before=p)
        q.pack_propagate(False)
        inner = frame(q, bg=C["panel"])
        inner.pack(fill="both", expand=True, padx=14, pady=12)
        head = frame(inner, bg=C["panel"])
        head.pack(fill="x", pady=(0, 10))
        cap(head, "Wait / Timing", bg=C["panel"]).pack(side="left")
        label(head, " Screen aware ", bg=C["badge"], fg=C["teal"], font=F.cap).pack(side="right")

        r = self._row(inner)
        self._lbl(r, "Run when", 11).pack(side="left")
        combo(r, self.v_wait_mode, [m[1] for m in model.WAIT_MODES], width=26).pack(side="left", fill="x", expand=True)

        r = self._row(inner)
        self._lbl(r, "Watch for", 11).pack(side="left")
        self.cb_wait_target = combo(r, self.v_wait_target, [], width=18, editable=True)
        self.cb_wait_target.pack(side="left", fill="x", expand=True)
        self.btn_wait_capture = Button(r, "Capture", self.capture_wait_target)
        self.btn_wait_capture.pack(side="left", padx=(6, 0))
        self.image_combos.append(self.cb_wait_target)

        r = self._row(inner)
        self._lbl(r, "Timeout s", 11).pack(side="left")
        entry(r, self.v_wait_timeout, 5, mono=True).pack(side="left")
        self._lbl(r, "Every ms").pack(side="left", padx=(10, 6))
        entry(r, self.v_wait_poll, 5, mono=True).pack(side="left")
        self._lbl(r, "Match %").pack(side="left", padx=(10, 6))
        self.e_wait_conf = entry(r, self.v_wait_conf, 4, mono=True)
        self.e_wait_conf.pack(side="left")

        r = self._row(inner)
        self._lbl(r, "If timed out", 11).pack(side="left")
        combo(r, self.v_on_timeout, [m[1] for m in model.ON_TIMEOUT], width=26).pack(side="left", fill="x",
                                                                                  expand=True)

        r = self._row(inner)
        self._lbl(r, "Retries", 11).pack(side="left")
        entry(r, self.v_retries, 4, mono=True).pack(side="left")
        self._lbl(r, "Go to").pack(side="left", padx=(14, 6))
        self.e_wait_goto = entry(r, self.v_wait_goto, 10, mono=True)
        self.e_wait_goto.pack(side="left")

        r = self._row(inner)
        self._lbl(r, "Error handler", 11).pack(side="left")
        entry(r, self.v_handler, 10, mono=True).pack(side="left")
        self._lbl(r, "Restarts").pack(side="left", padx=(14, 6))
        entry(r, self.v_restart, 4, mono=True).pack(side="left")

        r = self._row(inner)
        check(r, "Find images at other display scales (slower)", self.v_scale_search,
              command=lambda: self._changed_settings(), bg=C["panel"]).pack(side="left")

        self.lbl_wait_hint = label(inner, "", bg=C["panel"], muted=True, font=F.small,
                                   anchor="w", justify="left", wraplength=370)
        self.lbl_wait_hint.pack(fill="x")

    def _build_list(self):
        row = frame(self)
        row.pack(fill="both", expand=True, padx=14, pady=12)
        p = panel(row)
        p.pack(side="left", fill="both", expand=True)
        head = frame(p, bg=C["panel"])
        head.pack(fill="x", padx=12, pady=(10, 8))
        cap(head, "Actions in sequence", bg=C["panel"]).pack(side="left")
        self.btn_undo = Button(head, "Undo", self.undo, small=True)
        self.btn_undo.pack(side="left", padx=(16, 4))
        self.btn_redo = Button(head, "Redo", self.redo, small=True)
        self.btn_redo.pack(side="left")
        label(head, "Drag rows to reorder. Ctrl+C / Ctrl+V copy and paste steps.", bg=C["panel"], muted=True,
              font=F.small).pack(side="left", padx=12)
        Button(head, "Run Logs", self.open_logs, small=True).pack(side="right", padx=(10, 0))
        self.lbl_count = label(head, "", bg=C["panel"], muted=True, font=F.small)
        self.lbl_count.pack(side="right")
        cols = [("sr", "Sr", 40, False), ("label", "Label", 76, False), ("action", "Action", 150, False),
                ("x", "X", 64, False),
                ("y", "Y", 70, False), ("back", "Cursor back", 86, False), ("delay", "Delay ms", 76, False),
                ("rep", "Repeat", 60, False), ("cond", "Wait / Condition", 260, True),
                ("note", "Comment", 170, True)]
        box, self.tree = scrolled_tree(p, cols)
        self.tree.configure(selectmode="extended")
        box.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.delete_step())
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_end, add="+")

        side = frame(row)
        side.pack(side="right", fill="y", padx=(12, 0), before=p)
        self.btn_start2 = Button(side, "Start", self.toggle_run, kind="primary", width=12)
        self.btn_start2.pack(fill="x")
        Button(side, "Test Step", self.test_step, width=12).pack(fill="x", pady=(8, 0))
        frame(side, height=14).pack()
        for text, cmd in (("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1)),
                          ("Duplicate", self.duplicate), ("Copy", self.copy_steps), ("Paste", self.paste_steps)):
            Button(side, text, cmd, width=12).pack(fill="x", pady=(0, 8))
        frame(side, height=6).pack()
        Button(side, "Delete", self.delete_step, kind="danger", width=12).pack(fill="x", pady=(0, 8))
        Button(side, "Delete All", self.delete_all, kind="danger", width=12).pack(fill="x")

    def _build_hotkeys(self):
        p = panel(self)
        p.pack(fill="x", padx=14, pady=(0, 12))
        inner = frame(p, bg=C["panel"])
        inner.pack(fill="x", padx=14, pady=10)
        cap(inner, "Global shortcut keys", bg=C["panel"]).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.hotkey_rows = self.app.hotkey_rows(inner, [
            ("Add action at cursor position", "add_action"),
            ("Start / stop script", "script_toggle"),
            ("Pause / resume", "pause"),
            ("Emergency stop everything", "emergency"),
        ], columns=2, start_row=1)

    # ------------------------------------------------------------ editor logic

    def _on_action_change(self, *_):
        action = self.v_action.get()
        self.lbl_group.configure(text=model.ACTION_GROUP.get(action, ""))
        for w in self.detail_widgets:
            w.destroy()
        self.detail_widgets = []
        self.image_combos = [c for c in self.image_combos if c is self.cb_wait_target]
        spec = model.FIELD_SPECS.get(action, [])
        row = None
        slots = 3
        for key, text, width, kind in spec:
            # image and region fields carry extra buttons, so they take two of a row's three slots
            cost = 2 if kind in ("image", "region") else 1
            if slots + cost > 3:
                row = self._row(self.details)
                self.detail_widgets.append(row)
                self._lbl(row, text, LEFT_W).pack(side="left")
                slots = cost
            else:
                self._lbl(row, text).pack(side="left", padx=(14, 6))
                slots += cost
            var = self.detail_vars.get(key)
            if var is None:
                var = self.detail_vars[key] = tk.StringVar(value=model.DEFAULTS.get(key, ""))
            if kind.startswith("choice:"):
                combo(row, var, kind[7:].split(","), width=width).pack(side="left")
            elif kind == "image":
                cb = combo(row, var, self.assets.names(), width=width, editable=True)
                cb.pack(side="left")
                self.image_combos.append(cb)
                Button(row, "Capture", lambda v=var: self.capture_image(v), small=True).pack(side="left", padx=(6, 0))
                Button(row, "Load", lambda v=var: self.load_image(v), small=True).pack(side="left", padx=(4, 0))
            else:
                entry(row, var, width, mono=kind in ("int", "sint", "percent", "region", "color", "target")
                      ).pack(side="left")
                if kind == "region":
                    Button(row, "Draw", lambda v=var: self.draw_region(v), small=True).pack(side="left", padx=(6, 0))
                elif kind == "color":
                    Button(row, "Grab", lambda v=var: self.grab_pixel(v), small=True).pack(side="left", padx=(6, 0))
                elif kind == "file":
                    Button(row, "Browse", lambda v=var: self.browse_script(v), small=True).pack(side="left", padx=(6, 0))
        self.lbl_hint.configure(text=model.ACTION_HINTS.get(action, ""))

    def _on_wait_mode(self, *_):
        mode = model.WAIT_ID.get(self.v_wait_mode.get(), "none")
        texts = {
            "none": ("Capture", "Runs after the fixed delay. Pick a condition to wait on the screen instead."),
            "image_appears": ("Capture", "Waits until the captured image is visible."),
            "image_vanishes": ("Capture", "Waits until the captured image is gone."),
            "pixel_is": ("Grab", "Enter x, y, #color. Grab fills it from under the cursor after 3 s."),
            "region_stable": ("Draw", "Region x, y, w, h to watch (blank = whole screen)."),
        }
        btn, hint = texts[mode]
        self.btn_wait_capture.set_text(btn)
        self.btn_wait_capture.set_enabled(mode != "none")
        self.lbl_wait_hint.configure(text=hint + " The delay on the left still applies after it.")
        self.cb_wait_target.configure(values=self.assets.names() if mode.startswith("image") else [])
        self.cb_wait_target.configure(state="normal" if mode != "none" else "disabled")

    def _refresh_image_lists(self):
        names = self.assets.names()
        for cb in self.image_combos:
            try:
                if cb is not self.cb_wait_target or model.WAIT_ID.get(self.v_wait_mode.get(), "").startswith("image"):
                    cb.configure(values=names)
            except tk.TclError:
                pass

    def form_to_step(self):
        a = self.v_action.get()
        if a not in model.ACTION_GROUP:
            raise ValueError("Choose an action type.")
        step = {
            "action": a,
            "x": model.parse_int(self.v_x.get(), "X", allow_blank=True),
            "y": model.parse_int(self.v_y.get(), "Y", allow_blank=True),
            "cursor_back": bool(self.v_back.get()),
            "delay_ms": model.parse_int(self.v_delay.get() or "0", "Delay", 0),
            "repeat": model.parse_int(self.v_repeat.get() or "1", "Repeat", 1),
            "comment": self.v_comment.get().strip(),
            "label": self.v_label.get().strip(),
        }
        for key, text, _w, kind in model.FIELD_SPECS.get(a, []):
            raw = self.detail_vars[key].get() if key in self.detail_vars else model.DEFAULTS.get(key, "")
            step[key] = model.parse_field(kind, raw, text)
        if a in model.IMAGE_ACTIONS and step.get("image") and not self.assets.has(step["image"]):
            raise ValueError(f"Image '{step['image']}' is not in this script. Capture or Load it.")
        mode = model.WAIT_ID.get(self.v_wait_mode.get(), "none")
        w = {"mode": mode}
        if mode != "none":
            target = self.v_wait_target.get().strip()
            if mode.startswith("image"):
                name = model.image_name(target)
                if not name or not self.assets.has(name):
                    raise ValueError("Capture the image to wait for (Watch for).")
                w["image"] = name
                w["confidence"] = model.parse_int(self.v_wait_conf.get(), "Match %", 50, 100) / 100.0
            elif mode == "pixel_is":
                w["x"], w["y"], w["color"] = model.parse_pixel_target(target)
                w["tolerance"] = 12
            elif mode == "region_stable":
                w["region"] = model.parse_region(target, "Watch for region")
                w["stable_ms"] = 800
            w["timeout_s"] = model.parse_int(self.v_wait_timeout.get(), "Timeout", 0)
            w["poll_ms"] = model.parse_int(self.v_wait_poll.get(), "Check every", 20)
            w["on_timeout"] = model.ON_TIMEOUT_ID.get(self.v_on_timeout.get(), "stop")
            if w["on_timeout"] in ("retry", "retry_handler"):
                w["retries"] = model.parse_int(self.v_retries.get() or "0", "Retries", 0, 100)
            if w["on_timeout"] == "goto":
                w["goto"] = model.parse_target(self.v_wait_goto.get(), "Timeout step")
                if w["goto"] is None:
                    raise ValueError("Enter the step number or label to go to when it times out.")
        step["wait"] = w
        err = model.check_step(step)
        if err:
            raise ValueError(err)
        return step

    def step_to_form(self, step):
        for key, text, _w, kind in model.FIELD_SPECS.get(step["action"], []):
            var = self.detail_vars.setdefault(key, tk.StringVar())
            val = step.get(key)
            var.set(model.field_to_text(kind, val, text) if val is not None else model.DEFAULTS.get(key, ""))
        self.v_x.set("" if step.get("x") is None else str(step["x"]))
        self.v_y.set("" if step.get("y") is None else str(step["y"]))
        self.v_action.set(step["action"])
        self.v_back.set(bool(step.get("cursor_back")))
        self.v_delay.set(str(step.get("delay_ms", 0)))
        self.v_repeat.set(str(step.get("repeat", 1)))
        self.v_comment.set(step.get("comment", ""))
        self.v_label.set(step.get("label", ""))
        w = step.get("wait") or {}
        mode = w.get("mode", "none")
        self.v_wait_mode.set(model.WAIT_LABEL.get(mode, model.WAIT_LABEL["none"]))
        if mode.startswith("image"):
            self.v_wait_target.set(w.get("image", ""))
            self.v_wait_conf.set(str(int(round(float(w.get("confidence", 0.9)) * 100))))
        elif mode == "pixel_is":
            self.v_wait_target.set(f"{w.get('x')}, {w.get('y')}, {w.get('color')}")
        elif mode == "region_stable":
            self.v_wait_target.set(model.format_region(w.get("region")))
        else:
            self.v_wait_target.set("")
        if mode != "none":
            self.v_wait_timeout.set(str(w.get("timeout_s", 30)))
            self.v_wait_poll.set(str(w.get("poll_ms", 250)))
            self.v_on_timeout.set(model.ON_TIMEOUT_LABEL.get(w.get("on_timeout", "stop")))
            self.v_wait_goto.set(str(w.get("goto") or ""))
            self.v_retries.set(str(w.get("retries", model.DEFAULT_RETRIES)))
        self.lbl_form_msg.configure(text="")

    def _form_step(self):
        try:
            step = self.form_to_step()
        except ValueError as e:
            self.lbl_form_msg.configure(text=str(e))
            self.app.set_status(str(e), error=True)
            return None
        self.lbl_form_msg.configure(text="")
        return step

    def _selected(self):
        """The first selected step (the one shown in the form), or None."""
        sel = self._selection()
        return sel[0] if sel else None

    def _selection(self):
        n = len(self.script["steps"])
        return sorted(int(i) for i in self.tree.selection() if int(i) < n)

    def _editable(self):
        if self.app.job_running_for(self):
            self.app.set_status("Stop the script before editing it.", error=True)
            return False
        return True

    def _record(self):
        self.history.record(self.script, self._selection())

    def _changed(self, select=None, sync=True):
        self.dirty = True
        if sync:
            self._sync_settings()
        self.refresh_list(select)
        self._update_undo_buttons()

    def _changed_settings(self):
        self.dirty = True
        self._sync_settings()
        self.app.update_title()

    def _update_undo_buttons(self):
        self.btn_undo.set_enabled(self.history.can_undo)
        self.btn_redo.set_enabled(self.history.can_redo)

    def _check_label_free(self, step, ignore=None):
        lab = step.get("label")
        if not lab:
            return True
        for i, other in enumerate(self.script["steps"]):
            if i != ignore and other.get("label") == lab:
                self.lbl_form_msg.configure(text=f"Step {i + 1} already has the label '{lab}'.")
                return False
        return True

    def add_step(self):
        step = self._form_step()
        if step and self._editable() and self._check_label_free(step):
            self._record()
            self.script["steps"].append(step)
            self._changed(len(self.script["steps"]) - 1)

    def update_step(self):
        i = self._selected()
        if i is None:
            self.lbl_form_msg.configure(text="Select a step in the list to update.")
            return
        step = self._form_step()
        if step and self._editable() and self._check_label_free(step, ignore=i):
            self._record()
            self.script["steps"][i] = step
            self._changed(i)

    def insert_step(self):
        i = self._selected()
        step = self._form_step()
        if not step or not self._editable() or not self._check_label_free(step):
            return
        self._record()
        new = editing.insert(self.script, 0 if i is None else i, [step])
        self._changed(new)

    def add_at_cursor(self):
        x, y = inputs.position()
        self.v_x.set(str(x))
        self.v_y.set(str(y))
        self.v_label.set("")
        step = self._form_step()
        if step and self._editable():
            self._record()
            self.script["steps"].append(step)
            self._changed(len(self.script["steps"]) - 1)
            self.app.set_status(f"Added {step['action']} at {x}, {y}")

    def move(self, d):
        sel = self._selection()
        if not sel or not self._editable():
            return
        self._record()
        new = editing.shift(self.script, sel, d)
        if new == sel:
            self.history.discard_last()
            return
        self._changed(new)

    def duplicate(self):
        sel = self._selection()
        if not sel or not self._editable():
            return
        self._record()
        self._changed(editing.duplicate(self.script, sel))

    def delete_step(self):
        sel = self._selection()
        if not sel or not self._editable():
            return
        self._record()
        nxt = editing.delete(self.script, sel)
        self._changed(nxt)
        self.app.set_status(f"Deleted {len(sel)} step{'s' if len(sel) != 1 else ''}. Ctrl+Z brings "
                            f"{'them' if len(sel) != 1 else 'it'} back.")

    def delete_all(self):
        if not self.script["steps"] or not self._editable():
            return
        if messagebox.askyesno("Delete all", "Remove every step from this script?", parent=self):
            self._record()
            self.script["steps"].clear()
            self._changed()

    def undo(self):
        if not self._editable():
            return
        sel = self.history.undo(self.script, self._selection())
        if sel is None:
            self.app.set_status("Nothing to undo.")
            return
        self._after_history(sel)

    def redo(self):
        if not self._editable():
            return
        sel = self.history.redo(self.script, self._selection())
        if sel is None:
            self.app.set_status("Nothing to redo.")
            return
        self._after_history(sel)

    def _after_history(self, sel):
        self.v_handler.set(str(self.script.get("error_handler") or ""))
        self._changed(sel, sync=False)

    # ------------------------------------------------------------ clipboard

    def copy_steps(self, cut=False):
        sel = self._selection()
        if not sel:
            return
        text = editing.copy_payload(self.script, self.assets, sel)
        self.clipboard_clear()
        self.clipboard_append(text)
        if cut:
            if not self._editable():
                return
            self._record()
            self._changed(editing.delete(self.script, sel))
        self.app.set_status(f"{'Cut' if cut else 'Copied'} {len(sel)} step{'s' if len(sel) != 1 else ''}")

    def paste_steps(self):
        if not self._editable():
            return
        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        sel = self._selection()
        pos = sel[-1] + 1 if sel else len(self.script["steps"])
        self._record()
        try:
            new = editing.paste(self.script, self.assets, text, pos)
        except ValueError as e:
            new = None
            self.app.set_status(f"Could not paste: {e}", error=True)
        if not new:
            self.history.discard_last()
            self.app.set_status("The clipboard has no Clicker steps. Copy steps first.", error=True)
            return
        self._refresh_image_lists()
        self._changed(new)
        self.app.set_status(f"Pasted {len(new)} step{'s' if len(new) != 1 else ''}")

    # ------------------------------------------------------------ keys and dragging

    def _bind_keys(self):
        mods = ["Control"] + (["Command"] if sys.platform == "darwin" else [])
        for m in mods:
            self.tree.bind(f"<{m}-c>", lambda e: self.copy_steps() or "break")
            self.tree.bind(f"<{m}-x>", lambda e: self.copy_steps(cut=True) or "break")
            self.tree.bind(f"<{m}-v>", lambda e: self.paste_steps() or "break")
            self.tree.bind(f"<{m}-d>", lambda e: self.duplicate() or "break")
            self.tree.bind(f"<{m}-a>", lambda e: self.tree.selection_set(self.tree.get_children()) or "break")
        self.tree.bind("<Alt-Up>", lambda e: self.move(-1) or "break")
        self.tree.bind("<Alt-Down>", lambda e: self.move(1) or "break")

    def _typing(self):
        w = self.focus_get()
        return isinstance(w, (tk.Entry, tk.Text)) or (w is not None and w.winfo_class() == "TCombobox")

    def _key_undo(self, _e=None):
        if self.app.current_tab == "actions" and not self._typing():
            self.undo()
            return "break"

    def _key_redo(self, _e=None):
        if self.app.current_tab == "actions" and not self._typing():
            self.redo()
            return "break"

    def _drag_start(self, e):
        row = self.tree.identify_row(e.y)
        self._drag = {"row": int(row), "moved": False} if row and not (e.state & 0x0005) else None

    def _drag_motion(self, e):
        d = self._drag
        if not d or self.app.job_running_for(self):
            return
        target = self.tree.identify_row(e.y)
        if not target or int(target) == d["row"]:
            return
        if not d["moved"]:
            self.history.record(self.script, [d["row"]])
            d["moved"] = True
            self.tree.configure(cursor="fleur")
        new = editing.move_to(self.script, [d["row"]], int(target))
        d["row"] = new[0]
        self._changed(new)

    def _drag_end(self, _e=None):
        if self._drag and self._drag["moved"]:
            self.tree.configure(cursor="")
            self.app.set_status(f"Moved to step {self._drag['row'] + 1}. Jumps were renumbered to match.")
        self._drag = None

    def _on_select(self, _e=None):
        i = self._selected()
        if i is not None and (self._drag is None or not self._drag["moved"]):
            self.step_to_form(self.script["steps"][i])

    def _row_data(self, i, s, labels):
        xt, yt, cond = model.describe_step(s)
        tags = ["odd" if i % 2 else "even"]
        if model.is_screen_step(s):
            tags.append("screen")
        if i == self.running_row:
            tags.append("running")
        if model.check_step(s, self.script["steps"], labels):
            tags.append("error")
        back = ("Yes" if s.get("cursor_back") else "No") if s["action"] in model.MOUSE_ACTIONS else ""
        values = (i + 1, s.get("label", ""), s["action"], xt, yt, back, s.get("delay_ms", 0), s.get("repeat", 1),
                  cond, s.get("comment", ""))
        return values, tuple(tags)

    def refresh_list(self, select=None):
        """Bring the table in line with the script, touching only the rows that changed."""
        steps = self.script["steps"]
        labels = model.label_map(steps)
        shown = getattr(self, "_shown_rows", None)
        if shown is None or len(self.tree.get_children()) != len(shown):
            self.tree.delete(*self.tree.get_children())
            shown = []
        rows = [self._row_data(i, s, labels) for i, s in enumerate(steps)]
        for i, row in enumerate(rows):
            if i < len(shown):
                if shown[i] != row:
                    self.tree.item(str(i), values=row[0], tags=row[1])
            else:
                self.tree.insert("", "end", iid=str(i), values=row[0], tags=row[1])
        for i in range(len(rows), len(shown)):
            self.tree.delete(str(i))
        self._shown_rows = rows
        self.tree.selection_set(())
        if select is not None:
            want = [select] if isinstance(select, int) else list(select)
            want = [str(i) for i in want if 0 <= i < len(steps)]
            if want:
                self.tree.selection_set(want)
                self.tree.see(want[-1])
                self.tree.see(want[0])
        n = len(steps)
        scr = self.script.get("screen")
        where = f", built on {scr['width']} x {scr['height']}" if scr else ""
        self.lbl_count.configure(text=f"{n} action{'s' if n != 1 else ''}{where}")
        self.app.update_title()

    def mark_running(self, i):
        prev = self.running_row
        self.running_row = i
        for idx in (prev, i):
            if idx is None or not self.tree.exists(str(idx)):
                continue
            tags = [t for t in self.tree.item(str(idx), "tags") if t != "running"]
            if idx == i:
                tags.append("running")
            self.tree.item(str(idx), tags=tags)
            rows = getattr(self, "_shown_rows", None)
            if rows and idx < len(rows):
                rows[idx] = (rows[idx][0], tuple(tags))
        if i is not None and self.tree.exists(str(i)):
            self.tree.see(str(i))

    # ------------------------------------------------------------ capture helpers

    def pick_position(self):
        def done():
            x, y = inputs.position()
            self.v_x.set(str(x))
            self.v_y.set(str(y))
        ui.countdown(self.app.root, self.app.toast, 3, "Picking position", done)

    def grab_pixel(self, color_var):
        def done():
            x, y = inputs.position()
            color = vision.rgb_hex(vision.pixel(x, y))
            self.v_x.set(str(x))
            self.v_y.set(str(y))
            color_var.set(color)
        ui.countdown(self.app.root, self.app.toast, 3, "Grabbing pixel", done)

    def capture_image(self, var, suggested=None):
        def done(region, img):
            if img is None:
                return
            base = suggested or self.v_comment.get() or model.image_stem(var.get()) or "image"
            name = ui.ask_string(self.app.root, "Name this image", "Image name", base.lower().replace(" ", "_"))
            if name is None:
                return
            name = self.assets.add_image(img, name or "image")
            var.set(name)
            self.dirty = True
            self._refresh_image_lists()
            self.app.set_status(f"Captured {name} ({region[2]} x {region[3]})")
        ui.select_region(self.app.root, done, "Drag around the image to capture. Esc cancels.")

    def load_image(self, var):
        path = filedialog.askopenfilename(parent=self, title="Load image",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                img = vision.decode_png(f.read())
        except (OSError, ValueError) as e:
            messagebox.showerror("Could not load image", str(e), parent=self)
            return
        name = self.assets.add_image(img, os.path.splitext(os.path.basename(path))[0])
        var.set(name)
        self.dirty = True
        self._refresh_image_lists()

    def draw_region(self, var):
        def done(region, _img):
            if region:
                var.set(model.format_region(region))
        ui.select_region(self.app.root, done, "Drag the area to search in. Esc cancels.")

    def browse_script(self, var):
        path = filedialog.askopenfilename(parent=self, title="Script to run",
                                          filetypes=[("Clicker scripts", "*.clk *.clkpkg *.json")])
        if path:
            var.set(path)

    def capture_wait_target(self):
        mode = model.WAIT_ID.get(self.v_wait_mode.get(), "none")
        if mode.startswith("image"):
            self.capture_image(self.v_wait_target)
        elif mode == "pixel_is":
            def done():
                x, y = inputs.position()
                self.v_wait_target.set(f"{x}, {y}, {vision.rgb_hex(vision.pixel(x, y))}")
            ui.countdown(self.app.root, self.app.toast, 3, "Grabbing pixel", done)
        elif mode == "region_stable":
            self.draw_region(self.v_wait_target)

    # ------------------------------------------------------------ files

    def _sync_settings(self):
        try:
            self.script["settings"]["repeat"] = int(self.v_script_repeat.get() or 1)
        except ValueError:
            pass
        self.script["settings"]["speed"] = float(self.v_speed.get().rstrip("x") or 1)
        try:
            self.script["settings"]["random_delay_ms"] = int(self.v_rand.get() or 0)
        except ValueError:
            pass
        try:
            self.script["error_handler"] = model.parse_target(self.v_handler.get(), "Error handler")
        except ValueError:
            self.script["error_handler"] = None
        try:
            self.script["settings"]["restart_on_failure"] = max(0, int(self.v_restart.get() or 0))
        except ValueError:
            pass
        self.script["settings"]["scale_search"] = bool(self.v_scale_search.get())

    def _save_hide(self):
        self.app.settings["hide_while_running"] = bool(self.v_hide.get())
        self.app.save_settings()

    def confirm_discard(self):
        if not self.dirty or not self.script["steps"]:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Save the current script first?", parent=self)
        if ans is None:
            return False
        if ans:
            return self.save()
        return True

    def set_script(self, script, assets, path=None):
        self.script = model.copy_script(script)
        self.assets = assets
        self.path = path
        self.dirty = path is None and bool(script["steps"])
        st = self.script.get("settings") or {}
        self.v_script_repeat.set(str(st.get("repeat", 1)))
        sp = float(st.get("speed", 1.0))
        self.v_speed.set(f"{sp:g}x" if f"{sp:g}x" in SPEEDS else f"{sp:.1f}x")
        self.v_rand.set(str(st.get("random_delay_ms", 0)))
        self.v_handler.set(str(self.script.get("error_handler") or ""))
        self.v_restart.set(str(st.get("restart_on_failure", 0)))
        self.v_scale_search.set(bool(st.get("scale_search", False)))
        self.running_row = None
        self.history.clear()
        self._update_undo_buttons()
        self._refresh_image_lists()
        self.refresh_list(0 if self.script["steps"] else None)

    def new_script(self):
        if self.app.job_running_for(self):
            return
        if self.confirm_discard():
            self.set_script(model.new_script(), AssetStore())
            self.dirty = False
            self.app.update_title()

    def load(self):
        if self.app.job_running_for(self) or not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self, title="Open script",
                                          filetypes=[("Clicker scripts", "*.clk *.clkpkg *.json"),
                                                     ("All files", "*.*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            messagebox.showerror("Could not open script", str(e), parent=self)
            return
        self.set_script(script, assets, path)
        self.dirty = False
        storage.add_recent(self.app.settings, path)
        self.app.save_settings()
        self.app.update_title()

    def save(self, save_as=False):
        self._sync_settings()
        path = self.path
        if save_as or not path or not path.lower().endswith((".clk", ".clkpkg")):
            base = os.path.splitext(os.path.basename(path))[0] if path else self.script.get("name", "script")
            path = filedialog.asksaveasfilename(parent=self, title="Save script", defaultextension=".clk",
                                                initialfile=f"{base}.clk",
                                                filetypes=[("Clicker script", "*.clk")])
            if not path:
                return False
        if not self.script.get("screen"):
            self.script["screen"] = vision.display_info()
        if self.script.get("name") in (None, "", "Untitled"):
            self.script["name"] = os.path.splitext(os.path.basename(path))[0]
        try:
            storage.save_script(path, self.script, self.assets)
        except Exception as e:
            messagebox.showerror("Could not save", str(e), parent=self)
            return False
        self.path = path
        self.dirty = False
        storage.add_recent(self.app.settings, path)
        self.app.save_settings()
        self.refresh_list(self._selected())
        self.app.set_status(f"Saved {os.path.basename(path)}")
        return True

    def open_logs(self):
        path = self.app.last_log_dir if getattr(self.app, "last_log_dir", None) else runlog.logs_dir()
        if not os.path.isdir(path):
            path = runlog.logs_dir()
        if not runlog.open_folder(path):
            messagebox.showinfo("Run logs", f"Run logs are saved in:\n{path}", parent=self)

    def title_text(self):
        name = os.path.basename(self.path) if self.path else (self.script.get("name") or "Untitled")
        return name + (" *" if self.dirty else "")

    # ------------------------------------------------------------ running

    def _runner(self, script, start_delay, dry=False, label_text="Script"):
        self._sync_settings()
        st = self.script["settings"]
        values = {}
        if script.get("inputs"):
            values = ui.ask_inputs(self.app.root, script["inputs"], self.app.last_inputs)
            if values is None:
                return None
            self.app.last_inputs.update(values)
        return Runner(script, self.assets, self.app.emitter("script"), inputs_map=values,
                      speed=st.get("speed", 1.0), repeat=st.get("repeat", 1),
                      random_delay_ms=st.get("random_delay_ms", 0), dry_run=dry,
                      start_delay=start_delay, label=label_text,
                      save_log=self.app.settings.get("save_run_logs", True))

    def toggle_run(self, from_hotkey=False):
        if self.app.job_running_for(self):
            self.app.stop_job()
            return
        if not self.script["steps"]:
            self.app.set_status("Add some steps first.", error=True)
            return
        problems = [m for lvl, m in storage.validate(self.script, self.assets) if lvl == "error"]
        if problems:
            messagebox.showerror("Script has problems", "\n".join(problems), parent=self)
            return
        job = self._runner(self.script, 0 if from_hotkey else 2)
        if job:
            self.app.start_job(job, self, hide=self.v_hide.get())

    def test_step(self):
        i = self._selected()
        if i is None or self.app.job_running():
            return
        one = model.copy_script(self.script)
        step = copy.deepcopy(one["steps"][i])
        w = step.get("wait") or {}
        if w.get("on_timeout") in ("goto", "handler"):
            w["on_timeout"] = "stop"
        for key in ("goto", "else_goto"):
            step.pop(key, None)
        if step["action"] in model.WHILE_ACTIONS or step["action"] in (
                "End While", "Go to Step", "Loop Back", "Call Subroutine", "Return"):
            self.app.set_status("Loops and jumps can only be tested by running the script.", error=True)
            return
        step["repeat"] = 1
        one["steps"] = [step]
        one["settings"] = dict(one["settings"], repeat=1, restart_on_failure=0)
        one["error_handler"] = None
        job = self._runner(one, 1.5, label_text=f"Test step {i + 1}")
        if job:
            job.repeat = 1
            self.app.start_job(job, self)

    def on_job(self, kind, payload):
        if kind == "step":
            self.mark_running(payload)
        elif kind == "done":
            self.mark_running(None)

    def update_state(self, running_mine, running_any, paused):
        text = "Stop" if running_mine else "Start"
        self.btn_start.set_text(text)
        self.btn_start2.set_text(text)
        self.btn_start.set_kind("danger" if running_mine else "primary")
        self.btn_start2.set_kind("danger" if running_mine else "primary")
        can = running_mine or not running_any
        self.btn_start.set_enabled(can)
        self.btn_start2.set_enabled(can)
        self.btn_pause.set_enabled(running_mine)
        self.btn_pause.set_text("Resume" if (running_mine and paused) else "Pause")
        self.btn_stop.set_enabled(running_mine)
