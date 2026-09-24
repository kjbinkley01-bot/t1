"""Draw the Clicker app icon and save it as PNG, ICO (Windows) and ICNS (macOS).

Run from the project folder:  python tools/make_icon.py
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets")

BG = (15, 17, 19, 255)       # theme "bg"
EDGE = (35, 38, 42, 255)     # theme "border"
ACCENT = (62, 207, 178, 255)  # theme "accent"


def draw(size=1024):
    s = size / 24.0  # the logo is drawn on the same 24 unit grid as the in-app mark
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG, outline=EDGE, width=max(2, size // 64))
    # cursor arrow (same shape as the in-app mark: M4 4 l7 17 2.5 -7.5 L21 11 z),
    # scaled down and nudged right so the click ripple fits at its tip
    arrow = [(4, 4), (11, 21), (13.5, 13.5), (21, 11)]
    k, cx, cy = 0.66, 12.5, 12.5
    pts = [((x - cx) * k + cx + 1.3, (y - cy) * k + cy + 1.3) for x, y in arrow]
    tip = pts[0]
    d.polygon([(x * s, y * s) for x, y in pts], fill=ACCENT)
    w = max(2, int(s * 0.75))
    for rr, start, end in ((2.6, 190, 260), (4.4, 195, 255)):
        box = [(tip[0] - rr) * s, (tip[1] - rr) * s, (tip[0] + rr) * s, (tip[1] + rr) * s]
        d.arc(box, start, end, fill=ACCENT, width=w)
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    big = draw(1024)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "clicker.png"))
    big.save(os.path.join(OUT, "clicker.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(OUT, "clicker.icns"))
    print("Wrote", ", ".join(sorted(os.listdir(OUT))), "to", OUT)


if __name__ == "__main__":
    main()
