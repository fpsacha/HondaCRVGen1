r"""
How many lit lamp texels keep their lamp zone in the game, per Vehicle Texture Size cap (bug wave 1, H-VISUAL-1).

    python scripts\lampcov.py [<textures dir>] [--guard] [--lens <shell_uvmesh.npz>]

The game shrinks each sheet to the cap the way pzview_rules.game_cap replays it (repeated 2 x 2 integer
averages, the Lights premultiplied), then the shader samples both sheets bilinearly and lights a fragment
where the Mask sample lies within 0.01 of a lamp zone (vehicle_crvgen1_norandom.frag, t1en). Two figures:
  texel     Lights texels with alpha > 0.5 at the cap whose Mask block (same size) is exactly a lamp zone
            (the reviewer's lampcov.py measure);
  fragment  alpha-weighted share of fragments (a 2048 grid of sample points, both sheets bilinear) with
            Lights alpha > LAMP_GUARD_ALPHA whose Mask sample is a lamp zone; this one also counts the seam
            where a lens's tail and stop halves meet.
--guard applies compose_textures.lamp_guard to the Mask first (what compose now ships).
--lens NPZ (the build's triangle dump) also gives both figures on the lens's own surface only (lens_region),
and lets --guard keep to it as compose does: since R2-VIS-1 the guard leaves Lights alpha that bled onto a
neighbouring island unlit, so the plain figures count those texels as lost.
"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import pzview_rules as R  # noqa: E402

NAME = "Vehicles_HondaCRVGen1"
CAPS = (2048, 1024, 512, 256)
LAMP_RGB = np.array([c for g in R.LAMP_ZONES.values() for (_n, _i, c) in g])


def _bilinear(tex, n_pts):
    """tex (h, w, C) float sampled GL_LINEAR at the centres of an n_pts x n_pts grid over [0, 1]^2 (edges clamped)."""
    h, w = tex.shape[:2]
    u = (np.arange(n_pts) + 0.5) / n_pts
    def axis(n):
        x = u * n - 0.5
        x0 = np.floor(x).astype(np.int64)
        f = (x - x0).astype(np.float32)
        return np.clip(x0, 0, n - 1), np.clip(x0 + 1, 0, n - 1), f
    y0, y1, fy = axis(h)
    x0, x1, fx = axis(w)
    top = tex[y0][:, x0] * (1 - fx)[None, :, None] + tex[y0][:, x1] * fx[None, :, None]
    bot = tex[y1][:, x0] * (1 - fx)[None, :, None] + tex[y1][:, x1] * fx[None, :, None]
    return top * (1 - fy)[:, None, None] + bot * fy[:, None, None]


def is_lamp(rgb):
    """rgb (..., 3) floats 0..1 -> bool: within the shader's 0.01 of any lamp zone colour."""
    ok = np.zeros(rgb.shape[:-1], dtype=bool)
    for c in LAMP_RGB:
        ok |= np.linalg.norm(rgb - c, axis=-1) < R.ZONE_TOL
    return ok


def coverage(mask, lights, cap, n_pts=2048, alpha_min=13, region=None):
    """(texel %, fragment %) for one cap. mask (H, W, 3) uint8, lights (h, w, 4) uint8 as shipped. region: an
    optional (n_pts, n_pts) bool mask of the sample points that count (lens_region: the lens's own surface;
    Lights alpha bled onto a neighbouring island is that panel's and must not light)."""
    m = R.game_cap(mask, cap)[..., :3].astype(np.float32) / 255.0
    L = R.game_cap(lights, cap).astype(np.float32) / 255.0
    # texel: the Mask at the Lights' size (box of whole Mask texels: the reviewer's measure)
    k = m.shape[0] // L.shape[0]
    mb = m.reshape(L.shape[0], k, L.shape[1], k, 3).mean(axis=(1, 3)) if k > 1 else m
    lit = L[..., 3] > 0.5
    if region is not None:                     # a cap texel counts when most of its block is in the region
        q = region.shape[0] // L.shape[0]
        lit &= region.reshape(L.shape[0], q, L.shape[1], q).mean(axis=(1, 3)) >= 0.5
    texel = 100.0 * (is_lamp(mb) & lit).sum() / max(1, lit.sum())
    # fragment
    a = _bilinear(L[..., 3:4], n_pts)[..., 0]
    w = np.where(a > alpha_min / 255.0, a, 0.0)
    if region is not None:
        w = np.where(region, w, 0.0)
    ok = is_lamp(_bilinear(m, n_pts))
    return texel, 100.0 * float((w * ok).sum()) / max(float(w.sum()), 1e-9)


def lens_region(mask, lights, npz):
    """The lens's own surface on the Mask's grid (bug wave 2, R2-VIS-1): covered texels, lit (alpha >=
    LAMP_GUARD_ALPHA), within LAMP_GUARD_NEAR on the car of a covered lit lamp-zone texel. None without the
    triangle dump."""
    import compose_textures as C
    geo = C.lens_geometry(npz, mask.shape[0])
    if geo is None:
        return None
    code = (mask[..., 0].astype(np.int64) << 16) | (mask[..., 1].astype(np.int64) << 8) | mask[..., 2]
    k = mask.shape[0] // lights.shape[0]
    lit = np.repeat(np.repeat(lights[..., 3], k, 0), k, 1) >= C.LAMP_GUARD_ALPHA
    close, _own = C.lens_surface(code, lit, np.array(list(C._zone_codes(("lights_", "stop_")).values())), geo)
    return close & lit & geo[1]


def load(tex_dir):
    mask = np.asarray(Image.open(os.path.join(tex_dir, NAME + "_Mask.png")).convert("RGB"))
    lights = np.asarray(Image.open(os.path.join(tex_dir, NAME + "_Lights.png")).convert("RGBA"))
    return mask, lights


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tex = args[0] if args else os.path.join(os.path.dirname(HERE), "mod", "Contents", "mods", "HondaCRVGen1", "common",
                                            "media", "textures", "Vehicles")
    mask, lights = load(tex)
    npz = sys.argv[sys.argv.index("--lens") + 1] if "--lens" in sys.argv else None
    if "--guard" in sys.argv:
        import compose_textures as C
        img, _s = C.lamp_guard(mask, lights[..., 3], geo=C.lens_geometry(npz, mask.shape[0]) if npz else None)
        mask = np.asarray(img)
    region = lens_region(mask, lights, npz) if npz else None
    for cap in CAPS:
        t, f = coverage(mask, lights, cap)
        line = "cap %4d: lamp texels keeping a lamp zone %.1f%%, lit fragments %.1f%%" % (cap, t, f)
        if region is not None:
            t, f = coverage(mask, lights, cap, region=region)
            line += "; on the lens surface %.2f%% / %.2f%%" % (t, f)
        print(line)


if __name__ == "__main__":
    main()
