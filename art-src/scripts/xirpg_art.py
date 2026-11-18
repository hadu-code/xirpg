"""XIRPG's own art: the icon, the HOME button, the logo tile and the Home page banners.
Type and drawn shapes only: no Square Enix artwork and no picture files are read.

Usage: python3 xirpg_art.py ASSETS_DIR        (the kit's assets folder)
Writes ASSETS_DIR/ui/icon.png, icon.ico, home.png, home_hover.png, home_off.png, logo_tile.png
and    ASSETS_DIR/press/xirpg_1_night__center.png, xirpg_2_dawn__center.png, xirpg_3_ember__center.png
"""
import math
import os
import random
import sys
from lib import *

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
GOLD_TOP, GOLD_BOTTOM = (255, 236, 170), (196, 144, 52)
IVORY_TOP, IVORY_BOTTOM = (252, 246, 228), (214, 200, 160)
TEAL_TOP, TEAL_BOTTOM = (22, 62, 74), (6, 18, 26)
GOLD_FRAME = ((250, 226, 150), (150, 104, 36))
FRAME_INK = (10, 20, 26)


def toned_text(size, text, f, spacing, top, bottom, at=None):
    """Text filled with a top-to-bottom tone, on a transparent layer of the given size."""
    w, h = size
    mask = Image.new('L', size, 0)
    text_spaced(ImageDraw.Draw(mask), at or (w / 2, h / 2), text, f, 255, spacing, 'mm')
    tone = vgrad(w, h, top, bottom).convert('RGBA')
    tone.putalpha(mask)
    return tone


def diamond(d, cx, cy, r, fill):
    d.polygon([(cx - r, cy), (cx, cy - r * 0.8), (cx + r, cy), (cx, cy + r * 0.8)], fill=fill)


def wordmark_layer(w, h, top=GOLD_TOP, bottom=GOLD_BOTTOM, rule=(150, 190, 200), sub=None, sub_ink=(226, 232, 230)):
    """'XIRPG' in one line over a rule with a diamond; an optional small spaced line under it. Scaled to fit w x h."""
    W, H = 1400, 560 if sub else 420
    lay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    f_big = font(300)
    lay.alpha_composite(toned_text((W, H), 'XIRPG', f_big, 26, top, bottom, (W / 2, 160)))
    d = ImageDraw.Draw(lay)
    tw = measure_spaced(d, 'XIRPG', f_big, 26)
    cy = 350
    for sx in (-1, 1):
        x_in, x_out = W / 2 + sx * 44, W / 2 + sx * tw / 2
        d.rectangle((min(x_in, x_out), cy - 4, max(x_in, x_out), cy + 4), fill=rule + (255,))
    diamond(d, W / 2, cy, 24, top + (255,))
    if sub:
        text_spaced(d, (W / 2, 470), sub, font(62), sub_ink + (255,), 20, 'mm')
    lay = lay.crop(bbox_alpha(lay, 10))
    lay.thumbnail((w, h), Image.LANCZOS)
    return lay


def home_button():
    w, h = 133, 56
    img = vgrad(w, h, TEAL_TOP, TEAL_BOTTOM).convert('RGBA')
    lay = wordmark_layer(w - 22, h - 18)
    img.alpha_composite(lay, ((w - lay.width) // 2, (h - lay.height) // 2 + 1))
    return frame(img, 7, GOLD_FRAME, 2, ink=FRAME_INK)


def logo_tile():
    w, h = 442, 186
    img = vgrad(w, h, TEAL_TOP, TEAL_BOTTOM).convert('RGBA')
    lay = wordmark_layer(w - 80, h - 50, sub='SINGLE PLAYER')
    img.alpha_composite(lay, ((w - lay.width) // 2, (h - lay.height) // 2 + 2))
    return frame(img, 14, GOLD_FRAME, 4, ink=FRAME_INK)


def app_icon(size=256):
    """A dark teal rounded square with a gold frame, a gold 'XI' and a small spaced 'RPG' under it."""
    s = size * 4
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    m = Image.new('L', (s, s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, s - 1, s - 1), s // 6, fill=255)
    img.paste(vgrad(s, s, (30, 80, 94), (5, 16, 24)).convert('RGBA'), (0, 0), m)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((s * 0.05, s * 0.05, s * 0.95 - 1, s * 0.95 - 1), s // 8, outline=(214, 170, 78, 255), width=max(2, s // 44))
    img.alpha_composite(toned_text((s, s), 'XI', font(int(s * 0.5)), int(s * 0.02), GOLD_TOP, GOLD_BOTTOM, (s / 2, s * 0.42)))
    d = ImageDraw.Draw(img)
    text_spaced(d, (s / 2, s * 0.76), 'RPG', font(int(s * 0.17)), (232, 238, 236, 255), int(s * 0.045), 'mm')
    for sx in (-1, 1):
        diamond(d, s / 2 + sx * s * 0.34, s * 0.76, s * 0.022, (214, 170, 78, 255))
    return img.resize((size, size), Image.LANCZOS)


# ----- banners (920 x 368, the Home page's picture frame) -----
def glow(size, centre, radius, colour, strength=1.0):
    """A soft round light on a transparent layer."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - centre[0]) ** 2 + (yy - centre[1]) ** 2) / radius
    alpha = np.clip(1 - dist, 0, 1) ** 2 * 255 * strength
    out = np.zeros((h, w, 4), np.uint8)
    out[..., :3] = colour
    out[..., 3] = alpha.astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def stars(img, count, seed, colour=(236, 240, 255)):
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    for _ in range(count):
        x, y = rnd.uniform(0, img.width), rnd.uniform(0, img.height * 0.8)
        r = rnd.choice((1, 1, 1, 2, 2, 3))
        d.ellipse((x - r, y - r, x + r, y + r), fill=colour + (rnd.randint(70, 220),))


def crystal(img, cx, cy, size, light, dark):
    """A faceted upright crystal: our own drawing, flat polygons in tones between light and dark."""
    d = ImageDraw.Draw(img)
    w, h = size * 0.34, size

    def tone(t):
        return tuple(int(dark[i] + (light[i] - dark[i]) * t) for i in range(3)) + (255,)

    top, bottom = (cx, cy - h / 2), (cx, cy + h / 2)
    upper, lower = cy - h * 0.2, cy + h * 0.24
    xs = [cx - w, cx - w * 0.3, cx + w * 0.4, cx + w]
    for i, t in enumerate((0.55, 0.95, 0.4)):
        d.polygon([top, (xs[i], upper), (xs[i + 1], upper)], fill=tone(t))
        d.polygon([(xs[i], upper), (xs[i + 1], upper), (xs[i + 1], lower), (xs[i], lower)], fill=tone(t * 0.8))
        d.polygon([bottom, (xs[i], lower), (xs[i + 1], lower)], fill=tone(t * 0.55))
    for x in xs[1:3]:
        d.line([top, (x, upper), (x, lower), bottom], fill=tone(1.0), width=2)


def compass(img, cx, cy, r, ink):
    """A compass rose: rings and sixteen points."""
    d = ImageDraw.Draw(img)
    for rr, width in ((r, 4), (r * 0.92, 2), (r * 0.5, 2)):
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=ink, width=width)
    for i in range(16):
        a = math.pi * i / 8
        long = r * (0.88 if i % 4 == 0 else 0.66 if i % 2 == 0 else 0.44)
        tip = (cx + math.sin(a) * long, cy - math.cos(a) * long)
        side = r * 0.07
        left = (cx + math.sin(a - math.pi / 2) * side, cy - math.cos(a - math.pi / 2) * side)
        right = (cx + math.sin(a + math.pi / 2) * side, cy - math.cos(a + math.pi / 2) * side)
        d.polygon([tip, left, right], fill=ink)


def border(img, colour, inset=14):
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.rectangle((inset, inset, w - inset - 1, h - inset - 1), outline=colour, width=3)
    d.rectangle((inset + 8, inset + 8, w - inset - 9, h - inset - 9), outline=colour, width=1)


def banner(kind):
    S = 2
    w, h = 920 * S, 368 * S
    if kind == 'night':
        img = vgrad(w, h, (20, 36, 78), (4, 8, 22)).convert('RGBA')
        stars(img, 220, 11)
        img.alpha_composite(glow((w, h), (w * 0.76, h * 0.5), h * 0.9, (90, 150, 230), 0.55))
        crystal(img, w * 0.76, h * 0.5, h * 0.72, (190, 226, 255), (24, 60, 130))
        mark = wordmark_layer(int(w * 0.5), int(h * 0.6), sub='SINGLE PLAYER  ·  OFFLINE')
        at = (int(w * 0.31 - mark.width / 2), int(h * 0.5 - mark.height / 2))
        edge = (214, 170, 78, 255)
    elif kind == 'dawn':
        img = vgrad(w, h, (250, 240, 214), (226, 200, 150)).convert('RGBA')
        img.alpha_composite(glow((w, h), (w * 0.24, h * 0.5), h * 1.0, (255, 252, 236), 0.8))
        compass(img, w * 0.24, h * 0.5, h * 0.36, (150, 108, 44, 255))
        mark = wordmark_layer(int(w * 0.48), int(h * 0.6), top=(34, 70, 84), bottom=(8, 26, 36), rule=(170, 124, 50),
                              sub='SINGLE PLAYER  ·  OFFLINE', sub_ink=(60, 44, 20))
        at = (int(w * 0.67 - mark.width / 2), int(h * 0.5 - mark.height / 2))
        edge = (150, 108, 44, 255)
    else:                                   # ember
        img = vgrad(w, h, (70, 22, 30), (16, 6, 12)).convert('RGBA')
        img.alpha_composite(glow((w, h), (w * 0.5, h * 1.05), h * 1.3, (240, 130, 60), 0.6))
        d = ImageDraw.Draw(img)
        for i in range(5):                  # rings rising from below the frame, like a sun on the horizon (kept under the text)
            rr = h * (0.28 + i * 0.07)
            d.ellipse((w / 2 - rr, h * 1.25 - rr, w / 2 + rr, h * 1.25 + rr), outline=(250, 190, 110, 150 - i * 22), width=3)
        stars(img, 90, 5, (255, 226, 190))
        mark = wordmark_layer(int(w * 0.56), int(h * 0.62), top=IVORY_TOP, bottom=IVORY_BOTTOM, rule=(230, 150, 90),
                              sub='SINGLE PLAYER  ·  OFFLINE', sub_ink=(250, 226, 200))
        at = (int(w / 2 - mark.width / 2), int(h * 0.40 - mark.height / 2))
        edge = (230, 170, 100, 255)
    img.alpha_composite(mark, at)
    border(img, edge, 14 * S)
    return img.convert('RGB').resize((920, 368), Image.LANCZOS)


if __name__ == '__main__':
    ui, press = os.path.join(OUT, 'ui'), os.path.join(OUT, 'press')
    os.makedirs(ui, exist_ok=True)
    os.makedirs(press, exist_ok=True)
    home = home_button()
    home.save(os.path.join(ui, 'home.png'))
    hover_of(home).save(os.path.join(ui, 'home_hover.png'))
    grayscale_off(home).save(os.path.join(ui, 'home_off.png'))
    logo_tile().save(os.path.join(ui, 'logo_tile.png'))
    icon = app_icon(256)
    icon.save(os.path.join(ui, 'icon.png'))
    icon.save(os.path.join(ui, 'icon.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for number, kind in enumerate(('night', 'dawn', 'ember'), 1):
        banner(kind).save(os.path.join(press, f'xirpg_{number}_{kind}__center.png'))
    print('ok')
