"""Points for sliding the cursor to a spot instead of jumping there.

Pure math, so the real mouse (inputs) and background mode (target) share it and tests need no display.
"""

import math

FRAME_S = 0.008  # about 120 moves a second
MAX_MS = 5000
BEND = 0.12      # a curved slide bows out by this share of its length, halfway along


def points(sx, sy, x, y, duration, curve=False):
    """[(x, y), ...] ending exactly at (x, y), eased so it starts and stops gently.

    curve bows the path out to one side (always the same amount and side, so a script moves the same way
    every run).
    """
    steps = max(2, min(600, int(round(duration / FRAME_S))))
    dx, dy = x - sx, y - sy
    dist = math.hypot(dx, dy)
    bend = BEND * dist if curve and dist > 20 else 0.0
    nx, ny = (-dy / dist, dx / dist) if dist else (0.0, 0.0)
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)        # smoothstep: ease in and out
        side = bend * 4 * e * (1 - e)  # 0 at both ends, full bend halfway
        out.append((int(round(sx + dx * e + nx * side)), int(round(sy + dy * e + ny * side))))
    out[-1] = (int(x), int(y))
    return out
