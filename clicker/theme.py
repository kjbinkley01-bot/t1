"""Themes (Classic and Liquid Glass) and small widget helpers built on tkinter.

C holds the active palette and S the active style. Both are mutated in place by
use(), so every module that imported them sees the switch; the app then rebuilds
its widgets. px() converts design pixels to screen pixels for the display's
scaling, so layouts don't clip at 125% or 150%.
"""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import anim

PALETTES = {
    "classic": {
        "bg": "#0f1113", "bar": "#0a0b0c", "panel": "#16181b", "panel_alt": "#141619",
        "head": "#1b1e21", "border": "#23262a", "line": "#1f2226", "field": "#0f1113",
        "field_bd": "#2a2d31", "text": "#e6e8ea", "muted": "#8b9097", "dim": "#5a5f66",
        "accent": "#3ecfb2", "accent_hover": "#5bdcc2", "on_accent": "#06201b", "teal": "#58d6bd",
        "btn": "#1b1e21", "btn_hover": "#23272b", "btn_bd": "#2a2d31", "danger": "#f08c8c",
        "rec": "#c93a3f", "rec_hover": "#d9494e", "sel": "#133b36", "sel_fg": "#e6f7f3",
        "running": "#1e2f2c", "ok": "#3fb950", "warn": "#d29922", "err": "#f85149", "badge": "#10302c",
        "status": "#9aa0a6", "chip": "#c9cdd2", "warn_bg": "#2d2412", "err_bg": "#2a1414",
        "err_bd": "#5b2c2c", "thumb_bd": "#2c5b54", "rim_hi": "#2a2d31", "on_rec": "#e6e8ea",
    },
    "glass_dark": {
        "bg": "#0b1020", "bar": "#0e1426", "panel": "#161e33", "panel_alt": "#131a2d",
        "head": "#1b2440", "border": "#2b3656", "line": "#222b46", "field": "#0f1528",
        "field_bd": "#303c5f", "text": "#eef2fb", "muted": "#94a0bd", "dim": "#5b6683",
        "accent": "#7cc4ff", "accent_hover": "#a3d5ff", "on_accent": "#06162b", "teal": "#7fe3f0",
        "btn": "#1f2946", "btn_hover": "#2a3659", "btn_bd": "#36446b", "danger": "#ff9e9e",
        "rec": "#ff4d6a", "rec_hover": "#ff6e86", "sel": "#26396a", "sel_fg": "#ffffff",
        "running": "#1b3a4d", "ok": "#5ee08f", "warn": "#f7c14b", "err": "#ff7a7a", "badge": "#15314f",
        "status": "#9aa6c2", "chip": "#d5dcee", "warn_bg": "#342a14", "err_bg": "#3a1a24",
        "err_bd": "#6b2c3a", "thumb_bd": "#2f5a7a", "rim_hi": "#56679a", "on_rec": "#ffffff",
    },
    "glass_light": {
        "bg": "#dde4f0", "bar": "#e8edf6", "panel": "#f7f9fd", "panel_alt": "#eef2f9",
        "head": "#eef2f9", "border": "#c9d3e5", "line": "#e1e7f2", "field": "#ffffff",
        "field_bd": "#c3cde0", "text": "#111827", "muted": "#566175", "dim": "#8e98ab",
        "accent": "#0a7cff", "accent_hover": "#3395ff", "on_accent": "#ffffff", "teal": "#0b7285",
        "btn": "#ffffff", "btn_hover": "#eef3fc", "btn_bd": "#c6d0e3", "danger": "#c62a36",
        "rec": "#e5364f", "rec_hover": "#ef5268", "sel": "#d4e5ff", "sel_fg": "#0b1b33",
        "running": "#d8f1f5", "ok": "#1e8e4a", "warn": "#a35f00", "err": "#c62a36", "badge": "#dcecff",
        "status": "#566175", "chip": "#2f3a4f", "warn_bg": "#fff1d6", "err_bg": "#fde4e7",
        "err_bd": "#f0b3bb", "thumb_bd": "#9cc3ea", "rim_hi": "#ffffff", "on_rec": "#ffffff",
    },
}
THEMES = [("classic", "Classic"), ("glass_dark", "Rounded Dark"), ("glass_light", "Rounded Light")]
THEME_LABEL = dict(THEMES)

C = dict(PALETTES["classic"])
_img_cache = {}  # rendered glass images, keyed by size and colors
S = {"name": "classic", "rounded": False, "dark": True, "scale": 1.0}


def use(name):
    """Switch the active palette and style (widgets must be rebuilt afterwards)."""
    name = name if name in PALETTES else "classic"
    C.clear()
    C.update(PALETTES[name])
    S["name"] = name
    S["rounded"] = name != "classic"
    S["dark"] = name != "glass_light"


def px(n):
    """Design pixels (at 100% scaling) to screen pixels."""
    return int(round(n * S["scale"]))


class F:
    body = bold = small = cap = mono = mono_big = title = None


def _pick(families, options, fallback):
    for name in options:
        if name in families:
            return name
    return fallback


def init(root):
    if _img_cache.get("__root__") is not root:  # images belong to one Tk interpreter
        _img_cache.clear()
        _img_cache["__root__"] = root
    try:
        S["scale"] = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        S["scale"] = 1.0
    fams = set(tkfont.families(root))
    base = _pick(fams, ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue",
                        "Inter", "Noto Sans", "DejaVu Sans"], "TkDefaultFont")
    mono = _pick(fams, ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono",
                        "DejaVu Sans Mono"], "TkFixedFont")
    F.body = tkfont.Font(root, family=base, size=10)
    F.bold = tkfont.Font(root, family=base, size=10, weight="bold")
    F.small = tkfont.Font(root, family=base, size=9)
    F.cap = tkfont.Font(root, family=base, size=8, weight="bold")
    F.mono = tkfont.Font(root, family=mono, size=10)
    F.mono_big = tkfont.Font(root, family=mono, size=18)
    F.title = tkfont.Font(root, family=base, size=12, weight="bold")

    root.configure(bg=C["bg"])
    root.option_add("*Font", F.body)
    root.option_add("*TCombobox*Listbox.background", C["panel"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["sel"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["text"])
    root.option_add("*TCombobox*Listbox.font", F.body)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["field"],
                    troughcolor=C["panel"], bordercolor=C["field_bd"], lightcolor=C["panel"],
                    darkcolor=C["border"], selectbackground=C["sel"], selectforeground=C["text"],
                    insertcolor=C["text"], font=F.body)
    style.configure("TCombobox", fieldbackground=C["field"], background=C["btn"],
                    foreground=C["text"], bordercolor=C["field_bd"], arrowsize=12, padding=(6, 3))
    style.map("TCombobox",
              fieldbackground=[("readonly", C["field"]), ("disabled", C["panel"]), ("", C["field"])],
              foreground=[("disabled", C["dim"]), ("", C["text"])],
              background=[("active", C["btn_hover"]), ("", C["btn"])],
              selectbackground=[("readonly", C["field"]), ("", C["sel"])],
              selectforeground=[("", C["text"])])
    row_h = max(28, F.body.metrics("linespace") + px(12 if S["rounded"] else 10))
    style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"],
                    foreground=C["text"], rowheight=row_h, borderwidth=0, font=F.body)
    style.map("Treeview", background=[("selected", C["sel"])], foreground=[("selected", C["sel_fg"])])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview.Heading", background=C["head"], foreground=C["muted"],
                    relief="flat", borderwidth=0, font=F.cap, padding=(px(6), px(7 if S["rounded"] else 6)))
    style.map("Treeview.Heading", background=[("active", C["head"]), ("", C["head"])],
              foreground=[("", C["muted"])])
    style.configure("TScrollbar", troughcolor=C["panel"], background=C["btn"],
                    bordercolor=C["panel"], gripcount=0, arrowcolor=C["muted"],
                    lightcolor=C["btn"], darkcolor=C["btn"])
    style.map("TScrollbar", background=[("active", C["btn_hover"]), ("", C["btn"])])
    style.configure("TScale", troughcolor=C["field_bd"], background=C["accent"],
                    bordercolor=C["panel"])
    return style


def dark_titlebar(win):
    """Match the Windows title bar to the theme (dark mode flag, and caption color on Windows 11)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1 if S["dark"] else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        r, g, b = anim.hex_rgb(C["bar"])
        colorref = ctypes.c_int(r | (g << 8) | (b << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:
        pass


# ---------------------------------------------------------------- widgets

def frame(parent, bg=None, **kw):
    return tk.Frame(parent, bg=bg or C["bg"], bd=0, highlightthickness=0, **kw)


# ---------------------------------------------------------------- glass rendering


def _cache_put(key, img):
    if len(_img_cache) > 600:
        root = _img_cache.get("__root__")
        _img_cache.clear()
        _img_cache["__root__"] = root
    _img_cache[key] = img
    return img


def pill_image(w, h, fill, rim, hi, bg, radius=None, sheen=True):
    """An anti-aliased glass capsule: fill, 1px rim, a lighter top rim and a soft top sheen."""
    w, h = max(4, int(w)), max(4, int(h))
    radius = h // 2 if radius is None else min(int(radius), h // 2, w // 2)
    key = ("pill", w, h, fill, rim, hi, bg, radius, sheen)
    hit = _img_cache.get(key)
    if hit is not None:
        return hit
    from PIL import Image, ImageDraw, ImageTk
    ss = 3
    W, H, R = w * ss, h * ss, radius * ss
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=rim)
    # the top rim catches the light: redraw the upper part of the edge in the highlight color
    top = Image.new("RGB", (W, H), bg)
    ImageDraw.Draw(top).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=hi)
    mask = Image.linear_gradient("L").resize((W, H)).point(lambda v: 255 - v)
    mask = mask.point(lambda v: 255 if v > 150 else int(v * 1.7))
    shape = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shape).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
    from PIL import ImageChops
    img.paste(top, (0, 0), ImageChops.multiply(mask, shape))
    d.rounded_rectangle([ss, ss, W - 1 - ss, H - 1 - ss], radius=max(0, R - ss), fill=fill)
    if sheen:
        inner = Image.new("L", (W, H), 0)
        ImageDraw.Draw(inner).rounded_rectangle([ss, ss, W - 1 - ss, H - 1 - ss], radius=max(0, R - ss), fill=255)
        glow = Image.linear_gradient("L").resize((W, H)).point(lambda v: max(0, 60 - v // 2))
        white = Image.new("RGB", (W, H), "#ffffff")
        img.paste(white, (0, 0), ImageChops.multiply(glow, inner))
    out = ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS))
    return _cache_put(key, out)


def corner_images(r, fill, rim, hi, bg):
    """Four anti-aliased panel corners (tl, tr, bl, br) of radius r."""
    key = ("corners", r, fill, rim, hi, bg)
    hit = _img_cache.get(key)
    if hit is not None:
        return hit
    from PIL import Image, ImageDraw, ImageTk
    ss = 4
    R = r * ss
    out = []
    for corner, edge in (("tl", hi), ("tr", hi), ("bl", rim), ("br", rim)):
        big = Image.new("RGB", (2 * R, 2 * R), bg)
        d = ImageDraw.Draw(big)
        d.ellipse([0, 0, 2 * R - 1, 2 * R - 1], fill=edge)
        d.ellipse([ss, ss, 2 * R - 1 - ss, 2 * R - 1 - ss], fill=fill)
        box = {"tl": (0, 0, R, R), "tr": (R, 0, 2 * R, R), "bl": (0, R, R, 2 * R), "br": (R, R, 2 * R, 2 * R)}[corner]
        out.append(ImageTk.PhotoImage(big.crop(box).resize((r, r), Image.LANCZOS)))
    return _cache_put(key, tuple(out))


class GlassPanel(tk.Frame):
    """A rounded glass card. Children pack or grid inside it like a normal frame.

    The rounded shape is drawn on a canvas stacked under the children; the
    frame's own padding keeps children clear of the rounded corners.
    """

    def __init__(self, parent, **kw):
        self.r = px(14)
        inset = max(2, int(self.r * 0.3) + 1)
        outer = parent["bg"]
        super().__init__(parent, bg=C["panel"], bd=0, highlightthickness=0, padx=inset, pady=inset, **kw)
        self.cv = tk.Canvas(self, bg=outer, highlightthickness=0, bd=0)
        # place() measures from inside the frame's padding, so reach back over it
        self.cv.place(x=-inset, y=-inset, relwidth=1, relheight=1, width=2 * inset, height=2 * inset)
        tk.Misc.lower(self.cv)
        r, cv = self.r, self.cv
        imgs = corner_images(r, C["panel"], C["border"], C["rim_hi"], outer)
        self._imgs = imgs
        self.items = {
            "fill_h": cv.create_rectangle(0, 0, 0, 0, fill=C["panel"], width=0),
            "fill_v": cv.create_rectangle(0, 0, 0, 0, fill=C["panel"], width=0),
            "top": cv.create_line(0, 0, 0, 0, fill=C["rim_hi"]),
            "bottom": cv.create_line(0, 0, 0, 0, fill=C["border"]),
            "left": cv.create_line(0, 0, 0, 0, fill=C["border"]),
            "right": cv.create_line(0, 0, 0, 0, fill=C["border"]),
        }
        for name, img in zip(("tl", "tr", "bl", "br"), imgs):
            self.items[name] = cv.create_image(0, 0, image=img, anchor="nw")
        cv.bind("<Configure>", self._layout)

    def _layout(self, e):
        w, h, r, cv, it = e.width, e.height, self.r, self.cv, self.items
        if w < 2 * r or h < 2 * r:
            return
        cv.coords(it["fill_h"], 0, r, w, h - r)
        cv.coords(it["fill_v"], r, 0, w - r, h)
        cv.coords(it["top"], r, 0, w - r, 0)
        cv.coords(it["bottom"], r, h - 1, w - r, h - 1)
        cv.coords(it["left"], 0, r, 0, h - r)
        cv.coords(it["right"], w - 1, r, w - 1, h - r)
        cv.coords(it["tl"], 0, 0)
        cv.coords(it["tr"], w - r, 0)
        cv.coords(it["bl"], 0, h - r)
        cv.coords(it["br"], w - r, h - r)


def panel(parent, **kw):
    if S["rounded"]:
        return GlassPanel(parent, **kw)
    return tk.Frame(parent, bg=C["panel"], bd=0, highlightthickness=1,
                    highlightbackground=C["border"], highlightcolor=C["border"], **kw)


def label(parent, text="", bg=None, muted=False, font=None, fg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent["bg"], bd=0,
                    fg=fg or (C["muted"] if muted else C["text"]), font=font or F.body, **kw)


def cap(parent, text, bg=None):
    return label(parent, text.upper(), bg=bg, muted=True, font=F.cap)


def vsep(parent, bg=None, height=22):
    return tk.Frame(parent, bg=C["field_bd"], width=1, height=px(height))


class Button(tk.Label):
    """A flat button (Classic) or a glossy glass capsule (Liquid Glass) with animated hover."""

    KINDS = {
        "normal": ("btn", "btn_hover", "text", "btn_bd"),
        "primary": ("accent", "accent_hover", "on_accent", "accent"),
        "danger": ("btn", "btn_hover", "danger", "btn_bd"),
        "record": ("rec", "rec_hover", "on_rec", "rec"),
        "ghost": ("panel", "btn_hover", "muted", "panel"),
    }

    def __init__(self, parent, text, command=None, kind="normal", width=None, big=False, small=False):
        self.kind = kind
        self.glass = S["rounded"]
        self._command = command
        self.enabled = True
        self._hover = 0.0
        self._pressed = False
        font = F.bold if kind in ("primary", "record") or big else (F.small if small else F.body)
        bg, _, fg, bd = (C[k] for k in self.KINDS[kind])
        if self.glass:
            self._outer = parent["bg"]
            self._padx = px(10 if small else 16)
            self._pady = px(12 if big else (3 if small else 6))
            self._font = font
            self._alloc = (0, 0)  # room the layout gives us beyond the natural size
            self._min_w = (width * font.measure("0") + 2 * self._padx) if width else 0
            super().__init__(parent, text=text, fg=fg, bg=self._outer, font=font, cursor="hand2",
                             compound="center", bd=0, highlightthickness=0, padx=0, pady=0)
            self._size = None
            self._resize_job = None
            self._render()
            self.bind("<Configure>", self._on_configure)
        else:
            super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2", font=font,
                             padx=px(10 if small else 14), pady=px(12 if big else (2 if small else 5)),
                             highlightthickness=1, highlightbackground=bd, bd=0)
            if width:
                self.configure(width=width)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._click)

    # ---- glass drawing

    def _natural(self):
        w = self._font.measure(self.cget("text")) + 2 * self._padx
        h = self._font.metrics("linespace") + 2 * self._pady
        return max(w, self._min_w), h

    def _colors(self):
        return [C[k] for k in self.KINDS[self.kind]]

    def _render(self, size=None):
        if size is None:
            size = self._size or self._natural()
        self._size = size
        w, h = size
        if not self.enabled:
            fill, rim, fg = C["panel_alt"], C["line"], C["dim"]
            hi = C["line"]
        else:
            base, hover, fg, rim = self._colors()
            fill = anim.mix(base, hover, self._hover)
            if self._pressed:
                fill = anim.mix(fill, C["bg"], 0.18)
            hi = C["rim_hi"] if self.kind in ("normal", "danger", "ghost") else anim.mix(fill, "#ffffff", 0.45)
            if self.kind in ("primary", "record"):
                rim = anim.mix(fill, "#000000", 0.12)
        img = pill_image(w, h, fill, rim, hi, self._outer, radius=min(h // 2, px(12)))
        self.configure(image=img, fg=fg, width=w, height=h)
        self._img = img

    def _target_size(self):
        nw, nh = self._natural()
        return max(nw, self._alloc[0]), max(nh, self._alloc[1])

    def _on_configure(self, e):
        # stretch the capsule when the layout gives the button more room (fill="x", sticky="ew")
        self._alloc = (e.width, e.height)
        if self._target_size() == self._size:
            return
        # while the window is being dragged to a new size, redraw once it settles
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(70, self._settle)

    def _settle(self):
        self._resize_job = None
        if self.winfo_exists():
            self._render(self._target_size())

    def _animate_hover(self, target):
        start = self._hover

        def step(t):
            self._hover = start + (target - start) * t
            self._render()
        anim.Tween(self, 130, step, key="hover")

    # ---- events

    def _enter(self, _e):
        if not self.enabled:
            return
        if self.glass:
            self._animate_hover(1.0)
        else:
            self.configure(bg=self._colors()[1])

    def _leave(self, _e):
        self._pressed = False
        if not self.enabled:
            return
        if self.glass:
            self._animate_hover(0.0)
        else:
            self.configure(bg=self._colors()[0])

    def _press(self, _e):
        if self.enabled and self.glass:
            self._pressed = True
            self._render()

    def _click(self, e):
        was = self._pressed
        self._pressed = False
        if self.glass and was:
            self._render()
        if not self.enabled or not self._command:
            return
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self._command()

    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        if self.glass:
            self._hover = 0.0
            self.configure(cursor="hand2" if on else "arrow")
            self._render()
            return
        bg, _, fg, bd = self._colors()
        if on:
            self.configure(bg=bg, fg=fg, cursor="hand2", highlightbackground=bd)
        else:
            self.configure(bg=C["panel_alt"], fg=C["dim"], cursor="arrow", highlightbackground=C["line"])

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        if self.glass:
            self._render()
            return
        bg, _, fg, bd = self._colors()
        if self.enabled:
            self.configure(bg=bg, fg=fg, highlightbackground=bd)

    def set_text(self, text):
        if self.cget("text") != text:
            self.configure(text=text)
            if self.glass:
                self._render(self._target_size())


def entry(parent, var, width=10, mono=False, readonly=False, justify="left"):
    e = tk.Entry(parent, textvariable=var, width=width, font=F.mono if mono else F.body,
                 bg=C["field"], fg=C["text"], insertbackground=C["text"], relief="flat", bd=4,
                 highlightthickness=1, highlightbackground=C["field_bd"], highlightcolor=C["accent"],
                 disabledbackground=C["panel_alt"], disabledforeground=C["dim"],
                 readonlybackground=C["field"], selectbackground=C["sel"],
                 selectforeground=C["text"], justify=justify)
    if readonly:
        e.configure(state="readonly")
    return e


def check(parent, text, var, command=None, bg=None):
    bg = bg or parent["bg"]
    return tk.Checkbutton(parent, text=text, variable=var, command=command, bg=bg, fg=C["text"],
                          activebackground=bg, activeforeground=C["text"], selectcolor=C["field"],
                          highlightthickness=0, bd=0, font=F.body, anchor="w", cursor="hand2")


def combo(parent, var, values, width=18, editable=False):
    cb = ttk.Combobox(parent, textvariable=var, values=list(values), width=width,
                      state="normal" if editable else "readonly", font=F.body)
    if not editable:
        cb.bind("<<ComboboxSelected>>", lambda e: cb.selection_clear())
    return cb


def text_box(parent, height=6, mono=True, **kw):
    return tk.Text(parent, height=height, bg=C["field"], fg=C["text"], insertbackground=C["text"],
                   relief="flat", bd=6, highlightthickness=1, highlightbackground=C["field_bd"],
                   highlightcolor=C["accent"], font=F.mono if mono else F.body,
                   selectbackground=C["sel"], selectforeground=C["text"], wrap="word", **kw)


def listbox(parent, height=5, **kw):
    return tk.Listbox(parent, height=height, bg=C["panel_alt"], fg=C["text"], bd=0,
                      highlightthickness=1, highlightbackground=C["line"],
                      highlightcolor=C["line"], selectbackground=C["sel"],
                      selectforeground=C["text"], activestyle="none", font=F.body, **kw)


def dot(parent, color, bg=None, size=8):
    c = tk.Canvas(parent, width=size, height=size, bg=bg or parent["bg"], highlightthickness=0, bd=0)
    c.create_oval(0, 0, size - 1, size - 1, fill=color, outline=color)
    return c


def scrolled_tree(parent, columns, bg=None):
    """Treeview with a vertical scrollbar in a frame. Returns (frame, tree).

    Column widths are design pixels; they are scaled for the display and never
    made narrower than their heading text.
    """
    box = frame(parent, bg=bg or C["panel"])
    # a small requested height lets the list shrink and grow with the window instead of
    # pushing the panels below it off screen
    tree = ttk.Treeview(box, columns=[c[0] for c in columns], show="headings", selectmode="browse", height=4)
    for cid, text, width, stretch in columns:
        need = F.cap.measure(text.upper()) + px(18)
        w = max(px(width), need)
        tree.heading(cid, text=text.upper(), anchor="w")
        tree.column(cid, width=w, minwidth=need, stretch=stretch, anchor="w")
    sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tree.tag_configure("odd", background=C["panel_alt"])
    tree.tag_configure("even", background=C["panel"])
    tree.tag_configure("screen", foreground=C["teal"])
    tree.tag_configure("running", background=C["running"])
    tree.tag_configure("error", foreground=C["err"])
    return box, tree
