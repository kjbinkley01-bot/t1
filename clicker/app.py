"""Main window: tab bar, status bar, hotkeys, jobs, and trigger monitoring."""

import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from . import inputs, model, storage, ui, vision
from .hotkeys import HotkeyManager
from .runner import Runner
from .tab_actions import ActionTab
from .tab_import import ImportTab
from .tab_recorder import RecorderTab
from .tab_triggers import TriggersTab
from .theme import C, F, Button, entry, frame, label
from .triggers import TriggerEngine

TABS = [("actions", "Action Script"), ("recorder", "Macro Recorder"),
        ("triggers", "Screen Triggers"), ("import", "Import Script")]
HOTKEY_NAMES = {
    "add_action": "Add action at cursor", "script_toggle": "Start / stop script",
    "emergency": "Emergency stop", "rec_toggle": "Start / stop recording",
    "play_toggle": "Start / stop playback", "pause": "Pause / resume",
}


class Ctx:
    """Thread-safe bridge the trigger engine uses to reach the running job."""

    def __init__(self, app):
        self.app = app

    def _job(self):
        j = self.app.job
        return j if j is not None and j.running else None

    def script_running(self):
        return self._job() is not None

    def hold(self):
        j = self._job()
        if j:
            j.hold()
            self.app._held_job = j

    def release(self):
        j = getattr(self.app, "_held_job", None)
        if j:
            j.release()
            self.app._held_job = None

    def pause(self):
        j = self._job()
        if j:
            j.pause()

    def resume(self):
        j = self._job()
        if j:
            j.resume()

    def rewind(self, n):
        j = self._job()
        if j:
            j.rewind(n)

    def stop_all(self):
        self.app.post("app", "stop_all", None)

    def run_script(self, path):
        self.app.post("app", "run_script", path)


class App:
    def __init__(self, root):
        self.root = root
        from . import theme
        theme.init(root)
        root.title(model.APP_NAME)
        root.geometry("1180x960")
        root.minsize(1060, 760)
        self.q = queue.Queue()
        self.settings = storage.load_settings()
        self.last_inputs = {}
        self.job = None
        self.job_owner = None
        self._held_job = None
        self._hid_window = False
        self._state_sig = None
        self.hotkey_displays = {}
        self.capture_action = None
        self.toast = ui.Toast(root)
        self.current_tab = None

        try:
            self.rules, self.trigger_assets = storage.load_triggers(storage.triggers_path())
        except Exception:
            self.rules, self.trigger_assets = [], storage.AssetStore()
        self._rules_lock = threading.Lock()
        self.triggers = TriggerEngine(self.get_rules, self.trigger_assets, self.emitter("trigger"), Ctx(self))
        self.hotkeys = HotkeyManager(lambda kind, payload: self.post("hotkey", kind, payload),
                                     self.settings["hotkeys"])

        self._build_chrome()
        self.action_tab = ActionTab(self.content, self)
        self.recorder_tab = RecorderTab(self.content, self)
        self.triggers_tab = TriggersTab(self.content, self)
        self.import_tab = ImportTab(self.content, self)
        self.tabs = {"actions": self.action_tab, "recorder": self.recorder_tab,
                     "triggers": self.triggers_tab, "import": self.import_tab}
        for t in self.tabs.values():
            t.grid(row=0, column=0, sticky="nsew")
        self.show_tab("actions")
        self.refresh_hotkey_displays()

        self.hotkeys.start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, lambda: ui.dark_titlebar(root))
        root.after(40, self._poll)
        root.after(200, self._status_tick)
        self.refresh_states()

    # ------------------------------------------------------------ chrome

    def _build_chrome(self):
        top = tk.Frame(self.root, bg=C["bar"])
        top.pack(fill="x")
        brand = frame(top, bg=C["bar"])
        brand.pack(side="left", padx=(16, 18))
        logo = tk.Canvas(brand, width=16, height=16, bg=C["bar"], highlightthickness=0)
        logo.create_polygon(3, 2, 8, 15, 10, 9, 15, 7, fill="", outline=C["accent"], width=2)
        logo.pack(side="left", padx=(0, 8))
        label(brand, model.APP_NAME, bg=C["bar"], font=F.bold).pack(side="left")
        self.tab_labels = {}
        self.tab_lines = {}
        for key, text in TABS:
            cell = frame(top, bg=C["bar"])
            cell.pack(side="left")
            lbl = tk.Label(cell, text=text, bg=C["bar"], fg=C["muted"], font=F.body, padx=14, pady=10,
                           cursor="hand2")
            lbl.pack()
            line = tk.Frame(cell, bg=C["bar"], height=2)
            line.pack(fill="x")
            lbl.bind("<Button-1>", lambda e, k=key: self.show_tab(k))
            lbl.bind("<Enter>", lambda e, w=lbl: w.configure(fg=C["text"]))
            lbl.bind("<Leave>", lambda e, k=key, w=lbl: w.configure(
                fg=C["text"] if self.current_tab == k else C["muted"]))
            self.tab_labels[key] = lbl
            self.tab_lines[key] = line
        self.lbl_file = label(top, "", bg=C["bar"], muted=True)
        self.lbl_file.pack(side="right", padx=16)
        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")

        self.status = tk.Frame(self.root, bg=C["bar"])
        self.status.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=C["line"], height=1).pack(side="bottom", fill="x")
        si = frame(self.status, bg=C["bar"])
        si.pack(fill="x", padx=14, pady=5)
        self.lbl_cursor = label(si, "", bg=C["bar"], font=F.mono, fg="#9aa0a6")
        self.lbl_cursor.pack(side="left")
        self.swatch = tk.Frame(si, bg=C["bar"], width=12, height=12, highlightthickness=1,
                               highlightbackground=C["field_bd"])
        self.swatch.pack(side="left", padx=(18, 6))
        self.lbl_pixel = label(si, "", bg=C["bar"], font=F.mono, fg="#9aa0a6")
        self.lbl_pixel.pack(side="left")
        try:
            info = vision.display_info()
            scr = f"Screen {info['width']} x {info['height']} at {info['scale']}%"
        except Exception:
            scr = ""
        label(si, scr, bg=C["bar"], fg="#9aa0a6").pack(side="left", padx=18)
        self.lbl_state = label(si, "Ready", bg=C["bar"], fg=C["teal"], font=F.bold)
        self.lbl_state.pack(side="right")
        self.lbl_trig = label(si, "", bg=C["bar"], fg="#9aa0a6")
        self.lbl_trig.pack(side="right", padx=18)
        self.lbl_msg = label(si, "", bg=C["bar"], fg="#9aa0a6")
        self.lbl_msg.pack(side="right", padx=18)

        self.content = frame(self.root)
        self.content.pack(fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

    def show_tab(self, key):
        self.current_tab = key
        self.tabs[key].tkraise()
        for k in self.tab_labels:
            on = k == key
            self.tab_labels[k].configure(fg=C["text"] if on else C["muted"], font=F.bold if on else F.body)
            self.tab_lines[k].configure(bg=C["accent"] if on else C["bar"])
        self.update_title()

    def update_title(self):
        if not getattr(self, "current_tab", None) or self.current_tab not in getattr(self, "tabs", {}):
            return
        text = self.tabs[self.current_tab].title_text()
        self.lbl_file.configure(text=text)
        self.root.title(f"{model.APP_NAME}  |  {text}")

    def set_status(self, msg, error=False):
        self.lbl_msg.configure(text=msg, fg=C["err"] if error else "#9aa0a6")
        if getattr(self, "_msg_job", None):
            self.root.after_cancel(self._msg_job)
        self._msg_job = self.root.after(6000, lambda: self.lbl_msg.configure(text=""))

    def _status_tick(self):
        try:
            x, y = inputs.position()
            self.lbl_cursor.configure(text=f"X {x:>5}   Y {y:>5}")
            rgb = vision.pixel(x, y)
            hexc = vision.rgb_hex(rgb)
            self.swatch.configure(bg=hexc)
            self.lbl_pixel.configure(text=hexc)
        except Exception:
            pass
        self.root.after(150, self._status_tick)

    # ------------------------------------------------------------ hotkeys

    def hotkey_rows(self, parent, rows, columns=2, start_row=0):
        bg = parent["bg"]
        for c in range(columns):
            parent.columnconfigure(c, weight=1, uniform="hk")
        for i, (text, action) in enumerate(rows):
            cell = frame(parent, bg=bg)
            cell.grid(row=start_row + i // columns, column=i % columns, sticky="ew",
                      padx=(0, 24) if i % columns == 0 else (0, 0), pady=3)
            label(cell, text, bg=bg).pack(side="left")
            Button(cell, "Clear", lambda a=action: self.set_hotkey(a, ""), small=True).pack(side="right")
            Button(cell, "Assign", lambda a=action: self.begin_assign(a), small=True).pack(side="right", padx=(0, 4))
            var = tk.StringVar()
            entry(cell, var, 12, mono=True, readonly=True, justify="center").pack(side="right", padx=(0, 8))
            self.hotkey_displays.setdefault(action, []).append(var)

    def refresh_hotkey_displays(self):
        for action, vars_ in self.hotkey_displays.items():
            val = self.settings["hotkeys"].get(action) or "None"
            if self.capture_action == action:
                val = "Press keys..."
            for v in vars_:
                v.set(val)

    def begin_assign(self, action):
        self.capture_action = action
        self.hotkeys.capture_next()
        self.refresh_hotkey_displays()
        self.set_status(f"Press the new key for '{HOTKEY_NAMES[action]}' (Esc to clear)")

    def set_hotkey(self, action, label_text):
        if label_text:
            for other, val in self.settings["hotkeys"].items():
                if other != action and val and val.lower() == label_text.lower():
                    self.settings["hotkeys"][other] = ""
                    self.set_status(f"{label_text} moved from '{HOTKEY_NAMES[other]}'")
        self.settings["hotkeys"][action] = label_text
        self.hotkeys.bindings = dict(self.settings["hotkeys"])
        self.save_settings()
        self.refresh_hotkey_displays()

    def _on_hotkey(self, action):
        if action == "emergency":
            self.stop_all()
        elif action == "pause":
            self.toggle_pause()
        elif action == "add_action":
            self.action_tab.add_at_cursor()
        elif action == "script_toggle":
            self.action_tab.toggle_run(from_hotkey=True)
        elif action == "rec_toggle":
            self.recorder_tab.toggle_record(from_hotkey=True)
        elif action == "play_toggle":
            self.recorder_tab.toggle_play()

    # ------------------------------------------------------------ jobs

    def post(self, source, kind, payload):
        self.q.put((source, kind, payload))

    def emitter(self, source):
        return lambda kind, payload=None: self.q.put((source, kind, payload))

    def job_running(self):
        return self.job is not None and self.job.running

    def job_running_for(self, owner):
        return self.job_running() and self.job_owner is owner

    def start_job(self, job, owner, hide=False):
        if self.job_running() or self.recorder_tab.recorder.active:
            self.set_status("Something is already running.", error=True)
            return False
        self.job = job
        self.job_owner = owner
        self.triggers.reset_counts()
        job.start()
        if hide:
            self._hid_window = True
            self.root.iconify()
        self.refresh_states()
        return True

    def stop_job(self):
        if self.job_running():
            self.job.stop()

    def toggle_pause(self):
        if self.job_running():
            self.job.toggle_pause()
            self.refresh_states()

    def stop_all(self):
        self.stop_job()
        if self.recorder_tab.recorder.active:
            self.recorder_tab.stop_record(from_hotkey=True)
        if self.triggers.running:
            self.triggers.stop()
        self.toast.show("Stopped", "Everything was stopped.", ms=2500, accent=C["rec"])
        self.refresh_states()

    def toggle_monitoring(self):
        if self.triggers.running:
            self.triggers.stop()
        else:
            if not any(r.get("enabled") for r in self.rules):
                self.set_status("Enable at least one rule first.", error=True)
                return
            self.triggers.start()
        self.root.after(100, self.refresh_states)

    def _run_script_from_trigger(self, path):
        if self.job_running():
            self.triggers_tab.add_log("Run script", "Skipped: a job is already running", False)
            return
        try:
            script, assets = storage.load_script(path)
        except Exception as e:
            self.triggers_tab.add_log("Run script", f"Could not open {path}: {e}", False)
            return
        st = script.get("settings") or {}
        job = Runner(script, assets, self.emitter("script"), inputs_map=dict(self.last_inputs),
                     speed=st.get("speed", 1.0), repeat=st.get("repeat", 1),
                     random_delay_ms=st.get("random_delay_ms", 0), label=path)
        self.start_job(job, self.import_tab)

    # ------------------------------------------------------------ rules

    def get_rules(self):
        return list(self.rules)

    def replace_rule(self, rule):
        for i, r in enumerate(self.rules):
            if r["id"] == rule["id"]:
                self.rules[i] = rule
                break
        else:
            self.rules.append(rule)
        self.save_rules()

    def save_rules(self):
        try:
            storage.save_triggers(storage.triggers_path(), self.rules, self.trigger_assets)
        except Exception as e:
            self.set_status(f"Could not save rules: {e}", error=True)

    def save_settings(self):
        try:
            storage.save_settings(self.settings)
        except Exception:
            pass

    # ------------------------------------------------------------ event loop

    def refresh_states(self):
        running = self.job_running()
        paused = running and self.job.paused
        for t in self.tabs.values():
            t.update_state(running and self.job_owner is t, running, paused)
        if self.recorder_tab.recorder.active:
            state, color = "Recording", C["danger"]
        elif running:
            state = "Paused" if paused else getattr(self.job, "status", "Running")
            color = C["warn"] if paused else C["teal"]
        else:
            state, color = "Ready", C["teal"]
        self.lbl_state.configure(text=state, fg=color)
        n = sum(1 for r in self.rules if r.get("enabled"))
        self.lbl_trig.configure(text=(f"Monitoring {n} rule{'s' if n != 1 else ''}" if self.triggers.running
                                      else "Monitoring off"),
                                fg=C["teal"] if self.triggers.running else "#9aa0a6")

    def _poll(self):
        changed = False
        try:
            for _ in range(200):
                source, kind, payload = self.q.get_nowait()
                changed = True
                self._dispatch(source, kind, payload)
        except queue.Empty:
            pass
        sig = (self.job_running(), self.job.paused if self.job else None,
               self.triggers.running, self.recorder_tab.recorder.active)
        if changed or sig != self._state_sig:
            self._state_sig = sig
            self.refresh_states()
        self.root.after(40, self._poll)

    def _dispatch(self, source, kind, payload):
        if source == "hotkey":
            if kind == "hotkey_captured":
                action = self.capture_action
                self.capture_action = None
                if action:
                    self.set_hotkey(action, payload)
                    self.set_status(f"'{HOTKEY_NAMES[action]}' is now {payload or 'None'}")
            elif kind == "hotkey":
                self._on_hotkey(payload)
            return
        if source == "app":
            if kind == "stop_all":
                self.stop_all()
            elif kind == "run_script":
                self._run_script_from_trigger(payload)
            return
        if kind == "notify":
            self.toast.show("Clicker", str(payload))
            return
        if kind == "highlight":
            try:
                ui.flash(self.root, payload, ms=700)
            except Exception:
                pass
            return
        if source == "trigger":
            if kind == "log":
                rule, msg, hit = payload
                self.triggers_tab.add_log(rule, msg, hit)
            return
        # job events
        owner = self.job_owner
        if kind == "state" and self.job:
            self.job.status = "Running" if payload == "running" else (
                "Paused" if payload == "paused" else str(payload))
        elif kind == "run" and self.job:
            self.job.status = f"Running, pass {payload}"
        elif kind == "step" and self.job:
            self.job.status = f"Running step {payload + 1}"
        elif kind == "log":
            self.set_status(str(payload))
        elif kind == "done":
            ok, reason = payload
            if self._hid_window:
                self._hid_window = False
                self.root.deiconify()
            if ok:
                self.set_status("Finished")
            else:
                self.set_status(reason, error=not reason.startswith("Stop"))
                if reason.startswith("Error") or "timed out" in reason or "not found" in reason \
                        or "missing" in reason or "does not exist" in reason:
                    self.toast.show("Script stopped", reason, ms=8000, accent=C["rec"])
        if owner is not None and hasattr(owner, "on_job"):
            owner.on_job(kind, payload)

    def on_close(self):
        if self.action_tab.dirty and self.action_tab.script["steps"]:
            ans = messagebox.askyesnocancel("Unsaved script", "Save the action script before closing?",
                                            parent=self.root)
            if ans is None:
                return
            if ans and not self.action_tab.save():
                return
        if self.recorder_tab.dirty and self.recorder_tab.events:
            if not messagebox.askyesno("Unsaved recording", "Close without saving the recording?",
                                       parent=self.root):
                return
        self.stop_job()
        if self.recorder_tab.recorder.active:
            self.recorder_tab.recorder.stop()
        self.triggers.stop()
        self.hotkeys.stop()
        self.save_rules()
        self.save_settings()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    root = tk.Tk()
    try:
        App(root)
    except Exception as e:
        import traceback
        traceback.print_exc()
        messagebox.showerror("Clicker could not start", f"{e}")
        raise
    root.mainloop()
