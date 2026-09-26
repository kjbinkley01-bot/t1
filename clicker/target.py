"""Background mode: run a script inside one window while you keep using your computer.

A script can name a target window (by title and/or program). Then:

* input goes to that window instead of your real mouse and keyboard, with one of two methods
    - "messages": clicks, keys and text are posted to the window as Windows messages. Nothing on your
      desktop moves. Works with most normal apps; apps that read the physical mouse ignore it.
    - "quickswitch": the window is brought forward for a moment, real input is sent, then your previous
      window and cursor position are put back. Works with nearly everything (including apps and games
      that read raw input), at the cost of a very brief flicker of focus.
* screen checks (images, pixels, Read Text) read the window's own picture, so they work while it is
  covered by other windows,
* positions are relative to the window's content area, so moving the window doesn't break scripts.

The Windows parts live in WinBackend. Everything else talks to a backend object, so tests can use a
fake one and the module imports cleanly on any system.
"""

import math
import re
import sys
import threading
import time

from . import glide
from .inputs_names import canonical, split_combo

METHODS = [("messages", "Background messages (your mouse stays free)"),
           ("quickswitch", "Quick switch (works with more apps, briefly takes focus)")]
METHOD_LABEL = dict(METHODS)
METHOD_ID = {v: k for k, v in METHODS}

DEFAULT_TARGET = {"title": "", "process": "", "method": "messages", "restore_minimized": True,
                  "focus_messages": True}


def normalize(target):
    """A clean target dict, or None when the script runs on the whole screen."""
    if not isinstance(target, dict):
        return None
    t = dict(DEFAULT_TARGET)
    t.update({k: target[k] for k in DEFAULT_TARGET if k in target})
    t["title"] = str(t["title"] or "").strip()
    t["process"] = str(t["process"] or "").strip()
    if t["method"] not in METHOD_LABEL:
        t["method"] = "messages"
    if not t["title"] and not t["process"]:
        return None
    return t


def describe(target):
    t = normalize(target)
    if not t:
        return "Whole screen"
    who = t["title"] or t["process"]
    if t["title"] and t["process"]:
        who = f"{t['title']} ({t['process']})"
    return f"{who} · {'background' if t['method'] == 'messages' else 'quick switch'}"


class WindowNotFound(RuntimeError):
    pass


# ---------------------------------------------------------------- key names -> Windows virtual keys

VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "pause": 0x13,
    "caps_lock": 0x14, "esc": 0x1B, "space": 0x20, "page_up": 0x21, "page_down": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "print_screen": 0x2C,
    "insert": 0x2D, "delete": 0x2E, "cmd": 0x5B, "menu": 0x5D, "num_lock": 0x90, "scroll_lock": 0x91,
    "shift_l": 0xA0, "shift_r": 0xA1, "ctrl_l": 0xA2, "ctrl_r": 0xA3, "alt_l": 0xA4, "alt_r": 0xA5,
    "alt_gr": 0xA5, "cmd_l": 0x5B, "cmd_r": 0x5C, "media_play_pause": 0xB3, "media_next": 0xB0,
    "media_previous": 0xB1, "media_volume_up": 0xAF, "media_volume_down": 0xAE, "media_volume_mute": 0xAD,
}
VK.update({f"f{i}": 0x6F + i for i in range(1, 25)})
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0xA3, 0xA5, 0x90}
MOD_VK = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "cmd": 0x5B}


def key_to_vk(name, char_vk=None):
    """A key name as used in scripts ('enter', 'f5', 'a', '+', 'vk65') -> (vk, needs_shift)."""
    n = canonical(name)
    if n in VK:
        return VK[n], False
    m = re.fullmatch(r"vk_?(\d+)", n)
    if m:
        return int(m.group(1)), False
    if len(n) == 1:
        if char_vk:
            return char_vk(n)
        c = n.upper()
        if "A" <= c <= "Z" or "0" <= c <= "9":
            return ord(c), n.isupper()
    raise ValueError(f"Unknown key '{name}'")


def parse_combo(text):
    return split_combo(text)


def recorded_vk(ev, char_vk=None):
    """The virtual key of a recorded key event ({'key': 'enter'} or {'char': 'a', 'vk': 65})."""
    if ev.get("key"):
        return key_to_vk(ev["key"])[0]
    if ev.get("vk") is not None:
        return int(ev["vk"])
    if ev.get("char"):
        return key_to_vk(ev["char"], char_vk)[0]
    raise ValueError("Recorded key has no name")


# ---------------------------------------------------------------- targeted input and capture

class WindowIO:
    """The same calls the runner makes on the inputs module, aimed at one window.

    Coordinates are relative to the window's content (client) area. The virtual cursor
    remembers the last position so "click where the cursor is" steps keep working.
    """

    def __init__(self, target, backend=None):
        self.target = normalize(target)
        if not self.target:
            raise ValueError("No target window")
        self._backend = backend
        self.hwnd = None
        self._shot = None  # (time, image): a capture is reused for a few ms so back-to-back checks share it
        self.cursor = (0, 0)
        self.held = set()
        self._lock = threading.Lock()

    @property
    def b(self):
        if self._backend is None:
            try:
                self._backend = default_backend()
            except RuntimeError as e:
                raise WindowNotFound(str(e))
        return self._backend

    # ---- window

    def attach(self):
        """Find the window (and restore it behind others if it is minimized). Raises WindowNotFound."""
        t = self.target
        hwnd = self.hwnd if self.hwnd and self.b.is_window(self.hwnd) else None
        if hwnd is None:
            hwnd = self.b.find_window(t["title"], t["process"])
        if hwnd is None:
            who = t["title"] or t["process"]
            raise WindowNotFound(f"Target window '{who}' is not open")
        if t["restore_minimized"] and self.b.is_minimized(hwnd):
            self.b.restore_behind(hwnd)
            time.sleep(0.15)
        self.hwnd = hwnd
        return hwnd

    def client_origin(self):
        return self.b.client_origin(self.attach())

    def to_screen(self, rect):
        ox, oy = self.client_origin()
        x, y, w, h = rect
        return x + ox, y + oy, w, h

    # ---- capture (used by vision through WindowSource)

    def grab(self, x, y, w, h):
        now = time.monotonic()
        if self._shot is None or now - self._shot[0] > 0.03:
            self._shot = (now, self.b.capture_client(self.attach()))
        return crop(self._shot[1], x, y, w, h)

    def bounds(self):
        w, h = self.b.client_size(self.attach())
        return 0, 0, w, h

    # ---- mouse

    def position(self):
        return self.cursor

    def move_to(self, x, y):
        self.cursor = (int(x), int(y))
        if self.target["method"] == "messages":
            self.b.post_mouse(self.attach(), "move", self.cursor, None, self._mods())

    def smooth_move(self, x, y, duration=0.12, curve=False):
        sx, sy = self.cursor
        pts = glide.points(sx, sy, x, y, duration, curve)
        for p in pts:
            self.move_to(*p)
            time.sleep(duration / len(pts))

    def move_by(self, dx, dy):
        self.move_to(self.cursor[0] + int(dx), self.cursor[1] + int(dy))

    def move_by_angle(self, angle_deg, distance):
        a = math.radians(float(angle_deg))
        self.move_to(self.cursor[0] + math.cos(a) * float(distance), self.cursor[1] - math.sin(a) * float(distance))

    def _mods(self):
        return tuple(m for m in ("ctrl", "shift", "alt") if MOD_VK[m] in self.held)

    def click(self, button="left", count=1, mods=()):
        hwnd = self.attach()
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("click", self.cursor, button, count, tuple(mods))])
            return
        if self.target["focus_messages"]:
            self.b.post_focus(hwnd)
        allmods = tuple(sorted(set(mods) | set(self._mods())))
        for m in mods:
            self.b.post_key(hwnd, MOD_VK[m], True)
        try:
            for i in range(max(1, count)):
                self.b.post_mouse(hwnd, "down", self.cursor, button, allmods, dbl=(i == 1))
                time.sleep(0.012)
                self.b.post_mouse(hwnd, "up", self.cursor, button, allmods)
                if i < count - 1:
                    time.sleep(0.03)
        finally:
            for m in reversed(mods):
                self.b.post_key(hwnd, MOD_VK[m], False)

    def press_button(self, name):
        hwnd = self.attach()
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("down", self.cursor, name)])
        else:
            self.b.post_mouse(hwnd, "down", self.cursor, name, self._mods())
        self.held.add(("button", name))
        return name

    def get_button(self, name):
        return name or "left"

    def release_button(self, b):
        try:
            hwnd = self.attach()
            if self.target["method"] == "quickswitch":
                self.b.quick_input(hwnd, [("up", self.cursor, b)])
            else:
                self.b.post_mouse(hwnd, "up", self.cursor, b, self._mods())
        except WindowNotFound:
            pass
        self.held.discard(("button", b))

    def scroll(self, dx, dy):
        hwnd = self.attach()
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("scroll", self.cursor, dx, dy)])
        else:
            self.b.post_wheel(hwnd, self.cursor, dx, dy)

    # ---- keyboard

    def type_text(self, text, interval=0.0):
        hwnd = self.attach()
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("text", text)])
            return
        if self.target["focus_messages"]:
            self.b.post_focus(hwnd)
        for ch in text:
            if ch == "\n":
                self.b.post_key(hwnd, VK["enter"], True)
                self.b.post_key(hwnd, VK["enter"], False)
            else:
                self.b.post_char(hwnd, ch)
            time.sleep(interval or 0.004)

    def _vks(self, text):
        out = []
        for name in parse_combo(text):
            vk, shift = key_to_vk(name, self.b.char_vk)
            if shift:
                out.append(VK["shift"])
            out.append(vk)
        return out

    def press_combo(self, text, hold=0.02):
        hwnd = self.attach()
        vks = self._vks(text)
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("keys", vks)])
            return
        if self.target["focus_messages"]:
            self.b.post_focus(hwnd)
        for vk in vks:
            self.b.post_key(hwnd, vk, True)
            time.sleep(hold)
        for vk in reversed(vks):
            self.b.post_key(hwnd, vk, False)
            time.sleep(0.005)

    def key_down(self, text):
        hwnd = self.attach()
        vks = self._vks(text)
        for vk in vks:
            if self.target["method"] == "quickswitch":
                self.b.quick_input(hwnd, [("keydown", vk)])
            else:
                self.b.post_key(hwnd, vk, True)
            self.held.add(vk)
        return vks

    def key_up(self, text):
        hwnd = self.attach()
        vks = self._vks(text)
        for vk in reversed(vks):
            if self.target["method"] == "quickswitch":
                self.b.quick_input(hwnd, [("keyup", vk)])
            else:
                self.b.post_key(hwnd, vk, False)
            self.held.discard(vk)
        return vks

    def vk_down(self, vk):
        hwnd = self.attach()
        if self.target["method"] == "quickswitch":
            self.b.quick_input(hwnd, [("keydown", vk)])
        else:
            if self.target["focus_messages"] and not self.held:
                self.b.post_focus(hwnd)
            self.b.post_key(hwnd, vk, True)
        self.held.add(vk)
        return vk

    def vk_up(self, vk):
        self.release_key(vk)

    def release_key(self, vk):
        try:
            if isinstance(vk, int):
                hwnd = self.attach()
                if self.target["method"] == "quickswitch":
                    self.b.quick_input(hwnd, [("keyup", vk)])
                else:
                    self.b.post_key(hwnd, vk, False)
        except WindowNotFound:
            pass
        self.held.discard(vk)

    def show_desktop(self):
        pass  # meaningless for one window; ignored in background mode

    def beep(self):
        from . import inputs
        inputs.beep()


def crop(img, x, y, w, h):
    """Crop with black padding outside the image, like a screen grab past the edge."""
    import numpy as np
    H, W = img.shape[:2]
    out = np.zeros((int(h), int(w), 3), np.uint8)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 > x0 and y1 > y0:
        out[y0 - y:y1 - y, x0 - x:x1 - x] = img[y0:y1, x0:x1, :3]
    return out


# ---------------------------------------------------------------- Windows backend

def message_scale(awareness, window_dpi, monitor_dpi):
    """How to turn real screen pixels into the units a window reads its mouse messages in.

    A window that isn't per-monitor DPI aware (awareness 0 or 1) is stretched by Windows on a scaled
    display (150% and so on) and reads positions in its own smaller units: without this, clicks sent to it
    land 1.5 times too far right and down, often off the window.
    """
    if awareness == 2 or not window_dpi or not monitor_dpi:
        return 1.0
    return float(window_dpi) / float(monitor_dpi)


def unstretch(img, k):
    """Undo a window capture that came back at the window's own smaller size.

    A window Windows stretches on a scaled display (see message_scale) draws itself at its unscaled size:
    its picture lands in the top left k-th of the capture with black around it. Scaling that part back up
    puts the capture in real screen pixels, like everything else. Left alone when it doesn't look like that.
    """
    import cv2
    h, w = img.shape[:2]
    if not 0.2 < k < 0.99 or h < 8 or w < 8:
        return img
    lw, lh = max(1, round(w * k)), max(1, round(h * k))
    inside = img[:lh, :lw]
    outside_right, outside_below = img[:, lw + 1:], img[lh + 1:, :lw]
    parts = [a for a in (outside_right, outside_below) if a.size]
    if not parts or max(float(a.mean()) for a in parts) > 4 or float(inside.std()) < 2:
        return img
    return cv2.resize(inside, (w, h), interpolation=cv2.INTER_LINEAR)


class WinBackend:
    """Win32 calls through ctypes. Only constructed on Windows."""

    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0200, 0x0201, 0x0202, 0x0203
    WM_RBUTTONDOWN, WM_RBUTTONUP, WM_RBUTTONDBLCLK = 0x0204, 0x0205, 0x0206
    WM_MBUTTONDOWN, WM_MBUTTONUP, WM_MBUTTONDBLCLK = 0x0207, 0x0208, 0x0209
    WM_XBUTTONDOWN, WM_XBUTTONUP, WM_XBUTTONDBLCLK = 0x020B, 0x020C, 0x020D
    WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x020A, 0x020E
    WM_KEYDOWN, WM_KEYUP, WM_CHAR, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0102, 0x0104, 0x0105
    WM_ACTIVATE, WM_SETFOCUS, WM_NCACTIVATE = 0x0006, 0x0007, 0x0086
    MK = {"left": 0x0001, "right": 0x0002, "shift": 0x0004, "ctrl": 0x0008, "middle": 0x0010,
          "x1": 0x0020, "x2": 0x0040}

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ct = ctypes
        self.wt = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32")
        self.kernel32 = ctypes.WinDLL("kernel32")
        u = self.user32
        g = self.gdi32
        k = self.kernel32
        H, HDC, HBM, HGDI = wintypes.HWND, wintypes.HDC, wintypes.HBITMAP, wintypes.HGDIOBJ
        # Declare handle types so 64-bit handles are never truncated to 32-bit ints.
        for fn, args, res in (
                (u.GetWindowDC, [H], HDC), (u.GetDC, [H], HDC), (u.ReleaseDC, [H, HDC], ctypes.c_int),
                (u.GetForegroundWindow, [], H), (u.SetForegroundWindow, [H], wintypes.BOOL),
                (u.GetAncestor, [H, wintypes.UINT], H), (u.GetWindow, [H, wintypes.UINT], H),
                (u.WindowFromPoint, [wintypes.POINT], H), (u.IsWindow, [H], wintypes.BOOL),
                (u.IsIconic, [H], wintypes.BOOL), (u.IsWindowVisible, [H], wintypes.BOOL),
                (u.ShowWindow, [H, ctypes.c_int], wintypes.BOOL),
                (u.SetWindowPos, [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT],
                 wintypes.BOOL),
                (u.GetWindowTextLengthW, [H], ctypes.c_int),
                (u.GetWindowTextW, [H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                (u.GetWindowThreadProcessId, [H, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
                (u.ClientToScreen, [H, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
                (u.GetClientRect, [H, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
                (u.PrintWindow, [H, HDC, wintypes.UINT], wintypes.BOOL),
                (g.CreateCompatibleDC, [HDC], HDC), (g.CreateCompatibleBitmap, [HDC, ctypes.c_int, ctypes.c_int], HBM),
                (g.SelectObject, [HDC, HGDI], HGDI), (g.DeleteObject, [HGDI], wintypes.BOOL),
                (g.DeleteDC, [HDC], wintypes.BOOL),
                (g.BitBlt, [HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, HDC, ctypes.c_int,
                            ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
                (g.GetDIBits, [HDC, HBM, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                               wintypes.UINT], ctypes.c_int),
                (k.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
                (k.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
                (k.QueryFullProcessImageNameW, [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL)):
            fn.argtypes, fn.restype = args, res
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        try:  # Windows 10+: per window DPI, for mouse messages to windows Windows stretches
            u.GetWindowDpiAwarenessContext.argtypes = [wintypes.HWND]
            u.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
            u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.restype = wintypes.UINT
            u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            u.MonitorFromWindow.restype = ctypes.c_void_p
            u.PhysicalToLogicalPointForPerMonitorDPI.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            self.shcore = ctypes.windll.shcore
            self.shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(wintypes.UINT),
                                                     ctypes.POINTER(wintypes.UINT)]
        except (AttributeError, OSError):
            self.shcore = None
        u.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
        u.ChildWindowFromPointEx.restype = wintypes.HWND
        u.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        u.VkKeyScanW.argtypes = [wintypes.WCHAR]
        u.VkKeyScanW.restype = ctypes.c_short
        self._pid_names = {}

    # ---- finding windows

    def _title(self, hwnd):
        n = self.user32.GetWindowTextLengthW(hwnd)
        buf = self.ct.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _process(self, hwnd):
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        pid = pid.value
        if pid in self._pid_names:
            return self._pid_names[pid]
        name = ""
        h = self.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            try:
                size = self.wt.DWORD(1024)
                buf = self.ct.create_unicode_buffer(1024)
                if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, self.ct.byref(size)):
                    name = buf.value.replace("\\", "/").split("/")[-1]
            finally:
                self.kernel32.CloseHandle(h)
        self._pid_names[pid] = name
        return name

    def list_windows(self):
        """[(hwnd, title, process)] for visible top-level windows with a title."""
        out = []
        proto = self.ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)

        def cb(hwnd, _lp):
            if self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                title = self._title(hwnd)
                if title and not self.user32.GetWindow(hwnd, 4):  # GW_OWNER: skip owned popups
                    out.append((hwnd, title, self._process(hwnd)))
            return True
        self.user32.EnumWindows(proto(cb), 0)  # the callback object lives until EnumWindows returns
        return out

    def find_window(self, title, process):
        title_l, proc_l = title.lower(), process.lower()
        best = None
        for hwnd, t, p in self.list_windows():
            if proc_l and p.lower() != proc_l:
                continue
            if title_l:
                if t.lower() == title_l:
                    return hwnd
                if title_l in t.lower() and best is None:
                    best = hwnd
            elif best is None:
                best = hwnd
        return best

    def window_at(self, x, y):
        hwnd = self.user32.WindowFromPoint(self.wt.POINT(int(x), int(y)))
        root = self.user32.GetAncestor(hwnd, 2) if hwnd else None  # GA_ROOT
        if not root:
            return None
        return root, self._title(root), self._process(root)

    def is_window(self, hwnd):
        return bool(self.user32.IsWindow(hwnd))

    def is_minimized(self, hwnd):
        return bool(self.user32.IsIconic(hwnd))

    def focus(self, hwnd):
        """Bring a window to the front (restoring it if minimized) and give it the keyboard."""
        from . import inputs
        u = self.user32
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
        if u.GetForegroundWindow() != hwnd:
            inputs.press_combo("alt", hold=0.0)  # lets SetForegroundWindow work from a background app
            u.SetForegroundWindow(hwnd)

    def move(self, hwnd, x, y, w=None, h=None):
        """Move (and optionally resize) the whole window, in screen pixels."""
        u = self.user32
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)
        flags = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
        if not w or not h:
            flags |= 0x0001      # SWP_NOSIZE
            w = h = 0
        u.SetWindowPos(hwnd, None, int(x), int(y), int(w), int(h), flags)

    def close(self, hwnd):
        self.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: the app may still ask to save

    def restore_behind(self, hwnd):
        """Un-minimize without taking focus, then send it behind other windows."""
        fg = self.user32.GetForegroundWindow()
        self.user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        self.user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # HWND_BOTTOM, no size/move/activate
        if fg:
            self.user32.SetForegroundWindow(fg)

    # ---- geometry

    def client_origin(self, hwnd):
        pt = self.wt.POINT(0, 0)
        self.user32.ClientToScreen(hwnd, self.ct.byref(pt))
        return pt.x, pt.y

    def client_size(self, hwnd):
        r = self.wt.RECT()
        self.user32.GetClientRect(hwnd, self.ct.byref(r))
        return r.right - r.left, r.bottom - r.top

    def _child_at(self, hwnd, x, y):
        """The deepest child window under a client point, and the point in its own client coordinates."""
        sx, sy = self.client_origin(hwnd)
        sx, sy = sx + x, sy + y
        cur = hwnd
        for _ in range(12):
            ox, oy = self.client_origin(cur)
            # skip invisible (1), disabled (2) and transparent (4) children: they drop the messages
            child = self.user32.ChildWindowFromPointEx(cur, self.wt.POINT(sx - ox, sy - oy),
                                                       0x0001 | 0x0002 | 0x0004)
            if not child or child == cur:
                break
            cur = child
        ox, oy = self.client_origin(cur)
        return cur, sx - ox, sy - oy

    # ---- capture

    def capture_client(self, hwnd):
        """The window's content area as a BGR image, even when covered by other windows."""
        import numpy as np
        w, h = self.client_size(hwnd)
        if w <= 0 or h <= 0:
            raise WindowNotFound("Target window has no visible content (is it minimized?)")
        user32, gdi32, ct, wt = self.user32, self.gdi32, self.ct, self.wt
        wdc = user32.GetWindowDC(hwnd)
        mdc = gdi32.CreateCompatibleDC(wdc)
        bmp = gdi32.CreateCompatibleBitmap(wdc, w, h)
        gdi32.SelectObject(mdc, bmp)
        try:
            # 1 = PW_CLIENTONLY, 2 = PW_RENDERFULLCONTENT (needed for GPU drawn apps and browsers)
            ok = user32.PrintWindow(hwnd, mdc, 1 | 2)
            if not ok:
                cdc = user32.GetDC(hwnd)
                gdi32.BitBlt(mdc, 0, 0, w, h, cdc, 0, 0, 0x00CC0020)  # SRCCOPY
                user32.ReleaseDC(hwnd, cdc)

            class BITMAPINFOHEADER(ct.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                            ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                            ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
            bih = BITMAPINFOHEADER(ct.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = (ct.c_ubyte * (w * h * 4))()
            gdi32.GetDIBits(mdc, bmp, 0, h, ct.addressof(buf), ct.addressof(bih), 0)
            img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()
            img = unstretch(img, self._msg_scale(hwnd))
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(hwnd, wdc)
        return img

    # ---- background messages

    def _msg_scale(self, hwnd):
        if self.shcore is None:
            return 1.0
        try:
            u = self.user32
            aware = u.GetAwarenessFromDpiAwarenessContext(u.GetWindowDpiAwarenessContext(hwnd))
            x, y = self.wt.UINT(), self.wt.UINT()
            if self.shcore.GetDpiForMonitor(u.MonitorFromWindow(hwnd, 2), 0, self.ct.byref(x), self.ct.byref(y)):
                return 1.0
            return message_scale(aware, u.GetDpiForWindow(hwnd), x.value)
        except Exception:
            return 1.0

    @staticmethod
    def _lparam_xy(x, y):
        return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)

    def post_mouse(self, hwnd, kind, pos, button, mods, dbl=False):
        child, cx, cy = self._child_at(hwnd, *pos)
        k = self._msg_scale(child)
        flags = 0
        for m in mods:
            flags |= self.MK.get(m, 0)
        lp = self._lparam_xy(round(cx * k), round(cy * k))
        if kind == "move":
            self.user32.PostMessageW(child, self.WM_MOUSEMOVE, flags, lp)
            return
        button = button or "left"
        msgs = {"left": (self.WM_LBUTTONDOWN, self.WM_LBUTTONUP, self.WM_LBUTTONDBLCLK),
                "right": (self.WM_RBUTTONDOWN, self.WM_RBUTTONUP, self.WM_RBUTTONDBLCLK),
                "middle": (self.WM_MBUTTONDOWN, self.WM_MBUTTONUP, self.WM_MBUTTONDBLCLK),
                "x1": (self.WM_XBUTTONDOWN, self.WM_XBUTTONUP, self.WM_XBUTTONDBLCLK),
                "x2": (self.WM_XBUTTONDOWN, self.WM_XBUTTONUP, self.WM_XBUTTONDBLCLK)}[button]
        wp = flags
        if button in ("x1", "x2"):
            wp |= (1 if button == "x1" else 2) << 16
        if kind == "down":
            wp |= self.MK[button]
            self.user32.PostMessageW(child, self.WM_MOUSEMOVE, flags, lp)
            self.user32.PostMessageW(child, msgs[2] if dbl else msgs[0], wp, lp)
        else:
            self.user32.PostMessageW(child, msgs[1], wp, lp)

    def post_wheel(self, hwnd, pos, dx, dy):
        child, _cx, _cy = self._child_at(hwnd, *pos)
        ox, oy = self.client_origin(hwnd)
        pt = self.wt.POINT(ox + pos[0], oy + pos[1])  # wheel messages use screen coordinates
        if self.shcore is not None and self._msg_scale(child) != 1.0:
            try:
                self.user32.PhysicalToLogicalPointForPerMonitorDPI(child, self.ct.byref(pt))
            except Exception:
                pass
        lp = self._lparam_xy(pt.x, pt.y)
        for msg, amount in ((self.WM_MOUSEWHEEL, dy), (self.WM_MOUSEHWHEEL, dx)):
            if amount:
                wp = (int(amount * 120) & 0xFFFF) << 16
                self.user32.PostMessageW(child, msg, wp, lp)

    def post_focus(self, hwnd):
        """Tell the window it is active without actually activating it (many apps ignore input otherwise)."""
        self.user32.PostMessageW(hwnd, self.WM_NCACTIVATE, 1, 0)
        self.user32.PostMessageW(hwnd, self.WM_ACTIVATE, 1, 0)
        self.user32.PostMessageW(hwnd, self.WM_SETFOCUS, 0, 0)

    def _key_target(self, hwnd):
        """Keys go to the focused control inside the target's thread when there is one."""
        tid = self.user32.GetWindowThreadProcessId(hwnd, None)
        self.user32.GetGUIThreadInfo.argtypes = [self.wt.DWORD, self.ct.c_void_p]

        class GUITHREADINFO(self.ct.Structure):
            _fields_ = [("cbSize", self.wt.DWORD), ("flags", self.wt.DWORD), ("hwndActive", self.wt.HWND),
                        ("hwndFocus", self.wt.HWND), ("hwndCapture", self.wt.HWND),
                        ("hwndMenuOwner", self.wt.HWND), ("hwndMoveSize", self.wt.HWND),
                        ("hwndCaret", self.wt.HWND), ("rcCaret", self.wt.RECT)]
        info = GUITHREADINFO(cbSize=self.ct.sizeof(GUITHREADINFO))
        if self.user32.GetGUIThreadInfo(tid, self.ct.byref(info)) and info.hwndFocus:
            return info.hwndFocus
        return hwnd

    def post_key(self, hwnd, vk, down):
        target = self._key_target(hwnd)
        scan = self.user32.MapVirtualKeyW(vk, 0)
        lp = 1 | (scan << 16)
        if vk in EXTENDED:
            lp |= 1 << 24
        if not down:
            lp |= (1 << 30) | (1 << 31)
            if self.ct.sizeof(self.wt.LPARAM) == 4:  # 32-bit Python: LPARAM is signed 32-bit
                lp -= 1 << 32
        alt = vk in (0x12, 0xA4, 0xA5)
        msg = (self.WM_SYSKEYDOWN if down else self.WM_SYSKEYUP) if alt else (self.WM_KEYDOWN if down else self.WM_KEYUP)
        self.user32.PostMessageW(target, msg, vk, lp)

    def post_char(self, hwnd, ch):
        target = self._key_target(hwnd)
        for unit in ch.encode("utf-16-le").decode("utf-16-le"):
            self.user32.PostMessageW(target, self.WM_CHAR, ord(unit), 1)

    def char_vk(self, ch):
        r = self.user32.VkKeyScanW(ch)
        if r == -1:
            raise ValueError(f"Key '{ch}' has no key on this keyboard layout")
        return r & 0xFF, bool(r & 0x100)

    # ---- quick switch

    def quick_input(self, hwnd, actions):
        """Bring the window forward, send real input, then give focus and the cursor back."""
        from . import inputs
        u = self.user32
        prev_fg = u.GetForegroundWindow()
        prev_pos = inputs.position()
        ox, oy = self.client_origin(hwnd)
        try:
            if u.GetForegroundWindow() != hwnd:
                inputs.press_combo("alt", hold=0.0)  # lets SetForegroundWindow work from a background app
                u.SetForegroundWindow(hwnd)
                time.sleep(0.03)
            for a in actions:
                kind = a[0]
                if kind == "click":
                    _k, (x, y), button, count, mods = a
                    inputs.move_to(ox + x, oy + y)
                    time.sleep(0.01)
                    inputs.click(button, count, mods)
                elif kind in ("down", "up"):
                    _k, (x, y), button = a
                    inputs.move_to(ox + x, oy + y)
                    b = inputs.get_button(button)
                    inputs.mouse_ctl.press(b) if kind == "down" else inputs.mouse_ctl.release(b)
                elif kind == "scroll":
                    _k, (x, y), dx, dy = a
                    inputs.move_to(ox + x, oy + y)
                    inputs.scroll(dx, dy)
                elif kind == "text":
                    inputs.type_text(a[1])
                elif kind == "keys":
                    self._send_vks(a[1])
                elif kind in ("keydown", "keyup"):
                    self._send_vk(a[1], kind == "keydown")
        finally:
            inputs.move_to(*prev_pos)
            if prev_fg and prev_fg != hwnd:
                inputs.press_combo("alt", hold=0.0)  # same unlock, so focus can go back to your window
                u.SetForegroundWindow(prev_fg)

    def _send_vk(self, vk, down):
        from pynput.keyboard import KeyCode
        from . import inputs
        k = KeyCode.from_vk(vk)
        inputs.kb_ctl.press(k) if down else inputs.kb_ctl.release(k)

    def _send_vks(self, vks):
        for vk in vks:
            self._send_vk(vk, True)
            time.sleep(0.02)
        for vk in reversed(vks):
            self._send_vk(vk, False)


_backend = None


def default_backend():
    global _backend
    if _backend is None:
        if sys.platform != "win32":
            raise RuntimeError("Background mode needs Windows.")
        _backend = WinBackend()
    return _backend


def available():
    return sys.platform == "win32"


def list_windows():
    try:
        return default_backend().list_windows()
    except RuntimeError:
        return []


def find_window(title, process, backend=None):
    """A window handle matching title (contains) and/or program, or None. Raises WindowNotFound off Windows."""
    try:
        b = backend or default_backend()
    except RuntimeError as e:
        raise WindowNotFound(str(e))
    return b.find_window(str(title or ""), str(process or ""))


def window_at(x, y):
    try:
        return default_backend().window_at(x, y)
    except RuntimeError:
        return None

