"""Engine bay v2, group "front": decals (spec/engine-bay-v2.md). System Python + Pillow.

    bay_front_fins.png     radiator core, front and back faces: tubes and louvred fins
    bay_front_cap.png      radiator cap top: silver, pressed rim, red / yellow warning label
    bay_front_bottle.png   coolant overflow bottle, front face: moulded MAX / MIN marks, coolant level
    bay_front_tiebar.png   upper tie bar top: pressed holes, bolt heads, the latch footprint

The mappings (which model rectangle each image covers) are in front.py DECALS.
"""
import random

from PIL import Image, ImageDraw, ImageFilter

from bay.painting import bolt, font, grime, ground, shade, srgb


def fins():
    """0.72 x 0.207 m of core at 20 px/cm: flat tubes (vertical, ~9 mm pitch) with louvred fins between."""
    w, h = 1440, 414
    base = srgb("RadCore")
    im = ground(w, h, base)
    d = ImageDraw.Draw(im)
    pitch = 18
    # fins: fine horizontal ripples between the tubes
    for y in range(0, h, 3):
        c = shade(base, 1.18 if (y // 3) % 2 == 0 else 0.82)
        d.line([(0, y), (w, y)], fill=c, width=1)
    # tubes: a light flat with a dark gap either side
    for x in range(pitch // 2, w, pitch):
        d.rectangle([(x - 3, 0), (x + 3, h)], fill=shade(base, 0.55))
        d.rectangle([(x - 2, 0), (x + 2, h)], fill=shade(base, 1.35))
        d.line([(x - 2, 0), (x - 2, h)], fill=shade(base, 1.6), width=1)
    # header plates top and bottom where the tubes enter the tanks
    for y0, y1 in ((0, 10), (h - 10, h)):
        d.rectangle([(0, y0), (w, y1)], fill=shade(base, 0.9))
    # a few bent fin patches (stone damage) and dust low down
    rnd = random.Random(5)
    for _ in range(14):
        cx, cy = rnd.randint(20, w - 20), rnd.randint(h // 3, h - 20)
        rw, rh = rnd.randint(6, 18), rnd.randint(3, 8)
        d.ellipse([(cx - rw, cy - rh), (cx + rw, cy + rh)], fill=shade(base, 0.7))
    im = im.filter(ImageFilter.GaussianBlur(0.5))
    return grime(im, strength=0.22, seed=11, scale=40)


def cap():
    """Top of the radiator cap (x and y +-0.021 m about its centre), seen from the bumper."""
    s = 256
    steel = srgb("Steel")
    im = ground(s, s, shade(steel, 0.8))
    d = ImageDraw.Draw(im)
    c = s / 2
    r_cap = s * 0.019 / 0.042
    # pressed outer rim, a darker groove, the domed centre
    d.ellipse([(c - r_cap, c - r_cap), (c + r_cap, c + r_cap)], fill=shade(steel, 1.15))
    r2 = r_cap * 0.86
    d.ellipse([(c - r2, c - r2), (c + r2, c + r2)], fill=shade(steel, 0.75))
    r3 = r_cap * 0.80
    d.ellipse([(c - r3, c - r3), (c + r3, c + r3)], fill=steel)
    # the warning label: red band with DANGER, yellow field with small print, clipped to the dome
    lab = Image.new("RGB", (s, s), (0, 0, 0))
    ld = ImageDraw.Draw(lab)
    lw, lh = r3 * 1.30, r3 * 1.20
    x0, y0, x1, y1 = c - lw / 2, c - lh / 2 - 6, c + lw / 2, c + lh / 2 - 6
    ld.rectangle([(x0, y0), (x1, y1)], fill=(214, 182, 46))
    ld.rectangle([(x0, y0), (x1, y0 + lh * 0.42)], fill=(176, 28, 24))
    # warning triangle and the word
    tx = x0 + 14
    ld.polygon([(tx, y0 + lh * 0.34), (tx + 18, y0 + lh * 0.34), (tx + 9, y0 + lh * 0.08)], fill=(236, 226, 200))
    ld.text((tx + 24, y0 + lh * 0.07), "DANGER", font=font(17), fill=(240, 232, 214))
    for k in range(4):
        yy = y0 + lh * (0.52 + 0.11 * k)
        ld.line([(x0 + 10, yy), (x1 - 10 - 14 * (k % 2), yy)], fill=(60, 44, 20), width=3)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([(c - r3 + 3, c - r3 + 3), (c + r3 - 3, c + r3 - 3)], fill=255)
    im.paste(lab, (0, 0), mask)
    # small centre rivet and a highlight on the rim nearest the viewer
    d.arc([(c - r_cap + 2, c - r_cap + 2), (c + r_cap - 2, c + r_cap - 2)], 20, 160, fill=shade(steel, 1.45), width=4)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def bottle():
    """Coolant overflow bottle, inboard (-x) wall: y 1.800 (left) to 1.722 (right), z 0.728-0.882."""
    w, h = 320, 616
    base = srgb("Reservoir")
    im = ground(w, h, base, grain=4, seed=3, blur=1.0)
    d = ImageDraw.Draw(im)
    px = lambda z: h - (z - 0.728) / 0.154 * h          # noqa: E731  model z -> image row
    # coolant seen through the translucent wall: a soft, slightly greener lower part
    lvl = px(0.802)
    tint = (int(base[0] * 0.80), int(base[1] * 0.86), int(base[2] * 0.78))
    d.rectangle([(0, lvl), (w, h)], fill=tint)
    d.line([(0, lvl), (w, lvl)], fill=shade(tint, 0.8), width=4)
    # moulded marks: MAX and MIN with their lines, slightly darker raised plastic
    mk = shade(base, 0.62)
    f = font(46)
    for z, word in ((0.838, "MAX"), (0.768, "MIN")):
        y = px(z)
        d.line([(w * 0.08, y), (w * 0.40, y)], fill=mk, width=7)
        d.text((w * 0.44, y - 27), word, font=f, fill=mk)
    # moulding seams near the edges and a dirty bottom
    d.line([(10, 0), (10, h)], fill=shade(base, 0.8), width=3)
    d.line([(w - 10, 0), (w - 10, h)], fill=shade(base, 0.8), width=3)
    d.rectangle([(0, h - 30), (w, h)], fill=shade(tint, 0.8))
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    return grime(im, strength=0.18, seed=9, scale=32)


def tiebar():
    """Upper tie bar top (x 0.43 to -0.43 left to right, y 1.868 at the top to 1.835): 20 px/cm."""
    w, h = 1720, 66
    base = srgb("BlackPaint")
    im = ground(w, h, base, grain=3, seed=4, blur=0.8)
    d = ImageDraw.Draw(im)
    X = lambda x: (0.43 - x) / 0.86 * w                 # noqa: E731
    # a pressed rib along the front edge and a light edge along the rear
    d.rectangle([(0, 6), (w, 12)], fill=shade(base, 1.35))
    d.rectangle([(0, h - 6), (w, h)], fill=shade(base, 0.75))
    # lightening holes, oval, between the mounts
    for x in (-0.33, -0.25, -0.17, 0.17, 0.25, 0.33):
        cx = X(x)
        d.ellipse([(cx - 22, 22), (cx + 22, 46)], fill=shade(base, 0.25), outline=shade(base, 1.4), width=2)
    # bolts: the radiator mounts and the latch
    for x in (-0.38, -0.10, 0.10, 0.38):
        bolt(d, X(x), 34, 11, rgb=(78, 78, 82), rim=(22, 22, 24))
    # the latch footprint shadow, a small white service sticker on the right side of the car
    d.rectangle([(X(0.08), 14), (X(-0.08), h - 10)], fill=shade(base, 0.6))
    d.rectangle([(X(0.30), 18), (X(0.27), 48)], fill=(150, 146, 136))
    for k in range(3):
        d.line([(X(0.297), 24 + 8 * k), (X(0.273), 24 + 8 * k)], fill=(70, 68, 62), width=2)
    return grime(im, strength=0.2, seed=13, scale=20)


IMAGES = {
    "bay_front_fins.png": fins,
    "bay_front_cap.png": cap,
    "bay_front_bottle.png": bottle,
    "bay_front_tiebar.png": tiebar,
}
