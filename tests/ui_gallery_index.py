#!/usr/bin/env python3
"""Turns the gallery PNGs written by tests/ui_gallery.js into something a person (or a model) can read at once:
INDEX.md (every file, what it shows, who is signed in, theme, size), README.md (what the product is and how it looks) and contact
sheets in sheets/ (several screens per image, captioned) so a handful of images give the whole picture.
    python3 tests/ui_gallery_index.py [galleryDir]"""
import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'docs', 'ui', 'gallery'))
data = json.load(open(os.path.join(OUT, 'index.json')))
entries = data['entries']

GROUPS = [
    ('A', 'Home of every role', lambda e: e['file'].startswith('home-')),
    ('B', 'Home: what you can do on it (hover, period, search, menus)', lambda e: e['file'].startswith('state-home')),
    ('C', 'Every menu entry: the list or cards, the first record, a new record', lambda e: e['file'].startswith('menu-')),
    ('D', 'Menus, filters, dialogs, pick-lists', lambda e: e['file'].startswith('state-') and not e['file'].startswith('state-home')),
    ('R', 'Reports: catalog and the receivables report', lambda e: e['file'].startswith('reports-')),
    ('E', 'Ask (assistant), Match bank payments, Party 360', lambda e: e['file'].startswith(('ask-', 'match-', 'party360-'))),
    ('F', 'Dark theme', lambda e: e['file'].startswith('dark-')),
    ('G', 'Phone (390px)', lambda e: e['file'].startswith('phone-')),
    ('H', 'Sign-in', lambda e: e['file'] == 'login.png'),
]

# ---------------------------------------------------------------- INDEX.md
lines = ['# Screenshot index', '',
         f'{len(entries)} screenshots of the Export International system (staging copy, synthetic DEMO data). '
         'Tall pages are captured whole ("whole page"). Each row: file, what it shows, who is signed in, theme, size.', '']
for key, title, test in GROUPS:
    rows = [e for e in entries if test(e)]
    if not rows:
        continue
    lines += [f'## {key}. {title}', '', '| File | What it shows | Signed in as | Theme | Size |', '|---|---|---|---|---|']
    for e in rows:
        lines.append(f"| `{e['file']}` | {e['what']} | {e['user']} | {e['scheme']} | {e['size']} |")
    lines.append('')
if data.get('problems'):
    lines += ['## Screens that could not be captured', ''] + [f'* {p}' for p in data['problems']] + ['']
open(os.path.join(OUT, 'INDEX.md'), 'w').write('\n'.join(lines))

# ---------------------------------------------------------------- contact sheets
try:
    F = ImageFont.truetype('/home/synthor/.local/share/fonts/Inter/Inter-SemiBold.ttf', 17)
    FS = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
except OSError:
    F = FS = ImageFont.load_default()
COLS, TW, TH, PAD, CAP = 3, 620, 430, 22, 78
os.makedirs(os.path.join(OUT, 'sheets'), exist_ok=True)
for f in os.listdir(os.path.join(OUT, 'sheets')):
    os.remove(os.path.join(OUT, 'sheets', f))


def wrap(text, width, font, draw):
    words, line, out = text.split(), '', []
    for w in words:
        t = (line + ' ' + w).strip()
        if draw.textlength(t, font=font) <= width:
            line = t
        else:
            out.append(line)
            line = w
    out.append(line)
    return out[:3]


sheet_no = 0
for key, title, test in GROUPS:
    rows = [e for e in entries if test(e)]
    per = COLS * 3
    for start in range(0, len(rows), per):
        chunk = rows[start:start + per]
        sheet_no += 1
        n_rows = (len(chunk) + COLS - 1) // COLS
        W = COLS * (TW + PAD) + PAD
        H = 70 + n_rows * (TH + CAP + PAD) + PAD
        sheet = Image.new('RGB', (W, H), '#EEF1F7')
        d = ImageDraw.Draw(sheet)
        d.text((PAD, 20), f'{key}. {title}  -  sheet {start // per + 1} of {(len(rows) + per - 1) // per}', font=ImageFont.truetype('/home/synthor/.local/share/fonts/Inter/Inter-SemiBold.ttf', 26) if F != ImageFont.load_default() else F, fill='#0F1B33')
        for i, e in enumerate(chunk):
            r, c = divmod(i, COLS)
            x, y = PAD + c * (TW + PAD), 70 + r * (TH + CAP + PAD)
            im = Image.open(os.path.join(OUT, e['file'])).convert('RGB')
            scale = TW / im.width
            im = im.resize((TW, max(1, int(im.height * scale))), Image.LANCZOS)
            crop = im.crop((0, 0, TW, min(im.height, TH)))          # the top of a tall page; the full file is next to this sheet
            d.rounded_rectangle((x - 2, y - 2, x + TW + 2, y + TH + CAP + 2), radius=10, fill='white', outline='#D5DBE6')
            sheet.paste(crop, (x, y))
            cap = wrap(e['what'], TW - 16, FS, d)
            d.text((x + 8, y + TH + 6), e['file'], font=F, fill='#1D4ED8')
            for k, t in enumerate(cap):
                d.text((x + 8, y + TH + 28 + k * 17), t, font=FS, fill='#334155')
            if im.height > TH:
                d.text((x + TW - 150, y + TH - 22), 'top of a taller page', font=FS, fill='#64748B')
        sheet.save(os.path.join(OUT, 'sheets', f'sheet-{sheet_no:02d}-{key}.png'), optimize=True)

print(f'{len(entries)} files indexed, {sheet_no} contact sheets')
