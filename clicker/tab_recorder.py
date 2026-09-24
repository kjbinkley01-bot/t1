"""Macro Recorder tab: record, play back with variation, convert to a script."""

import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from . import model, storage
from .recorder import Player, Recorder, recording_to_steps
from .storage import AssetStore
from .theme import C, F, Button, cap, check, combo, entry, frame, label, panel


class RecorderTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=C["bg"])
        self.app = app
        self.recorder = Recorder(app.hotkeys.is_hotkey)
        self.events = []
        self.path = None
        self.dirty = False
        o = app.settings.get("recorder") or {}
        sv = lambda k, d: tk.StringVar(value=str(o.get(k, d)))  # noqa: E731
        bv = lambda k, d: tk.BooleanVar(value=bool(o.get(k, d)))  # noqa: E731
        self.v_repeat = sv("repeat", 1)
        self.v_clicks, self.v_moves, self.v_keys = bv("clicks", True), bv("moves", True), bv("keys", True)
        self.v_smin, self.v_smax = sv("speed_min", 100), sv("speed_max", 100)
        self.v_gmin, self.v_gmax = sv("gap_min", 0), sv("gap_max", 0)
        self.v_gunit = tk.StringVar(value=o.get("gap_unit", "seconds"))
        self.v_hmin, self.v_hmax = sv("dx_min", 0), sv("dx_max", 0)
        self.v_vmin, self.v_vmax = sv("dy_min", 0), sv("dy_max", 0)
        self.v_hwhole, self.v_vwhole = bv("dx_whole", True), bv("dy_whole", True)
        self.v_settle = bv("settle", False)
        self.v_count = tk.StringVar(value="0")
        self.v_elapsed = tk.StringVar(value="00:00")
        self._build()
        self._tick()

    # ------------------------------------------------------------ layout

    def _build(self):
        bar = frame(self)
        bar.pack(fill="x", padx=14, pady=(12, 10))
        for text, cmd in (("New", self.new), ("Open", self.open), ("Save", self.save),
                          ("Save As", lambda: self.save(True))):
            Button(bar, text, cmd).pack(side="left", padx=(0, 6))
        Button(bar, "Convert to Action Script", self.convert).pack(side="right")

        body = frame(self)
        body.pack(fill="both", expand=True, padx=14)
        col = frame(body)
        col.pack(fill="both", expand=True)
        col.columnconfigure(0, weight=1)
        col.columnconfigure(1, weight=1)

        # record / play
        p = panel(col)
        p.grid(row=0, column=0, columnspan=2, sticky="nsew")
        inner = frame(p, bg=C["panel"])
        inner.pack(fill="x", padx=16, pady=14)
        g = frame(inner, bg=C["panel"])
        g.pack(fill="x")
        for i in range(3):
            g.columnconfigure(i, weight=1, uniform="rec")
        self.btn_rec = Button(g, "Start Recording", self.toggle_record, kind="record", big=True)
        self.btn_rec.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn_rec_stop = Button(g, "Stop Recording", self.stop_record, big=True)
        self.btn_rec_stop.grid(row=0, column=1, sticky="ew", padx=4)
        stats = frame(g, bg=C["panel"])
        stats.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        for var, text in ((self.v_count, "events"), (self.v_elapsed, "length")):
            s = frame(stats, bg=C["panel"])
            s.pack(side="left", expand=True)
            tk.Label(s, textvariable=var, bg=C["panel"], fg=C["text"], font=F.mono_big).pack()
            label(s, text, bg=C["panel"], muted=True, font=F.small).pack()
        self.lbl_note = label(inner, "Click Start Recording (or press the record hotkey), do the task, "
                                     "then press the hotkey again to stop.", bg=C["panel"], muted=True, font=F.small)
        self.lbl_note.pack(anchor="w", pady=(10, 12))

        g2 = frame(inner, bg=C["panel"])
        g2.pack(fill="x")
        for i in range(3):
            g2.columnconfigure(i, weight=1, uniform="rec")
        self.btn_play = Button(g2, "Play Recording", self.toggle_play, kind="primary", big=True)
        self.btn_play.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        rp = frame(g2, bg=C["panel"])
        rp.grid(row=0, column=1)
        label(rp, "Repeat", bg=C["panel"]).pack(side="left", padx=(0, 8))
        entry(rp, self.v_repeat, 5, mono=True, justify="right").pack(side="left")
        label(rp, "0 = loop", bg=C["panel"], muted=True, font=F.small).pack(side="left", padx=8)
        opts = frame(g2, bg=C["panel"])
        opts.grid(row=0, column=2, sticky="w", padx=(8, 0))
        check(opts, "Record mouse clicks and scrolls", self.v_clicks, bg=C["panel"]).pack(anchor="w")
        check(opts, "Record mouse movement", self.v_moves, bg=C["panel"]).pack(anchor="w")
        check(opts, "Record keyboard", self.v_keys, bg=C["panel"]).pack(anchor="w")

        # variation
        p = panel(col)
        p.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=12)
        inner = frame(p, bg=C["panel"])
        inner.pack(fill="x", padx=16, pady=14)
        cap(inner, "Playback variation", bg=C["panel"]).pack(anchor="w", pady=(0, 10))
        r = self._row(inner)
        label(r, "Random playback speed between", bg=C["panel"], width=30, anchor="w").pack(side="left")
        entry(r, self.v_smin, 6, mono=True, justify="right").pack(side="left")
        label(r, "and", bg=C["panel"]).pack(side="left", padx=8)
        entry(r, self.v_smax, 6, mono=True, justify="right").pack(side="left")
        label(r, "%", bg=C["panel"], muted=True).pack(side="left", padx=6)
        r = self._row(inner)
        label(r, "Random delay between playbacks", bg=C["panel"], width=30, anchor="w").pack(side="left")
        entry(r, self.v_gmin, 6, mono=True, justify="right").pack(side="left")
        label(r, "to", bg=C["panel"]).pack(side="left", padx=8)
        entry(r, self.v_gmax, 6, mono=True, justify="right").pack(side="left")
        combo(r, self.v_gunit, ["seconds", "minutes"], width=9).pack(side="left", padx=8)

        dev = frame(inner, bg=C["panel"])
        dev.pack(fill="x", pady=(4, 10))
        dev.columnconfigure(0, weight=1, uniform="dev")
        dev.columnconfigure(1, weight=1, uniform="dev")
        for col_i, (title, vmin, vmax, whole) in enumerate((
                ("Horizontal mouse deviation", self.v_hmin, self.v_hmax, self.v_hwhole),
                ("Vertical mouse deviation", self.v_vmin, self.v_vmax, self.v_vwhole))):
            box = tk.Frame(dev, bg=C["panel_alt"], highlightthickness=1, highlightbackground=C["line"])
            box.grid(row=0, column=col_i, sticky="nsew", padx=(0, 6) if col_i == 0 else (6, 0))
            bi = frame(box, bg=C["panel_alt"])
            bi.pack(fill="x", padx=12, pady=10)
            label(bi, title, bg=C["panel_alt"], font=F.bold).pack(anchor="w", pady=(0, 8))
            rr = frame(bi, bg=C["panel_alt"])
            rr.pack(anchor="w", pady=(0, 8))
            label(rr, "Min", bg=C["panel_alt"]).pack(side="left", padx=(0, 6))
            entry(rr, vmin, 5, mono=True, justify="right").pack(side="left")
            label(rr, "Max", bg=C["panel_alt"]).pack(side="left", padx=(14, 6))
            entry(rr, vmax, 5, mono=True, justify="right").pack(side="left")
            label(rr, "px", bg=C["panel_alt"], muted=True).pack(side="left", padx=6)
            check(bi, "Same offset for the whole playback", whole, bg=C["panel_alt"]).pack(anchor="w")
        check(inner, "Wait for the screen to settle before each recorded click (max 10 s)",
              self.v_settle, bg=C["panel"]).pack(anchor="w")

        # hotkeys
        p = panel(col)
        p.grid(row=2, column=0, columnspan=2, sticky="nsew")
        inner = frame(p, bg=C["panel"])
        inner.pack(fill="x", padx=16, pady=12)
        cap(inner, "Shortcut keys", bg=C["panel"]).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.app.hotkey_rows(inner, [
            ("Start / stop recording", "rec_toggle"),
            ("Start / stop playback", "play_toggle"),
            ("Pause / resume playback", "pause"),
            ("Emergency stop everything", "emergency"),
        ], columns=2, start_row=1)

    def _row(self, parent):
        r = frame(parent, bg=C["panel"])
        r.pack(fill="x", pady=(0, 8))
        return r

    # ------------------------------------------------------------ state

    def _read_options(self):
        def num(var, name, lo=None):
            try:
                v = float(var.get() or 0)
            except ValueError:
                raise ValueError(f"{name} must be a number.")
            if lo is not None and v < lo:
                raise ValueError(f"{name} must be at least {lo:g}.")
            return v
        o = {
            "repeat": int(num(self.v_repeat, "Repeat", 0)),
            "clicks": bool(self.v_clicks.get()), "moves": bool(self.v_moves.get()),
            "keys": bool(self.v_keys.get()),
            "speed_min": num(self.v_smin, "Speed", 1), "speed_max": num(self.v_smax, "Speed", 1),
            "gap_min": num(self.v_gmin, "Delay", 0), "gap_max": num(self.v_gmax, "Delay", 0),
            "gap_unit": self.v_gunit.get(),
            "dx_min": num(self.v_hmin, "Deviation"), "dx_max": num(self.v_hmax, "Deviation"),
            "dy_min": num(self.v_vmin, "Deviation"), "dy_max": num(self.v_vmax, "Deviation"),
            "dx_whole": bool(self.v_hwhole.get()), "dy_whole": bool(self.v_vwhole.get()),
            "settle": bool(self.v_settle.get()),
        }
        self.app.settings["recorder"] = o
        self.app.save_settings()
        return o

    def _tick(self):
        if self.recorder.active:
            self.v_count.set(str(self.recorder.count))
            secs = int(time.monotonic() - self.recorder.started)
            self.v_elapsed.set(f"{secs // 60:02d}:{secs % 60:02d}")
        self._tick_job = self.after(250, self._tick)

    def destroy(self):
        job = getattr(self, "_tick_job", None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        super().destroy()

    def adopt(self, recorder, events, path, dirty):
        """Take over the recording from the tab this one replaces (theme change)."""
        self.recorder = recorder
        self.events, self.path, self.dirty = events, path, dirty
        self._show_counts()

    def _show_counts(self):
        self.v_count.set(str(len(self.events)))
        secs = int(self.events[-1]["t"]) if self.events else 0
        self.v_elapsed.set(f"{secs // 60:02d}:{secs % 60:02d}")

    def update_state(self, running_mine, running_any, paused):
        rec = self.recorder.active
        self.btn_rec.set_enabled(not rec and not running_any)
        self.btn_rec_stop.set_enabled(rec)
        self.btn_play.set_enabled(running_mine or (not running_any and not rec and bool(self.events)))
        self.btn_play.set_text("Stop Playback" if running_mine else "Play Recording")
        self.btn_play.set_kind("danger" if running_mine else "primary")

    def title_text(self):
        name = os.path.basename(self.path) if self.path else "Untitled recording"
        return name + (" *" if self.dirty else "")

    # ------------------------------------------------------------ actions

    def toggle_record(self, from_hotkey=False):
        if self.recorder.active:
            self.stop_record(from_hotkey=from_hotkey)
            return
        if self.app.job_running():
            self.app.set_status("Stop the running job before recording.", error=True)
            return
        if self.dirty and self.events and not from_hotkey:
            if not messagebox.askyesno("Discard recording?", "The current recording is not saved. Record over it?",
                                       parent=self):
                return
        try:
            o = self._read_options()
        except ValueError as e:
            self.app.set_status(str(e), error=True)
            return
        self.recorder.start(clicks=o["clicks"], moves=o["moves"], keys=o["keys"])
        self.lbl_note.configure(text="Recording. Press the record hotkey to stop.", fg=C["danger"])
        self.app.set_status("Recording")
        self.app.refresh_states()

    def stop_record(self, from_hotkey=False):
        if not self.recorder.active:
            return
        self.events = self.recorder.stop(trim_last_click=not from_hotkey)
        self.path = None
        self.dirty = bool(self.events)
        self._show_counts()
        self.lbl_note.configure(text=f"Recorded {len(self.events)} events. Save it, play it, or convert it "
                                     "to an Action Script.", fg=C["muted"])
        self.app.set_status("Recording stopped")
        self.app.update_title()
        self.app.refresh_states()

    def toggle_play(self):
        if self.app.job_running_for(self):
            self.app.stop_job()
            return
        if self.app.job_running() or self.recorder.active:
            return
        if not self.events:
            self.app.set_status("Nothing to play. Record or open a recording first.", error=True)
            return
        try:
            o = self._read_options()
        except ValueError as e:
            self.app.set_status(str(e), error=True)
            return
        mult = 60.0 if o["gap_unit"] == "minutes" else 1.0
        job = Player(self.events, self.app.emitter("recording"), repeat=o["repeat"],
                     speed_min=o["speed_min"], speed_max=o["speed_max"],
                     dx_min=o["dx_min"], dx_max=o["dx_max"], dy_min=o["dy_min"], dy_max=o["dy_max"],
                     whole=o["dx_whole"] and o["dy_whole"],
                     gap_min=o["gap_min"] * mult, gap_max=o["gap_max"] * mult,
                     settle=o["settle"], start_delay=2.0)
        self.app.start_job(job, self)

    def on_job(self, kind, payload):
        if kind == "run":
            self.lbl_note.configure(text=f"Playing run {payload}.", fg=C["teal"])
        elif kind == "done":
            ok, reason = payload
            self.lbl_note.configure(text=f"Playback {'finished' if ok else 'stopped'}. {'' if ok else reason}",
                                    fg=C["muted"])

    def new(self):
        if self.recorder.active or self.app.job_running_for(self):
            return
        if self.dirty and self.events and not messagebox.askyesno(
                "Discard recording?", "The current recording is not saved. Discard it?", parent=self):
            return
        self.events, self.path, self.dirty = [], None, False
        self._show_counts()
        self.app.update_title()

    def open(self):
        if self.recorder.active or self.app.job_running_for(self):
            return
        path = filedialog.askopenfilename(parent=self, title="Open recording",
                                          filetypes=[("Recordings", "*.clkrec *.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            events, options = storage.load_recording(path)
        except Exception as e:
            messagebox.showerror("Could not open recording", str(e), parent=self)
            return
        self.events, self.path, self.dirty = events, path, False
        self._show_counts()
        self.lbl_note.configure(text=f"Opened {os.path.basename(path)}.", fg=C["muted"])
        self.app.update_title()

    def save(self, save_as=False):
        if not self.events:
            return
        path = self.path
        if save_as or not path:
            path = filedialog.asksaveasfilename(parent=self, title="Save recording", defaultextension=".clkrec",
                                                filetypes=[("Recording", "*.clkrec")])
            if not path:
                return
        try:
            storage.save_recording(path, self.events, self._read_options())
        except Exception as e:
            messagebox.showerror("Could not save", str(e), parent=self)
            return
        self.path, self.dirty = path, False
        self.app.update_title()
        self.app.set_status(f"Saved {os.path.basename(path)}")

    def convert(self):
        if not self.events:
            self.app.set_status("Record something first.", error=True)
            return
        steps = recording_to_steps(self.events)
        if not steps:
            self.app.set_status("The recording has no clicks or keys to convert.", error=True)
            return
        tab = self.app.action_tab
        if self.app.job_running_for(tab) or not tab.confirm_discard():
            return
        script = model.new_script("Converted recording")
        script["steps"] = steps
        from . import vision
        script["screen"] = vision.display_info()
        tab.set_script(script, AssetStore())
        self.app.show_tab("actions")
        self.app.set_status(f"Converted {len(self.events)} events into {len(steps)} steps")
