r"""
The cargo bay's painted detail: the deck carpet and the two side trims (interior sheet), and the top
of the picnic table that rides flush in the cargo floor (shell sheet).

Why (2026-10-13, feedback: "better texture ... with more details"; screenshot 34.png: with the gate open the
cargo bay was plain dark carpet and plain trim). Reference: the Commons RD1 series MG 8826 / 8829 /
8834 (blender/references/commons/unclear), the bay with the gate open and the table out:
  * deck: the carpeted floor board's gap a few centimetres inside the side trims and along the sill;
    tie-down anchors in the four corners (a dark base, a folded steel loop); a dark plastic scuff
    plate along the rear sill; a pull strap at the board's rear edge; the carpet compressed along the
    well the table sits in;
  * side trims: moulded grey plastic with a round speaker grille high in the middle, a storage recess
    behind it, a louvred vent at the tailgate pillar, the wheelhouse bulge below a moulded line, a
    bag hook low at the rear;
  * the table (build_table: its grey top flush with the floor, the grab slot and umbrella plug as
    geometry): a moulded lip round the rim, dark corner caps, the rivets of the folded leg hinges, the
    moulded CR-V plate beside the grab slot (photo MG 8834).
A pzview probe grid over the open-gate views (2026-10-13) found the table top is most of the floor
the camera sees; the deck shows as the side and rear margins round it.

Density: the interior sheet carries the deck at ~0.8 texels/cm and the side trims at ~0.7 (measured on
the shipped crv_kotris.blend, 2026-10-13), KI5's own density; the default 512 cap halves it. So every
line is >= 1.4 cm (one texel), every part >= 3 cm, and the maps are prefiltered to ~half a texel
because the bake point-samples them. The table rides the shell sheet at ~2.9 texels/cm (weight 2).

Encoding: the deck and side maps REPLACE the colour (bake_atlas TEXTURED_BY_SPACE["interior"]) at the
PALETTE's own levels (Interieur_sol 0.030 -> sRGB 48, Interieur 0.060/0.062 -> 69/70), so the bay
matches the cabin and highlights can rise above the carpet: a multiply map can only darken, and on
a sRGB-48 carpet nothing it drew could be seen (first trial). Their own soft grain stands in for the
PolyHaven grain, which at 0.7-0.8 texels/cm was single-texel noise. The table map MULTIPLIES the
AccTable grain (a pixel of lin_to_srgb(f) scales the linear colour by f; TABLE_BASE leaves headroom
for the lip's highlight).
Coordinates (model metres): deck u = x over FLOOR_X, v = y over FLOOR_Y (rear sill at v 0); sides
u = y over SIDE_Y (rear at u 0), v = z over SIDE_Z, one map for both walls (|x| symmetric); table
u = x over TABLE_X, v = y over TABLE_Y.
"""
import os

import numpy as np

import trim_paint as tp

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
BAKE_PNG = os.path.join(ROOT, "blender", "bake")
FLOOR_PNG = "cargo_floor.png"
SIDE_PNG = "cargo_side.png"
TABLE_PNG = "cargo_table.png"
FLOOR_X = (-0.72, 0.72)          # the deck: kotris interior, z 0.766, x -0.70..0.70, y -1.98..-1.04
FLOOR_Y = (-2.06, -1.02)
FLOOR_Z = (0.74, 0.80)           # deck height band (the table well's floor at 0.626 stays plain)
SIDE_Y = (-2.06, -1.22)          # behind the rear doors (which end at y -1.215)
SIDE_Z = (0.76, 1.20)            # below the quarter glass
SIDE_X = (0.45, 0.80)            # |x| of the side walls
TABLE_X = (-0.39, 0.39)          # build_table: TOP_W / TOP_L 0.78, centre y -1.58, top z 0.766 + 0.002
TABLE_Y = (-1.97, -1.19)
TABLE_Z = (0.75, 0.80)
PX_PER_M = 200.0
PREFILTER = 0.003                # half a BAKE texel: the 2x bake samples 1.4-1.6 /cm (0.006 was half a shipped
                                 # texel at 0.7-0.8 texels/cm, from before the supersampled bake; fix 2026-10-13)
CARPET = (48, 48, 49)            # bake_atlas PALETTE Interieur_sol (0.030) in sRGB
TRIM = (69, 69, 71)              # bake_atlas PALETTE Interieur (0.060, 0.060, 0.062) in sRGB
TABLE_PX_PER_M = 1000.0
TABLE_PREFILTER = 0.0008         # half a BAKE texel at ~2.9 texels/cm x 2 (was 0.0016, half a shipped texel)
TABLE_BASE = 0.92
WELL_X = 0.39 + 0.012            # build_table: the table's well gap
WELL_Y = (-1.58 - 0.402, -1.58 + 0.402)


def render_floor():
    """The deck's colour (sRGB), rows bottom-up = rear sill first."""
    x0, x1 = FLOOR_X
    y0, y1 = FLOOR_Y
    c = tp.Canvas(x1 - x0, y1 - y0, PX_PER_M, CARPET)

    def box(xa, ya, xb, yb, r=0.0, X=None, Y=None):
        return c.rrect(min(xa, xb) - x0, min(ya, yb) - y0, max(xa, xb) - x0, max(ya, yb) - y0, r, X, Y)
    c.grain(0.04, 0.05, seed=21)                          # carpet pile: soft, >= 3 texels a cell
    # carpet folding down against the trims: darker toward the walls
    c.scale(c.cut(box(-1, -3, 1, 0), box(-0.69, -2.1, 0.69, 0)), 0.80)
    # the floor board's gap: 3.5 cm inside the side trims, along the sill and the seat back
    board = box(-0.665, -1.990, 0.665, -1.075, 0.04)
    c.groove(board, 0.014, k=0.50, hi=1.30, hw=0.012)
    # the carpet compressed along the table's well (its lid outline when the table is out)
    well = box(-WELL_X, WELL_Y[0], WELL_X, WELL_Y[1], 0.01)
    c.scale(c.cut(well - 0.02, well), 0.78)
    # rear scuff plate along the sill: dark plastic, two ribs, its rounded top edge lit
    plate = box(-0.72, -2.06, 0.72, -1.996)
    c.fill(plate, (30, 30, 32))
    for yy in (-2.040, -2.017):
        c.fill(box(-0.70, yy - 0.006, 0.70, yy + 0.006), (40, 40, 42))
    c.fill(box(-0.72, -2.002, 0.72, -1.994), (64, 64, 66))
    # pull strap at the board's rear edge, in the middle
    strap = box(-0.055, -1.990, 0.055, -1.970, 0.006)
    c.fill(strap, (26, 26, 28))
    c.fill(box(-0.045, -1.986, 0.045, -1.980, 0.002), (40, 40, 42))   # its stitched loop
    # tie-down anchors in the four corners: a dark plastic base, the folded steel loop on it
    for ax in (-0.60, 0.60):
        for ay in (-1.93, -1.13):
            c.shadow(lambda X, Y, ax=ax, ay=ay: box(ax - 0.030, ay - 0.022, ax + 0.030, ay + 0.022, 0.010, X, Y),
                     off=0.010, soft=0.012, k=0.70)
            c.fill(box(ax - 0.030, ay - 0.022, ax + 0.030, ay + 0.022, 0.010), (24, 24, 26))
            loop = box(ax - 0.020, ay - 0.008, ax + 0.020, ay + 0.008, 0.007)
            c.fill(loop, (112, 113, 116))
            c.bevel(loop, 0.006, hi=1.20, lo=0.70, raised=True)
    c.prefilter(PREFILTER)
    return c


def render_side():
    """One side trim's colour (sRGB), u = y (rear at 0), v = z."""
    ya, yb = SIDE_Y
    za, zb = SIDE_Z
    c = tp.Canvas(yb - ya, zb - za, PX_PER_M, TRIM)

    def box(y0, z0, y1, z1, r=0.0, X=None, Y=None):
        return c.rrect(y0 - ya, z0 - za, y1 - ya, z1 - za, r, X, Y)
    c.grain(0.035, 0.035, seed=31)
    # the moulded line over the wheelhouse bulge: the lower kick panel is a step out from the trim
    pts = [(y - ya, z - za) for y, z in ((-2.10, 0.885), (-1.80, 0.885), (-1.70, 0.925), (-1.50, 0.945),
                                         (-1.33, 0.925), (-1.25, 0.895), (-1.18, 0.885))]
    line = c.seg_dist(pts)
    above = c.polygon(pts + [(pts[-1][0], 1.0), (pts[0][0], 1.0)])
    c.scale(-above, 0.90)                                  # the kick panel below it, a shade darker
    c.groove(np.where(above < 0, -line, line), 0.014, k=0.58, hi=1.25, hw=0.012)
    c.gradient_v(c.rrect(-1, -1, 3, 3), 1.05, 0.95, 0.0, zb - za)
    # speaker grille high in the middle: a lit ring, the dark perforated grille
    cy, cz = -1.45 - ya, 1.045 - za
    ring = c.circle(cy, cz, 0.088)
    c.bevel(ring, 0.014, hi=1.30, lo=0.70, raised=True)
    sp = c.circle(cy, cz, 0.074)
    c.fill(sp, (34, 34, 36))
    c.dots(sp, 0.022, 0.006, 0.70, offset=(cy, cz))
    c.bevel(sp, 0.012, hi=1.25, lo=0.70, raised=False)
    # storage recess behind it
    rc = box(-1.79, 0.960, -1.67, 1.135, 0.02)
    c.groove(rc, 0.012, k=0.60, hi=1.25, hw=0.010)
    c.fill(rc, (44, 44, 46))
    c.bevel(rc, 0.022, hi=1.30, lo=0.60, raised=False)
    # louvred vent at the tailgate pillar
    vt = box(-1.99, 0.950, -1.90, 1.140, 0.012)
    c.groove(vt, 0.012, k=0.60, hi=1.25, hw=0.010)
    c.fill(vt, (28, 28, 30))
    for k in range(3):
        y = -1.975 + k * 0.030
        c.fill(box(y - 0.006, 0.962, y + 0.006, 1.128, 0.004), (60, 60, 62))   # the louvres' lit faces
    # bag hook low at the rear
    c.shadow(lambda X, Y: box(-1.95, 0.840, -1.91, 0.875, 0.010, X, Y), off=0.010, soft=0.012, k=0.70)
    hk = box(-1.95, 0.840, -1.91, 0.875, 0.010)
    c.fill(hk, (30, 30, 32))
    c.bevel(hk, 0.008, hi=1.6, lo=0.7, raised=True)
    c.prefilter(PREFILTER)
    return c


def render_table():
    """Multiply factors (linear, x255) over the table's top, u = x, v = y."""
    xa, xb = TABLE_X
    ya, yb = TABLE_Y
    c = tp.Canvas(xb - xa, yb - ya, TABLE_PX_PER_M, (255 * TABLE_BASE,) * 3)
    W, H = xb - xa, yb - ya
    top = c.rrect(0.0, 0.0, W, H, 0.015)
    # the moulded lip round the rim (1 cm, build_table._top): lit, a groove inside it
    c.scale(c.cut(top, top + 0.010), 1.08)
    c.groove(top + 0.012, 0.007, k=0.62, hi=1.06, hw=0.006)
    # dark corner caps
    for cx, cy, sx, sy in ((0, 0, 1, 1), (W, 0, -1, 1), (0, H, 1, -1), (W, H, -1, -1)):
        cap = c.polygon([(cx, cy), (cx + sx * 0.06, cy), (cx, cy + sy * 0.06)])
        c.scale(cap - 0.002, 0.40)
    # the folded leg frames' hinge rivets, 4.5 cm in from the long sides (build_table.HINGE_X)
    for x in (0.045, W - 0.045):
        for y in (0.09, H - 0.09):
            c.scale(c.circle(x, y, 0.007), 0.35)
    # the moulded CR-V plate beside the grab slot (slot at x 0 +- 5.5 cm, y centre + 0.10)
    sy = -1.58 + 0.10 - ya
    plate = c.rrect(0.5 * W + 0.085, sy - 0.022, 0.5 * W + 0.285, sy + 0.022, 0.012)
    c.groove(plate, 0.006, k=0.65, hi=1.06, hw=0.005)
    # the script: four strokes at low contrast (C, R, dash, V), >= 1 cm each
    x0 = 0.5 * W + 0.105
    strokes = [[(x0 + 0.030, sy + 0.012), (x0 + 0.008, sy + 0.012), (x0, sy), (x0 + 0.008, sy - 0.012), (x0 + 0.030, sy - 0.012)],
               [(x0 + 0.045, sy - 0.013), (x0 + 0.050, sy + 0.013), (x0 + 0.070, sy + 0.010), (x0 + 0.066, sy), (x0 + 0.050, sy - 0.001), (x0 + 0.074, sy - 0.013)],
               [(x0 + 0.088, sy), (x0 + 0.104, sy)],
               [(x0 + 0.116, sy + 0.013), (x0 + 0.132, sy - 0.013), (x0 + 0.150, sy + 0.013)]]
    for s in strokes:
        c.scale(c.band(s, 0.0035), 0.72)
    c.prefilter(TABLE_PREFILTER)
    return c


def encode_factor(c):
    """Canvas of factors x 255 -> RGBA floats whose sRGB decode is the factor (rows bottom-up)."""
    f = np.clip(c.img[..., 0] / 255.0, 0.0, 1.0)
    s = tp.lin_to_srgb(f)
    rgb = np.repeat(s[..., None], 3, axis=2)
    return np.concatenate([rgb, np.ones(rgb.shape[:2] + (1,), np.float32)], axis=2)


def paint(out_dir=None):
    """Write the cargo maps into out_dir (default blender/bake) through Blender."""
    import bpy
    paths = []
    for png, rgba in ((FLOOR_PNG, render_floor().to_rgba()), (SIDE_PNG, render_side().to_rgba()),
                      (TABLE_PNG, encode_factor(render_table()))):
        H, W = rgba.shape[:2]
        path = os.path.join(out_dir or BAKE_PNG, png)
        name = os.path.splitext(png)[0]
        old = bpy.data.images.get(name)
        if old:
            bpy.data.images.remove(old)
        im = bpy.data.images.new(name, W, H, alpha=False, float_buffer=False)
        im.pixels[:] = rgba.ravel()
        im.filepath_raw = path
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
        paths.append(path)
    print("cargo_bay_paint: wrote %s" % ", ".join(os.path.basename(p) for p in paths))
    return paths
