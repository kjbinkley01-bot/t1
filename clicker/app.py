"""Main window: tab bar, status bar, hotkeys, jobs, and trigger monitoring."""

import datetime
import gc
import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import messagebox

from . import anim, inputs, model, runlog, storage, theme, ui, updates, vision
from .hotkeys import HotkeyManager
from .runner import Runner
from .tab_actions import ActionTab
from .tab_import import ImportTab
from .tab_recorder import RecorderTab
from .tab_triggers import TriggersTab
from .theme import C, F, Button, check, combo, entry, frame, label, px
from .triggers import TriggerEngine

AUTOSAVE_MS = 60_000

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


class CursorSampler:
    """Reads the cursor position and the pixel under it on a background thread.

    Grabbing the screen can take tens of milliseconds on Windows; doing it on
    the UI thread made the whole window stutter, especially while resizing.
    """

    def __init__(self, post, interval=0.12):
        self.post = post
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._main, daemon=True, name="cursor-sampler")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _main(self):
        last = None
        while not self.stop_event.wait(self.interval):
            try:
                x, y = inputs.position()
                hexc = vision.rgb_hex(vision.pixel(x, y))
            except Exception:
                continue
            if (x, y, hexc) != last:
                last = (x, y, hexc)
                self.post("app", "cursor", last)
        vision.release_thread()


# events where only the newest one matters; older ones are dropped when the queue backs up
COALESCE = {("script", "step"), ("script", "log"), ("script", "state"), ("script", "run"),
            ("script", "highlight"), ("app", "cursor"), ("trigger", "highlight")}


class App:
    def __init__(self, root):
        self.root = root
        # Background threads (scripts, triggers, the cursor sampler) share Python's lock with
        # the window. Handing it over every 1 ms instead of 5 ms keeps the window responsive
        # while a busy script runs, at no measurable cost.
        sys.setswitchinterval(0.001)
        self.settings = storage.load_settings()
        theme.use(self.settings.get("theme", "classic"))
        anim.motion["on"] = not self.settings.get("reduce_motion", False)
        theme.init(root)
        root.title(model.APP_NAME)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(px(1180), sw - 40)}x{min(px(960), sh - 80)}")
        self.q = queue.Queue()
        self.last_inputs = {}
        self.job = None
        self.job_owner = None
        self._held_job = None
        self._hid_window = False
        self._state_sig = None
        self._state_shown = None
        self.hotkey_displays = {}
        self.capture_action = None
        self.toast = ui.Toast(root)
        self.flasher = ui.Flash(root)
        self.current_tab = None
        self.last_log_dir = None
        self.update_info = None
        self._rebuilding = False
        self._set_icon()
        self._install_error_handlers()

        try:
            self.rules, self.trigger_assets = storage.load_triggers(storage.triggers_path())
        except Exception:
            self.rules, self.trigger_assets = [], storage.AssetStore()
        self._rules_lock = threading.Lock()
        self.triggers = TriggerEngine(self.get_rules, self.trigger_assets, self.emitter("trigger"), Ctx(self))
        self.hotkeys = HotkeyManager(lambda kind, payload: self.post("hotkey", kind, payload),
                                     self.settings["hotkeys"])

        self._build_ui()
        self._bind_global_keys()
        self.show_tab("actions", animate=False)

        self.hotkeys.start()
        self.sampler = CursorSampler(self.post)
        self.sampler.start()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(50, lambda: ui.dark_titlebar(root))
        root.after(40, self._poll)
        root.after(2500, self.check_updates)
        root.after(600, self._offer_recovery)
        root.after(AUTOSAVE_MS, self._autosave)
        self.refresh_states()

    def _build_ui(self):
        """Create the window's widgets for the active theme (also used when the theme changes)."""
        self.hotkey_displays = {}
        self._state_shown = None
        self._build_chrome()
        self.action_tab = ActionTab(self.content, self)
        self.recorder_tab = RecorderTab(self.content, self)
        self.triggers_tab = TriggersTab(self.content, self)
        self.import_tab = ImportTab(self.content, self)
        self.tabs = {"actions": self.action_tab, "recorder": self.recorder_tab,
                     "triggers": self.triggers_tab, "import": self.import_tab}
        for t in self.tabs.values():
            t.grid(row=0, column=0, sticky="nsew")
        self.refresh_hotkey_displays()
        self._fit_minsize()

    def _bind_global_keys(self):
        mods = ["Control"] + (["Command"] if sys.platform == "darwin" else [])
        for m in mods:
            self.root.bind_all(f"<{m}-z>", lambda e: self.action_tab._key_undo(e))
            for seq in (f"<{m}-y>", f"<{m}-Shift-Z>", f"<{m}-Z>"):
                self.root.bind_all(seq, lambda e: self.action_tab._key_redo(e))

    # ------------------------------------------------------------ themes

    def show_theme_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["sel"],
                    activeforeground=C["sel_fg"], selectcolor=C["accent"], bd=0, font=F.body)
        var = tk.StringVar(value=theme.S["name"])
        for key, text in theme.THEMES:
            m.add_radiobutton(label=text, value=key, variable=var, command=lambda k=key: self.set_theme(k))
        m.add_separator()
        motion = tk.BooleanVar(value=not anim.motion["on"])
        m.add_checkbutton(label="Reduce motion", variable=motion,
                          command=lambda: self.set_reduce_motion(motion.get()))
        self._theme_menu_vars = (var, motion)
        w = self.lnk_style
        try:
            m.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height())
        finally:
            m.grab_release()

    def set_reduce_motion(self, on):
        anim.motion["on"] = not on
        self.settings["reduce_motion"] = bool(on)
        self.save_settings()

    def set_theme(self, name):
        if name == theme.S["name"]:
            return
        if self.job_running() or self.recorder_tab.recorder.active:
            self.set_status("Stop the running script or recording before changing the style.", error=True)
            return
        self.settings["theme"] = name
        self.save_settings()

        def swap():
            theme.use(name)
            self.rebuild_ui()
        self._fade(swap)

    def _fade(self, middle):
        """Dip the window's opacity, run middle(), and bring it back (skipped with reduced motion)."""
        root = self.root

        def alpha(a):
            try:
                root.attributes("-alpha", a)
            except tk.TclError:
                pass
        if not anim.motion["on"]:
            middle()
            return

        def back():
            anim.Tween(root, 180, lambda t: alpha(0.35 + 0.65 * t), key="fade")
        anim.Tween(root, 120, lambda t: alpha(1 - 0.65 * t), key="fade",
                   done=lambda: (middle(), root.update_idletasks(), back()))

    def _capture_state(self):
        a, r, i = self.action_tab, self.recorder_tab, self.import_tab
        a._sync_settings()
        try:
            r._read_options()  # saved to settings, so the new tab starts with them
        except ValueError:
            pass
        return {
            "tab": self.current_tab,
            "action": (a.script, a.assets, a.path, a.dirty, a.history, a._selection()),
            "action_vars": {k: getattr(a, k).get() for k in ("v_script_repeat", "v_speed", "v_rand", "v_hide")},
            "rec": (r.recorder, r.events, r.path, r.dirty),
            "imp": (i.script, i.assets, i.path),
            "trig": self.triggers_tab.sel_id,
        }

    def _restore_state(self, st):
        a = self.action_tab
        script, assets, path, dirty, history, sel = st["action"]
        a.set_script(script, assets, path)
        a.dirty = dirty
        a.history = history
        for k, v in st["action_vars"].items():
            getattr(a, k).set(v)
        a._update_undo_buttons()
        a.refresh_list(sel or None)
        self.recorder_tab.adopt(*st["rec"])
        script, assets, path = st["imp"]
        if script is not None:
            self.import_tab.show(script, assets, path)
        if st["trig"]:
            try:
                self.triggers_tab.select_rule(st["trig"])
            except Exception:
                pass

    def rebuild_ui(self):
        """Recreate every widget for the active theme, keeping all open work."""
        self._rebuilding = True
        try:
            st = self._capture_state()
            self.toast.hide(animate=False)
            for w in self.root.winfo_children():
                w.destroy()
            # free the old widgets' Tk variables now, on this thread; left to the garbage
            # collector they could be freed on a worker thread, which Tk does not allow
            gc.collect()
            self.flasher = ui.Flash(self.root)
            self.toast = ui.Toast(self.root)
            theme.init(self.root)
            self._build_ui()
            self._restore_state(st)
            self.show_tab(st["tab"] or "actions", animate=False)
            self.refresh_states()
            ui.dark_titlebar(self.root)
            self.set_status(f"Style: {theme.THEME_LABEL[theme.S['name']]}")
        finally:
            self._rebuilding = False

    # ------------------------------------------------------------ errors and recovery

    def _errors_path(self):
        return os.path.join(storage.data_dir(), "errors.log")

    def _install_error_handlers(self):
        self.root.report_callback_exception = self._report_error
        try:
            import faulthandler
            self._fault_file = open(os.path.join(storage.data_dir(), "crash.log"), "a")
            faulthandler.enable(self._fault_file)
        except Exception:
            pass
        prev = threading.excepthook

        def hook(args):
            self._log_error(args.exc_type, args.exc_value, args.exc_traceback, f"thread {args.thread.name}")
            prev(args)
        threading.excepthook = hook

    def _log_error(self, exc, val, tb, where="UI"):
        try:
            text = "".join(traceback.format_exception(exc, val, tb))
            with open(self._errors_path(), "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ({where}, Clicker {model.APP_VERSION})\n")
                f.write(text + "\n")
        except Exception:
            pass

    def _report_error(self, exc, val, tb):
        """A button or timer crashed: keep the app alive, log it, and tell the user once."""
        self._log_error(exc, val, tb)
        traceback.print_exception(exc, val, tb)
        try:
            self.set_status(f"Something went wrong ({val}). Details were saved to errors.log.", error=True)
        except Exception:
            pass

    def _autosave_paths(self):
        d = storage.data_dir()
        return os.path.join(d, "autosave.clk"), os.path.join(d, "autosave.json")

    def _autosave(self):
        """Every minute, quietly save unsaved Action Script work so a crash can't lose it."""
        try:
            a = self.action_tab
            if a.dirty and a.script["steps"] and not self._rebuilding:
                a._sync_settings()
                script, assets = model.copy_script(a.script), a.assets.copy()
                clk, meta = self._autosave_paths()
                info = {"path": a.path, "time": datetime.datetime.now().isoformat(timespec="seconds"),
                        "steps": len(script["steps"])}

                def work():
                    try:
                        storage.save_script(clk, script, assets)
                        with open(meta, "w", encoding="utf-8") as f:
                            json.dump(info, f)
                    except Exception:
                        pass
                threading.Thread(target=work, daemon=True, name="autosave").start()
        finally:
            self.root.after(AUTOSAVE_MS, self._autosave)

    def _clear_autosave(self):
        for p in self._autosave_paths():
            try:
                os.remove(p)
            except OSError:
                pass

    def _offer_recovery(self):
        clk, meta = self._autosave_paths()
        if not os.path.exists(clk):
            return
        try:
            with open(meta, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {}
        when = str(info.get("time", "")).replace("T", " ")
        name = os.path.basename(info.get("path") or "") or "an unsaved script"
        if messagebox.askyesno("Recover unsaved work?",
                               f"Clicker closed without saving {name} ({info.get('steps', '?')} steps, "
                               f"last autosaved {when or 'recently'}).\n\nOpen the recovered copy?",
                               parent=self.root):
            try:
                script, assets = storage.load_script(clk)
                self.action_tab.set_script(script, assets, None)
                self.action_tab.dirty = True
                self.show_tab("actions")
                self.set_status("Recovered your unsaved script. Save it to keep it.")
            except Exception as e:
                self.set_status(f"Could not recover the script: {e}", error=True)
        self._clear_autosave()

    def _fit_minsize(self):
        """Never let the window shrink below what its contents need (no clipped text)."""
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        need_w = max(t.winfo_reqwidth() for t in self.tabs.values()) + px(8)
        need_h = max(t.winfo_reqheight() for t in self.tabs.values()) + self.top.winfo_reqheight() \
            + self.status.winfo_reqheight() + px(4)
        w, h = min(need_w, sw - 40), min(need_h, sh - 80)
        self.root.minsize(w, min(h, px(760)))
        cur_w, cur_h = self.root.winfo_width(), self.root.winfo_height()
        if cur_w > 1 and (cur_w < w or cur_h < min(h, px(760))):
            self.root.geometry(f"{max(cur_w, w)}x{max(cur_h, min(h, px(760)))}")

    # ------------------------------------------------------------ chrome

    def _build_chrome(self):
        top = tk.Frame(self.root, bg=C["bar"])
        top.pack(fill="x")
        self.top = top
        brand = frame(top, bg=C["bar"])
        brand.pack(side="left", padx=(px(16), px(18)))
        logo = tk.Canvas(brand, width=px(16), height=px(16), bg=C["bar"], highlightthickness=0)
        k = px(16) / 16.0
        logo.create_polygon(*(v * k for v in (3, 2, 8, 15, 10, 9, 15, 7)), fill="", outline=C["accent"],
                            width=max(2, px(2)))
        logo.pack(side="left", padx=(0, px(8)))
        label(brand, model.APP_NAME, bg=C["bar"], font=F.bold).pack(side="left")
        self.tab_labels = {}
        self.tab_lines = {}
        self.glass_tabs = None
        if theme.S["rounded"]:
            self.glass_tabs = ui.GlassTabs(top, TABS, self.show_tab)
            self.glass_tabs.pack(side="left", pady=px(4))
        else:
            for key, text in TABS:
                cell = frame(top, bg=C["bar"])
                cell.pack(side="left")
                lbl = tk.Label(cell, text=text, bg=C["bar"], fg=C["muted"], font=F.body, padx=px(14), pady=px(10),
                               cursor="hand2")
                lbl.pack()
                line = tk.Frame(cell, bg=C["bar"], height=max(2, px(2)))
                line.pack(fill="x")
                lbl.bind("<Button-1>", lambda e, k=key: self.show_tab(k))
                lbl.bind("<Enter>", lambda e, w=lbl: w.configure(fg=C["text"]))
                lbl.bind("<Leave>", lambda e, k=key, w=lbl: w.configure(
                    fg=C["text"] if self.current_tab == k else C["muted"]))
                self.tab_labels[key] = lbl
                self.tab_lines[key] = line
        for text, cmd in (("Settings", self.show_settings), ("Style", self.show_theme_menu)):
            lnk = tk.Label(top, text=text, bg=C["bar"], fg=C["muted"], font=F.body, padx=px(12), pady=px(10),
                           cursor="hand2")
            lnk.pack(side="right", padx=(0, px(4)))
            lnk.bind("<Button-1>", lambda e, c=cmd: c())
            lnk.bind("<Enter>", lambda e, w=lnk: w.configure(fg=C["text"]))
            lnk.bind("<Leave>", lambda e, w=lnk: w.configure(fg=C["muted"]))
            if text == "Style":
                self.lnk_style = lnk
        self.lbl_update = tk.Label(top, text="", bg=C["bar"], fg=C["accent"], font=F.bold, cursor="hand2")
        self.lbl_update.pack(side="right", padx=px(8))
        self.lbl_update.bind("<Button-1>", lambda e: self.open_update())
        if self.update_info:
            self.lbl_update.configure(text=f"Update {self.update_info['tag']} available")
        self.lbl_file = label(top, "", bg=C["bar"], muted=True)
        self.lbl_file.pack(side="right", padx=px(16))
        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x")

        self.status = tk.Frame(self.root, bg=C["bar"])
        self.status.pack(side="bottom", fill="x")
        tk.Frame(self.root, bg=C["line"], height=1).pack(side="bottom", fill="x")
        si = frame(self.status, bg=C["bar"])
        si.pack(fill="x", padx=px(14), pady=px(5))
        # fixed widths: changing text must not make Tk re-lay out the whole window
        self.lbl_cursor = label(si, "", bg=C["bar"], font=F.mono, fg=C["status"], width=18, anchor="w")
        self.lbl_cursor.pack(side="left")
        self.swatch = tk.Frame(si, bg=C["bar"], width=px(12), height=px(12), highlightthickness=1,
                               highlightbackground=C["field_bd"])
        self.swatch.pack(side="left", padx=(px(12), px(6)))
        self.lbl_pixel = label(si, "", bg=C["bar"], font=F.mono, fg=C["status"], width=8, anchor="w")
        self.lbl_pixel.pack(side="left")
        try:
            info = vision.display_info()
            scr = f"Screen {info['width']} x {info['height']} at {info['scale']}%"
        except Exception:
            scr = ""
        label(si, scr, bg=C["bar"], fg=C["status"]).pack(side="left", padx=px(18))
        self.lbl_state = label(si, "Ready", bg=C["bar"], fg=C["teal"], font=F.bold)
        self.lbl_state.pack(side="right")
        self.lbl_trig = label(si, "", bg=C["bar"], fg=C["status"])
        self.lbl_trig.pack(side="right", padx=px(18))
        self.lbl_msg = label(si, "", bg=C["bar"], fg=C["status"], anchor="e")
        self.lbl_msg.pack(side="right", padx=px(18), fill="x", expand=True)

        self.content = frame(self.root)
        self.content.pack(fill="both", expand=True)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

    def show_tab(self, key, animate=True):
        self.current_tab = key
        self.tabs[key].tkraise()
        if self.glass_tabs:
            self.glass_tabs.select(key, animate=animate)
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
        self.lbl_msg.configure(text=msg, fg=C["err"] if error else C["status"])
        if getattr(self, "_msg_job", None):
            self.root.after_cancel(self._msg_job)
        self._msg_job = self.root.after(6000, lambda: self.lbl_msg.configure(text=""))

    def _show_cursor(self, payload):
        x, y, hexc = payload
        self.lbl_cursor.configure(text=f"X {x:>5}   Y {y:>5}")
        self.swatch.configure(bg=hexc)
        self.lbl_pixel.configure(text=hexc)

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
                     random_delay_ms=st.get("random_delay_ms", 0), label=path,
                     save_log=self.settings.get("save_run_logs", True))
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
        if self._state_shown != (state, color):
            self._state_shown = (state, color)
            self.lbl_state.configure(text=state, fg=color)
        n = sum(1 for r in self.rules if r.get("enabled"))
        self.lbl_trig.configure(text=(f"Monitoring {n} rule{'s' if n != 1 else ''}" if self.triggers.running
                                      else "Monitoring off"),
                                fg=C["teal"] if self.triggers.running else C["status"])

    def _poll(self):
        batch = []
        try:
            for _ in range(2000):
                batch.append(self.q.get_nowait())
        except queue.Empty:
            pass
        if batch:
            # a fast script can post thousands of step and log updates a second; only
            # the newest of each kind is worth drawing
            last = {}
            for i, (source, kind, _p) in enumerate(batch):
                if (source, kind) in COALESCE:
                    last[(source, kind)] = i
            for i, (source, kind, payload) in enumerate(batch):
                if (source, kind) in COALESCE and last[(source, kind)] != i:
                    continue
                try:
                    self._dispatch(source, kind, payload)
                except Exception:
                    self._report_error(*sys.exc_info())
        sig = (self.job_running(), self.job.paused if self.job else None,
               self.triggers.running, self.recorder_tab.recorder.active)
        if batch or sig != self._state_sig:
            self._state_sig = sig
            self.refresh_states()
        self.root.after(15 if len(batch) >= 2000 else 40, self._poll)

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
            if kind == "cursor":
                self._show_cursor(payload)
                return
            if kind == "update":
                self._on_update_result(payload)
                return
            if kind == "stop_all":
                self.stop_all()
            elif kind == "run_script":
                self._run_script_from_trigger(payload)
            return
        if kind == "notify":
            self.toast.show("Clicker", str(payload))
            return
        if kind == "highlight":
            self.flasher.show(payload, ms=700)
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
        elif kind == "logfile":
            self.last_log_dir = payload
        elif kind == "done":
            ok, reason = payload
            if self._hid_window:
                self._hid_window = False
                self.root.deiconify()
            if ok:
                self.set_status("Finished")
            else:
                self.set_status(reason, error=not reason.startswith("Stop"))
                if not reason.startswith("Stop"):
                    more = " The run log and a screenshot are in Run Logs." if self.last_log_dir else ""
                    self.toast.show("Script stopped", reason + more, ms=9000, accent=C["rec"])
        if owner is not None and hasattr(owner, "on_job"):
            owner.on_job(kind, payload)

    # ------------------------------------------------------------ icon, settings, updates

    def _set_icon(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(base, "assets", "clicker.png")
        try:
            self._icon = tk.PhotoImage(file=path)
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def check_updates(self, force=False):
        started = updates.check_async(self.settings, lambda r: self.post("app", "update", dict(r, force=force)),
                                      force=force)
        if force and started:
            self.set_status("Checking for updates...")

    def _on_update_result(self, r):
        self.save_settings()
        if r.get("error"):
            if r.get("force"):
                self.set_status(f"Could not check for updates: {r['error']}", error=True)
            return
        if r.get("newer"):
            self.update_info = r
            self.lbl_update.configure(text=f"Update {r['tag']} available")
            if r.get("force"):
                self.open_update()
        elif r.get("force"):
            self.set_status(f"Clicker {model.APP_VERSION} is up to date.")

    def open_update(self):
        r = self.update_info
        if not r:
            return
        notes = (r.get("notes") or "").strip()
        if len(notes) > 900:
            notes = notes[:900].rstrip() + " ..."
        msg = f"Clicker {r['tag']} is available (you have {model.APP_VERSION})."
        if notes:
            msg += "\n\n" + notes
        msg += "\n\nOpen the download page?"
        if messagebox.askyesno("Update available", msg, parent=self.root):
            webbrowser.open(r["url"])

    def show_settings(self):
        d = ui.Dialog(self.root, "Settings")
        v_logs = tk.BooleanVar(value=self.settings.get("save_run_logs", True))
        v_upd = tk.BooleanVar(value=self.settings.get("check_updates", True))
        label(d.body, f"{model.APP_NAME} {model.APP_VERSION}", font=F.title).pack(anchor="w")
        label(d.body, "Auto clicker, macro recorder, screen-aware scripts and triggers.",
              muted=True).pack(anchor="w", pady=(2, 14))
        v_theme = tk.StringVar(value=theme.THEME_LABEL[theme.S["name"]])
        v_motion = tk.BooleanVar(value=not anim.motion["on"])
        row = frame(d.body)
        row.pack(anchor="w", pady=(0, 4))
        label(row, "Style", font=F.bold).pack(side="left", padx=(0, px(10)))
        combo(row, v_theme, [t[1] for t in theme.THEMES], width=22).pack(side="left")
        check(d.body, "Reduce motion (no sliding or fading)", v_motion).pack(anchor="w", pady=(0, 12))
        check(d.body, "Save a log for every script run (with a screenshot when it fails)", v_logs).pack(anchor="w")
        row = frame(d.body)
        row.pack(anchor="w", pady=(4, 12))
        Button(row, "Open Run Logs", lambda: runlog.open_folder(runlog.logs_dir()), small=True).pack(side="left")
        label(row, runlog.logs_dir(), muted=True, font=F.small).pack(side="left", padx=10)
        check(d.body, "Check for updates once a day", v_upd).pack(anchor="w")
        row = frame(d.body)
        row.pack(anchor="w", pady=(4, 0))
        Button(row, "Check now", lambda: self.check_updates(force=True), small=True).pack(side="left")
        label(row, f"Releases from github.com/{self.settings.get('update_repo') or updates.DEFAULT_REPO}",
              muted=True, font=F.small).pack(side="left", padx=10)
        problem = vision.ocr_problem()
        label(d.body, "Read Text (OCR): " + ("ready" if not problem else problem), muted=True, font=F.small,
              wraplength=460, justify="left").pack(anchor="w", pady=(14, 0))

        def ok():
            self.settings["save_run_logs"] = bool(v_logs.get())
            self.settings["check_updates"] = bool(v_upd.get())
            self.set_reduce_motion(bool(v_motion.get()))
            self.save_settings()
            d.destroy()
            chosen = {v: k for k, v in theme.THEMES}.get(v_theme.get(), theme.S["name"])
            if chosen != theme.S["name"]:
                self.root.after(50, lambda: self.set_theme(chosen))
        d.ok = ok
        d.add_buttons("Save")
        d.run()

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
        self.sampler.stop()
        self._clear_autosave()
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
