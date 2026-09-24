"""Action Script tab: build, edit and run step lists."""

import copy
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from . import inputs, model, storage, ui, vision
from .runner import Runner
from .storage import AssetStore
from .theme import (C, F, Button, cap, check, combo, entry, frame, label, panel,
                    scrolled_tree, vsep)

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
        self.running_row = None
        self.detail_vars = {}
        self.detail_widgets = []
        self.image_combos = []

        sv = lambda v="": tk.StringVar(value=v)  # noqa: E731
        self.v_x, self.v_y = sv(), sv()
        self.v_action = sv("Left Click")
        self.v_delay, self.v_repeat, self.v_comment = sv("100"), sv("1"), sv()
        self.v_back = tk.BooleanVar(value=False)
        self.v_wait_mode = sv(model.WAIT_LABEL["none"])
        self.v_wait_target = sv()
        self.v_wait_timeout, self.v_wait_poll, self.v_wait_conf = sv("30"), sv("250"), sv("90")
        self.v_on_timeout = sv(model.ON_TIMEOUT_LABEL["stop"])
        self.v_wait_goto, self.v_handler = sv(), sv()
        self.v_script_repeat, self.v_speed, self.v_rand = sv("1"), sv("1.0x"), sv("0")
        self.v_hide = tk.BooleanVar(value=bool(app.settings.get("hide_while_running", False)))

        self._build_toolbar()
        self._build_editor()
        self._build_list()
        self._build_hotkeys()
        self.v_action.trace_add("write", self._on_action_change)
        self.v_wait_mode.trace_add("write", self._on_wait_mode)
        self._on_action_change()
        self._on_wait_mode()
        self.refresh_list()

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
        self._lbl(r, "Comment", LEFT_W).pack(side="left")
        entry(r, self.v_comment, 40).pack(side="left", fill="x", expand=True)

        r = self._row(inner, pady=(4, 0))
        Button(r, "Add", self.add_step, kind="primary").pack(side="left")
        Button(r, "Update", self.update_step).pack(side="left", padx=(6, 0))
        Button(r, "Insert Above", self.insert_step).pack(side="left", padx=(6, 0))
        self.lbl_form_msg = label(r, "", bg=C["panel"], fg=C["err"], font=F.small)
        self.lbl_form_msg.pack(side="left", padx=12)

        # right: wait / timing
        q = panel(row, width=410)
        q.pack(side="left", fill="y", padx=(12, 0))
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
        combo(r, self.v_on_timeout, [m[1] for m in model.ON_TIMEOUT], width=17).pack(side="left")
        self._lbl(r, "Step").pack(side="left", padx=(10, 6))
        self.e_wait_goto = entry(r, self.v_wait_goto, 4, mono=True)
        self.e_wait_goto.pack(side="left")

        r = self._row(inner)
        self._lbl(r, "Error handler", 11).pack(side="left")
        entry(r, self.v_handler, 4, mono=True).pack(side="left")
        label(r, "step for 'Run error handler'", bg=C["panel"], muted=True, font=F.small).pack(side="left", padx=8)

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
        self.lbl_count = label(head, "", bg=C["panel"], muted=True, font=F.small)
        self.lbl_count.pack(side="right")
        cols = [("sr", "Sr", 44, False), ("action", "Action", 150, False), ("x", "X", 70, False),
                ("y", "Y", 70, False), ("back", "Cursor back", 86, False), ("delay", "Delay ms", 76, False),
                ("rep", "Repeat", 60, False), ("cond", "Wait / Condition", 260, True),
                ("note", "Comment", 170, True)]
        box, self.tree = scrolled_tree(p, cols)
        box.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Delete>", lambda e: self.delete_step())

        side = frame(row)
        side.pack(side="left", fill="y", padx=(12, 0))
        self.btn_start2 = Button(side, "Start", self.toggle_run, kind="primary", width=12)
        self.btn_start2.pack(fill="x")
        Button(side, "Test Step", self.test_step, width=12).pack(fill="x", pady=(8, 0))
        frame(side, height=14).pack()
        for text, cmd in (("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1)),
                          ("Duplicate", self.duplicate)):
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
        for idx, (key, text, width, kind) in enumerate(spec):
            if idx % 3 == 0:
                row = self._row(self.details)
                self.detail_widgets.append(row)
                self._lbl(row, text, LEFT_W).pack(side="left")
            else:
                self._lbl(row, text).pack(side="left", padx=(14, 6))
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
                entry(row, var, width, mono=kind in ("int", "region", "color")).pack(side="left")
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
            if w["on_timeout"] == "goto":
                w["goto"] = model.parse_int(self.v_wait_goto.get(), "Timeout step", 1)
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
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _changed(self, select=None):
        self.dirty = True
        self._sync_settings()
        self.refresh_list(select)

    def add_step(self):
        step = self._form_step()
        if step:
            self.script["steps"].append(step)
            self._changed(len(self.script["steps"]) - 1)

    def update_step(self):
        i = self._selected()
        if i is None:
            self.lbl_form_msg.configure(text="Select a step in the list to update.")
            return
        step = self._form_step()
        if step:
            self.script["steps"][i] = step
            self._changed(i)

    def insert_step(self):
        i = self._selected()
        step = self._form_step()
        if not step:
            return
        if i is None:
            i = 0
        self.script["steps"].insert(i, step)
        self._changed(i)

    def add_at_cursor(self):
        x, y = inputs.position()
        self.v_x.set(str(x))
        self.v_y.set(str(y))
        step = self._form_step()
        if step:
            self.script["steps"].append(step)
            self._changed(len(self.script["steps"]) - 1)
            self.app.set_status(f"Added {step['action']} at {x}, {y}")

    def move(self, d):
        i = self._selected()
        steps = self.script["steps"]
        if i is None or not 0 <= i + d < len(steps):
            return
        steps[i], steps[i + d] = steps[i + d], steps[i]
        self._changed(i + d)

    def duplicate(self):
        i = self._selected()
        if i is None:
            return
        self.script["steps"].insert(i + 1, copy.deepcopy(self.script["steps"][i]))
        self._changed(i + 1)

    def delete_step(self):
        i = self._selected()
        if i is None:
            return
        del self.script["steps"][i]
        self._changed(min(i, len(self.script["steps"]) - 1))

    def delete_all(self):
        if not self.script["steps"]:
            return
        if messagebox.askyesno("Delete all", "Remove every step from this script?", parent=self):
            self.script["steps"].clear()
            self._changed()

    def _on_select(self, _e=None):
        i = self._selected()
        if i is not None and i < len(self.script["steps"]):
            self.step_to_form(self.script["steps"][i])

    def refresh_list(self, select=None):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.script["steps"]):
            xt, yt, cond = model.describe_step(s)
            tags = ["odd" if i % 2 else "even"]
            if model.is_screen_step(s):
                tags.append("screen")
            if i == self.running_row:
                tags.append("running")
            back = ("Yes" if s.get("cursor_back") else "No") if s["action"] in model.MOUSE_ACTIONS else ""
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                i + 1, s["action"], xt, yt, back, s.get("delay_ms", 0), s.get("repeat", 1),
                cond, s.get("comment", "")))
        if select is not None and 0 <= select < len(self.script["steps"]):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        n = len(self.script["steps"])
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
        h = self.v_handler.get().strip()
        self.script["error_handler"] = int(h) if h.isdigit() else None

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
        self.running_row = None
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
                      start_delay=start_delay, label=label_text)

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
        step["repeat"] = 1
        one["steps"] = [step]
        one["settings"] = dict(one["settings"], repeat=1)
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
