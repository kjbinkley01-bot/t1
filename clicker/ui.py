"""Overlays and dialogs: region picker, match highlight, countdown, toasts, prompts."""

import sys
import tkinter as tk

import numpy as np
from PIL import Image, ImageTk

from . import inputs, triggers, vision
from .theme import C, F, Button, check, combo, dark_titlebar, entry, frame, label, text_box


# ---------------------------------------------------------------- region picker

def select_region(root, callback, prompt="Drag to select an area. Esc cancels."):
    """Hide the app, freeze the screen, let the user drag a box.

    callback(region, image) gets region [x, y, w, h] and the cropped BGR image,
    or (None, None) if cancelled.
    """
    state = {"win": None}
    was_top = str(root.attributes("-topmost")).lower() in ("1", "true")
    root.withdraw()

    def begin():
        try:
            frame_img, (ox, oy) = vision.capture(None)
        except Exception:
            root.deiconify()
            callback(None, None)
            return
        h, w = frame_img.shape[:2]
        rgb = vision.to_rgb(frame_img)
        dim = (rgb.astype(np.float32) * 0.45).astype(np.uint8)
        win = tk.Toplevel(root)
        state["win"] = win
        win.overrideredirect(True)
        win.geometry(f"{w}x{h}+{ox}+{oy}")
        win.attributes("-topmost", True)
        canvas = tk.Canvas(win, width=w, height=h, highlightthickness=0, bd=0, cursor="crosshair",
                           bg="black")
        canvas.pack()
        dim_photo = ImageTk.PhotoImage(Image.fromarray(dim))
        full = Image.fromarray(rgb)
        canvas.create_image(0, 0, image=dim_photo, anchor="nw")
        canvas.dim_photo = dim_photo
        pw, ph = 420, 40
        _, _, sw, sh = vision.primary_screen()
        px = max(0, (sw - pw) // 2 - ox)
        canvas.create_rectangle(px, 24 - oy + 0, px + pw, 24 - oy + ph, fill=C["panel"], outline=C["border"])
        canvas.create_text(px + pw // 2, 24 - oy + ph // 2, text=prompt, fill=C["text"], font=F.body)
        sel = {"start": None, "rect": None, "img": None, "photo": None, "size": None}

        def finish(region):
            try:
                win.destroy()
            finally:
                root.deiconify()
                root.attributes("-topmost", was_top)
                root.lift()
            if region is None:
                callback(None, None)
                return
            x, y, rw, rh = region
            crop = frame_img[y - oy:y - oy + rh, x - ox:x - ox + rw].copy()
            callback(region, crop)

        def press(e):
            sel["start"] = (e.x, e.y)

        def drag(e):
            if not sel["start"]:
                return
            x0, y0 = sel["start"]
            x1, y1 = max(0, min(w - 1, e.x)), max(0, min(h - 1, e.y))
            l, t, r, b = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
            for key in ("img", "rect", "size"):
                if sel[key]:
                    canvas.delete(sel[key])
            if r - l > 1 and b - t > 1:
                photo = ImageTk.PhotoImage(full.crop((l, t, r, b)))
                sel["photo"] = photo
                sel["img"] = canvas.create_image(l, t, image=photo, anchor="nw")
            sel["rect"] = canvas.create_rectangle(l, t, r, b, outline=C["accent"], width=2)
            sel["size"] = canvas.create_text(l, max(12, t - 12), anchor="w", fill=C["accent"],
                                             text=f"{l + ox}, {t + oy}   {r - l} x {b - t}", font=F.mono)

        def release(e):
            if not sel["start"]:
                return
            x0, y0 = sel["start"]
            x1, y1 = max(0, min(w - 1, e.x)), max(0, min(h - 1, e.y))
            l, t, r, b = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
            if r - l < 3 or b - t < 3:
                sel["start"] = None
                return
            finish([l + ox, t + oy, r - l, b - t])

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", release)
        canvas.bind("<ButtonPress-3>", lambda e: finish(None))
        win.bind("<Escape>", lambda e: finish(None))
        win.focus_force()
        win.grab_set()

    root.after(300, begin)


# ---------------------------------------------------------------- highlight

def flash(root, rect, ms=900, color=None):
    x, y, w, h = (int(v) for v in rect)
    pad = 3
    win = tk.Toplevel(root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.geometry(f"{w + pad * 2}x{h + pad * 2}+{x - pad}+{y - pad}")
    key = "#ff00fe"
    if sys.platform == "win32":
        win.configure(bg=key)
        win.attributes("-transparentcolor", key)
    else:
        win.configure(bg=key)
        try:
            win.attributes("-alpha", 0.5)
        except tk.TclError:
            pass
    cv = tk.Canvas(win, width=w + pad * 2, height=h + pad * 2, bg=key, highlightthickness=0, bd=0)
    cv.pack()
    cv.create_rectangle(1, 1, w + pad * 2 - 2, h + pad * 2 - 2, outline=color or C["accent"], width=3)
    try:
        win.attributes("-disabled", True)
    except tk.TclError:
        pass
    win.after(ms, win.destroy)


# ---------------------------------------------------------------- toasts

class Toast:
    def __init__(self, root):
        self.root = root
        self.win = None
        self.job = None

    def show(self, title, message, ms=5000, accent=None):
        self.hide()
        win = tk.Toplevel(self.root)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C["border"])
        body = frame(win, bg=C["panel"])
        body.pack(padx=1, pady=1)
        bar = tk.Frame(body, bg=accent or C["accent"], width=3)
        bar.pack(side="left", fill="y")
        inner = frame(body, bg=C["panel"])
        inner.pack(side="left", padx=14, pady=10)
        label(inner, title, font=F.bold).pack(anchor="w")
        if message:
            label(inner, message, muted=True, wraplength=320, justify="left").pack(anchor="w", pady=(2, 0))
        win.update_idletasks()
        _, _, sw, sh = vision.primary_screen()
        ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{sw - ww - 24}+{sh - wh - 72}")
        for w in (win, body, inner) + tuple(inner.winfo_children()):
            w.bind("<Button-1>", lambda e: self.hide())
        if ms:
            self.job = self.root.after(ms, self.hide)

    def hide(self):
        if self.job:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
        if self.win:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


def countdown(root, toast, seconds, title, on_done):
    def tick(n):
        if n <= 0:
            toast.hide()
            on_done()
            return
        toast.show(f"{title} in {n}", "Move the cursor to the target now.", ms=0)
        root.after(1000, tick, n - 1)
    tick(int(seconds))


# ---------------------------------------------------------------- dialogs

class Dialog(tk.Toplevel):
    def __init__(self, root, title):
        super().__init__(root)
        self.withdraw()
        self.title(title)
        self.configure(bg=C["bg"])
        self.transient(root)
        self.resizable(False, False)
        self.result = None
        self.body = frame(self)
        self.body.pack(fill="both", expand=True, padx=18, pady=16)
        self.buttons = frame(self)
        self.buttons.pack(fill="x", padx=18, pady=(0, 16))
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def add_buttons(self, ok_text="OK"):
        Button(self.buttons, ok_text, self.ok, kind="primary").pack(side="right")
        Button(self.buttons, "Cancel", self.cancel).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda e: self.ok())

    def run(self):
        self.update_idletasks()
        m = self.master
        x = m.winfo_rootx() + max(0, (m.winfo_width() - self.winfo_reqwidth()) // 2)
        y = m.winfo_rooty() + max(0, (m.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        dark_titlebar(self)
        self.grab_set()
        self.focus_force()
        self.wait_window()
        return self.result

    def ok(self):
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


def ask_string(root, title, prompt, default=""):
    d = Dialog(root, title)
    var = tk.StringVar(value=default)
    label(d.body, prompt).pack(anchor="w", pady=(0, 6))
    e = entry(d.body, var, width=36)
    e.pack(fill="x")
    e.focus_set()
    e.select_range(0, "end")

    def ok():
        d.result = var.get()
        d.destroy()
    d.ok = ok
    d.add_buttons()
    return d.run()


def ask_choice(root, title, prompt, choices):
    d = Dialog(root, title)
    var = tk.StringVar(value=choices[0] if choices else "")
    label(d.body, prompt).pack(anchor="w", pady=(0, 6))
    combo(d.body, var, choices, width=34).pack(fill="x")

    def ok():
        d.result = var.get()
        d.destroy()
    d.ok = ok
    d.add_buttons()
    return d.run()


def ask_inputs(root, inputs, current):
    """Prompt for script inputs. Returns dict or None."""
    d = Dialog(root, "Script inputs")
    label(d.body, "Fill in the values this script needs.", muted=True).pack(anchor="w", pady=(0, 10))
    vars_ = {}
    for item in inputs:
        name = item["name"]
        label(d.body, item.get("label") or name, font=F.bold).pack(anchor="w")
        v = tk.StringVar(value=current.get(name, item.get("default", "")))
        entry(d.body, v, width=40).pack(fill="x", pady=(2, 10))
        vars_[name] = v

    def ok():
        d.result = {k: v.get() for k, v in vars_.items()}
        d.destroy()
    d.ok = ok
    d.add_buttons("Run")
    return d.run()


def ask_text(root, title, prompt):
    d = Dialog(root, title)
    d.resizable(True, True)
    label(d.body, prompt, muted=True, wraplength=560, justify="left").pack(anchor="w", pady=(0, 8))
    box = text_box(d.body, height=18, width=80)
    box.pack(fill="both", expand=True)
    box.focus_set()

    def ok():
        d.result = box.get("1.0", "end")
        d.destroy()
    d.ok = ok
    d.add_buttons("Import")
    d.unbind("<Return>")
    return d.run()


def edit_output(root, output=None, toast=None):
    output = dict(output or {"type": "click_match", "value": "left"})
    d = Dialog(root, "Trigger output")
    tvar = tk.StringVar(value=triggers.OUTPUT_LABEL.get(output.get("type"), triggers.OUTPUT_TYPES[0][1]))
    vvar = tk.StringVar(value=str(output.get("value") or ""))
    label(d.body, "Do this", font=F.bold).pack(anchor="w")
    combo(d.body, tvar, [t[1] for t in triggers.OUTPUT_TYPES], width=36).pack(fill="x", pady=(2, 10))
    vlabel = label(d.body, "Value", font=F.bold)
    vlabel.pack(anchor="w")
    vrow = frame(d.body)
    vrow.pack(fill="x", pady=(2, 4))
    ventry = entry(vrow, vvar, width=32)
    ventry.pack(side="left", fill="x", expand=True)

    def grab():
        d.grab_release()
        d.withdraw()

        def done():
            x, y = inputs.position()
            parts = [p.strip() for p in vvar.get().split(",")]
            extra = f", {parts[2]}" if len(parts) > 2 and parts[2] else ""
            vvar.set(f"{x}, {y}{extra}")
            d.deiconify()
            d.grab_set()
            d.focus_force()
        countdown(root, toast or Toast(root), 3, "Grabbing position", done)

    grab_btn = Button(vrow, "Grab", grab, small=True)
    grab_btn.pack(side="left", padx=(6, 0))
    hint = label(d.body, "", muted=True, font=F.small)
    hint.pack(anchor="w")

    def refresh(*_):
        tid = triggers.OUTPUT_ID.get(tvar.get())
        grab_btn.set_enabled(tid == "click_at")
        if tid in triggers.NO_VALUE:
            ventry.configure(state="disabled")
            hint.configure(text="No value needed.")
        else:
            ventry.configure(state="normal")
            hint.configure(text=triggers.OUTPUT_HINT.get(tid, ""))
    tvar.trace_add("write", refresh)
    refresh()

    def ok():
        tid = triggers.OUTPUT_ID.get(tvar.get())
        val = "" if tid in triggers.NO_VALUE else vvar.get().strip()
        if tid == "click_at":
            parts = [p.strip() for p in val.split(",")]
            if len(parts) < 2 or not all(p.lstrip("-").isdigit() for p in parts[:2]):
                hint.configure(text="Enter a position like 640, 410", fg=C["err"])
                return
        if tid in ("wait_ms", "wait_vanish", "rewind"):
            try:
                float(val or "0")
            except ValueError:
                hint.configure(text="Enter a number", fg=C["err"])
                return
        if tid in ("press_keys", "type_text", "run_script") and not val:
            hint.configure(text="This output needs a value", fg=C["err"])
            return
        d.result = {"type": tid, "value": val}
        d.destroy()
    d.ok = ok
    d.add_buttons()
    return d.run()


def thumbnail(img, max_w, max_h):
    """BGR ndarray -> PhotoImage scaled to fit."""
    pil = Image.fromarray(vision.to_rgb(img))
    pil.thumbnail((max_w, max_h))
    return ImageTk.PhotoImage(pil)
