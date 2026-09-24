"""Sleek dark theme and small widget helpers built on tkinter."""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

C = {
    "bg": "#0f1113",
    "bar": "#0a0b0c",
    "panel": "#16181b",
    "panel_alt": "#141619",
    "head": "#1b1e21",
    "border": "#23262a",
    "line": "#1f2226",
    "field": "#0f1113",
    "field_bd": "#2a2d31",
    "text": "#e6e8ea",
    "muted": "#8b9097",
    "dim": "#5a5f66",
    "accent": "#3ecfb2",
    "accent_hover": "#5bdcc2",
    "on_accent": "#06201b",
    "teal": "#58d6bd",
    "btn": "#1b1e21",
    "btn_hover": "#23272b",
    "btn_bd": "#2a2d31",
    "danger": "#f08c8c",
    "rec": "#c93a3f",
    "rec_hover": "#d9494e",
    "sel": "#133b36",
    "running": "#1e2f2c",
    "ok": "#3fb950",
    "warn": "#d29922",
    "err": "#f85149",
    "badge": "#10302c",
}


class F:
    body = bold = small = cap = mono = mono_big = title = None


def _pick(families, options, fallback):
    for name in options:
        if name in families:
            return name
    return fallback


def init(root):
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
    style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"],
                    foreground=C["text"], rowheight=28, borderwidth=0, font=F.body)
    style.map("Treeview", background=[("selected", C["sel"])], foreground=[("selected", "#e6f7f3")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Treeview.Heading", background=C["head"], foreground=C["muted"],
                    relief="flat", borderwidth=0, font=F.cap, padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", C["head"]), ("", C["head"])],
              foreground=[("", C["muted"])])
    style.configure("TScrollbar", troughcolor=C["panel"], background=C["btn"],
                    bordercolor=C["panel"], gripcount=0)
    style.map("TScrollbar", background=[("active", C["btn_hover"]), ("", C["btn"])])
    style.configure("TScale", troughcolor=C["field_bd"], background=C["accent"],
                    bordercolor=C["panel"])
    return style


def dark_titlebar(win):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        value = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


# ---------------------------------------------------------------- widgets

def frame(parent, bg=None, **kw):
    return tk.Frame(parent, bg=bg or C["bg"], bd=0, highlightthickness=0, **kw)


def panel(parent, **kw):
    return tk.Frame(parent, bg=C["panel"], bd=0, highlightthickness=1,
                    highlightbackground=C["border"], highlightcolor=C["border"], **kw)


def label(parent, text="", bg=None, muted=False, font=None, fg=None, **kw):
    return tk.Label(parent, text=text, bg=bg or parent["bg"], bd=0,
                    fg=fg or (C["muted"] if muted else C["text"]), font=font or F.body, **kw)


def cap(parent, text, bg=None):
    return label(parent, text.upper(), bg=bg, muted=True, font=F.cap)


def vsep(parent, bg=None, height=22):
    return tk.Frame(parent, bg=C["field_bd"], width=1, height=height)


class Button(tk.Label):
    KINDS = {
        "normal": ("btn", "btn_hover", "text", "btn_bd"),
        "primary": ("accent", "accent_hover", "on_accent", "accent"),
        "danger": ("btn", "btn_hover", "danger", "btn_bd"),
        "record": ("rec", "rec_hover", "text", "rec"),
        "ghost": ("panel", "btn_hover", "muted", "panel"),
    }

    def __init__(self, parent, text, command=None, kind="normal", width=None, big=False, small=False):
        self.kind = kind
        bg, _, fg, bd = (C[k] for k in self.KINDS[kind])
        super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                         font=F.bold if kind in ("primary", "record") or big else (F.small if small else F.body),
                         padx=10 if small else 14, pady=(12 if big else (2 if small else 5)),
                         highlightthickness=1, highlightbackground=bd, bd=0)
        if width:
            self.configure(width=width)
        self._command = command
        self.enabled = True
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)

    def _colors(self):
        return [C[k] for k in self.KINDS[self.kind]]

    def _enter(self, _e):
        if self.enabled:
            self.configure(bg=self._colors()[1])

    def _leave(self, _e):
        if self.enabled:
            self.configure(bg=self._colors()[0])

    def _click(self, e):
        if not self.enabled or not self._command:
            return
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height():
            self._command()

    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        bg, _, fg, bd = self._colors()
        if on:
            self.configure(bg=bg, fg=fg, cursor="hand2", highlightbackground=bd)
        else:
            self.configure(bg=C["panel_alt"], fg=C["dim"], cursor="arrow", highlightbackground=C["line"])

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        bg, _, fg, bd = self._colors()
        if self.enabled:
            self.configure(bg=bg, fg=fg, highlightbackground=bd)

    def set_text(self, text):
        if self.cget("text") != text:
            self.configure(text=text)


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
    """Treeview with a vertical scrollbar in a frame. Returns (frame, tree)."""
    box = frame(parent, bg=bg or C["panel"])
    tree = ttk.Treeview(box, columns=[c[0] for c in columns], show="headings", selectmode="browse")
    for cid, text, width, stretch in columns:
        tree.heading(cid, text=text.upper(), anchor="w")
        tree.column(cid, width=width, minwidth=30, stretch=stretch, anchor="w")
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
