r"""
Texture sheet layout shared by the UV projector (Blender) and the painter (PIL).

Pure Python on purpose: Blender's interpreter has no PIL and the system Python has no bpy, and
both must agree to the pixel on where every panel lives. Four planar projections share one
square sheet, the way KI5 lays out a vehicle, plus a few small swatches:

    SIDE    both flanks (the right one mirrored), nose at the left
    TOP     hood, windscreen, roof, tailgate glass top
    FRONT   (left half) and REAR (right half) faces
    swatches: spare tread, black trim, plain paint (mirror housings), grey cladding

Everything is derived from PXM and SIZE, so the sheet can be re-rendered at another resolution
without touching UVs (which are normalised).

The rear-end numbers live here too, because the mesh builder and the painter must agree on where
the glass ends and the lamps begin (spec/decisions.md 2026-09-05, rear end from the photographs).

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import bisect
import math

SIZE = 2048
PXM = 400.0                           # pixels per metre on the sheet

Y_MAX, Y_MIN = 2.20, -2.30            # the side and top strips cover this length (incl. spare)
Z_MAX, Z_MIN = 1.72, 0.20
X_MAX = 0.90                          # half-width covered by the top / front / rear regions

W_LEN = int((Y_MAX - Y_MIN) * PXM)    # 1800
H_Z = int((Z_MAX - Z_MIN) * PXM)      # 608
W_X = int(2 * X_MAX * PXM)            # 720
GAP = int(0.03 * PXM)                 # 12

SIDE = (0, 0, W_LEN, H_Z)
TOP = (0, H_Z + GAP, W_LEN, H_Z + GAP + W_X)
FRONT = (0, TOP[3] + GAP, W_X, TOP[3] + GAP + H_Z)
REAR = (W_X, FRONT[1], 2 * W_X, FRONT[3])
_sx = 2 * W_X + 3 * GAP                                  # swatches to the right of the end faces
_u = SIZE // 1024
PATCH_TYRE = (_sx, FRONT[1], _sx + 160 * _u, FRONT[1] + 160 * _u)
PATCH_BLACK = (PATCH_TYRE[2] + GAP, FRONT[1], PATCH_TYRE[2] + GAP + 80 * _u, FRONT[1] + 80 * _u)
PATCH_CLAD = (PATCH_BLACK[0], PATCH_BLACK[3] + GAP, PATCH_BLACK[2], PATCH_BLACK[3] + GAP + 80 * _u)
PATCH_PAINT = (PATCH_TYRE[0], PATCH_TYRE[3] + GAP, PATCH_TYRE[2], PATCH_TYRE[3] + GAP + 120 * _u)
REGIONS = {"side": SIDE, "top": TOP, "front": FRONT, "rear": REAR,
           "tyre": PATCH_TYRE, "black": PATCH_BLACK, "clad": PATCH_CLAD, "paint": PATCH_PAINT}


def side_px(y, z):
    return (SIDE[0] + (Y_MAX - y) * PXM, SIDE[1] + (Z_MAX - z) * PXM)


def top_px(y, x):
    return (TOP[0] + (Y_MAX - y) * PXM, TOP[1] + (X_MAX - x) * PXM)


def front_px(x, z):
    """Seen from ahead: the car's right (+x) is on the viewer's left."""
    return (FRONT[0] + (X_MAX - x) * PXM, FRONT[1] + (Z_MAX - z) * PXM)


def rear_px(x, z):
    """Seen from behind: the car's right (+x) is on the viewer's right."""
    return (REAR[0] + (x + X_MAX) * PXM, REAR[1] + (Z_MAX - z) * PXM)


def to_uv(px):
    """Pixel (x, y) with the image origin top-left -> Blender UV (u, v) with v up."""
    return (px[0] / SIZE, 1.0 - px[1] / SIZE)


def patch_uv(name, u, v):
    """(u, v) in 0..1 inside a named swatch -> sheet UV."""
    x0, y0, x1, y1 = REGIONS[name]
    return to_uv((x0 + (x1 - x0) * (0.1 + 0.8 * u), y0 + (y1 - y0) * (0.1 + 0.8 * v)))


def project(nx, ny, nz, y=0.0, x=0.0, z=None):
    """Which region a face with world normal (nx, ny, nz), centred at model (x, y, z), belongs
    to. A face that looks along the car's length takes the end it is nearest to, so the hidden
    inward faces of the spare, the bumper and the mirrors share pixels with their visible
    neighbours instead of landing on the opposite end's grille or lamps. At the tail the choice
    is by position, not normal: the raked glass plane, the D-pillar chamfers and the lamps on
    them all read from the rear sheet, however a face straddling the chamfer's edge tilts."""
    if z is not None and y < -1.75 and z > Z_GLASS_BOT - 0.03 and y < tail_crease_y(z) + 0.012:
        return "rear"
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if az >= 0.55 and az >= ax:
        return "top"
    if ax >= ay:
        return "side"
    if y < -1.5:
        return "rear"
    if y > 1.5:
        return "front"
    return "front" if ny > 0 else "rear"


def uv_for(region, x, y, z):
    if region == "side":
        return to_uv(side_px(y, z))
    if region == "top":
        return to_uv(top_px(y, x))
    if region == "front":
        return to_uv(front_px(x, z))
    return to_uv(rear_px(x, z))


# ---------------------------------------------------------------- side glass
# The perpendicular side photograph of the front half (commons MG 8751) puts the A-pillar at
# about 45 degrees from vertical, base at (y 0.81, z 1.12), top at the roof edge near y 0.29;
# the-blueprints side silhouette agrees once its 53-degree line is read as the windscreen's
# centreline (the base is 10 cm further forward at the centre than at the pillars). The earlier
# 35-degree reading of the brochure drawing was wrong. The front-door glass edge runs a little
# steeper than the pillar, so the painted pillar is a slim wedge, over a short mirror sail.
A_PILLAR_RAKE = 1.00                 # dy per dz along the A-pillar: 45 degrees from vertical
GLASS_RAKE = 0.90                    # the glass edge, 42 degrees
Y_HOOD_BACK = 0.96                   # hood rear edge; the black cowl grille lies behind it
Y_WS_TOP = 0.30                      # windscreen top edge, in plan


def ws_base(x):
    """y of the windscreen's lower edge at lateral x: curved in plan, 0.92 at the centre and
    0.81 at the pillars, with the cowl grille between it and the hood's rear edge."""
    return 0.92 - 0.11 * (x / 0.70) ** 2


def hood_side(y):
    """Half-width of the hood at y: the seam runs at 0.74, an 8 cm fender-top ledge inboard of
    the crease, then a 16 cm plan radius rounds the front corners in to 0.58 above the lamps."""
    if y <= 1.82:
        return 0.74
    return 0.58 + math.sqrt(max(0.0256 - (y - 1.82) ** 2, 0.0))


def hood_back(x):
    """y of the hood's rear edge at lateral x: concentric with the glass base, 7.5 cm ahead of
    it (the cowl grille's width). The hood mesh is cut straight at Y_HOOD_BACK; this curve is
    the painted seam."""
    return ws_base(x) + 0.075
PANE_FRONT = ((0.57, 1.12, 0.0), (0.57, 1.20, 0.03), (0.57 - 0.36 * GLASS_RAKE, 1.56, 0.08),
              (-0.22, 1.56, 0.05), (-0.22, 1.12, 0.0))
PANE_REAR = ((-0.35, 1.12, 0.0), (-0.35, 1.58, 0.05), (-1.06, 1.58, 0.05), (-1.06, 1.12, 0.0))
# The quarter glass starts right behind the rear door's shut line and its rear edge is nearly
# upright (6 degrees), 0.22 ahead of the tail at the belt: measured on the perpendicular side
# photograph (commons MG 8770).
PANE_QUARTER = ((-1.29, 1.13, 0.0), (-1.29, 1.59, 0.05), (-1.83, 1.59, 0.08), (-1.87, 1.13, 0.04))
B_PILLAR = (-0.35, -0.22)            # black, 0.13 wide
C_PILLAR = (-1.29, -1.06)            # body colour, 0.23 wide: the rear door's own frame, shut line at its rear edge
SAIL = ((0.57, 1.12), (0.67, 1.12), (0.57, 1.21))      # black mirror-mount triangle

# ---------------------------------------------------------------- rear end
# From the straight rear photograph (commons MG 8759) and the side one (MG 8770), which agree
# with the-blueprints side view: the tailgate glass rakes 24 degrees (top forward), the tail
# lamps sit on flat chamfered D-pillar corners 31 degrees off the rear face, the lower gate is
# 1.40 wide and its body corners round out to the flanks.
TG_FACE = -2.11                      # lower tailgate face; the glass plane starts here
Z_GLASS_BOT, Z_GLASS_TOP = 1.15, 1.575
TG_RAKE = 0.4535                     # dy per dz of the glass plane: 24.4 degrees from vertical
ROOF_EDGE_Y = -1.89                  # where the plane meets the drip height (z 1.61)
X_GATE = 0.70                        # lower tailgate half-width (its shut lines)
LAMP_Z = (1.14, 1.20, 1.385, 1.598)  # tail lamp: clear / red / amber bands; the amber runs up under the drip
CHAMFER_TAN = 0.60                   # D-pillar corner: a flat chamfer, dy per dx, 31 degrees
Z_BUMPER_TOP = 0.72
# half-width of the body side at the D-pillar (the same greenhouse taper as the doors), z -> x
REAR_SIDE = ((1.00, 0.845), (1.10, 0.80), (1.13, 0.74), (1.20, 0.715), (1.30, 0.682),
             (1.40, 0.648), (1.50, 0.612), (1.58, 0.588), (1.61, 0.578), (1.635, 0.548), (1.655, 0.48))


def tg_y(z):
    """y of the tailgate glass plane at height z."""
    return TG_FACE + (z - Z_GLASS_BOT) * TG_RAKE


def glass_edge(z):
    """Half-width of the tailgate glass at height z: near-rectangular, 10 cm top corners."""
    if z <= 1.16:
        return 0.55
    if z <= 1.475:
        return 0.55 - 0.02 * (z - 1.16) / 0.315
    if z <= Z_GLASS_TOP:
        d = z - 1.475
        return 0.43 + math.sqrt(max(0.0, 0.01 - d * d))
    return 0.43


def x_flat(z):
    """Where the flat rear face ends and the D-pillar chamfer begins: the glass plus its seal."""
    return glass_edge(z) + 0.02


def rear_side(z):
    zs = [p[0] for p in REAR_SIDE]
    xs = [p[1] for p in REAR_SIDE]
    if z <= zs[0]:
        return xs[0]
    if z >= zs[-1]:
        return xs[-1]
    i = bisect.bisect_right(zs, z)
    t = (z - zs[i - 1]) / (zs[i] - zs[i - 1])
    return xs[i - 1] + (xs[i] - xs[i - 1]) * t


def tail_crease_y(z):
    """y where the D-pillar chamfer meets the flank at height z; behind it lies the chamfer,
    then the glass plane."""
    return tg_y(z) + CHAMFER_TAN * max(rear_side(z) - x_flat(z), 0.0)


def lamp_outline(sgn, z0, z1, n=12):
    """(x, z) polygon of the tail lamp between two heights: inner edge on the glass seal, outer
    edge 1.5 cm short of the body side. Painted on the rear sheet; the mesh chamfer under it
    faces 31 degrees outward, so it shows from the side as well."""
    zs = [z0 + (z1 - z0) * i / n for i in range(n + 1)]
    inner = [(sgn * (x_flat(z) + 0.004), z) for z in zs]
    outer = [(sgn * (rear_side(z) - 0.015), z) for z in reversed(zs)]
    return inner + outer


def glass_outline():
    """(x, z) polygon of the tailgate glass."""
    right = [(0.55, 1.16), (0.53, 1.45)]
    for k in range(1, 6):
        a = math.pi / 2 * k / 5
        right.append((0.43 + 0.10 * math.cos(a), 1.475 + 0.10 * math.sin(a)))
    left = [(-x, z) for x, z in reversed(right)]
    return [(-0.55, 1.16)] + right + left


# ---------------------------------------------------------------- wheel sheet
# The wheel has its own square texture: the rim face is a polar map (hub at the centre, the
# tyre's outer radius near the edge), the tread a strip along the bottom.
WHEEL_SIZE = 512
WHEEL_FACE = (0, 0, 512, 400)        # polar face: centre (256, 200), 196 px = tyre radius
WHEEL_TREAD = (0, 412, 512, 512)


def wheel_face_uv(ry, rz, r_tyre):
    """Point on the rim face at radial offset (ry, rz) from the hub -> UV on the wheel sheet."""
    cx, cy, R = 256.0, 200.0, 196.0
    px = (cx + ry / r_tyre * R, cy - rz / r_tyre * R)
    return (px[0] / WHEEL_SIZE, 1.0 - px[1] / WHEEL_SIZE)


def wheel_tread_uv(angle, side_t):
    """Tread quad: angle around the axle 0..2pi -> u, across the tread 0..1 -> v."""
    x0, y0, x1, y1 = WHEEL_TREAD
    px = (x0 + (angle / 6.283185307) * (x1 - x0), y0 + side_t * (y1 - y0))
    return (px[0] / WHEEL_SIZE, 1.0 - px[1] / WHEEL_SIZE)
