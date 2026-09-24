"""Import Script tab: open a package Claude wrote, check it, dry run, run."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

from . import model, storage, ui
from .runner import Runner
from .storage import AssetStore
from .theme import (C, F, Button, cap, check, combo, dot, entry, frame, label, panel,
                    scrolled_tree)


class ImportTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.script = None
        self.assets = AssetStore()
        self.path = None
        self.input_vars = {}
        self.thumbs = []
        self.pending_real = False
        self.v_recent = tk.StringVar()
        self.v_ask = tk.BooleanVar(value=True)
        self.v_dry_first = tk.BooleanVar(value=True)
        self._build()
        self._show_empty()

    # ------------------------------------------------------------ layout

    def _build(self):
        bar = frame(self)
        bar.pack(fill="x", padx=14, pady=(12, 10))
        Button(bar, "Open package", self.open, kind="primary").pack(side="left")
        Button(bar, "Paste script text", self.paste).pack(side="left", padx=(6, 0))
        self.cb_recent = combo(bar, self.v_recent, [], width=34)
        self.cb_recent.pack(side="left", padx=(12, 0))
        self.cb_recent.bind("<<ComboboxSelected>>", self._open_recent)
        label(bar, "Accepts .clkpkg / .clk (script plus images) or .json", muted=True).pack(side="right")

        body = frame(self)
        body.pack(fill="both", expand=True, padx=14)

        head = panel(body)
        head.pack(fill="x")
        hi = frame(head, bg=C["panel"])
        hi.pack(fill="x", padx=16, pady=14)
        icon = tk.Canvas(hi, width=44, height=44, bg=C["panel"], highlightthickness=0)
        icon.create_rectangle(0, 0, 43, 43, fill=C["badge"], outline=C["badge"])
        icon.create_polygon(15, 11, 25, 11, 31, 17, 31, 33, 15, 33, outline=C["accent"], fill="", width=2)
        icon.create_line(19, 23, 27, 23, fill=C["accent"], width=2)
        icon.create_line(19, 27, 25, 27, fill=C["accent"], width=2)
        icon.pack(side="left", padx=(0, 14))
        txt = frame(hi, bg=C["panel"])
        txt.pack(side="left", fill="x", expand=True)
        line = frame(txt, bg=C["panel"])
        line.pack(fill="x")
        self.lbl_name = label(line, "", bg=C["panel"], font=F.title)
        self.lbl_name.pack(side="left")
        self.lbl_desc = label(line, "", bg=C["panel"], muted=True)
        self.lbl_desc.pack(side="left", padx=10)
        self.chips = frame(txt, bg=C["panel"])
        self.chips.pack(fill="x", pady=(6, 0))

        mid = frame(body)
        mid.pack(fill="both", expand=True, pady=12)
        sp = panel(mid)
        sp.pack(side="left", fill="both", expand=True)
        h = frame(sp, bg=C["panel"])
        h.pack(fill="x", padx=12, pady=(10, 8))
        cap(h, "Steps preview", bg=C["panel"]).pack(side="left")
        label(h, "teal steps wait on the screen instead of a fixed time", bg=C["panel"], muted=True,
              font=F.small).pack(side="right")
        box, self.tree = scrolled_tree(sp, [("n", "#", 44, False), ("step", "Step", 190, False),
                                            ("waits", "Waits for", 300, True), ("timeout", "Timeout", 90, False)])
        box.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        side = frame(mid, width=340)
        side.pack(side="left", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        ip = panel(side)
        ip.pack(fill="x")
        self.inputs_box = frame(ip, bg=C["panel"])
        self.inputs_box.pack(fill="x", padx=14, pady=12)
        tp = panel(side)
        tp.pack(fill="x", pady=12)
        ti = frame(tp, bg=C["panel"])
        ti.pack(fill="x", padx=14, pady=12)
        th = frame(ti, bg=C["panel"])
        th.pack(fill="x", pady=(0, 8))
        cap(th, "Image templates", bg=C["panel"]).pack(side="left")
        Button(th, "Recapture", self.recapture, small=True).pack(side="right")
        self.thumb_grid = frame(ti, bg=C["panel"])
        self.thumb_grid.pack(fill="x")
        self.lbl_more = label(ti, "", bg=C["panel"], muted=True, font=F.small, wraplength=300, justify="left")
        self.lbl_more.pack(anchor="w", pady=(6, 0))
        cp = panel(side)
        cp.pack(fill="both", expand=True)
        ci = frame(cp, bg=C["panel"])
        ci.pack(fill="both", expand=True, padx=14, pady=12)
        cap(ci, "Checks", bg=C["panel"]).pack(anchor="w", pady=(0, 8))
        self.checks_box = frame(ci, bg=C["panel"])
        self.checks_box.pack(fill="both", expand=True)

        foot = frame(self)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        check(foot, "Dry run first: find each target and highlight it without clicking",
              self.v_dry_first).pack(side="left")
        self.btn_run = Button(foot, "Run", self.run_real, kind="primary")
        self.btn_run.pack(side="right")
        self.btn_dry = Button(foot, "Dry Run", self.run_dry)
        self.btn_dry.pack(side="right", padx=(0, 6))
        self.btn_open = Button(foot, "Open in Action Script", self.to_actions)
        self.btn_open.pack(side="right", padx=(0, 6))
        Button(foot, "Clear", self.clear).pack(side="right", padx=(0, 6))

    def _chip(self, text, good=None):
        bg = C["badge"] if good else ("#2d2412" if good is False else C["line"])
        fg = C["teal"] if good else (C["warn"] if good is False else "#c9cdd2")
        label(self.chips, f"  {text}  ", bg=bg, fg=fg, font=F.small, pady=3).pack(side="left", padx=(0, 6))

    def _clear(self, w):
        for c in w.winfo_children():
            c.destroy()

    def _show_empty(self):
        self.lbl_name.configure(text="No script loaded")
        self.lbl_desc.configure(text="Open a package from Claude, or paste the script text.")
        self._clear(self.chips)
        self.tree.delete(*self.tree.get_children())
        self._clear(self.inputs_box)
        cap(self.inputs_box, "Inputs to fill", bg=C["panel"]).pack(anchor="w")
        label(self.inputs_box, "None", bg=C["panel"], muted=True).pack(anchor="w", pady=(6, 0))
        self._clear(self.thumb_grid)
        self.lbl_more.configure(text="")
        self._clear(self.checks_box)
        self.cb_recent.configure(values=self._recent_labels())

    def _recent_labels(self):
        return [p for p in self.app.settings.get("recent", []) if os.path.exists(p)]

    # ------------------------------------------------------------ loading

    def open(self):
        path = filedialog.askopenfilename(parent=self, title="Open script package",
                                          filetypes=[("Clicker packages", "*.clkpkg *.clk *.json"),
                                                     ("All files", "*.*")])
        if path:
            self.load_path(path)

    def _open_recent(self, _e=None):
        p = self.v_recent.get()
        if p:
            self.load_path(p)

    def load_path(self, path):
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            messagebox.showerror("Could not open package", str(e), parent=self)
            return
        storage.add_recent(self.app.settings, path)
        self.app.save_settings()
        self.show(script, assets, path)

    def paste(self):
        text = ui.ask_text(self.app.root, "Paste script",
                           "Paste the script JSON Claude gave you. Images can be added afterwards with Recapture.")
        if not text or not text.strip():
            return
        try:
            script = storage.parse_script_text(text)
        except Exception as e:
            messagebox.showerror("Could not read script", str(e), parent=self)
            return
        self.show(script, AssetStore(), None)

    def show(self, script, assets, path):
        self.script, self.assets, self.path = script, assets, path
        name = script.get("name") or (os.path.splitext(os.path.basename(path))[0] if path else "Pasted script")
        self.lbl_name.configure(text=os.path.basename(path) if path else name)
        self.lbl_desc.configure(text=script.get("description") or name)
        self.refresh()
        self.cb_recent.configure(values=self._recent_labels())

    def refresh(self):
        s, a = self.script, self.assets
        self._clear(self.chips)
        refs = model.referenced_images(s)
        self._chip(f"{len(s['steps'])} steps")
        self._chip(f"{len(refs)} image templates")
        self._chip(f"{len(s.get('inputs') or [])} inputs to fill")
        scr = s.get("screen")
        if scr:
            try:
                same = storage.screen_matches(s)
            except Exception:
                same = None
            txt = f"Built for {scr.get('width')} x {scr.get('height')} at {scr.get('scale', 100)}%"
            self._chip(txt + (", matches this screen" if same else ", differs from this screen"), bool(same))

        self.tree.delete(*self.tree.get_children())
        for i, st in enumerate(s["steps"]):
            lbl, waits, timeout = model.describe_for_import(st)
            tags = ["odd" if i % 2 else "even"]
            if model.is_screen_step(st):
                tags.append("screen")
            if model.check_step(st, len(s["steps"])):
                tags.append("error")
            self.tree.insert("", "end", iid=str(i), tags=tags, values=(i + 1, lbl, waits, timeout))

        self._clear(self.inputs_box)
        cap(self.inputs_box, "Inputs to fill", bg=C["panel"]).pack(anchor="w", pady=(0, 6))
        old = {k: v.get() for k, v in self.input_vars.items()}
        self.input_vars = {}
        if not s.get("inputs"):
            label(self.inputs_box, "None", bg=C["panel"], muted=True).pack(anchor="w")
        for item in s.get("inputs") or []:
            label(self.inputs_box, item.get("label") or item["name"], bg=C["panel"], font=F.small).pack(anchor="w")
            v = tk.StringVar(value=old.get(item["name"], self.app.last_inputs.get(item["name"], item.get("default", ""))))
            entry(self.inputs_box, v, 30).pack(fill="x", pady=(2, 8))
            self.input_vars[item["name"]] = v
        if s.get("inputs"):
            check(self.inputs_box, "Ask me for these each run", self.v_ask, bg=C["panel"]).pack(anchor="w")

        self._clear(self.thumb_grid)
        self.thumbs = []
        for col in range(2):
            self.thumb_grid.columnconfigure(col, weight=1, uniform="th")
        shown = 0
        for name in refs:
            if shown >= 4:
                break
            img = a.get(name)
            cell = frame(self.thumb_grid, bg=C["panel"])
            cell.grid(row=shown // 2, column=shown % 2, sticky="nsew", padx=3, pady=3)
            if img is not None:
                ph = ui.thumbnail(img, 140, 54)
                self.thumbs.append(ph)
                tk.Label(cell, image=ph, bg=C["badge"], height=58, highlightthickness=1,
                         highlightbackground="#2c5b54").pack(fill="x")
            else:
                tk.Label(cell, text="missing", bg="#2a1414", fg=C["err"], height=3, font=F.small,
                         highlightthickness=1, highlightbackground="#5b2c2c").pack(fill="x")
            label(cell, model.image_stem(name), bg=C["panel"], muted=True, font=F.small).pack(anchor="w")
            shown += 1
        extra = len(refs) - shown
        self.lbl_more.configure(text=(f"+{extra} more. " if extra > 0 else "")
                                + ("Recapture any template that does not match your screen." if refs else
                                   "This script uses no images."))

        self._clear(self.checks_box)
        colors = {"ok": C["ok"], "warn": C["warn"], "error": C["err"]}
        for lvl, msg in storage.validate(s, a):
            row = frame(self.checks_box, bg=C["panel"])
            row.pack(fill="x", pady=2)
            dot(row, colors[lvl], bg=C["panel"]).pack(side="left", padx=(0, 8), pady=5, anchor="n")
            label(row, msg, bg=C["panel"], wraplength=270, justify="left", anchor="w").pack(side="left", fill="x")
        self.app.refresh_states()

    def clear(self):
        if self.app.job_running_for(self):
            return
        self.script, self.assets, self.path = None, AssetStore(), None
        self.input_vars = {}
        self._show_empty()
        self.app.refresh_states()

    def recapture(self):
        if not self.script:
            return
        refs = model.referenced_images(self.script)
        if not refs:
            return
        missing = [n for n in refs if not self.assets.has(n)]
        choice = ui.ask_choice(self.app.root, "Recapture template", "Which image do you want to capture again?",
                               missing + [n for n in refs if n not in missing])
        if not choice:
            return

        def done(region, img):
            if img is None:
                return
            self.assets.put_image(choice, img)
            self.refresh()
            self.app.set_status(f"Recaptured {choice}")
        ui.select_region(self.app.root, done, f"Drag around '{model.image_stem(choice)}'. Esc cancels.")

    def to_actions(self):
        if not self.script:
            return
        tab = self.app.action_tab
        if self.app.job_running_for(tab) or not tab.confirm_discard():
            return
        tab.set_script(self.script, self.assets.copy(), None)
        self.app.show_tab("actions")

    # ------------------------------------------------------------ running

    def _ready(self):
        if not self.script or self.app.job_running():
            return False
        errors = [m for lvl, m in storage.validate(self.script, self.assets) if lvl == "error"]
        if errors:
            messagebox.showerror("Fix these first", "\n".join(errors), parent=self)
            return False
        return True

    def _values(self):
        values = {k: v.get() for k, v in self.input_vars.items()}
        if self.script.get("inputs") and self.v_ask.get():
            values = ui.ask_inputs(self.app.root, self.script["inputs"], values)
            if values is None:
                return None
            for k, v in values.items():
                if k in self.input_vars:
                    self.input_vars[k].set(v)
        self.app.last_inputs.update(values)
        return values

    def _start(self, dry, values):
        st = self.script.get("settings") or {}
        job = Runner(self.script, self.assets, self.app.emitter("script"), inputs_map=values,
                     speed=st.get("speed", 1.0), repeat=1 if dry else st.get("repeat", 1),
                     random_delay_ms=st.get("random_delay_ms", 0), dry_run=dry, start_delay=2.0,
                     label="Dry run" if dry else "Imported script")
        self.app.start_job(job, self, hide=not dry and self.app.action_tab.v_hide.get())

    def run_dry(self):
        if self._ready():
            values = self._values()
            if values is not None:
                self.pending_real = False
                self._start(True, values)

    def run_real(self):
        if not self._ready():
            return
        values = self._values()
        if values is None:
            return
        if self.v_dry_first.get():
            self.pending_real = True
            self.pending_values = values
            self._start(True, values)
        else:
            self._start(False, values)

    def on_job(self, kind, payload):
        if kind == "step" and self.tree.exists(str(payload)):
            self.tree.selection_set(str(payload))
            self.tree.see(str(payload))
        elif kind == "done":
            ok, reason = payload
            if self.pending_real:
                self.pending_real = False
                if ok and messagebox.askyesno("Dry run finished",
                                              "Every target was found. Run the script for real now?", parent=self):
                    self.after(100, lambda: self._start(False, self.pending_values))
                elif not ok:
                    messagebox.showwarning("Dry run stopped", reason, parent=self)

    def update_state(self, running_mine, running_any, paused):
        has = self.script is not None
        self.btn_run.set_enabled(has and not running_any)
        self.btn_dry.set_enabled(has and not running_any)
        self.btn_open.set_enabled(has)

    def title_text(self):
        return os.path.basename(self.path) if self.path else "Import script"
