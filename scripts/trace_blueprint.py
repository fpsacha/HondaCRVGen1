r"""
Trace the body silhouettes from the calibrated blueprint crops into spec/trace/*.json.

    python scripts/trace_blueprint.py

Reads blender/references/blueprints/bp_{side,front,top}.png with calibration.json and writes:
  spec/trace/side.json   y -> z_top, z_bot   (wheels cut out by arch circles; rails/spare/text clipped)
  spec/trace/top.json    y -> half-width      (mirrors clipped)
  spec/trace/front.json  z -> half-width      (mirrors, rails, dimension line clipped)
plus bp_*_trace.png debug overlays showing exactly what was traced.

Model space: metres, +Y front, +Z up, +X right, front axle at y=+1.31, ground z=0.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BP = os.path.join(ROOT, "blender", "references", "blueprints")
TRACE = os.path.join(ROOT, "spec", "trace")
Y_AXF = 1.31
INK = 190              # min channel below this = drawing (watermark ~200-235 stays background)

# clips, metres
R_ARCH = 0.42          # arch opening radius: tyre + wheel-well shadow removed from the side mask
Z_RAIL = 1.655         # roof crown; anything above is roof rail / title text
X_BODY = 0.88          # widest the body gets (flares)
X_UPPER = 0.88         # above the flares nothing but mirrors is wider than this
X_MIRROR = 0.775       # at belt height the mirrors start here (A-pillar/glass is ~0.74-0.78)
MIRROR_Z = (0.95, 1.40)          # front view, heights the door mirrors occupy (after recalibration)
Z_RAIL_FRONT = 1.75              # front view: above this only the roof-rail feet
# Greenhouse half-widths (side-view z -> half-width). The front view cannot be traced above the
# belt: the door mirrors bridge the body from z 1.09 to 1.38, and above them the artist draws the
# roof corner 4-5 cm wider than the plan view does. The plan view measures the drip rail directly
# (side glass in plan runs |x| 0.60-0.74 at y -0.60, roof-rail bar |x| 0.49-0.57), so the roof edge
# is fixed from the plan and the belt from the front view just under the mirrors.
# A 5.5 cm step at the belt: the door shoulder holds 0.815 to z 1.09, the glass base starts at
# 0.76 at z 1.13, then 17 degrees of tumblehome to the drip rail (the audit measured the model's
# one continuous ramp at 23 degrees against the photographs' 17).
# Narrowed 2-4 cm a side on 2026-09-05 to the straight rear photograph (commons MG 8759): the
# pillar face measures 0.735 at z 1.14, 0.68 at 1.29, 0.64 at 1.385, 0.575 at 1.53, the roof
# edge 0.58 at 1.60 and the flat roof 0.52 at 1.635; the old table was the plan view's outer line.
GREENHOUSE = ((1.02, 0.850), (1.09, 0.815), (1.13, 0.740), (1.20, 0.715), (1.30, 0.682),
              (1.40, 0.648), (1.50, 0.612), (1.58, 0.588), (1.61, 0.578), (1.63, 0.548),
              (1.655, 0.480))
Y_NOSE, Y_TAIL = 2.20, -2.19    # beyond the tail clip it is the spare
FENDER_MIRROR = (1.45, 1.66)    # JDM fender mirror on the drawing; not on the subject car
SMOOTH = 13            # samples (~4.5 cm) of moving average on the traced curves


def keep_component(mask, seed):
    """Keep only the connected blob containing seed (px). Drops watermark letters, labels."""
    img = Image.fromarray(np.where(mask, 255, 0).astype(np.uint8)).copy()
    x, y = int(seed[0]), int(seed[1])
    if img.getpixel((x, y)) != 255:
        return mask                                   # seed missed the body; leave as is
    ImageDraw.floodfill(img, (x, y), 128)
    return np.asarray(img) == 128


def car_mask(im, seed=None):
    """Drawing pixels with enclosed holes filled (windows), thin lines removed,
    optionally reduced to the blob that contains `seed`."""
    arr = np.asarray(im).astype(int)
    car = arr.min(axis=2) < INK
    bg = Image.fromarray(np.where(car, 0, 255).astype(np.uint8)).copy()   # copy: fromarray is read-only
    w, h = bg.size
    for x in range(0, w, 25):
        for y in (0, h - 1):
            if bg.getpixel((x, y)) == 255:
                ImageDraw.floodfill(bg, (x, y), 128)
    for y in range(0, h, 25):
        for x in (0, w - 1):
            if bg.getpixel((x, y)) == 255:
                ImageDraw.floodfill(bg, (x, y), 128)
    filled = np.asarray(bg) != 128
    # kill dimension / extension lines: NARROW groups of near-full-height ink columns
    # (the body itself is also tall in front/top view, but hundreds of columns wide)
    colrun = _longest_runs(filled)
    tall = colrun > 0.30 * h                      # a label splits the 1705 line into ~0.4 h runs
    kill = np.zeros(w, dtype=bool)
    x = 0
    while x < w:
        if tall[x]:
            s = x
            while x < w and tall[x]:
                x += 1
            if x - s <= 14:
                kill[max(0, s - 3):min(w, x + 3)] = True
        else:
            x += 1
    filled[:, kill] = False
    op = Image.fromarray((filled * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(7)).filter(ImageFilter.MaxFilter(7))
    out = np.asarray(op) > 127
    return keep_component(out, seed) if seed is not None else out


def _longest_runs(m):
    h, w = m.shape
    out = np.zeros(w, dtype=int)
    for x in range(w):
        col = m[:, x]
        best = cur = 0
        for v in col:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        out[x] = best
    return out


def load(name):
    cal = json.load(open(os.path.join(BP, "calibration.json")))
    up, pxm = cal["up"], cal["pxm_preview"] * cal["up"]
    x0, y0, _, _ = cal["crops"][name]
    a = cal[name]
    ax = (a.get("front_axle_x", a.get("centre_x")) - x0) * up
    ay = (a.get("ground_y", a.get("centre_y")) - y0) * up
    im = Image.open(os.path.join(BP, "bp_%s.png" % name)).convert("RGB")
    # a point certainly inside the body in each view (door skin / grille / roof)
    seed = {"side": (ax + Y_AXF * pxm, ay - 1.0 * pxm),
            "front": (ax, ay - 0.7 * pxm),
            "top": (ax + Y_AXF * pxm, ay)}[name]
    return im, car_mask(im, seed), pxm, ax, ay


def smooth(vals):
    """Sliding median: removes pixel jitter but keeps steps (tailgate, bumper ledge) vertical."""
    if len(vals) < SMOOTH:
        return vals
    v = np.asarray(vals, dtype=float)
    h = SMOOTH // 2
    pad = np.pad(v, (h, h), mode="edge")
    win = np.stack([pad[i:i + len(v)] for i in range(SMOOTH)])
    med = np.median(win, axis=0)
    # a short mean afterwards removes the pixel-quantisation plateaus the median leaves
    k = 5
    pad2 = np.pad(med, (k // 2, k // 2), mode="edge")
    out = np.convolve(pad2, np.ones(k) / k, mode="valid")
    return [round(float(x), 4) for x in out]


HOOD_SPAN = (0.98, 1.99)         # the hood, cowl to leading edge
MIRROR_SPAN = (1.38, 1.80)       # the drawing's JDM fender mirror and its stalk sit here


def fit_hood(ys, ztop):
    """Replace the hood profile with a cubic fitted to the trace OUTSIDE the mirror zone.
    A real hood is one smooth convex curve; bridging the mirror with a chord left a flat with a
    kink at each end and the stalk put a dent behind it. Blends back into the trace at both ends."""
    y = np.asarray(ys, dtype=float)
    z = np.asarray(ztop, dtype=float)
    lo, hi = HOOD_SPAN
    m_lo, m_hi = MIRROR_SPAN
    fit_sel = (y >= lo) & (y <= hi) & ~((y > m_lo) & (y < m_hi))
    if fit_sel.sum() < 12:
        return ztop
    coef = np.polyfit(y[fit_sel], z[fit_sel], 3)
    out = z.copy()
    span = (y >= lo) & (y <= hi)
    fitted = np.polyval(coef, y[span])
    # blend over 6 cm at each end so the cowl and the nose keep the traced values
    w = np.clip(np.minimum(y[span] - lo, hi - y[span]) / 0.06, 0.0, 1.0)
    out[span] = w * fitted + (1.0 - w) * z[span]
    return [round(float(v), 4) for v in out]


def chord_cap(xs, ys, lo, hi):
    """Replace upward bumps between lo..hi by the chord (min of value and chord)."""
    xs = np.asarray(xs); ys = np.asarray(ys, dtype=float)
    i0 = int(np.argmin(np.abs(xs - lo))); i1 = int(np.argmin(np.abs(xs - hi)))
    a, b = sorted((i0, i1))
    if b - a < 2:
        return ys.tolist()
    chord = np.interp(xs[a:b + 1], [xs[a], xs[b]], [ys[a], ys[b]])
    ys[a:b + 1] = np.minimum(ys[a:b + 1], chord)
    return [round(float(v), 4) for v in ys]


def trace_side():
    im, m, pxm, ax, ay = load("side")
    h, w = m.shape
    Y = Y_AXF - (np.arange(w) - ax) / pxm                    # +u = -Y
    Z = (ay - np.arange(h)) / pxm
    YY, ZZ = np.meshgrid(Y, Z)
    m = m & (ZZ >= 0.0) & (ZZ <= Z_RAIL) & (YY <= Y_NOSE) & (YY >= Y_TAIL)
    for yc in (Y_AXF, -Y_AXF):                               # cut the wheels + wells
        m &= ((YY - yc) ** 2 + (ZZ - 0.334) ** 2) > R_ARCH ** 2
    ys, ztop, zbot = [], [], []
    for x in range(w):
        col = np.nonzero(m[:, x])[0]
        if col.size < 3:
            continue
        ys.append(round(float(Y[x]), 4))
        ztop.append(round(float(Z[col.min()]), 4))
        zbot.append(round(float(Z[col.max()]), 4))
    ztop, zbot = smooth(ztop), smooth(zbot)
    ztop = fit_hood(ys, ztop)                                 # JDM fender mirror off, hood smooth
    # the drawing hangs a mud flap under the front arch; the valance itself sits at ~0.28
    zbot = [max(z, 0.27) if 1.70 < y < 2.02 else z for y, z in zip(ys, zbot)]
    dbg = im.copy(); d = ImageDraw.Draw(dbg)
    d.line([(ax + (Y_AXF - y) * pxm, ay - z * pxm) for y, z in zip(ys, ztop)], fill=(255, 0, 0), width=3)
    d.line([(ax + (Y_AXF - y) * pxm, ay - z * pxm) for y, z in zip(ys, zbot)], fill=(0, 0, 255), width=3)
    dbg.save(os.path.join(BP, "bp_side_trace.png"))
    return {"y": ys, "z_top": ztop, "z_bot": zbot}


def trace_top():
    im, m, pxm, ax, ay = load("top")
    h, w = m.shape
    Y = Y_AXF - (np.arange(w) - ax) / pxm
    X = (ay - np.arange(h)) / pxm
    YY, XX = np.meshgrid(Y, X)
    m = m & (np.abs(XX) <= X_BODY) & (YY <= Y_NOSE) & (YY >= Y_TAIL)
    ys, ws = [], []
    for x in range(w):
        col = np.nonzero(m[:, x])[0]
        if col.size < 3:
            continue
        ys.append(round(float(Y[x]), 4))
        ws.append(round(float(np.abs(X[col]).max()), 4))
    ws = chord_cap(ys, ws, 0.40, 0.75)                        # door mirrors
    ws = chord_cap(ys, ws, 1.70, 2.05)                        # JDM fender mirror
    ws = smooth(ws)
    dbg = im.copy(); d = ImageDraw.Draw(dbg)
    for sgn in (1, -1):
        d.line([(ax + (Y_AXF - y) * pxm, ay - sgn * wv * pxm) for y, wv in zip(ys, ws)], fill=(255, 0, 0), width=3)
    dbg.save(os.path.join(BP, "bp_top_trace.png"))
    return {"y": ys, "w": ws}


def trace_front():
    im, m, pxm, ax, ay = load("front")
    h, w = m.shape
    X = -(np.arange(w) - ax) / pxm                            # +u = -X
    Z = (ay - np.arange(h)) / pxm
    XX, ZZ = np.meshgrid(X, Z)
    limit = np.where(ZZ <= 0.90, X_BODY, X_UPPER)
    limit = np.where(ZZ < 0.42, 0.60, limit)              # below the sill only the air dam, not the tyres
    m = m & (np.abs(XX) <= limit) & (ZZ >= 0.0) & (ZZ <= Z_RAIL_FRONT)
    vscale = json.load(open(os.path.join(BP, "calibration.json")))["front"]["vscale"]
    zs, ws = [], []
    for y in range(h):
        row = np.nonzero(m[y, :])[0]
        if row.size < 3:
            continue
        zs.append(round(float(Z[y]), 4))
        xr = X[row]
        wl = float(-xr.min()) if xr.min() < 0 else 0.0
        wr = float(xr.max()) if xr.max() > 0 else 0.0
        ws.append(round((wl + wr) / 2.0 if wl > 0 and wr > 0 else max(wl, wr), 4))
    # mirrors: the body edge under them is hidden; bridge the zone linearly
    zs_a = np.asarray(zs); ws_a = np.asarray(ws, dtype=float)
    lo, hi = MIRROR_Z
    below = ws_a[(zs_a < lo) & (zs_a > lo - 0.03)]; above = ws_a[(zs_a > hi) & (zs_a < hi + 0.03)]
    if below.size and above.size:
        w_lo, w_hi = float(np.median(below)), float(np.median(above))
        sel = (zs_a >= lo) & (zs_a <= hi)
        ws_a[sel] = np.interp(zs_a[sel], [lo, hi], [w_lo, w_hi])
    ws = smooth([round(float(v), 4) for v in ws_a])
    zs = [round(z * vscale, 4) for z in zs]        # into the side view's height frame
    gz, gw = zip(*GREENHOUSE)
    ws = [round(float(np.interp(z, gz, gw)), 4) if z >= gz[0] else w0 for z, w0 in zip(zs, ws)]
    if max(zs) < gz[-1]:                                # extend to the crown
        step = abs(zs[1] - zs[0]) if len(zs) > 1 else 0.005
        asc = zs[0] < zs[-1]
        extra = [round(v, 4) for v in np.arange(max(zs) + step, gz[-1] + step, step)]
        exw = [round(float(np.interp(v, gz, gw)), 4) for v in extra]
        zs, ws = (zs + extra, ws + exw) if asc else (extra[::-1] + zs, exw[::-1] + ws)
    dbg = im.copy(); d = ImageDraw.Draw(dbg)
    for sgn in (1, -1):
        d.line([(ax - sgn * wv * pxm, ay - z * pxm) for z, wv in zip(zs, ws)], fill=(255, 0, 0), width=3)
    dbg.save(os.path.join(BP, "bp_front_trace.png"))
    return {"z": zs, "w": ws}


def main():
    os.makedirs(TRACE, exist_ok=True)
    out = {"side": trace_side(), "top": trace_top(), "front": trace_front()}
    for k, v in out.items():
        with open(os.path.join(TRACE, "%s.json" % k), "w") as f:
            json.dump({"source": "bp550 calibrated 2026-09-04", **v}, f)
    s, t, fr = out["side"], out["top"], out["front"]

    def at(xs, ys, x):
        return ys[min(range(len(xs)), key=lambda i: abs(xs[i] - x))]
    print("side : y %.2f..%.2f  z_top@1.6 %.3f @1.0 %.3f @0.0 %.3f | z_bot@0.0 %.3f" % (
        max(s["y"]), min(s["y"]), at(s["y"], s["z_top"], 1.6), at(s["y"], s["z_top"], 1.0),
        at(s["y"], s["z_top"], 0.0), at(s["y"], s["z_bot"], 0.0)))
    print("top  : w@2.1 %.3f @1.9 %.3f @0.56 %.3f @0.0 %.3f @-2.1 %.3f" % tuple(at(t["y"], t["w"], v) for v in (2.1, 1.9, 0.56, 0.0, -2.1)))
    print("front: w@0.6 %.3f @1.10 %.3f @1.3 %.3f @1.5 %.3f @1.61 %.3f" % tuple(at(fr["z"], fr["w"], v) for v in (0.6, 1.10, 1.3, 1.5, 1.61)))


if __name__ == "__main__":
    main()
