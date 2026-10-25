r"""
The awning item's inventory icon is the rolled awning in its bag, not the deployed canopy (I-VISUAL-1: the
canopy on its poles read as a second picnic table). System Python only:

  1. the icon scene (features/awning.py _icon_scene) builds from the bag mesh alone, never the canopy or poles;
  2. the shipped icon (Item_CRVGen1_Awning.png, written by gen_icons) is one long roll: its opaque silhouette's
     principal axes are at least ASPECT_MIN to 1 (the old table-like icon was 1.11), it fills the icon along
     its length, and it is one solid piece (no legs or gaps).

    python scripts\test_awning_icon.py
"""
import ast
import inspect
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TEX = os.path.join(os.path.dirname(HERE), "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures")
ASPECT_MIN = 2.2       # the old deployed-canopy icon: 1.11

from features import awning  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)
    print("ok   " + msg)


def alpha(item):
    a = np.asarray(Image.open(os.path.join(TEX, "Item_%s.png" % item)).convert("RGBA"))[..., 3]
    check(a.shape == (32, 32), "%s is 32 x 32" % item)
    return a > 127


def aspect(mask):
    ys, xs = np.nonzero(mask)
    P = np.stack([xs, ys], 1).astype(float)
    P -= P.mean(0)
    w = np.linalg.eigvalsh(P.T @ P / len(P))
    return float(np.sqrt(w[1] / max(w[0], 1e-9))), P


def components(mask):
    seen = np.zeros_like(mask)
    n = 0
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        n += 1
        stack = [(y, x)]
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < 32 and 0 <= nx < 32 and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return n


def test_scene_uses_the_bag_only():
    scene, az, el = awning.ICONS[awning.ITEM_ID]
    check(scene is awning._icon_scene, "the awning icon is drawn by _icon_scene")
    names = {n.id for n in ast.walk(ast.parse(inspect.getsource(scene).lstrip())) if isinstance(n, ast.Name)}
    check("BAG" in names, "the icon scene builds from the bag mesh")
    check(not names & {"CANOPY", "POLES", "POLES_LIFT"}, "the icon scene leaves out the canopy and poles (%s)"
          % sorted(names & {"CANOPY", "POLES", "POLES_LIFT"}))


def test_icon_is_a_long_roll():
    m = alpha(awning.ITEM_ID)
    r, P = aspect(m)
    check(r >= ASPECT_MIN, "the awning icon is a long roll: principal aspect %.2f >= %.1f" % (r, ASPECT_MIN))
    w, V = np.linalg.eigh(P.T @ P)
    along = P @ V[:, 1]
    check(along.max() - along.min() >= 24, "the roll spans the icon (%.1f px along its axis)" % (along.max() - along.min()))
    check(components(m) == 1, "the roll is one solid piece (no legs)")
    check(150 <= int(m.sum()) <= 700, "the roll has a vanilla-sized silhouette (%d px)" % int(m.sum()))


def test_icon_is_a_black_strapped_bag():
    """R2-VIS-2: the roll read as a light blue-grey metal beam (gen_icons' levels lifted the all-dark bag: half its
    inside >= 0.40 luminance in one piece, blue over red +0.055). The bag is black canvas wrapped in straps: the
    inside's median luminance <= 0.30, no blue cast, and its light pixels are the straps, 3+ separate bands."""
    from scipy import ndimage
    check(max(awning.ICON_CANVAS) <= 0.15, "the icon paints the bag in its black canvas colour %s" % (awning.ICON_CANVAS,))
    a = np.asarray(Image.open(os.path.join(TEX, "Item_%s.png" % awning.ITEM_ID)).convert("RGBA")).astype(float) / 255.0
    lum = a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722
    inner = ndimage.binary_erosion(a[..., 3] > 0.5)               # inside the dark outline
    check(float(np.median(lum[inner])) <= 0.30, "the bag reads dark: median luminance %.2f <= 0.30" % np.median(lum[inner]))
    blue = float((a[..., 2] - a[..., 0])[inner].mean())
    check(blue <= 0.02, "no blue-grey metal cast (blue - red %.3f <= 0.02)" % blue)
    light = inner & (lum >= 0.40)
    _lab, n = ndimage.label(light)
    check(n >= 3 and light.sum() <= 0.35 * inner.sum(),
          "the light pixels are the straps: %d bands, %.0f %% of the bag" % (n, 100.0 * light.sum() / inner.sum()))


if __name__ == "__main__":
    test_scene_uses_the_bag_only()
    test_icon_is_a_long_roll()
    test_icon_is_a_black_strapped_bag()
    print("AWNING ICON OK")
