"""Mouse and keyboard output, plus key name parsing."""

import math
import re
import sys
import time

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

from . import glide
from .inputs_names import canonical, split_combo

mouse_ctl = mouse.Controller()
kb_ctl = keyboard.Controller()

MODIFIERS = {"ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt}


def parse_key(name):
    n = canonical(name)
    if not n:
        raise ValueError("Empty key name")
    if len(n) == 1:
        return KeyCode.from_char(n)
    if n in Key.__members__:
        return Key[n]
    m = re.fullmatch(r"vk_?(\d+)", n)
    if m:
        return KeyCode.from_vk(int(m.group(1)))
    raise ValueError(f"Unknown key '{name}'")


def parse_combo(text):
    return [parse_key(p) for p in split_combo(text)]


def press_combo(text, hold=0.02):
    keys = parse_combo(text)
    pressed = []
    try:
        for k in keys:
            kb_ctl.press(k)
            pressed.append(k)
            time.sleep(hold)
    finally:
        for k in reversed(pressed):
            kb_ctl.release(k)
            time.sleep(0.005)


def key_down(text):
    keys = parse_combo(text)
    for k in keys:
        kb_ctl.press(k)
    return keys


def key_up(text):
    keys = parse_combo(text)
    for k in reversed(keys):
        kb_ctl.release(k)
    return keys


def release_key(k):
    try:
        kb_ctl.release(k)
    except Exception:
        pass


def type_text(text, interval=0.0):
    if interval <= 0:
        kb_ctl.type(text)
        return
    for ch in text:
        kb_ctl.type(ch)
        time.sleep(interval)


def get_button(name):
    name = (name or "left").lower()
    b = getattr(Button, name, None)
    if b is None or name not in ("left", "right", "middle", "x1", "x2"):
        if name in ("x1", "x2"):
            raise ValueError("X1 and X2 buttons are only supported on Windows")
        raise ValueError(f"Unknown mouse button '{name}'")
    return b


def position():
    x, y = mouse_ctl.position
    return int(round(x)), int(round(y))


def move_to(x, y):
    mouse_ctl.position = (int(x), int(y))


def smooth_move(x, y, duration=0.12, curve=False):
    sx, sy = position()
    pts = glide.points(sx, sy, x, y, duration, curve)
    for p in pts:
        mouse_ctl.position = p
        time.sleep(duration / len(pts))


def move_by(dx, dy):
    x, y = position()
    move_to(x + int(dx), y + int(dy))


def move_by_angle(angle_deg, distance):
    x, y = position()
    a = math.radians(float(angle_deg))
    move_to(x + math.cos(a) * float(distance), y - math.sin(a) * float(distance))


def click(button="left", count=1, mods=(), hold_s=0.0):
    keys = [MODIFIERS[m] for m in mods]
    b = get_button(button)
    for k in keys:
        kb_ctl.press(k)
    try:
        if keys:
            time.sleep(0.02)
        if hold_s > 0:
            for i in range(count):
                mouse_ctl.press(b)
                time.sleep(hold_s)
                mouse_ctl.release(b)
                if i < count - 1:
                    time.sleep(0.03)
        else:
            mouse_ctl.click(b, count)
    finally:
        for k in reversed(keys):
            kb_ctl.release(k)


def press_button(name):
    b = get_button(name)
    mouse_ctl.press(b)
    return b


def release_button(b):
    try:
        mouse_ctl.release(b)
    except Exception:
        pass


def scroll(dx, dy):
    mouse_ctl.scroll(dx, dy)


def show_desktop():
    if sys.platform == "win32":
        press_combo("cmd+d")
    elif sys.platform == "darwin":
        press_combo("f11")
    else:
        press_combo("ctrl+alt+d")


def beep():
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep()
            return
        except Exception:
            pass
    print("\a", end="", flush=True)
