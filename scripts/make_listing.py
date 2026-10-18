r"""
The Workshop gallery, preview and poster, rendered from the SHIPPED mod with pzview's showcase mode (grey
ground, shadows, a chosen skin) and framed at 1920 x 1080 with a caption. System Python + Pillow.

    python scripts\make_listing.py [--only hero,bay] [--keep]

Writes listing\shots\<name>\*.png (pzview's raw renders; --keep reuses them instead of rendering again),
listing\gallery\<name>.png, listing\preview_256.png (= mod\preview.png, the uploader's) and the mod's poster (42\poster.png, 1280 x 720), all from
the hero shot. The mechanics window image (gallery\mechanics.png) is not rendered here; it is kept as is.
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
BLENDER = _crv_paths.BLENDER
LISTING = os.path.join(ROOT, "listing")
POSTER = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "poster.png")
GROUND = "0.62,0.62,0.65"        # renders about sRGB (128, 130, 135) under the showcase light, as the old gallery
RES = 2400
W, H = 1920, 1080
FILL = 0.80                       # the car's bounding box fills this share of the frame (the tighter axis)

ARMOUR = ["CRVArmourArchFrontLeft", "CRVArmourArchFrontRight", "CRVArmourArchRearLeft", "CRVArmourArchRearRight",
          "CRVArmourDoorFrontLeft", "CRVArmourDoorFrontRight", "CRVArmourDoorRearLeft", "CRVArmourDoorRearRight",
          "CRVGuardFrontLeft", "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVGuardWindshieldRear"]
GUARD_BARS = ["CRVGuardFrontLeft", "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVGuardWindshieldRear"]
OFFROAD = ["CRVBullbar", "CRVRoofRack", "CRVOffroadSnorkel", "CRVOffroadSkidPlate", "CRVOffroadRearBumper",
           "CRVOffroadLadder", "CRVOffroadCanGate", "CRVOffroadCanRoof"]

# name: (caption, pzview args, the file pzview writes)
SHOTS = {
    "hero": ("Honda CRV (1st Gen, RD1)",
             ["--skin", "red", "--poses", "shut", "--az", "135", "--scale", "5.4"], "shut_135.png"),
    "bay": ("A new engine bay, modelled from photos of the real B20B",
            ["--skin", "silver", "--only", "--view", "bay,hood,120,0.05,1.40,0.85,2.3"], "view_bay.png"),
    "rear_open": ("Side-hinged tailgate, the glass lifts with it on gas struts",
                  ["--skin", "white", "--poses", "gate", "--az", "315", "--scale", "5.4"], "gate_315.png"),
    "doors": ("Every door, the hood and the tailgate open; the prop rod holds the hood",
              ["--skin", "green", "--poses", "open", "--az", "45", "--scale", "7.6"], "open_045.png"),
    "offroad": ("Bull bar, snorkel, skid plate, rack, ladder, steel bumper and jerry cans",
                ["--skin", "gold", "--script", "HondaCRVGen1LiftAlloy", "--acc", "--acc-parts", ",".join(OFFROAD),
                 "--rack", "2", "--poses", "shut", "--az", "315", "--scale", "5.6"], "shut_315.png"),
    "lifted": ("3-inch lift on all-terrain tyres, black steel wheels",
               ["--skin", "black", "--script", "HondaCRVGen1LiftSteel", "--poses", "shut", "--az", "135",
                "--scale", "5.4"], "shut_135.png"),
    "armour": ("Bolt-on armour: door plates, window mesh, arch guards, rear glass plate",
               ["--skin", "silver", "--acc", "--acc-parts", ",".join(ARMOUR), "--hide-models", ",".join(GUARD_BARS),
                "--poses", "shut", "--az", "45", "--scale", "5.4"], "shut_045.png"),
}
PAINTS = [("Electron Blue Pearl", None), ("Taffeta White", "white"), ("Nighthawk Black Pearl", "black"),
          ("Milano Red", "red"), ("Supermarine Blue Pearl", "blue"), ("Clover Green Pearl", "green"),
          ("Sebring Silver", "silver"), ("Naples Gold", "gold")]


def font(size):
    p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")
    return ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()


def render(out_dir, args):
    os.makedirs(out_dir, exist_ok=True)
    cmd = [BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "pzview.py"), "--",
           "--out", out_dir, "--res", str(RES), "--ground", GROUND, "--shadows"] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "Traceback" in (r.stdout + r.stderr) or r.returncode:
        raise SystemExit("pzview failed for %s:\n%s" % (out_dir, (r.stdout + r.stderr)[-3000:]))


def ground_rgb(img):
    a = np.asarray(img, dtype=np.int16)
    corners = np.concatenate([a[:8, :8].reshape(-1, 3), a[:8, -8:].reshape(-1, 3)])
    return np.median(corners, axis=0)


def cover(img, w, h):
    """Scale img to cover w x h and crop the middle (a close-up that fills its render)."""
    img = img.convert("RGB")
    k = max(w / img.width, h / img.height)
    big = img.resize((int(round(img.width * k)), int(round(img.height * k))), Image.LANCZOS)
    x, y = (big.width - w) // 2, (big.height - h) // 2
    return big.crop((x, y, x + w, y + h))


def frame(img, w, h, fill=FILL):
    """Crop / pad img (the ground colour) so the car's box sits centred and fills `fill` of w x h; a
    close-up whose subject touches the render's edges covers the frame instead (cover)."""
    img = img.convert("RGB")
    g = ground_rgb(img)
    a = np.asarray(img, dtype=np.int16)
    car = np.abs(a - g).max(axis=2) > 14
    ys, xs = np.nonzero(car)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    if x0 <= 2 or y0 <= 2 or x1 >= img.width - 3 or y1 >= img.height - 3:
        return cover(img, w, h)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    k = min(fill * w / bw, fill * h / bh)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    big = img.resize((int(round(img.width * k)), int(round(img.height * k))), Image.LANCZOS)
    out = Image.new("RGB", (w, h), tuple(int(v) for v in g))
    out.paste(big, (int(round(w / 2 - cx * k)), int(round(h / 2 - cy * k))))
    return out


def caption(img, text, size=36, xy=(48, None)):
    d = ImageDraw.Draw(img)
    f = font(size)
    y = xy[1] if xy[1] is not None else img.height - 48 - size
    d.text((xy[0] + 2, y + 2), text, font=f, fill=(40, 40, 42))
    d.text((xy[0], y), text, font=f, fill=(235, 235, 238))
    return img


# The Workshop preview (mod\preview.png). The game's uploader (SteamWorkshopItem.validatePreviewImage) takes a
# square PNG of exactly 256 or 512 px, at most 1,024,000 bytes. A designed thumbnail rather than a game-camera shot:
# the lifted off-road build from a low front three-quarter perspective, cut out of a green key ground (pzview has no
# transparent background; the ground's shading gives the soft shadow), on a dusk gradient, the name across the top.
PREVIEW_EYE = ["preview", "shut", [-7.2, 6.2, 3.2], [0.0, 0.0, 0.85], 34]
PREVIEW_ARGS = ["--skin", "red", "--script", "HondaCRVGen1LiftAlloy", "--acc", "--acc-parts", ",".join(OFFROAD),
                "--rack", "2", "--ground", "0,1,0", "--res", "2000"]


def font_bold(size):
    for name in ("ariblk.ttf", "arialbd.ttf"):
        p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return font(size)


def render_eye(d, eye, args, keep):
    """One perspective pzview view (--eyes) into d; returns the png path."""
    import json
    src = os.path.join(d, "eye_%s.png" % eye[0])
    if keep and os.path.exists(src):
        return src
    os.makedirs(d, exist_ok=True)
    eyes = os.path.join(d, "eyes.json")
    with open(eyes, "w", encoding="utf-8") as f:
        json.dump([eye], f)
    cmd = [BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "pzview.py"), "--", "--out", d, "--only",
           "--shadows", "--eyes", eyes] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "Traceback" in (r.stdout + r.stderr) or r.returncode:
        raise SystemExit("pzview failed for %s:\n%s" % (eye[0], (r.stdout + r.stderr)[-3000:]))
    return src


def world(a, level=14.0):
    """Pixels of the render's empty black world: dark pixels connected to the top edge (the car's own dark
    parts are enclosed by the car or the ground, so they stay)."""
    from scipy import ndimage
    dark = a.max(axis=2) < level
    lab, _n = ndimage.label(dark)
    top = np.unique(lab[0][lab[0] > 0])
    return np.isin(lab, top)


def gradient(w, h):
    """The dusk backdrop: night blue at the top, warm haze low, a soft vignette."""
    t = np.linspace(0.0, 1.0, h)[:, None, None]
    top, mid, low = np.array([16, 20, 32.0]), np.array([58, 52, 62.0]), np.array([150, 82, 40.0])
    grad = np.where(t < 0.62, top + (mid - top) * (t / 0.62), mid + (low - mid) * ((t - 0.62) / 0.38))
    canvas = np.repeat(np.repeat(grad, w, axis=1), 1, axis=0).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1.0 - 0.35 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h * 0.55) / (h / 2)) ** 2)
    return canvas * np.clip(vig, 0.55, 1.0)[..., None]


def studio(src, w, h, fill=0.86, centre_y=0.61):
    """A green-ground render (--ground 0,1,0) cut out onto the dusk gradient, w x h, the car `fill` of the width
    (or 0.8 of the height, whichever is tighter), centred at `centre_y`; the ground's shading as the shadow."""
    from PIL import ImageFilter
    a = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
    r_, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
    green = (g_ > r_ + 25) & (g_ > b_ + 25)
    sky = world(a) & ~green                                # the black world beyond the ground, flood-filled from the top
    car = ~(green | sky)
    spill = np.clip((g_ - np.maximum(r_, b_)) / 60.0, 0.0, 1.0)
    edge = np.asarray(Image.fromarray((car * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255
    alpha = np.where(car, 1.0, np.where(green, np.clip(edge * (1 - spill), 0, 1), 0.0))
    ground_g = np.median(g_[green]) if green.any() else 255.0
    shade = np.where(green, np.clip(1.0 - g_ / max(ground_g, 1.0), 0.0, 1.0), 0.0)
    shade = np.clip((shade - 0.25) / 0.5, 0.0, 1.0)       # the cast shadow only, not the far ground's falloff
    rgb = a.copy()
    rgb[..., 1] = np.minimum(rgb[..., 1], np.maximum(rgb[..., 0], rgb[..., 2]) + 6)   # despill the edges
    rgb = np.clip(rgb * 1.35 + 6, 0, 255)                                              # the studio light is dim
    ys, xs = np.nonzero(car)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    canvas = gradient(w, h)
    k = min(fill * w / (x1 - x0), 0.80 * h / (y1 - y0))
    cw, chh = int((x1 - x0) * k), int((y1 - y0) * k)
    ox, oy = (w - cw) // 2, int(h * centre_y - chh * 0.45)
    crop = (int(x0), int(y0), int(x1) + 1, int(y1) + 1)

    def fit(arr, mode):
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode).crop(crop)
        return np.asarray(im.resize((cw, chh), Image.LANCZOS), np.float32)
    car_rgb = fit(rgb, "RGB")
    car_a = fit(alpha * 255, "L")[..., None] / 255.0
    sh_a = fit(shade * 255, "L")[..., None] / 255.0
    sh = Image.new("L", (w, h), 0)                       # a soft contact shadow under the wheels
    ImageDraw.Draw(sh).ellipse([ox + cw * 0.08, oy + chh * 0.80, ox + cw * 0.95, oy + chh * 1.03], fill=170)
    sh = np.asarray(sh.filter(ImageFilter.GaussianBlur(max(8, w // 46))), np.float32)[..., None] / 255.0
    canvas *= 1.0 - 0.75 * sh
    y_a, y_b = max(oy, 0), min(oy + chh, h)
    x_a, x_b = max(ox, 0), min(ox + cw, w)
    sl = (slice(y_a - oy, y_b - oy), slice(x_a - ox, x_b - ox))
    region = canvas[y_a:y_b, x_a:x_b]
    region *= 1.0 - 0.6 * sh_a[sl]
    region[:] = region * (1.0 - car_a[sl]) + car_rgb[sl] * car_a[sl]
    return Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))


def interior(src, w, h, gain=1.9):
    """A view inside the car (cabin, cargo bed): covered to w x h, the dim studio light lifted, the black world
    seen through the glass replaced by the dusk sky."""
    a = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
    lit = np.clip(a * gain + 4, 0, 255)
    sky = world(a, 4.0)
    lit[sky] = gradient(a.shape[1], a.shape[0])[sky]
    img = Image.fromarray(lit.astype(np.uint8))
    return cover(img, w, h)


def preview(keep):
    src = render_eye(os.path.join(LISTING, "shots", "preview"), PREVIEW_EYE, PREVIEW_ARGS, keep)
    N = 1024
    out = studio(src, N, N, 0.86, 0.61)
    dr = ImageDraw.Draw(out)
    f1, f2 = font_bold(138), font_bold(50)
    for text, f, y, fill in (("HONDA CRV", f1, 40, (245, 242, 236)), ("1ST GEN  \u00b7  BUILD 42", f2, 205, (236, 170, 96))):
        tw = dr.textlength(text, font=f)
        x = (N - tw) / 2
        dr.text((x + 4, y + 5), text, font=f, fill=(0, 0, 0))
        dr.text((x, y), text, font=f, fill=fill)
    big = out.resize((512, 512), Image.LANCZOS)
    big.save(os.path.join(ROOT, "mod", "preview.png"), optimize=True)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(LISTING, "preview_256.png"))
    size = os.path.getsize(os.path.join(ROOT, "mod", "preview.png"))
    if size > 1024000:
        raise SystemExit("preview.png is %d bytes: the uploader takes at most 1,024,000" % size)
    print("LISTING mod\\preview.png 512x512 (%d bytes), preview_256.png" % size)


# Perspective gallery shots: name -> (caption, eye [name, pose, eye xyz, look-at xyz, fov], pzview args, kind)
# kind "studio": cut out of the green ground onto the dusk gradient; "interior": a view inside the car.
GREEN = ["--ground", "0,1,0", "--res", "2400"]
EYE_SHOTS = {
    "front34": ("Clear chrome headlamps, the RD1 grille and grey bumpers",
                ["front34", "shut", [-4.4, 6.8, 1.15], [-0.1, 0.8, 0.8], 34], ["--skin", "red"] + GREEN, "studio"),
    "rear34": ("Tail lamps that light on the brake; the spare rides on the tailgate",
               ["rear34", "shut", [4.4, -5.6, 1.5], [0.1, -0.6, 0.9], 34], ["--skin", "white"] + GREEN, "studio"),
    "lifted34": ("Lifted on 30-inch all-terrain tyres and black steel wheels",
                 ["lifted34", "shut", [5.6, 5.0, 1.2], [0.0, 0.1, 0.95], 36],
                 ["--skin", "green", "--script", "HondaCRVGen1LiftSteel"] + GREEN, "studio"),
    "cabin": ("The cabin from the driver's seat: built for first and third person (Project Viewpoint)",
              ["cabin", "shut", [-0.36, -0.12, 1.47], [-0.05, 1.2, 1.05], 82],
              ["--skin", "blue", "--res", "2400", "--ground", "0.62,0.62,0.65"], "interior"),
    "bed": ("Fold the rear seats into a flat bed",
            ["bed", "gate", [0.35, -3.2, 1.55], [0.0, -0.7, 0.75], 58],
            ["--skin", "silver", "--folded", "--res", "2400", "--ground", "0.62,0.62,0.65"], "interior"),
}


def eye_shots(only, keep, gal):
    for name, (text, eye, args, kind) in EYE_SHOTS.items():
        if only and name not in only:
            continue
        src = render_eye(os.path.join(LISTING, "shots", name), eye, args, keep)
        img = studio(src, W, H, 0.80, 0.56) if kind == "studio" else interior(src, W, H)
        caption(img, text).save(os.path.join(gal, name + ".png"))
        print("LISTING gallery\\%s.png" % name)


def manual_page(only, gal):
    """The owner's manual's three spreads (listing\\manual, drawn by manual_art.py) on one page."""
    if only and "manual" not in only:
        return
    spreads = [os.path.join(LISTING, "manual", "owners_manual_%d.png" % i) for i in (1, 2, 3)]
    if not all(os.path.exists(p) for p in spreads):
        print("LISTING manual: spreads missing, skipped")
        return
    canvas = Image.fromarray(gradient(W, H).astype(np.uint8))
    big = Image.open(spreads[0]).convert("RGB")
    bw = int(W * 0.60)
    big = big.resize((bw, int(big.height * bw / big.width)), Image.LANCZOS)
    canvas.paste(big, (60, (H - big.height) // 2 - 20))
    sw = W - bw - 180
    y = 120
    for p in spreads[1:]:
        im = Image.open(p).convert("RGB")
        im = im.resize((sw, int(im.height * sw / im.width)), Image.LANCZOS)
        canvas.paste(im, (bw + 120, y))
        y += im.height + 40
    caption(canvas, "An illustrated owner's manual in every glove box").save(os.path.join(gal, "manual.png"))
    print("LISTING gallery\\manual.png")


# Photo shots (scripts\beauty.py: the shipped car in EEVEE with a sky, a sun and an asphalt ground), 2026-10-18.
# name -> (caption, [pose, eye xyz, look-at xyz, fov, options], beauty / pzview args). Shots with the same args
# render in one Blender run. They replace the pzview showcase shots in the gallery (SHOTS / EYE_SHOTS stay
# for --pzview).
RED, GOLD = ["--skin", "red"], ["--skin", "gold", "--script", "HondaCRVGen1LiftAlloy", "--acc", "--acc-parts",
                                ",".join(OFFROAD), "--rack", "2"]
PHOTOS = {
    "hero": ("Honda CRV (1st Gen, RD1)",
             ["shut", [-5.4, 5.6, 0.95], [-0.1, 0.2, 0.8], 34, {"sun": [22, 160]}], RED),
    "table": ("The picnic table comes out from under the cargo floor",
              ["gate", [-5.6, -7.6, 1.7], [-0.7, -2.9, 0.6], 40, {"table": [-0.3, -4.5, 10], "sun": [30, 60]}], RED),
    "bay": ("A new engine bay, modelled from photos of the real B20B",
            ["hood", [-1.5, 3.7, 1.95], [0.0, 1.3, 0.72], 46, {"sun": [50, 150]}], RED),
    "doors": ("Every door, the hood and the tailgate open; the prop rod holds the hood",
              ["open", [-5.6, 3.6, 2.0], [0.0, -0.2, 0.8], 40, {"sun": [35, 200]}], RED),
    "rear34": ("Tail lamps that light on the brake; the spare rides on the side-hinged tailgate",
               ["shut", [4.4, -5.9, 1.3], [0.1, -0.6, 0.85], 34, {"sun": [25, 300]}], ["--skin", "white"]),
    "offroad": ("Bull bar, snorkel, skid plate, rack, ladder, steel bumper and jerry cans",
                ["shut", [5.8, 5.4, 1.05], [0.0, 0.1, 1.0], 36, {"sun": [24, 200]}], GOLD),
    "offroad_rear": ("Steel rear bumper with a hitch, a ladder to the rack, jerry cans that hold real fuel",
                     ["shut", [-5.2, -6.2, 1.5], [0.0, -0.6, 1.0], 36, {"sun": [24, 200]}], GOLD),
    "lifted": ("3-inch lift on 30-inch all-terrain tyres and black steel wheels",
               ["shut", [5.6, 5.0, 1.0], [0.0, 0.1, 0.95], 36, {"sun": [26, 230]}],
               ["--skin", "green", "--script", "HondaCRVGen1LiftSteel"]),
    "armour": ("Bolt-on armour: door plates, window mesh, arch guards, rear glass plate",
               ["shut", [-5.6, 5.0, 1.3], [0.0, 0.0, 0.9], 36, {"sun": [30, 150]}],
               ["--skin", "silver", "--acc", "--acc-parts", ",".join(ARMOUR), "--hide-models", ",".join(GUARD_BARS)]),
    "bed": ("Fold the rear seats into a flat bed",
            ["bed", "gate", [0.35, -3.2, 1.55], [0.0, -0.7, 0.75], 58],
            ["--skin", "silver", "--folded", "--res", "2400", "--ground", "0.62,0.62,0.65"], "interior"),
}


def eye_shots(only, keep, gal):
    for name, (text, eye, args, kind) in EYE_SHOTS.items():
        if only and name not in only:
            continue
        src = render_eye(os.path.join(LISTING, "shots", name), eye, args, keep)
        img = studio(src, W, H, 0.80, 0.56) if kind == "studio" else interior(src, W, H)
        caption(img, text).save(os.path.join(gal, name + ".png"))
        print("LISTING gallery\\%s.png" % name)


def manual_page(only, gal):
    """The owner's manual's three spreads (listing\\manual, drawn by manual_art.py) on one page."""
    if only and "manual" not in only:
        return
    spreads = [os.path.join(LISTING, "manual", "owners_manual_%d.png" % i) for i in (1, 2, 3)]
    if not all(os.path.exists(p) for p in spreads):
        print("LISTING manual: spreads missing, skipped")
        return
    canvas = Image.fromarray(gradient(W, H).astype(np.uint8))
    big = Image.open(spreads[0]).convert("RGB")
    bw = int(W * 0.60)
    big = big.resize((bw, int(big.height * bw / big.width)), Image.LANCZOS)
    canvas.paste(big, (60, (H - big.height) // 2 - 20))
    sw = W - bw - 180
    y = 120
    for p in spreads[1:]:
        im = Image.open(p).convert("RGB")
        im = im.resize((sw, int(im.height * sw / im.width)), Image.LANCZOS)
        canvas.paste(im, (bw + 120, y))
        y += im.height + 40
    caption(canvas, "An illustrated owner's manual in every glove box").save(os.path.join(gal, "manual.png"))
    print("LISTING gallery\\manual.png")


# Photo shots (scripts\beauty.py: the shipped car in EEVEE with a sky, a sun and an asphalt ground), 2026-10-18.
# name -> (caption, [pose, eye xyz, look-at xyz, fov, options], beauty / pzview args). Shots with the same args
# render in one Blender run. They replace the pzview showcase shots in the gallery (SHOTS / EYE_SHOTS stay
# for --pzview).
RED, GOLD = ["--skin", "red"], ["--skin", "gold", "--script", "HondaCRVGen1LiftAlloy", "--acc", "--acc-parts",
                                ",".join(OFFROAD), "--rack", "2"]
PHOTOS = {
    "hero": ("Honda CRV (1st Gen, RD1)",
             ["shut", [-5.4, 5.6, 0.95], [-0.1, 0.2, 0.8], 34, {"sun": [22, 160]}], RED),
    "table": ("The picnic table comes out from under the cargo floor",
              ["gate", [-5.6, -7.6, 1.7], [-0.7, -2.9, 0.6], 40, {"table": [-0.3, -4.5, 10], "sun": [30, 60]}], RED),
    "bay": ("A new engine bay, modelled from photos of the real B20B",
            ["hood", [-1.5, 3.7, 1.95], [0.0, 1.3, 0.72], 46, {"sun": [50, 150]}], RED),
    "doors": ("Every door, the hood and the tailgate open; the prop rod holds the hood",
              ["open", [-5.6, 3.6, 2.0], [0.0, -0.2, 0.8], 40, {"sun": [35, 200]}], RED),
    "rear34": ("Tail lamps that light on the brake; the spare rides on the side-hinged tailgate",
               ["shut", [4.4, -5.9, 1.3], [0.1, -0.6, 0.85], 34, {"sun": [25, 300]}], ["--skin", "white"]),
    "offroad": ("Bull bar, snorkel, skid plate, rack, ladder, steel bumper and jerry cans",
                ["shut", [5.8, 5.4, 1.05], [0.0, 0.1, 1.0], 36, {"sun": [24, 200]}], GOLD),
    "offroad_rear": ("Steel rear bumper with a hitch, a ladder to the rack, jerry cans that hold real fuel",
                     ["shut", [-5.2, -6.2, 1.5], [0.0, -0.6, 1.0], 36, {"sun": [24, 200]}], GOLD),
    "lifted": ("3-inch lift on 30-inch all-terrain tyres and black steel wheels",
               ["shut", [5.6, 5.0, 1.0], [0.0, 0.1, 0.95], 36, {"sun": [26, 230]}],
               ["--skin", "green", "--script", "HondaCRVGen1LiftSteel"]),
    "armour": ("Bolt-on armour: door plates, window mesh, arch guards, rear glass plate",
               ["shut", [-5.6, 5.0, 1.3], [0.0, 0.0, 0.9], 36, {"sun": [30, 150]}],
               ["--skin", "silver", "--acc", "--acc-parts", ",".join(ARMOUR), "--hide-models", ",".join(GUARD_BARS)]),
    "bed": ("Fold the rear seats into a flat bed",
            ["gate", [0.35, -3.2, 1.55], [0.0, -0.7, 0.75], 58, {"interior": True, "exposure": -0.4, "sun": [40, 120]}],
            ["--skin", "silver", "--folded"]),
}
RETIRED = ["front34", "lifted34", "rear_open", "cabin"]       # older gallery names the photos replace (cabin: the
                                                     # low-poly seats read boxy in a close photo; the bed shot shows the cabin)


def photos(only, keep, gal):
    import json
    groups = {}
    for name, (text, shot, args) in PHOTOS.items():
        if only and name not in only:
            continue
        groups.setdefault(tuple(args), []).append(name)
    raw = os.path.join(LISTING, "shots", "photo")
    os.makedirs(raw, exist_ok=True)
    for args, names in groups.items():
        todo = [n for n in names if not (keep and os.path.exists(os.path.join(raw, n + ".png")))]
        if todo:
            rows = [[n] + PHOTOS[n][1] for n in todo]
            spec = os.path.join(raw, "_shots_%s.json" % todo[0])
            with open(spec, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            cmd = [BLENDER, "-b", "--factory-startup", "--python", os.path.join(S, "beauty.py"), "--",
                   "--shots", spec, "--out", raw, "--samples", "96"] + list(args)
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if "Traceback" in (r.stdout + r.stderr) or "BEAUTY DONE" not in r.stdout:
                raise SystemExit("beauty failed for %s:\n%s" % (todo, (r.stdout + r.stderr)[-3000:]))
        for n in names:
            img = caption(Image.open(os.path.join(raw, n + ".png")).convert("RGB"), PHOTOS[n][0])
            img.save(os.path.join(gal, n + ".png"))
            print("LISTING gallery\\%s.png (photo)" % n)
            if n == "hero":
                cover(Image.open(os.path.join(raw, n + ".png")), 1280, 720).save(POSTER)
                print("LISTING poster.png 1280x720")


def jpgs(gal):
    """listing\\gallery_jpg: the same pictures as JPG (smaller uploads), stale ones removed."""
    out = os.path.join(LISTING, "gallery_jpg")
    os.makedirs(out, exist_ok=True)
    names = {os.path.splitext(f)[0] for f in os.listdir(gal) if f.endswith(".png")}
    for f in os.listdir(out):
        if os.path.splitext(f)[0] not in names:
            os.remove(os.path.join(out, f))
    for n in sorted(names):
        Image.open(os.path.join(gal, n + ".png")).convert("RGB").save(os.path.join(out, n + ".jpg"), quality=92)


def main():
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    keep = "--keep" in sys.argv
    gal = os.path.join(LISTING, "gallery")
    os.makedirs(gal, exist_ok=True)
    for n in RETIRED:
        p = os.path.join(gal, n + ".png")
        if os.path.exists(p):
            os.remove(p)
    if "--pzview" in sys.argv:                           # the old game-camera showcase shots
        for name, (text, args, fn) in SHOTS.items():
            if only and name not in only:
                continue
            d = os.path.join(LISTING, "shots", name)
            if not (keep and os.path.exists(os.path.join(d, fn))):
                render(d, args)
            caption(frame(Image.open(os.path.join(d, fn)), W, H), text).save(os.path.join(gal, name + ".png"))
            print("LISTING gallery\\%s.png" % name)
        eye_shots(only, keep, gal)
    else:
        photos(only, keep, gal)
    if not only or "preview" in only:
        preview(keep)
    manual_page(only, gal)
    if not only or "paints" in only:
        cw, ch = W // 4, (H - 60) // 2
        sheet = None
        for i, (label, skin) in enumerate(PAINTS):
            d = os.path.join(LISTING, "shots", "paint_" + (skin or "electron"))
            if not (keep and os.path.exists(os.path.join(d, "shut_135.png"))):
                render(d, (["--skin", skin] if skin else []) + ["--poses", "shut", "--az", "135", "--scale", "5.4"])
            cell = frame(Image.open(os.path.join(d, "shut_135.png")), cw, ch, 0.84)
            if sheet is None:
                sheet = Image.new("RGB", (W, H), cell.getpixel((2, 2)))
            caption(cell, label, 30, (22, ch - 52))
            sheet.paste(cell, ((i % 4) * cw, 60 + (i // 4) * ch))
        caption(sheet, "Eight RD1 factory paints", 32, (48, 14))
        sheet.save(os.path.join(gal, "paints.png"))
        print("LISTING gallery\\paints.png")
    jpgs(gal)


if __name__ == "__main__":
    main()
