"""Screen Triggers tab: WHEN / THEN rules that watch the screen."""

import copy
import datetime
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import inputs, model, storage, triggers, ui, vision
from .theme import (C, F, Button, cap, check, combo, entry, frame, label, listbox, panel,
                    scrolled_tree, text_box, px)


class TriggersTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.sel_id = None
        self.thumb = None
        self.outputs = []
        sv = lambda v="": tk.StringVar(value=v)  # noqa: E731
        self.v_name = sv()
        self.v_kind = sv(model.CONDITION_LABEL["image_appears"])
        self.v_image = sv()
        self.v_region = sv()
        self.v_conf = tk.IntVar(value=90)
        self.v_gray = tk.BooleanVar(value=False)
        self.v_px, self.v_py, self.v_color, self.v_tol = sv(), sv(), sv(), sv("12")
        self.v_stable = sv("800")
        self.v_every, self.v_hold = sv("250"), sv("300")
        self.v_cool, self.v_max = sv("5"), sv("0")
        self.v_active = sv(triggers.ACTIVE_LABEL["script"])
        self.v_pause = tk.BooleanVar(value=True)
        self._build()
        self.v_kind.trace_add("write", self._on_kind)
        self.v_image.trace_add("write", lambda *_: self._show_thumb())
        self.refresh_rules()
        rules = self.app.rules
        if rules:
            self.select_rule(rules[0]["id"])
        else:
            self._set_editor_enabled(False)

    # ------------------------------------------------------------ layout

    def _build(self):
        bar = frame(self)
        bar.pack(fill="x", padx=14, pady=(12, 10))
        self.btn_monitor = Button(bar, "Monitoring off", self.app.toggle_monitoring)
        self.btn_monitor.pack(side="left")
        tk.Frame(bar, bg=C["field_bd"], width=1, height=22).pack(side="left", padx=12)
        for text, cmd in (("New Rule", self.new_rule), ("Duplicate", self.duplicate),
                          ("Delete", self.delete), ("Import", self.import_rules), ("Export", self.export_rules)):
            Button(bar, text, cmd).pack(side="left", padx=(0, 6))
        self.lbl_info = label(bar, "", muted=True)
        self.lbl_info.pack(side="right")

        body = frame(self)
        body.pack(fill="both", expand=True, padx=14)

        # rules list
        left = panel(body, width=px(320))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        head = frame(left, bg=C["panel"])
        head.pack(fill="x", padx=12, pady=(10, 8))
        cap(head, "Rules", bg=C["panel"]).pack(side="left")
        label(head, "click the dot to enable", bg=C["panel"], muted=True, font=F.small).pack(side="right")
        box, self.tree = scrolled_tree(left, [("on", "On", 44, False), ("name", "Rule", 240, True)])
        box.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        self.tree.configure(show="tree")
        self.tree.column("#0", width=0, stretch=False)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.tag_configure("off", foreground=C["dim"])
        self.lbl_summary = label(left, "", bg=C["panel"], muted=True, font=F.small, wraplength=290,
                                 justify="left", anchor="w")
        self.lbl_summary.pack(fill="x", padx=12, pady=10)

        # editor
        ed = panel(body)
        ed.pack(side="left", fill="both", expand=True, padx=(12, 0))
        inner = frame(ed, bg=C["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        self.editor = inner

        r = self._row(inner)
        label(r, "Rule name", bg=C["panel"], font=F.bold, width=12, anchor="w").pack(side="left")
        entry(r, self.v_name, 40).pack(side="left", fill="x", expand=True)

        when = self._section(inner, "WHEN", "this is true on screen")
        r = self._row(when)
        self._lbl(r, "Condition").pack(side="left")
        combo(r, self.v_kind, [k[1] for k in model.CONDITION_KINDS], width=24).pack(side="left")
        self.cond_body = frame(when, bg=C["panel_alt"])
        self.cond_body.pack(fill="x")

        # image block
        self.img_block = frame(self.cond_body, bg=C["panel_alt"])
        top = frame(self.img_block, bg=C["panel_alt"])
        top.pack(fill="x")
        fields = frame(top, bg=C["panel_alt"])
        fields.pack(side="left", fill="x", expand=True)
        r = self._row(fields)
        self._lbl(r, "Image").pack(side="left")
        self.cb_image = combo(r, self.v_image, self.app.trigger_assets.names(), width=22, editable=True)
        self.cb_image.pack(side="left")
        r = self._row(fields)
        self._lbl(r, "Match").pack(side="left")
        ttk.Scale(r, from_=50, to=100, variable=self.v_conf, orient="horizontal", length=150,
                  command=lambda v: self.lbl_conf.configure(text=f"{int(float(v))}%")).pack(side="left")
        self.lbl_conf = self._lbl(r, "90%")
        self.lbl_conf.configure(width=5)
        self.lbl_conf.pack(side="left", padx=6)
        check(r, "Grayscale", self.v_gray, bg=C["panel_alt"]).pack(side="left", padx=(8, 0))
        tb = frame(top, bg=C["panel_alt"])
        tb.pack(side="left", padx=(12, 0))
        self.thumb_lbl = tk.Label(tb, text="No image yet", bg=C["badge"], fg=C["teal"], width=24, height=4,
                                  font=F.small, highlightthickness=1, highlightbackground=C["thumb_bd"])
        self.thumb_lbl.pack()
        bb = frame(tb, bg=C["panel_alt"])
        bb.pack(fill="x", pady=(6, 0))
        Button(bb, "Capture", self.capture_image, small=True).pack(side="left")
        Button(bb, "Load file", self.load_image, small=True).pack(side="left", padx=(6, 0))

        # pixel block
        self.px_block = frame(self.cond_body, bg=C["panel_alt"])
        r = self._row(self.px_block)
        self._lbl(r, "Pixel X").pack(side="left")
        entry(r, self.v_px, 6, mono=True).pack(side="left")
        label(r, "Y", bg=C["panel_alt"]).pack(side="left", padx=(10, 6))
        entry(r, self.v_py, 6, mono=True).pack(side="left")
        self.lbl_color = label(r, "Color", bg=C["panel_alt"])
        self.lbl_color.pack(side="left", padx=(14, 6))
        self.e_color = entry(r, self.v_color, 9, mono=True)
        self.e_color.pack(side="left")
        label(r, "Tolerance", bg=C["panel_alt"]).pack(side="left", padx=(14, 6))
        entry(r, self.v_tol, 4, mono=True).pack(side="left")
        Button(r, "Grab", self.grab_pixel, small=True).pack(side="left", padx=(10, 0))

        # stable block
        self.stable_block = frame(self.cond_body, bg=C["panel_alt"])
        r = self._row(self.stable_block)
        self._lbl(r, "Still for ms").pack(side="left")
        entry(r, self.v_stable, 6, mono=True).pack(side="left")

        # region + timing (always)
        self.region_row = self._row(self.cond_body)
        self._lbl(self.region_row, "Search region").pack(side="left")
        entry(self.region_row, self.v_region, 20, mono=True).pack(side="left")
        Button(self.region_row, "Draw on screen", self.draw_region, small=True).pack(side="left", padx=(8, 0))
        label(self.region_row, "blank = whole screen", bg=C["panel_alt"], muted=True, font=F.small).pack(side="left", padx=8)
        self.timing_row = self._row(self.cond_body)
        self._lbl(self.timing_row, "Check every").pack(side="left")
        entry(self.timing_row, self.v_every, 6, mono=True).pack(side="left")
        label(self.timing_row, "ms", bg=C["panel_alt"], muted=True).pack(side="left", padx=(4, 16))
        label(self.timing_row, "Must stay true for", bg=C["panel_alt"]).pack(side="left", padx=(0, 6))
        entry(self.timing_row, self.v_hold, 6, mono=True).pack(side="left")
        label(self.timing_row, "ms", bg=C["panel_alt"], muted=True).pack(side="left", padx=4)

        then = self._section(inner, "THEN", "do these in order")
        lf = frame(then, bg=C["panel_alt"])
        lf.pack(fill="x")
        self.lb_out = listbox(lf, height=5)
        self.lb_out.pack(side="left", fill="x", expand=True)
        self.lb_out.bind("<Double-Button-1>", lambda e: self.edit_output())
        ob = frame(lf, bg=C["panel_alt"])
        ob.pack(side="left", padx=(10, 0), anchor="n")
        for text, cmd in (("Add", self.add_output), ("Edit", self.edit_output), ("Remove", self.remove_output),
                          ("Up", lambda: self.move_output(-1)), ("Down", lambda: self.move_output(1))):
            Button(ob, text, cmd, small=True, width=8).pack(fill="x", pady=(0, 4))

        opt = frame(inner, bg=C["panel"])
        opt.pack(fill="x", pady=(12, 0))
        r = self._row(opt, bg=C["panel"])
        label(r, "Cooldown", bg=C["panel"], width=12, anchor="w").pack(side="left")
        entry(r, self.v_cool, 5, mono=True).pack(side="left")
        label(r, "s", bg=C["panel"], muted=True).pack(side="left", padx=(4, 20))
        label(r, "Max fires per run", bg=C["panel"]).pack(side="left", padx=(0, 6))
        entry(r, self.v_max, 5, mono=True).pack(side="left")
        label(r, "0 = unlimited", bg=C["panel"], muted=True, font=F.small).pack(side="left", padx=6)
        r = self._row(opt, bg=C["panel"])
        label(r, "Active", bg=C["panel"], width=12, anchor="w").pack(side="left")
        combo(r, self.v_active, [a[1] for a in triggers.ACTIVE_MODES], width=24).pack(side="left")
        check(r, "Pause the running script while this fires", self.v_pause, bg=C["panel"]).pack(side="left", padx=16)

        btns = frame(inner, bg=C["panel"])
        btns.pack(fill="x", side="bottom", pady=(10, 0))
        Button(btns, "Save rule", self.save_rule, kind="primary").pack(side="right")
        Button(btns, "Show match on screen", lambda: self.test(True)).pack(side="right", padx=(0, 6))
        Button(btns, "Test condition now", lambda: self.test(False)).pack(side="right", padx=(0, 6))
        self.lbl_msg = label(btns, "", bg=C["panel"], font=F.small)
        self.lbl_msg.pack(side="left")

        # log
        lp = panel(self, height=150)
        lp.pack(fill="x", padx=14, pady=12)
        lp.pack_propagate(False)
        head = frame(lp, bg=C["panel"])
        head.pack(fill="x", padx=12, pady=(8, 4))
        cap(head, "Monitor log", bg=C["panel"]).pack(side="left")
        Button(head, "Clear", self.clear_log, small=True).pack(side="right")
        self.log_box = text_box(lp, height=6)
        self.log_box.configure(bg=C["panel"], highlightthickness=0, bd=8, font=F.mono, wrap="none")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_configure("time", foreground=C["dim"])
        self.log_box.tag_configure("rule", foreground=C["text"])
        self.log_box.tag_configure("hit", foreground=C["teal"])
        self.log_box.tag_configure("plain", foreground=C["muted"])
        self.log_box.configure(state="disabled")
        self._on_kind()

    def _section(self, parent, word, sub):
        box = tk.Frame(parent, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["line"])
        box.pack(fill="x", pady=(12, 0))
        inner = frame(box, bg=C["panel_alt"])
        inner.pack(fill="x", padx=12, pady=10)
        h = frame(inner, bg=C["panel_alt"])
        h.pack(fill="x", pady=(0, 8))
        label(h, word, bg=C["panel_alt"], fg=C["teal"], font=F.bold).pack(side="left")
        label(h, sub, bg=C["panel_alt"], muted=True).pack(side="left", padx=8)
        return inner

    def _row(self, parent, bg=None):
        r = frame(parent, bg=bg or C["panel_alt"])
        r.pack(fill="x", pady=(0, 8))
        return r

    def _lbl(self, parent, text):
        return label(parent, text, bg=C["panel_alt"], width=12, anchor="w")

    def _on_kind(self, *_):
        kind = model.CONDITION_ID.get(self.v_kind.get(), "image_appears")
        for b in (self.img_block, self.px_block, self.stable_block, self.region_row, self.timing_row):
            b.pack_forget()
        if kind.startswith("image"):
            self.img_block.pack(fill="x")
            self.region_row.pack(fill="x", pady=(0, 8))
        elif kind.startswith("pixel"):
            self.px_block.pack(fill="x")
            state = "normal" if kind == "pixel_is" else "disabled"
            self.e_color.configure(state=state)
        else:
            if kind == "region_stable":
                self.stable_block.pack(fill="x")
            self.region_row.pack(fill="x", pady=(0, 8))
        self.timing_row.pack(fill="x", pady=(0, 8))

    def _set_editor_enabled(self, on):
        self.lbl_msg.configure(text="" if on else "Fill in the rule and click Save rule to create it.",
                               fg=C["muted"])

    # ------------------------------------------------------------ list

    def refresh_rules(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.app.rules):
            tags = ["odd" if i % 2 else "even"]
            if not r.get("enabled"):
                tags.append("off")
            self.tree.insert("", "end", iid=r["id"], tags=tags,
                             values=("\u25cf" if r.get("enabled") else "\u25cb", r.get("name") or "Rule"))
        if self.sel_id and self.tree.exists(self.sel_id):
            self.tree.selection_set(self.sel_id)
        self.update_info()

    def update_info(self):
        n = sum(1 for r in self.app.rules if r.get("enabled"))
        self.lbl_info.configure(text=f"{n} of {len(self.app.rules)} rules enabled")
        r = self._rule(self.sel_id)
        self.lbl_summary.configure(text=triggers.describe_rule(r) if r else "")

    def _rule(self, rid):
        return next((r for r in self.app.rules if r["id"] == rid), None)

    def _on_click(self, e):
        if self.tree.identify_region(e.x, e.y) != "cell" or self.tree.identify_column(e.x) != "#1":
            return
        rid = self.tree.identify_row(e.y)
        r = self._rule(rid)
        if r:
            new = dict(r, enabled=not r.get("enabled"))
            self.app.replace_rule(new)
            self.refresh_rules()

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if sel and sel[0] != self.sel_id:
            self.select_rule(sel[0])

    def select_rule(self, rid):
        r = self._rule(rid)
        if not r:
            return
        self.sel_id = rid
        if self.tree.exists(rid) and self.tree.selection() != (rid,):
            self.tree.selection_set(rid)
        c = r.get("condition") or {}
        self.v_name.set(r.get("name", ""))
        self.v_kind.set(model.CONDITION_LABEL.get(c.get("kind"), model.CONDITION_KINDS[0][1]))
        self.v_image.set(c.get("image") or "")
        self.v_region.set(model.format_region(c.get("region")))
        conf = int(round(float(c.get("confidence") or 0.9) * 100))
        self.v_conf.set(conf)
        self.lbl_conf.configure(text=f"{conf}%")
        self.v_gray.set(bool(c.get("grayscale")))
        self.v_px.set("" if c.get("x") is None else str(c.get("x")))
        self.v_py.set("" if c.get("y") is None else str(c.get("y")))
        self.v_color.set(c.get("color") or "")
        self.v_tol.set(str(c.get("tolerance", 12)))
        self.v_stable.set(str(c.get("stable_ms", 800)))
        self.v_every.set(str(r.get("check_ms", 250)))
        self.v_hold.set(str(r.get("hold_ms", 300)))
        self.v_cool.set(str(r.get("cooldown_s", 5)))
        self.v_max.set(str(r.get("max_fires", 0)))
        self.v_active.set(triggers.ACTIVE_LABEL.get(r.get("active", "script")))
        self.v_pause.set(bool(r.get("pause_script", True)))
        self.outputs = copy.deepcopy(r.get("outputs") or [])
        self._refresh_outputs()
        self._show_thumb()
        self._set_editor_enabled(True)
        self.update_info()

    def _show_thumb(self):
        img = self.app.trigger_assets.get(self.v_image.get()) if self.v_image.get().strip() else None
        if img is None:
            self.thumb = None
            self.thumb_lbl.configure(image="", text="No image yet", width=24, height=4)
            return
        self.thumb = ui.thumbnail(img, 190, 80)
        self.thumb_lbl.configure(image=self.thumb, text="", width=190, height=80)

    def _refresh_outputs(self):
        self.lb_out.delete(0, "end")
        for i, o in enumerate(self.outputs, 1):
            self.lb_out.insert("end", f"  {i}.  {triggers.describe_output(o)}")

    # ------------------------------------------------------------ editing

    def form_to_rule(self):
        base = self._rule(self.sel_id) or triggers.new_rule()
        kind = model.CONDITION_ID.get(self.v_kind.get(), "image_appears")
        c = {"kind": kind, "image": model.image_name(self.v_image.get()),
             "region": model.parse_region(self.v_region.get(), "Search region"),
             "confidence": int(self.v_conf.get()) / 100.0, "grayscale": bool(self.v_gray.get()),
             "x": model.parse_int(self.v_px.get(), "Pixel X", allow_blank=True),
             "y": model.parse_int(self.v_py.get(), "Pixel Y", allow_blank=True),
             "color": model.parse_color(self.v_color.get()) if self.v_color.get().strip() else "",
             "tolerance": model.parse_int(self.v_tol.get() or "12", "Tolerance", 0, 255),
             "stable_ms": model.parse_int(self.v_stable.get() or "800", "Still for", 50)}
        rule = dict(base)
        rule.update({
            "name": self.v_name.get().strip() or "Rule",
            "condition": c,
            "check_ms": model.parse_int(self.v_every.get(), "Check every", 50),
            "hold_ms": model.parse_int(self.v_hold.get() or "0", "Must stay true", 0),
            "outputs": copy.deepcopy(self.outputs),
            "cooldown_s": model.parse_int(self.v_cool.get() or "0", "Cooldown", 0),
            "max_fires": model.parse_int(self.v_max.get() or "0", "Max fires", 0),
            "active": triggers.ACTIVE_ID.get(self.v_active.get(), "script"),
            "pause_script": bool(self.v_pause.get()),
        })
        err = triggers.check_rule(rule, self.app.trigger_assets)
        if err:
            raise ValueError(err)
        return rule

    def save_rule(self):
        try:
            rule = self.form_to_rule()
        except ValueError as e:
            self.lbl_msg.configure(text=str(e), fg=C["err"])
            return None
        is_new = self._rule(rule["id"]) is None
        self.app.replace_rule(rule)
        self.sel_id = rule["id"]
        self.refresh_rules()
        tip = ""
        if not self.app.triggers.running:
            tip = " Turn Monitoring on to use it."
        if rule.get("active") == "script" and not self.app.job_running():
            tip += " It only runs while a script is running (see Active)."
        self.lbl_msg.configure(text=("Rule created." if is_new else "Saved.") + tip, fg=C["teal"])
        return rule

    def new_rule(self):
        r = triggers.new_rule(f"Rule {len(self.app.rules) + 1}")
        self.app.rules.append(r)
        self.app.save_rules()
        self.sel_id = None
        self.refresh_rules()
        self.select_rule(r["id"])

    def duplicate(self):
        r = self._rule(self.sel_id)
        if not r:
            return
        new = copy.deepcopy(r)
        new["id"] = triggers.new_rule()["id"]
        new["name"] = (r.get("name") or "Rule") + " copy"
        self.app.rules.insert(self.app.rules.index(r) + 1, new)
        self.app.save_rules()
        self.refresh_rules()
        self.select_rule(new["id"])

    def delete(self):
        r = self._rule(self.sel_id)
        if not r or not messagebox.askyesno("Delete rule", f"Delete '{r.get('name')}'?", parent=self):
            return
        idx = self.app.rules.index(r)
        self.app.rules.remove(r)
        self.app.save_rules()
        self.sel_id = None
        self.refresh_rules()
        if self.app.rules:
            self.select_rule(self.app.rules[min(idx, len(self.app.rules) - 1)]["id"])
        else:
            self.outputs = []
            self._refresh_outputs()
            self._set_editor_enabled(False)

    def add_output(self):
        o = ui.edit_output(self.app.root, toast=self.app.toast)
        if o:
            self.outputs.append(o)
            self._refresh_outputs()

    def _out_index(self):
        sel = self.lb_out.curselection()
        return sel[0] if sel else None

    def edit_output(self):
        i = self._out_index()
        if i is None:
            return
        o = ui.edit_output(self.app.root, self.outputs[i], toast=self.app.toast)
        if o:
            self.outputs[i] = o
            self._refresh_outputs()
            self.lb_out.selection_set(i)

    def remove_output(self):
        i = self._out_index()
        if i is not None:
            del self.outputs[i]
            self._refresh_outputs()

    def move_output(self, d):
        i = self._out_index()
        if i is None or not 0 <= i + d < len(self.outputs):
            return
        self.outputs[i], self.outputs[i + d] = self.outputs[i + d], self.outputs[i]
        self._refresh_outputs()
        self.lb_out.selection_set(i + d)

    def capture_image(self):
        def done(region, img):
            if img is None:
                return
            base = self.v_name.get() or "trigger"
            name = ui.ask_string(self.app.root, "Name this image", "Image name", base.lower().replace(" ", "_"))
            if name is None:
                return
            name = self.app.trigger_assets.add_image(img, name or "trigger")
            self.cb_image.configure(values=self.app.trigger_assets.names())
            self.v_image.set(name)
            if not self.v_region.get().strip():
                pad = 150
                x, y, w, h = region
                self.v_region.set(model.format_region([x - pad, y - pad, w + pad * 2, h + pad * 2]))
            self.lbl_msg.configure(text="Captured. Search region set around it; clear it to search everywhere.",
                                   fg=C["muted"])
        ui.select_region(self.app.root, done, "Drag around the image this rule should look for. Esc cancels.")

    def load_image(self):
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
        name = self.app.trigger_assets.add_image(img, os.path.splitext(os.path.basename(path))[0])
        self.cb_image.configure(values=self.app.trigger_assets.names())
        self.v_image.set(name)

    def draw_region(self):
        def done(region, _img):
            if region:
                self.v_region.set(model.format_region(region))
        ui.select_region(self.app.root, done, "Drag the area this rule should watch. Esc cancels.")

    def grab_pixel(self):
        def done():
            x, y = inputs.position()
            self.v_px.set(str(x))
            self.v_py.set(str(y))
            self.v_color.set(vision.rgb_hex(vision.pixel(x, y)))
        ui.countdown(self.app.root, self.app.toast, 3, "Grabbing pixel", done)

    def test(self, show):
        try:
            rule = self.form_to_rule()
        except ValueError as e:
            self.lbl_msg.configure(text=str(e), fg=C["err"])
            return
        try:
            ok, match = self.app.triggers.test_rule(rule)
        except Exception as e:
            self.lbl_msg.configure(text=f"Check failed: {e}", fg=C["err"])
            return
        detail = ""
        if match and rule["condition"]["kind"].startswith("image"):
            detail = f" at {match.center[0]}, {match.center[1]} ({int(match.score * 100)}%)"
        self.lbl_msg.configure(text=("Condition is TRUE" if ok else "Condition is false") + detail,
                               fg=C["teal"] if ok else C["warn"])
        if show and match:
            ui.flash(self.app.root, match.rect, ms=1500)
        elif show and not match and rule["condition"].get("region"):
            ui.flash(self.app.root, rule["condition"]["region"], ms=1500, color=C["warn"])

    # ------------------------------------------------------------ import / export

    def export_rules(self):
        if not self.app.rules:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export rules", defaultextension=".clktrig",
                                            filetypes=[("Trigger rules", "*.clktrig")])
        if path:
            try:
                storage.save_triggers(path, self.app.rules, self.app.trigger_assets)
                self.app.set_status(f"Exported {len(self.app.rules)} rules")
            except Exception as e:
                messagebox.showerror("Could not export", str(e), parent=self)

    def import_rules(self):
        path = filedialog.askopenfilename(parent=self, title="Import rules",
                                          filetypes=[("Trigger rules", "*.clktrig")])
        if not path:
            return
        try:
            rules, assets = storage.load_triggers(path)
        except Exception as e:
            messagebox.showerror("Could not import", str(e), parent=self)
            return
        rename = {}
        for name in assets.names():
            new = self.app.trigger_assets.unique_name(name) if self.app.trigger_assets.has(name) else name
            self.app.trigger_assets.put_image(new, assets.get(name))
            rename[name] = new
        for r in rules:
            base = triggers.new_rule()
            base.update(r)
            base["id"] = triggers.new_rule()["id"]
            base["enabled"] = False
            img = model.image_name(base["condition"].get("image"))
            if img in rename:
                base["condition"]["image"] = rename[img]
            self.app.rules.append(base)
        self.app.save_rules()
        self.cb_image.configure(values=self.app.trigger_assets.names())
        self.refresh_rules()
        self.app.set_status(f"Imported {len(rules)} rules (turned off until you enable them)")

    # ------------------------------------------------------------ log / state

    def add_log(self, rule, message, hit):
        box = self.log_box
        box.configure(state="normal")
        stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        box.insert("1.0", "\n")
        box.insert("1.0", message, "hit" if hit else "plain")
        box.insert("1.0", f"{str(rule)[:28]:<30}", "rule")
        box.insert("1.0", f"{stamp}  ", "time")
        lines = int(box.index("end-1c").split(".")[0])
        if lines > 400:
            box.delete("400.0", "end")
        box.configure(state="disabled")

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def update_state(self, running_mine, running_any, paused):
        on = self.app.triggers.running
        self.btn_monitor.set_text("Monitoring on" if on else "Monitoring off")
        self.btn_monitor.set_kind("primary" if on else "normal")
        self.update_info()

    def title_text(self):
        return "Screen triggers"
