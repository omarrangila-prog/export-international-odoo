"""Draws the application icons (browser tab, home screen, install prompt) from the same blue mark as the sign-in page.
    python3 migration/make_app_icons.py
Writes addons/ei_app_shell/static/img/: ei-icon-192.png, ei-icon-512.png (rounded, "any"), ei-icon-maskable-512.png (full square, for
the shapes Android cuts), ei-icon-180.png (iPhone, full square: iOS rounds it itself) and ei-favicon-64.png."""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), '..', 'addons', 'ei_app_shell', 'static', 'img')
FONT = os.path.expanduser('~/.local/share/fonts/Inter/Inter-ExtraBold.ttf')
TOP, BOTTOM = (42, 120, 214), (29, 78, 216)          # #2A78D6 -> #1D4ED8


def gradient(size):
    img = Image.new('RGB', (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
    return img


def mark(size, rounded, text_ratio):
    base = gradient(size).convert('RGBA')
    d = ImageDraw.Draw(base)
    font = ImageFont.truetype(FONT, int(size * text_ratio))
    box = d.textbbox((0, 0), 'EI', font=font)
    d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]), 'EI', font=font, fill='white')
    if rounded:
        mask = Image.new('L', (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
        base.putalpha(mask)
    return base


os.makedirs(OUT, exist_ok=True)
mark(512, True, 0.42).save(os.path.join(OUT, 'ei-icon-512.png'), optimize=True)
mark(512, True, 0.42).resize((192, 192), Image.LANCZOS).save(os.path.join(OUT, 'ei-icon-192.png'), optimize=True)
mark(512, False, 0.30).save(os.path.join(OUT, 'ei-icon-maskable-512.png'), optimize=True)       # the letters stay inside the central 80 % that a mask keeps
mark(180, False, 0.40).save(os.path.join(OUT, 'ei-icon-180.png'), optimize=True)
mark(256, True, 0.46).resize((64, 64), Image.LANCZOS).save(os.path.join(OUT, 'ei-favicon-64.png'), optimize=True)
print('icons written to', os.path.abspath(OUT))
