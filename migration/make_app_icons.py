"""Draws every application icon from one mark: a white E whose middle stroke is a gold bar pointing outward, for a company that exports.
    python3 migration/make_app_icons.py
Writes, in addons/ei_app_shell/static/img/: ei-icon-192.png, ei-icon-512.png (rounded, "any"), ei-icon-maskable-512.png (full square, the
mark inside the central 80 % that a mask keeps), ei-icon-180.png (iPhone, full square: iOS rounds it itself), ei-favicon-64.png (mark larger,
so it still reads at 16 px). Also ei_ui_theme/static/description/icon.svg (the app's tile in Odoo) and export_international/static/description/icon.png
(its picture on the Apps page). Needs only Pillow."""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.join(HERE, '..', 'addons')
OUT = os.path.join(ADDONS, 'ei_app_shell', 'static', 'img')

UNITS = 128                # the drawing's grid; the mark is centred on 64,64
ROUND = 3                  # corner rounding: the shapes are stroked with this width and round joins
E = [(29, 29), (89, 29), (75, 44), (45, 44), (45, 84), (75, 84), (89, 99), (29, 99)]
ARROW = [(51, 55.5), (90, 55.5), (99, 64), (90, 72.5), (51, 72.5)]
BG = ((31, 90, 224), (10, 28, 82))           # top left -> bottom right
METAL = ((255, 255, 255), (205, 219, 247))   # top -> bottom
GOLD = ((255, 200, 87), (240, 149, 18))      # top -> bottom
SHADOW = (5, 16, 54)


def linear(size, start, end, diagonal=False):
    small = Image.new('RGB', (128, 128))
    px = small.load()
    for y in range(128):
        for x in range(128):
            t = (x + y) / 254 if diagonal else y / 127
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(start, end))
    return small.resize((size, size), Image.BICUBIC)


def place(points, scale, s):
    k = s / UNITS
    return [((64 + (x - 64) * scale) * k, (64 + (y - 64) * scale) * k) for x, y in points]


def shape_mask(points, scale, s):
    pts = place(points, scale, s)
    w = ROUND * scale * s / UNITS
    mask = Image.new('L', (s, s), 0)
    d = ImageDraw.Draw(mask)
    d.polygon(pts, fill=255)
    for a, b in zip(pts, pts[1:] + pts[:1]):
        d.line((a, b), fill=255, width=round(w))
        d.ellipse((a[0] - w / 2, a[1] - w / 2, a[0] + w / 2, a[1] + w / 2), fill=255)
    return mask


def fill_with(base, points, scale, colours, s, top, bottom):
    """The colour runs over the shape's own height, so the metal and the gold look the same at every scale."""
    mask = shape_mask(points, scale, s)
    grad = linear(128, *colours).resize((s, max(1, bottom - top)), Image.BICUBIC)
    layer = Image.new('RGB', (s, s), colours[1])
    layer.paste(linear(128, colours[0], colours[0]).resize((s, max(1, top))), (0, 0)) if top > 0 else None
    layer.paste(grad, (0, top))
    base.paste(layer, (0, 0), mask)


def mark(size, rounded, scale):
    s = max(size * 4, 1024)
    img = linear(s, *BG, diagonal=True).convert('RGB')
    # a soft light from the top left, so the tile is not a flat fill
    glow = Image.new('L', (s, s), 0)
    ImageDraw.Draw(glow).ellipse((-s * .35, -s * .55, s * .85, s * .5), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(s * .14))
    img.paste(Image.new('RGB', (s, s), (112, 163, 255)), (0, 0), glow)
    # the mark's shadow
    both = ImageChops.lighter(shape_mask(E, scale, s), shape_mask(ARROW, scale, s))
    off = round(s * .018)
    shadow = Image.new('L', (s, s), 0)
    shadow.paste(both, (0, off))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s * .022)).point(lambda v: round(v * .5))
    img.paste(Image.new('RGB', (s, s), SHADOW), (0, 0), shadow)
    top = round((64 + (29 - 64) * scale) * s / UNITS)
    bottom = round((64 + (99 - 64) * scale) * s / UNITS)
    fill_with(img, E, scale, METAL, s, top, bottom)
    fill_with(img, ARROW, scale, GOLD, s, top + (bottom - top) * 3 // 8, bottom - (bottom - top) * 3 // 8)
    img = img.convert('RGBA')
    if rounded:
        mask = Image.new('L', (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=round(s * .22), fill=255)
        img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


def poly(points):
    return ' '.join('%g,%g' % p for p in points)


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {UNITS} {UNITS}"><defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#{'%02X%02X%02X' % BG[0]}"/><stop offset="1" stop-color="#{'%02X%02X%02X' % BG[1]}"/></linearGradient>
<radialGradient id="glow" cx=".2" cy=".05" r=".75"><stop offset="0" stop-color="#70A3FF" stop-opacity=".3"/><stop offset="1" stop-color="#70A3FF" stop-opacity="0"/></radialGradient>
<linearGradient id="metal" gradientUnits="userSpaceOnUse" x1="0" y1="29" x2="0" y2="99"><stop offset="0" stop-color="#{'%02X%02X%02X' % METAL[0]}"/><stop offset="1" stop-color="#{'%02X%02X%02X' % METAL[1]}"/></linearGradient>
<linearGradient id="gold" gradientUnits="userSpaceOnUse" x1="0" y1="55" x2="0" y2="73"><stop offset="0" stop-color="#{'%02X%02X%02X' % GOLD[0]}"/><stop offset="1" stop-color="#{'%02X%02X%02X' % GOLD[1]}"/></linearGradient>
<filter id="lift" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="2.2" stdDeviation="2.6" flood-color="#{'%02X%02X%02X' % SHADOW}" flood-opacity=".5"/></filter>
</defs><rect width="{UNITS}" height="{UNITS}" rx="28" fill="url(#bg)"/><rect width="{UNITS}" height="{UNITS}" rx="28" fill="url(#glow)"/>
<g filter="url(#lift)" stroke-width="{ROUND}" stroke-linejoin="round"><polygon points="{poly(E)}" fill="url(#metal)" stroke="url(#metal)"/><polygon points="{poly(ARROW)}" fill="url(#gold)" stroke="url(#gold)"/></g></svg>
"""

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    save = lambda img, *where: img.save(os.path.join(*where), optimize=True)
    save(mark(512, True, 1.08), OUT, 'ei-icon-512.png')
    save(mark(192, True, 1.08), OUT, 'ei-icon-192.png')
    save(mark(512, False, .94), OUT, 'ei-icon-maskable-512.png')
    save(mark(180, False, 1.08), OUT, 'ei-icon-180.png')
    save(mark(64, True, 1.26), OUT, 'ei-favicon-64.png')
    save(mark(256, True, 1.08), ADDONS, 'export_international', 'static', 'description', 'icon.png')
    with open(os.path.join(ADDONS, 'ei_ui_theme', 'static', 'description', 'icon.svg'), 'w') as f:
        f.write(SVG)
    print('icons written')
