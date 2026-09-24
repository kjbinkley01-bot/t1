"""Global hotkeys with modifier support and a capture mode for assigning."""

from pynput import keyboard
from pynput.keyboard import Key

MOD_NAMES = {}
for _n, _m in (("ctrl", "ctrl"), ("ctrl_l", "ctrl"), ("ctrl_r", "ctrl"),
               ("shift", "shift"), ("shift_l", "shift"), ("shift_r", "shift"),
               ("alt", "alt"), ("alt_l", "alt"), ("alt_r", "alt"), ("alt_gr", "alt"),
               ("cmd", "win"), ("cmd_l", "win"), ("cmd_r", "win")):
    if _n in Key.__members__:
        MOD_NAMES[Key[_n]] = _m
MOD_ORDER = ["ctrl", "alt", "shift", "win"]


def key_label(key):
    if isinstance(key, Key):
        name = key.name
        if name.startswith("f") and name[1:].isdigit():
            return name.upper()
        return name.replace("_", " ").title().replace(" ", "")
    vk = getattr(key, "vk", None)
    if vk is not None and (48 <= vk <= 57 or 65 <= vk <= 90):
        return chr(vk)
    ch = getattr(key, "char", None)
    if ch and ch.isprintable():
        return ch.upper()
    return f"VK{vk}" if vk is not None else "?"


def combo_label(mods, key):
    return "+".join([m.capitalize() for m in MOD_ORDER if m in mods] + [key_label(key)])


class HotkeyManager:
    def __init__(self, emit, bindings):
        self.emit = emit
        self.bindings = dict(bindings)
        self.mods = set()
        self.down = set()
        self.capturing = False
        self.listener = None

    def start(self):
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.daemon = True
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()

    def capture_next(self):
        self.capturing = True

    def cancel_capture(self):
        self.capturing = False

    def is_hotkey(self, key):
        label = key_label(key).lower()
        for b in self.bindings.values():
            if b and b.split("+")[-1].lower() == label:
                return True
        return False

    def _on_press(self, key, injected=False):
        if injected:
            return
        if key in MOD_NAMES:
            self.mods.add(MOD_NAMES[key])
            return
        kl = key_label(key)
        if kl in self.down:
            return
        self.down.add(kl)
        label = combo_label(self.mods, key)
        if self.capturing:
            self.capturing = False
            if label.lower() in ("esc", "escape"):
                self.emit("hotkey_captured", "")
            else:
                self.emit("hotkey_captured", label)
            return
        for action, b in self.bindings.items():
            if b and b.lower() == label.lower():
                self.emit("hotkey", action)

    def _on_release(self, key, injected=False):
        if injected:
            return
        if key in MOD_NAMES:
            self.mods.discard(MOD_NAMES[key])
            return
        self.down.discard(key_label(key))
