r"""
Video memory of every texture the mod ships (optimization pass, 2026-10-24):

    python scripts\test_texture_vram.py            the tests
    python scripts\test_texture_vram.py --report   the table: MB per Vehicle Texture Size setting

How the game holds a texture (projectzomboid.jar B42, javap 2026-10-24):
  * BaseVehicle.LoadAllVehicleTextures loads EVERY skin of EVERY vehicle script at start (LoadVehicleTextures:
    texture, textureMask, damage overlays / shells, lights, rust), shared by file name; flags 256
    (LIMIT_TEXTURE_SIZE_2) | 4 (COMPRESS) when texture compression is on; the Mask 256 only. A model whose shader
    starts with "vehicle" (ModelManager.loadModelInternal) gets the same flags; it loads with the model.
  * Core.getMaxTextureSizeFromFlags(256) = the Vehicle Texture Size option 1..4 = 256 / 512 / 1024 / 2048
    (default 2: 512); TextureID.limitMaxSize takes 2 x 2 mip levels until both sides fit.
  * No MIPMAPS flag on these paths: one level, 4 bytes a texel (GL_RGBA8; GL_COMPRESSED_RGBA, ~1 byte, with the
    compression option, never for the Mask). RGB files are expanded to RGBA.
  * ImageData pads every side to the next power of two (widthHW / heightHW) and the upload is that size.
  * UI textures (getTexture: print media, the mechanics overlay) carry no size flag: never capped, resident
    once drawn. A 3232 x 2262 manual spread was 4096 x 4096 = 64 MB; a 263 x 600 overlay sheet 512 x 1024 = 2 MB.
Tests (each failed on master 0.4.4: manual 64 MB a spread, overlays 112 MB):
  * manual: every spread manual_art.SHIP_W x SHIP_H, a power-of-two width, the Print_Media spread's aspect, at
    least its logical 1616 px wide, <= 16 MB on the GPU;
  * overlays: compose_overlays.ship_crop keeps every drawn pixel where the window draws it (a synthetic sheet,
    re-padded, is identical); every shipped image is cut tight (its last column / row is the one transparent
    texel after the last drawn one) and the set is <= OVERLAY_MB;
  * vehicle sheets: the total at each setting stays within VEHICLE_MB (no texture grew).
"""
import glob
import os
import re
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(HERE)
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
MEDIA = os.path.join(MOD, "common", "media")
MB = 1024.0 * 1024.0
CAPS = (256, 512, 1024, 2048)
VEHICLE_MB = {256: 5.5, 512: 22.0, 1024: 76.0, 2048: 184.0}   # 0.4.4 (8 skins + Mask at 2048; see the report)
OVERLAY_MB = 24.0                                              # 112 before ship_crop, 20.1 after
MANUAL_MB = 16.0                                               # a spread; 64 before


def fail(msg):
    raise SystemExit("FAIL " + msg)


def pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def capped(w, h, cap):
    """TextureID.limitMaxSize: whole 2 x 2 mip levels until both sides fit the cap."""
    while w > cap or h > cap:
        w, h = max(1, w // 2), max(1, h // 2)
    return w, h


def gpu_mb(w, h, cap=None):
    if cap:
        w, h = capped(w, h, cap)
    return pow2(w) * pow2(h) * 4 / MB


def vehicle_sheets():
    """{name: (w, h)} of the Vehicles/ sheets some vehicle or model script names (what the game loads)."""
    used = ""
    for p in glob.glob(os.path.join(MOD, "42", "media", "scripts", "**", "*.txt"), recursive=True):
        used += open(p, encoding="utf-8").read()
    out = {}
    for p in sorted(glob.glob(os.path.join(MEDIA, "textures", "Vehicles", "*.png"))):
        name = os.path.basename(p)[:-4]
        if re.search(r"Vehicles/%s(?![A-Za-z0-9_])" % re.escape(name), used):
            out[name] = Image.open(p).size
    return out


def table():
    v = vehicle_sheets()
    veh = {c: sum(gpu_mb(w, h, c) for w, h in v.values()) for c in CAPS}
    manual = {os.path.basename(p): Image.open(p).size for p in sorted(glob.glob(os.path.join(MEDIA, "textures", "printMedia", "*.png")))}
    ov = [Image.open(p).size for p in glob.glob(os.path.join(MEDIA, "ui", "vehicles", "mechanic overlay", "*.png"))]
    return v, veh, manual, ov


def report():
    v, veh, manual, ov = table()
    unused = sorted(set(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(MEDIA, "textures", "Vehicles", "*.png"))) - set(v))
    print("vehicle sheets loaded (%d): %s" % (len(v), ", ".join("%s %dx%d" % (n.split("_", 2)[-1], w, h) for n, (w, h) in v.items())))
    print("never loaded (no script names them): %s" % (", ".join(unused) or "none"))
    m = sum(gpu_mb(w, h) for w, h in manual.values())
    o = sum(gpu_mb(w, h) for w, h in ov)
    mask = [wh for n, wh in v.items() if n.endswith("_Mask")]
    for c in CAPS:
        raw = sum(gpu_mb(w, h, c) for w, h in mask)          # the Mask is never compressed
        print("Vehicle Texture Size %4d: vehicle sheets %6.1f MB (compressed ~%5.1f) + manual %5.1f + mechanics overlay %5.1f = %6.1f MB"
              % (c, veh[c], (veh[c] - raw) / 4 + raw, m, o, veh[c] + m + o))


def test_manual():
    import manual_art as MA
    if MA.SHIP_W & (MA.SHIP_W - 1) or MA.SHIP_W < MA.W:
        fail("manual: SHIP_W %d is no power of two at least the spread's logical %d px" % (MA.SHIP_W, MA.W))
    info = open(os.path.join(MOD, "42", "media", "lua", "shared", "Translate", "EN", "Print_Media.json"), encoding="utf-8").read()
    pages = re.findall(r"texture:media/textures/printMedia/(\w+\.png), x:0, y:0, width:(\d+), height:(\d+)", info)
    if len(pages) != 3:
        fail("manual: Print_Media.json names %d spread textures, want 3" % len(pages))
    for f, lw, lh in pages:
        p = os.path.join(MEDIA, "textures", "printMedia", f)
        w, h = Image.open(p).size
        if (w, h) != (MA.SHIP_W, MA.SHIP_H):
            fail("manual: %s is %dx%d, want manual_art's %dx%d (run manual_art.py)" % (f, w, h, MA.SHIP_W, MA.SHIP_H))
        if abs(w / h - int(lw) / int(lh)) > 0.005 * int(lw) / int(lh):
            fail("manual: %s aspect %.4f, drawn at %s x %s (%.4f)" % (f, w / h, lw, lh, int(lw) / int(lh)))
        if gpu_mb(w, h) > MANUAL_MB:
            fail("manual: %s %dx%d is a %dx%d texture, %.0f MB on the GPU (budget %.0f)"
                 % (f, w, h, pow2(w), pow2(h), gpu_mb(w, h), MANUAL_MB))
    print("VRAM manual: 3 spreads %dx%d, %.0f MB each on the GPU" % (MA.SHIP_W, MA.SHIP_H, gpu_mb(MA.SHIP_W, MA.SHIP_H)))


def test_overlay_crop():
    import compose_overlays as CO
    rng = np.random.default_rng(3)
    sheet = np.zeros((CO.H, CO.W, 4), np.uint8)
    sheet[200:330, 40:190] = rng.integers(0, 256, (130, 150, 4), dtype=np.uint8)
    sheet[200:330, 40:190, 3] = 255
    sheet[100, 7, :] = (255, 255, 255, 40)                   # a faint lone texel: kept, it draws
    im = Image.fromarray(sheet)
    cut = CO.ship_crop(im)
    if cut.size != (191, 331):
        fail("overlay: ship_crop cut the synthetic sheet to %s, want (191, 331)" % (cut.size,))
    back = Image.new("RGBA", im.size, (0, 0, 0, 0))
    back.paste(cut, (0, 0))
    if (np.asarray(back) != sheet).any():
        fail("overlay: a cut sheet re-padded differs from the drawn one")
    empty = Image.new("RGBA", (CO.W, CO.H), (0, 0, 0, 0))
    if CO.ship_crop(empty).size != (CO.W, CO.H):
        fail("overlay: ship_crop must leave an empty sheet whole")
    print("VRAM overlay crop: a cut sheet re-padded is identical; only right / bottom margins go")


def test_overlays_shipped():
    import compose_overlays as CO
    files = sorted(glob.glob(os.path.join(MEDIA, "ui", "vehicles", "mechanic overlay", CO.PREFIX + "*.png")))
    if not files:
        fail("overlay: no %s*.png shipped" % CO.PREFIX)
    loose = []
    total = 0.0
    for p in files:
        im = Image.open(p)
        a = np.asarray(im.convert("RGBA"))[..., 3]
        ys, xs = np.nonzero(a)
        want = (min(CO.W, int(xs.max()) + 2), min(CO.H, int(ys.max()) + 2)) if len(xs) else (CO.W, CO.H)
        if im.size != want:
            loose.append("%s %dx%d (drawn to %dx%d)" % (os.path.basename(p), im.size[0], im.size[1], want[0], want[1]))
        total += gpu_mb(*im.size)
    if loose:
        fail("overlay: %d images not cut tight (run compose_overlays.py): %s" % (len(loose), "; ".join(loose[:4])))
    if total > OVERLAY_MB:
        fail("overlay: the %d images take %.1f MB on the GPU, budget %.0f" % (len(files), total, OVERLAY_MB))
    print("VRAM overlay: %d images cut tight, %.1f MB on the GPU (512 x 1024 each before: %.0f MB)"
          % (len(files), total, len(files) * gpu_mb(CO.W, CO.H)))


def test_vehicle_sheets():
    v, veh, _m, _o = table()
    if not v:
        fail("vehicle: no sheets found under %s" % MEDIA)
    for c in CAPS:
        if veh[c] > VEHICLE_MB[c] + 0.05:
            fail("vehicle: the sheets take %.1f MB at Vehicle Texture Size %d, budget %.1f (a sheet grew?)" % (veh[c], c, VEHICLE_MB[c]))
    print("VRAM vehicle sheets: %s MB at %s" % (" / ".join("%.1f" % veh[c] for c in CAPS), " / ".join(str(c) for c in CAPS)))


def main():
    if "--report" in sys.argv:
        report()
        return
    test_manual()
    test_overlay_crop()
    test_overlays_shipped()
    test_vehicle_sheets()
    print("TEXTURE VRAM TESTS OK")


if __name__ == "__main__":
    main()
