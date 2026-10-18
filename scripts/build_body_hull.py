r"""
Honda CR-V RD1 body from the traced blueprint silhouettes plus photo-verified landmarks.

    import sys; sys.path.append("scripts")
    import build_body_hull as bh, importlib; importlib.reload(bh); bh.build()

Method: the visual hull of the three orthographic silhouettes in spec/trace/*.json, built on a
structured quad loft so it stays low-poly and keeps clean face groups.
  * side.json  gives z_top(y), z_bot(y)  -> roof / hood / windscreen / bumper ledges / arches
  * top.json   gives w_plan(y)           -> plan rounding of nose and tail
  * front.json gives w_front(z)          -> tumblehome, roof width, flares
Each cross-section ring has fixed feature rows. At a station the rows clamp to [z_bot, z_top] and
take half-width min(w_plan(y), w_front(z)). Rows that clamp onto the top surface are spread across
the width, so hood, windscreen, nose slope and tailgate become strips carrying per-region
materials.

Diagonal edges are "line stations": rings whose glass-band rows follow a (y, z) polyline instead
of a constant y. Two of them - the windscreen side edge and the front-door glass edge (vertical
then raked, with the black mirror sail between the two). The tailgate is plain stations 2 cm
apart: its raked glass plane is the top surface there and the D-pillar chamfers grow out of it.

Where the drawing and the photographs disagree the photographs win; every such override is listed
in spec/trace/README.md. The big one: the front view is drawn ~4 % too tall with the door mirrors
bridging the greenhouse (so the roof width comes from the plan view instead). The drawing's
24-degree tailgate rake, once overridden to upright, turned out to be right: the photographs
agree with it (spec/decisions.md 2026-09-05).

Model space: metres, +Y front, +Z up, +X right, origin between the axles at ground level.
"""
import bisect
import json
import math
import os

import bpy

from build_body import (MATS, SLOT, PART_NAMES, _box, _coll, _ensure_mats, _mesh_obj,
                        _purge, _wheel_mesh, TYRE_W, TYRE_R, TRACK_F, TRACK_R, Y_AXF, Y_AXR)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE = os.path.join(ROOT, "spec", "trace")

# ---------------------------------------------------------------- ring layout
# feature rows: target heights; half-ring index = index here + 2 (two floor rows come first)
Z_ROWS = [0.23, 0.40, 0.43, 0.52, 0.60, 0.72, 0.90, 1.10, 1.13, 1.16, 1.25, 1.35, 1.45, 1.56, 1.61, 1.645]
N_HALF = 2 + len(Z_ROWS) + 1          # floor centre, floor inner, rows, top centre = 19
RING = 2 * N_HALF - 2                 # 36
ROW_GARNISH = 5                       # z 0.52: top of the black sill garnish; rocker bottom (0.43) below it
ROW_RUB_LO, ROW_RUB_HI = 6, 7         # z 0.60 / 0.72: rub strip, and the bumper top edge
ROW_BELT, ROW_STEP = 9, 10            # z 1.10 door shoulder, 1.13 glass base (7 cm inboard)
ROW_LAMP = 11                         # z 1.16: bottom of the tail lamps, top of the belt ledge
ROW_AMBER, ROW_GTOP = 14, 15          # z 1.45 / 1.56  (the glass band ends here)
ROW_EDGE, ROW_ROOF = 16, 17           # z 1.61 drip rail, 1.645 roof corner
# where each row sits across the width (fraction of the outermost) once it lies on the top surface
SPREAD = {2: 1.0, 3: 1.0, 4: 1.0, 5: 1.0, 6: 1.0, 7: 1.0, 8: 1.0, 9: 0.985, 10: 0.97, 11: 0.955,
          12: 0.94, 13: 0.92, 14: 0.86, 15: 0.77, 16: 0.62, 17: 0.40, 18: 0.0}
Z_FLOOR = 0.23
X_INNER = 0.55
Z_BOT_MIN = 0.23                      # body bottom between the wheels
Z_ROCKER, UNDER_HALF = 0.43, 0.60     # rocker bottom edge between the wheels; the floor pan is tucked in below
Y_BUMPER_REAR = -1.72                 # behind this (and ahead of Y_BUMPER_WRAP) the bumpers rule the low rows
# The door / quarter-panel section below the belt. The traced plan and front views only give the
# widest envelope (the flares, 0.877); the real skin is convex: tucked at the rocker, fullest at
# mid-door, drawn in again under the shoulder (rear photograph MG 8759, front MG 8738).
DOOR_SECTION = ((0.43, 0.795), (0.52, 0.825), (0.70, 0.845), (0.95, 0.850), (1.04, 0.840), (1.10, 0.815))
CROWN = 0.025                         # hood centre above its edges: the RD1 hood has a real dome
NOSE_DROOP = 0.020                    # extra fall of the hood's outer corners toward the lamps
SPLIT_PARTS = True                    # emit hood/doors/windows/tailgate as objects
SMOOTH_ANGLE = 45.0                   # shade-smooth-by-angle: continuous panels, crisp edges

# ------------------------------------------------------------- side landmarks
Y_COWL = 0.80
Z_BELT, Z_DRIP, Z_CROWN = 1.10, 1.61, 1.654
# A-pillar: windscreen side edge, then the front-door glass edge. Between them lie the painted
# pillar (above the sail) and the black mirror sail panel (below z 1.31).
import tex_layout as TL
# Windscreen side edge (front of the painted pillar) at 35 degrees from vertical, the glass edge
# parallel behind it: Honda's brochure drawing and the side photograph agree on the angle.
_R, _G = TL.A_PILLAR_RAKE, TL.GLASS_RAKE
Y_WS_TOP = TL.Y_WS_TOP                # windscreen top edge, in plan (0.30)
WS_POLY = ((0.78, 1.10), (0.78 - 0.51 * _R, 1.61), (0.78 - 0.545 * _R, 1.645))
DG_POLY = ((0.57, 1.10), (0.57, 1.20), (0.57 - 0.36 * _G, 1.56),
           (0.57 - 0.41 * _G, 1.61), (0.57 - 0.445 * _G, 1.645))
Y_SAIL_BACK, Z_SAIL_TOP = 0.67, 1.21  # black mirror-mount triangle at the pane's front corner
B_PILLAR = TL.B_PILLAR                # black, vertical
C_PILLAR = TL.C_PILLAR                # body colour, vertical
Y_QUARTER_FRONT = TL.PANE_QUARTER[0][0]      # -1.29, right behind the rear door's shut line
QP_REAR = ((-1.87, 1.13), (-1.83, 1.59))     # quarter glass rear edge: nearly upright
Y_FENDER_SEAM = 0.80
# hood / fender crease half-width along the length: narrower than the flares by 5-7 cm a side
# through the middle, widening slightly toward the lamps. The plan outline below it is the flare
# and must not set the hood edge.
HOOD_EDGE = ((0.80, 0.800), (1.03, 0.798), (1.21, 0.812), (1.40, 0.825), (1.60, 0.845),
             (1.75, 0.855), (2.05, 0.855))


def _hood_edge(y):
    ys = [p[0] for p in HOOD_EDGE]
    ws = [p[1] for p in HOOD_EDGE]
    if y <= ys[0]:
        return ws[0]
    if y >= ys[-1]:
        return ws[-1]
    i = bisect.bisect_right(ys, y)
    t = (y - ys[i - 1]) / (ys[i] - ys[i - 1])
    return ws[i - 1] + (ws[i] - ws[i - 1]) * t
SHOULDER_TUCK = 0.05                  # fender side tucks in this much between z 0.90 and the crease

# Side glass outlines, (y, z, corner radius). The loft cuts these apertures; build_glass lays the
# panes over them. Numbers from the photographs (spec/decisions.md 2026-09-05).
PANE_FRONT, PANE_REAR, PANE_QUARTER = TL.PANE_FRONT, TL.PANE_REAR, TL.PANE_QUARTER
PANES = {"front": PANE_FRONT, "rear": PANE_REAR, "quarter": PANE_QUARTER}
APERTURE_MARGIN = 0.035               # loft faces this far inside the outline are cut away

# ------------------------------------------------------------- rear landmarks
# Numbers shared with the painter live in tex_layout (photographs, spec/decisions.md).
ROOF_FLAT_END = -1.85                 # flat roof ends, corner radius starts
ROOF_EDGE_Y = TL.ROOF_EDGE_Y          # -1.89: roof meets the tailgate glass at the drip height
TG_FACE = TL.TG_FACE                  # -2.11: vertical lower tailgate panel
TG_GLASS = ((TG_FACE, TL.Z_GLASS_BOT), (TL.tg_y(1.58), 1.58))   # glass plane: bottom, top (24 deg)
X_GATE = TL.X_GATE                    # 0.70: lower tailgate half-width; the body corners round beyond it
Y_WALL = -1.85                        # the flank's plan width is read here, ahead of the tail rounding
Z_BUMPER_R = TL.Z_BUMPER_TOP          # 0.72: rear bumper top; the tailgate panel starts above it
LAMP_Z = TL.LAMP_Z                    # clear / red / amber band edges on the D-pillar chamfer

# --------------------------------------------------------------- nose numbers
Y_NOSE_SLOPE = 1.90                   # ahead of this the top surface is the nose, not the hood
# brow rounds over 8 cm, then the lamp / grille face drops at 16 degrees from vertical, and the
# bumper face stands 9 cm ahead of it (side photograph MG 8751)
NOSE_TOP = ((1.94, 0.940), (1.99, 0.932), (2.02, 0.900), (2.05, 0.800), (2.07, 0.720), (2.12, 0.700))
LAMP_F_X = (0.33, 0.76)
LAMP_F_Z = (0.72, 0.90)
GRILLE_X, GRILLE_Z = 0.31, (0.76, 0.90)
Y_LAMP_WRAP = 1.72                    # the headlamps run this far back along the fender sides
Z_BUMPER_F = 0.72
Y_BUMPER_WRAP = 1.75                  # the front bumper wraps back to the front flare

ARCH_R = {Y_AXF: 0.42, Y_AXR: 0.40}
ARCH_FLARE = 0.065                    # crescent width outside the opening
FLARE_PROUD = 0.0                     # the loft stays smooth; the flare is its own part (_flares_mesh)
ARCH_Z = 0.334                        # arch centre height = axle height

# (nominal y for ordering, polyline, y for rows below the belt)
LINE_STATIONS = [(0.60, WS_POLY, 0.80), (0.50, DG_POLY, 0.60)]


def round_polygon(pts, seg=4):
    """pts: [(y, z, r)] convex, in order. Replace each cornered vertex by a tangent arc."""
    n = len(pts)
    out = []
    for i, (y, z, r) in enumerate(pts):
        if r <= 1e-6:
            out.append((y, z))
            continue
        py, pz, _ = pts[i - 1]
        ny, nz, _ = pts[(i + 1) % n]
        a = (py - y, pz - z)
        b = (ny - y, nz - z)
        la, lb = math.hypot(*a), math.hypot(*b)
        a = (a[0] / la, a[1] / la)
        b = (b[0] / lb, b[1] / lb)
        ang = math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1])))
        t = min(r / math.tan(ang / 2), la * 0.49, lb * 0.49)
        rr = t * math.tan(ang / 2)
        p0 = (y + a[0] * t, z + a[1] * t)
        p1 = (y + b[0] * t, z + b[1] * t)
        bis = (a[0] + b[0], a[1] + b[1])
        lbis = math.hypot(*bis)
        bis = (bis[0] / lbis, bis[1] / lbis)
        d = rr / math.sin(ang / 2)
        c = (y + bis[0] * d, z + bis[1] * d)
        a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
        a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
        da = a1 - a0
        while da > math.pi:
            da -= 2 * math.pi
        while da < -math.pi:
            da += 2 * math.pi
        for k in range(seg + 1):
            th = a0 + da * k / seg
            out.append((c[0] + rr * math.cos(th), c[1] + rr * math.sin(th)))
    return out


def offset_polygon(pts, d):
    """Offset a convex (y, z, r) polygon outward by d (inward if negative); radii change by d."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        y0, z0, _ = pts[i]
        y1, z1, _ = pts[(i + 1) % n]
        area += y0 * z1 - y1 * z0
    sgn = 1.0 if area > 0 else -1.0
    lines = []
    for i in range(n):
        y0, z0, _ = pts[i]
        y1, z1, _ = pts[(i + 1) % n]
        ey, ez = y1 - y0, z1 - z0
        L = math.hypot(ey, ez)
        nyv, nzv = sgn * ez / L, -sgn * ey / L
        lines.append(((y0 + nyv * d, z0 + nzv * d), (ey, ez)))
    out = []
    for i in range(n):
        (p, e1) = lines[i - 1]
        (q, e2) = lines[i]
        det = e1[0] * e2[1] - e1[1] * e2[0]
        if abs(det) < 1e-12:
            out.append((q[0], q[1], max(pts[i][2] + d, 0.0)))
            continue
        t = ((q[0] - p[0]) * e2[1] - (q[1] - p[1]) * e2[0]) / det
        out.append((p[0] + e1[0] * t, p[1] + e1[1] * t, max(pts[i][2] + d, 0.0)))
    return out


def point_in_polygon(pts, y, z):
    inside = False
    n = len(pts)
    for i in range(n):
        y0, z0 = pts[i]
        y1, z1 = pts[(i + 1) % n]
        if (z0 > z) != (z1 > z):
            yx = y0 + (z - z0) * (y1 - y0) / (z1 - z0)
            if y < yx:
                inside = not inside
    return inside


_APERTURES = None
_SIL = None                           # the silhouettes, for the material rules (set by build_shell)


def _apertures():
    """Rounded outer outlines and margin-shrunk inner outlines of the three side panes."""
    global _APERTURES
    if _APERTURES is None:
        _APERTURES = []
        for name, poly in PANES.items():
            outer = round_polygon(poly)
            inner = round_polygon(offset_polygon(poly, -APERTURE_MARGIN))
            _APERTURES.append((name, outer, inner))
    return _APERTURES


def _aperture_test(quad):
    """('hole' | 'edge' | None): the face is fully inside a pane, straddles its edge, or is clear."""
    ys = [p[1] for p in quad]
    zs = [p[2] for p in quad]
    for name, outer, inner in _apertures():
        if max(zs) < 1.05 or min(zs) > 1.66:
            continue
        if all(point_in_polygon(inner, y, z) for y, z in zip(ys, zs)):
            return "hole"
        cy, cz = sum(ys) / 4, sum(zs) / 4
        if point_in_polygon(outer, cy, cz) or any(point_in_polygon(outer, y, z) for y, z in zip(ys, zs)):
            return "edge"
    return None


def _poly_y(poly, z):
    """y on a (y, z) polyline at height z, extrapolating from the end segments."""
    zs = [p[1] for p in poly]
    if z <= zs[0]:
        i = 0
    elif z >= zs[-1]:
        i = len(poly) - 2
    else:
        i = bisect.bisect_right(zs, z) - 1
    (y0, z0), (y1, z1) = poly[i], poly[i + 1]
    if abs(z1 - z0) < 1e-9:
        return y0
    return y0 + (y1 - y0) * (z - z0) / (z1 - z0)


def _tg_ztop(y):
    """Top of the body behind the roof edge: the raked tailgate glass plane."""
    (y0, z0), (y1, z1) = TG_GLASS
    return min(Z_DRIP, z0 + (z1 - z0) * (y - y0) / (y1 - y0))


def _door_section(z):
    zs = [p[0] for p in DOOR_SECTION]
    xs = [p[1] for p in DOOR_SECTION]
    if z <= zs[0]:
        return xs[0]
    if z >= zs[-1]:
        return 9.9                                        # above the belt the greenhouse trace rules
    i = bisect.bisect_right(zs, z)
    t = (z - zs[i - 1]) / (zs[i] - zs[i - 1])
    return xs[i - 1] + (xs[i] - xs[i - 1]) * t


def _x_side(sil, y, z):
    """Half-width of the flank at (y, z). The traced plan and front silhouettes are outer
    envelopes (flares, mirrors, bumpers), so between the bumpers the skin follows the convex
    DOOR_SECTION and the floor pan is tucked in under the rocker; at the bumpers the plan outline
    rules right down to the lip. Behind Y_WALL the traced plan is the rear bumper's outline, so
    the width is held there and the tail's own corner rules take over."""
    w_plan = sil.top(max(y, Y_WALL))
    w_front = sil.front(z)
    if (y > Y_BUMPER_WRAP or y < Y_BUMPER_REAR) and z < 0.95:
        return min(w_plan, max(w_front, 0.84))
    if z < Z_ROCKER:
        return min(w_plan, UNDER_HALF)
    if y > Y_COWL and z > 1.0:
        # the fender top: no glass here, so no belt step; it runs out to the hood edge (the
        # shoulder tuck in _ring keeps it under the crease) instead of stepping in like the doors
        w_front = max(w_front, 0.82)
    return min(w_plan, w_front, _door_section(z))


def _chamfer_depth(sil, z):
    """How far ahead of the glass plane the D-pillar chamfer reaches at height z."""
    return max(_x_side(sil, Y_WALL, z) - TL.x_flat(z), 0.0) * TL.CHAMFER_TAN


def _tail_x(sil, y, z):
    """(half-width, surface tag) of a side row at (y, z). Near the tail: above the belt ledge the
    flat chamfer that carries the tail lamp ('C': from the glass seal out to the flank, 31 degrees
    off the rear face); below it a rounded corner from the lower tailgate's edge out to the flank
    ('A'). Anywhere else this is just the flank ('F'); 'P' is the tailgate plane itself."""
    xs = _x_side(sil, y, z)
    if z >= Z_ROWS[ROW_LAMP - 2] - 1e-6:
        dy = y - TL.tg_y(z)
        if dy <= 0.0:
            return TL.x_flat(z), 'P'
        v = TL.x_flat(z) + dy / TL.CHAMFER_TAN
        return (v, 'C') if v < xs else (xs, 'F')
    dy = y - TG_FACE
    r = xs - X_GATE
    if r <= 1e-6 or dy >= r:
        return xs, 'F'
    if dy <= 0.0:
        return X_GATE, 'A'
    return X_GATE + math.sqrt(max(r * r - (r - dy) ** 2, 0.0)), 'A'


def _split(idx, tg):
    """One quad, or two triangles when three corners lie on one tail surface and the fourth on
    another: the fold then runs along a triangle edge instead of zig-zagging across the quads
    (the plane's columns shift every time a new row lands on it, so quads there straddle the
    plane / chamfer fold diagonally)."""
    if not ('P' in tg or 'C' in tg) or len(set(tg)) != 2:
        return [idx]
    for i in range(4):
        if tg.count(tg[i]) == 1:
            p, n = idx[(i - 1) % 4], idx[(i + 1) % 4]
            return [(idx[i], n, p), (n, idx[(i + 2) % 4], p)]
    return [idx]


def _arch_depth(y, z):
    """How far a point sits outside the nearest wheel opening (negative = inside it)."""
    best = 9.9
    for yc, r in ARCH_R.items():
        best = min(best, math.hypot(y - yc, z - ARCH_Z) - r)
    return best


class Sil:
    """Piecewise-linear lookups into the traced silhouettes, with the rear overrides."""

    def __init__(self):
        s = json.load(open(os.path.join(TRACE, "side.json")))
        t = json.load(open(os.path.join(TRACE, "top.json")))
        f = json.load(open(os.path.join(TRACE, "front.json")))
        self.sy, self.st, self.sb = self._asc(s["y"], s["z_top"], s["z_bot"])
        self.ty, self.tw = self._asc(t["y"], t["w"])[:2]
        self.fz, self.fw = self._asc(f["z"], f["w"])[:2]
        self.y_max, self.y_min = self.sy[-1], self.sy[0]

    @staticmethod
    def _asc(x, *cols):
        order = sorted(range(len(x)), key=lambda i: x[i])
        return [[c[i] for i in order] for c in (x,) + cols]

    @staticmethod
    def _interp(xs, ys, x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        i = bisect.bisect_right(xs, x)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

    def side(self, y):
        z_top = self._interp(self.sy, self.st, y)
        if y > NOSE_TOP[0][0]:                         # the brow holds, then drops to the bumper
            ys_ = [p[0] for p in NOSE_TOP]
            zs_ = [p[1] for p in NOSE_TOP]
            z_top = max(z_top, self._interp(ys_, zs_, y))
        if y <= ROOF_FLAT_END:
            if y >= ROOF_EDGE_Y:                       # roof-to-tailgate corner radius
                t = (ROOF_FLAT_END - y) / (ROOF_FLAT_END - ROOF_EDGE_Y)
                z_top = Z_CROWN - (Z_CROWN - Z_DRIP) * t * t
            else:
                z_top = _tg_ztop(y)
        return z_top, max(self._interp(self.sy, self.sb, y), Z_BOT_MIN)

    def top(self, y):
        return self._interp(self.ty, self.tw, y)

    def front(self, z):
        return self._interp(self.fz, self.fw, z)


def skin_x(sil, y, z):
    """Half-width of the loft skin at (y, z): the rows' widths interpolated in z the way the
    quads are. Anything that must sit proud of the body (glass panes, seals) uses this rather
    than the raw traced curve, which the rows only sample."""
    zs = [zr for zr in Z_ROWS if zr >= 0.90]
    ws = [_tail_x(sil, y, zr)[0] for zr in zs]
    if z <= zs[0]:
        return ws[0]
    if z >= zs[-1]:
        return ws[-1]
    i = bisect.bisect_right(zs, z)
    t = (z - zs[i - 1]) / (zs[i] - zs[i - 1])
    return ws[i - 1] + (ws[i] - ws[i - 1]) * t


def _between(y, a, b):
    return min(a, b) < y < max(a, b)


def _zone(line):
    ys = [line[2]] + [p[0] for p in line[1]]
    return min(ys) - 0.02, max(ys) + 0.02


def _stations(sil):
    """List of (nominal_y, line_spec or None), nose first."""
    ys = set()
    y = TG_FACE
    while y < -1.795:                                      # 2 cm through the tail: corners, lamps, roof edge
        ys.add(round(y, 3)); y += 0.02
    y = -1.79
    while y <= sil.y_max:                                  # base grid 6 cm
        ys.add(round(y, 3)); y += 0.06
    for k in range(14):                                    # 2 cm near the nose: ledges + rounding
        ys.add(round(sil.y_max - k * 0.02, 3))
    for yc, r in ARCH_R.items():                           # arch stations
        for k in range(21):                                # 21 stations across each arch
            f = -1.0 + 2.0 * k / 20
            ys.add(round(yc + f * (r + ARCH_FLARE), 3))
    for v in (Y_COWL, Y_FENDER_SEAM, B_PILLAR[0], B_PILLAR[1], C_PILLAR[0], C_PILLAR[1],
              Y_QUARTER_FRONT, Y_DOOR_R[0], ROOF_FLAT_END, ROOF_EDGE_Y, Y_HOOD_BACK,
              Y_NOSE_SLOPE, Y_BUMPER_WRAP, 2.02, 1.40, -0.60, -1.40):
        ys.add(round(v, 3))
    zones = [_zone(l) for l in LINE_STATIONS]
    ys = {v for v in ys
          if TG_FACE <= v <= sil.y_max and not any(lo < v < hi for lo, hi in zones)}
    ys.add(round(sil.y_max, 3))
    out = [(v, None) for v in ys] + [(l[0], l) for l in LINE_STATIONS]
    return sorted(out, key=lambda t: -t[0])                # nose first


def _ring(sil, y, line=None):
    """Half ring [(x, y, z)] for the +X side, bottom to top, plus one surface tag per vertex
    (see _tail_x; 'T' hood/roof top, 'L' line station, '-' floor); the caller mirrors x."""
    z_top, z_bot = sil.side(y)
    rows, clamped, tags = [], [], []
    top_tag = 'P' if y < ROOF_EDGE_Y else 'T'
    for k, zk in enumerate(Z_ROWS):
        half_idx = k + 2
        if line is not None:
            _, poly, y_low = line
            yk = _poly_y(poly, zk) if half_idx >= ROW_BELT else y_low
            zt_k, zb_k = sil.side(yk)
            z = min(zk, zt_k) if half_idx >= ROW_BELT else min(max(zk, zb_k), zt_k)
            rows.append([min(sil.top(yk), sil.front(z)), yk, z])
            tags.append('L')
            continue
        z = min(max(zk, z_bot), z_top)
        w, tag = _tail_x(sil, y, z)
        d = _arch_depth(y, z)
        if -0.02 < d < ARCH_FLARE:                        # the flare stands proud of the door skin
            w += FLARE_PROUD * min(1.0, 1.5 * math.sin(math.pi * max(d, 0.0) / ARCH_FLARE))
        if y > Y_COWL and zk >= 0.90 and z < z_top - 1e-4:  # fender shoulder under the hood crease
            w = min(w, _hood_edge(y) + SHOULDER_TUCK * (z_top - z) / max(z_top - 0.90, 0.05))
        rows.append([w, y, z])
        if z >= z_top - 1e-4:
            clamped.append(k)
            tag = top_tag
        tags.append(tag)
    if line is None and clamped:                          # spread top rows across the width
        # Ahead of the cowl the top surface is the hood: its outline is the PLAN width. Letting
        # the front-view curve bound it (as the visual hull does elsewhere) makes the hood edge
        # wander a couple of centimetres fore-aft and corrugates the panel.
        if y < ROOF_EDGE_Y:
            # the tailgate: the flat glass plane out to its seal, evenly divided; the chamfer
            # beyond it is made by the side rows above (see _tail_x)
            w_star = TL.x_flat(z_top)
            for i, k in enumerate(clamped):
                rows[k][0] = w_star * (len(clamped) - i) / len(clamped)
        else:
            w_star = min(sil.top(y), _hood_edge(y)) if y > Y_COWL else rows[clamped[0]][0]
            base = SPREAD[clamped[0] + 2]
            for k in clamped:
                # fixed fraction per ROW, normalised so the outermost clamped row lands exactly
                # on the crease; a row joining the clamped set slots in between its neighbours
                rows[k][0] = max(w_star * SPREAD[k + 2] / base, 0.0)
        for k in clamped:                                  # nothing on top sits outboard of the skin below it
            if k > 0:
                rows[k][0] = min(rows[k][0], rows[k - 1][0])
            if y > Y_COWL and rows[k][2] > LAMP_F_Z[1] + 0.02:   # hood crown, ramped in from the cowl
                # keyed to absolute x, not to w_star: every strip then keeps the same dz/dy and
                # the hood stays a smooth surface instead of a fan of slightly-tilted facets.
                # Toward the nose the corners droop a little more (the brow rolls down to the
                # lamps' outer ends); the lamp and grille face itself is left level.
                ramp = min(1.0, (y - Y_COWL) / 0.30)
                crown = CROWN + NOSE_DROOP * min(1.0, max(0.0, (y - 1.70) / 0.30))
                rows[k][2] = z_top - crown * ramp * (rows[k][0] / 0.85) ** 2
    y_top = rows[-1][1]
    zf = z_bot                                            # no slab under the overhangs
    y_low = rows[0][1]
    half = ([(0.0, y_low, zf), (min(X_INNER, max(rows[0][0] - 0.05, 0.05)), y_low, zf)] +
            [(w, yy, z) for w, yy, z in rows] + [(0.0, y_top, sil.side(y_top)[0])])
    return half, ['-', '-'] + tags + ['L' if line is not None else top_tag]


def _verts(half):
    right = [(w, yy, z) for (w, yy, z) in half]
    left = [(-w, yy, z) for (w, yy, z) in reversed(half[1:-1])]
    return right + left


def _mirror_tags(tags):
    return list(tags) + list(reversed(tags[1:-1]))


def _line_of(k):
    return k if k < N_HALF else RING - k


# ------------------------------------------------------------------ materials
def _glass_pane(y, z):
    """Which side window, if any, contains (y, z) in the glass band."""
    if _between(y, B_PILLAR[1], _poly_y(DG_POLY, z)):
        return "front"
    if _between(y, C_PILLAR[1], B_PILLAR[0]):
        return "rear"
    if _between(y, _poly_y(QP_REAR, z), Y_QUARTER_FRONT):
        return "quarter"
    return None


def _material(lo, hi, ymid, xmid, zmid, z_top, pillar=False):
    """lo/hi are half-ring row indices (0 floor centre .. 13 top centre)."""
    on_top = zmid > z_top - 0.035
    ax = abs(xmid)
    glass_band = lo >= ROW_BELT and hi <= ROW_GTOP

    if hi <= 2:
        return "black"                                    # floor and wheel wells
    if pillar and lo >= ROW_BELT:                         # between the A-pillar line stations
        return "black" if (zmid < Z_SAIL_TOP and ymid < Y_SAIL_BACK) else "paint"

    if on_top and ymid > Y_NOSE_SLOPE:                    # the nose, by height
        if LAMP_F_Z[0] < zmid < LAMP_F_Z[1] + 0.03:
            if ax < GRILLE_X and zmid > GRILLE_Z[0]:
                return "grille"
            if LAMP_F_X[0] < ax < LAMP_F_X[1] + 0.06:
                return "light_f"
            return "paint"
        if zmid >= LAMP_F_Z[1] + 0.03:
            return "paint"                                # hood leading edge
        return "cladding"                                 # bumper
    if ymid < ROOF_EDGE_Y + 0.05 and LAMP_Z[0] - 0.02 < zmid < LAMP_Z[3] and lo >= ROW_STEP:
        dy = ymid - TL.tg_y(zmid)                         # tail lamp on the D-pillar chamfer
        if 0.002 < dy < _chamfer_depth(_SIL, zmid) - 0.01 and ax > TL.x_flat(zmid) + 0.005:
            return "light_a" if zmid > LAMP_Z[2] else ("light_r" if zmid > LAMP_Z[1] else "light_f")
    if on_top and ymid < ROOF_EDGE_Y:                     # the tailgate, by height
        return _tailgate_mat(zmid, ax, 0.66)
    if lo >= ROW_BELT and Y_WS_TOP < ymid < TL.ws_base(xmid) and zmid > Z_BELT + 0.02:
        return "glass"                                    # windscreen (base curved in plan)
    if on_top and zmid > Z_BELT and TL.ws_base(xmid) <= ymid < TL.hood_back(xmid):
        return "black"                                    # cowl grille under the wipers
    if on_top and zmid > Z_BELT:
        return "paint"                                    # roof / cowl top

    if hi <= ROW_GARNISH:
        return "black" if -0.90 < ymid < 0.87 else "cladding"   # sill garnish / valance
    d = _arch_depth(ymid, zmid)
    if -0.03 < d < ARCH_FLARE + 0.02 and zmid < 0.95:
        return "cladding"                                 # wheel-arch flare crescent
    if ymid > Y_BUMPER_WRAP and hi <= ROW_RUB_HI:
        return "cladding"                                 # front bumper wraps to the flare
    if ymid < ROOF_EDGE_Y and hi <= ROW_RUB_HI:
        return "cladding"                                 # hidden behind the rear bumper part
    if lo >= ROW_RUB_LO and hi <= ROW_RUB_HI and -0.90 < ymid < 0.80:
        return "cladding"                                 # side rub strips
    if ymid > Y_LAMP_WRAP and lo == ROW_RUB_HI and hi == ROW_RUB_HI + 1:
        return "light_f"                                  # headlamps wrap the corner

    if glass_band:
        if _glass_pane(ymid, zmid):
            return "glass"
        if _between(ymid, B_PILLAR[0], B_PILLAR[1]):
            return "black"
    return "paint"


def _nose_cap_mat(zc, xc, w_row):
    if GRILLE_Z[0] < zc < GRILLE_Z[1] and xc < GRILLE_X:
        return "grille"
    if LAMP_F_Z[0] < zc < LAMP_F_Z[1] and LAMP_F_X[0] < xc < LAMP_F_X[1]:
        return "light_f"
    if zc < Z_BUMPER_F:
        return "grille" if (0.40 < zc < 0.585 and xc < 0.62) else "cladding"
    return "paint"


def _tailgate_mat(zc, xc, w_row):
    """Tailgate plane: the glass with its painted surround, the lower gate below it. The lamps
    are not on this plane - they sit on the D-pillar chamfers either side (see _material)."""
    if zc >= TL.Z_GLASS_TOP:
        return "paint"                                    # band under the roof edge
    if zc >= TL.Z_GLASS_BOT - 0.005:
        return "glass" if xc <= TL.glass_edge(zc) else "paint"
    if zc > Z_BUMPER_R:
        return "paint"                                    # lower tailgate panel
    return "cladding"                                     # hidden behind the bumper part


# --------------------------------------------------------------------- parts
# Shut lines. The shell is emitted as one loft and then split into these objects, KI5 style:
# every panel that opens is its own mesh bound to its own bone.
Y_HOOD_BACK, Y_HOOD_FRONT, X_HOOD = TL.Y_HOOD_BACK, 1.98, 0.78
Y_DOOR_F = (-0.28, 0.80)              # front door shut lines (fender seam .. B-pillar)
Y_DOOR_R = (-1.27, -0.28)             # rear door shut lines: B-pillar .. behind its own C-pillar frame
Z_DOOR = (0.52, 1.62)                 # door skin: sill garnish top .. drip rail
X_TAILGATE = X_GATE - 0.01            # the lower gate is the whole face between the body corners
Z_TAILGATE = (Z_BUMPER_R, TL.Z_GLASS_BOT)     # lower tailgate panel; the flip-up glass is above

OPENING_PARTS = ["hood", "door_fl", "door_fr", "door_rl", "door_rr",
                 "window_fl", "window_fr", "window_rl", "window_rr", "trunk", "trunk_top"]
SHELL_PARTS = ["body"] + OPENING_PARTS
EXTRA_PARTS = ["bumper_rear", "spare", "mirror_L", "mirror_R", "roofrail_L", "roofrail_R",
               "mudflaps", "antenna", "flares",
               "wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR"]


def _part(lo, hi, ymid, xmid, zmid, z_top, mat, quad=None):
    """Which named object a loft face belongs to. lo/hi are the half-ring row indices.
    Returns (name, on_pane_edge). name 'hole' means the face is cut away for a glass pane."""
    side = "l" if xmid < 0 else "r"
    on_top = zmid > z_top - 0.035
    if quad is not None and not on_top and lo >= ROW_BELT and hi <= ROW_EDGE and abs(xmid) > 0.5:
        ap = _aperture_test(quad)
        if ap == "hole":
            return "hole", False
        if ap == "edge":
            if Y_DOOR_F[0] < ymid < Y_DOOR_F[1]:
                return "door_f%s" % side, True
            if Y_DOOR_R[0] < ymid < Y_DOOR_R[1]:
                return "door_r%s" % side, True
            return "body", True
    if on_top and Y_HOOD_BACK < ymid < Y_HOOD_FRONT and abs(xmid) < TL.hood_side(ymid):
        return "hood", False
    if on_top and ymid < ROOF_EDGE_Y:                     # the glass plane: the flip-up hatch
        return _tailgate_part(zmid, abs(xmid)), False
    # rows 0-2 are the underbody. Behind the front axle the traced bottom rides up into the wheel
    # arches, so those faces can sit at door height with x near the centreline - keep them on the
    # body or the rear doors swallow the floor.
    if lo < ROW_GARNISH or abs(xmid) < 0.35:
        return "body", False
    if Z_DOOR[0] < zmid < Z_DOOR[1] and not on_top:
        if Y_DOOR_F[0] < ymid < Y_DOOR_F[1]:
            return "door_f%s" % side, False
        if Y_DOOR_R[0] < ymid < Y_DOOR_R[1]:
            return "door_r%s" % side, False
    return "body", False


def _tailgate_part(zc, xc):
    """Rear cap and glass plane: the lower gate between the body corners, the flip-up glass above
    it up to the painted band under the roof edge."""
    if xc >= X_TAILGATE:
        return "body"
    if zc >= Z_TAILGATE[1]:
        return "trunk_top" if zc < TL.Z_GLASS_TOP + 0.01 else "body"
    if zc > Z_TAILGATE[0]:
        return "trunk"
    return "body"


def _cap(verts, faces, mats_idx, half, n=10, mat_fn=_nose_cap_mat,
         parts=None, part_fn=None):
    """Close an end ring with a grid across the width; one row per distinct height."""
    rows = []
    for (w, yy, z) in half[2:-1]:
        if rows and abs(rows[-1][2] - z) < 1e-4:
            rows[-1][0] = max(rows[-1][0], w)
        else:
            rows.append([w, yy, z])
    v0 = len(verts)
    for (w, yy, z) in rows:
        for k in range(n + 1):
            verts.append((-w + 2 * w * k / n, yy, z))
    for i in range(len(rows) - 1):
        for k in range(n):
            a = v0 + i * (n + 1) + k
            b = v0 + (i + 1) * (n + 1) + k
            faces.append((a, a + 1, b + 1, b))
            w_row = (rows[i][0] + rows[i + 1][0]) / 2
            xc = abs(-w_row + 2 * w_row * (k + 0.5) / n)
            zc = (rows[i][2] + rows[i + 1][2]) / 2
            mats_idx.append(SLOT[mat_fn(zc, xc, w_row)])
            if parts is not None:
                parts.append(part_fn(zc, xc) if part_fn else "body")


# ------------------------------------------------------------- separate parts
Y_BUMPER_FACE, R_BUMPER, X_BUMPER_FACE = -2.24, 0.12, 0.72
Y_BUMPER_FRONT = -1.77                # the bumper's flanks run forward to the rear arch flare


def _bumper_plan(sil, y):
    """Plan half-width of the rear bumper: a flat face, a 12 cm corner out to the flank, then a
    flank that follows the traced plan a touch proud of the body."""
    w_side = min(sil.top(max(y, -2.00)), 0.86) + 0.012
    dy = y - Y_BUMPER_FACE
    if dy >= R_BUMPER:
        return w_side
    if dy <= 0.0:
        return X_BUMPER_FACE
    u = 1.0 - dy / R_BUMPER
    return X_BUMPER_FACE + (w_side - X_BUMPER_FACE) * math.sqrt(max(0.0, 1.0 - u * u))


def _bumper_ring(sil, y):
    """Rear bumper cross-section, bottom centre to top centre: tucked lower lip, lower face,
    groove, upper face standing a touch proud, top ledge. Solid across the tail; along the
    flanks the inner points close up into a shell just inside the skin."""
    w = _bumper_plan(sil, y)
    x_in = 0.55 * w if y <= TG_FACE + 0.005 else w - 0.06
    pts = [(0.0, 0.36), (w - 0.04, 0.36), (w - 0.012, 0.40), (w, 0.50), (w, 0.58),
           (w - 0.012, 0.595), (w - 0.012, 0.625), (w + 0.004, 0.64), (w + 0.004, 0.71),
           (w - 0.015, 0.73), (x_in, 0.73), (x_in, 0.70), (0.0, 0.70)]
    return [(x, y, z) for x, z in pts]


def build_rear_bumper(coll, mats, sil):
    ys = []
    y = Y_BUMPER_FRONT
    while y >= Y_BUMPER_FACE - 1e-6:
        ys.append(round(y, 3)); y -= 0.02
    halves = [_bumper_ring(sil, v) for v in ys]
    n_half = len(halves[0]); ring = 2 * n_half - 2
    verts, faces, mi = [], [], []
    for h in halves:
        verts.extend(_verts(h))
    for s in range(len(halves) - 1):
        a, b = s * ring, (s + 1) * ring
        ymid = (ys[s] + ys[s + 1]) / 2
        for k in range(ring):
            k2 = (k + 1) % ring
            faces.append((a + k, a + k2, b + k2, b + k))
            quad = (verts[a + k], verts[a + k2], verts[b + k2], verts[b + k])
            xc = abs(sum(p[0] for p in quad) / 4)
            zc = sum(p[2] for p in quad) / 4
            reflector = xc > 0.74 and -2.22 < ymid < -2.13 and 0.50 < zc < 0.58
            mi.append(SLOT["light_r"] if reflector else SLOT["cladding"])
    face = halves[-1]                                     # the rear face: outer profile only
    _cap(verts, faces, mi, [face[0], face[0]] + face[1:10] + [face[-1]], n=10,
         mat_fn=lambda zc, xc, w: "cladding")
    return _mesh_obj("bumper_rear", verts, faces, mi, coll, mats)


def _mirror_mesh(name, sgn, coll, mats):
    """Door mirror: a black housing on a short stalk from the sail panel. The housing is a box
    whose outboard face is drawn in, so its edges read as rounded; the glass side faces back."""
    x_in, x_h0, x_h1 = 0.79, 0.85, 0.98                   # sail, housing inner face, outer face
    y0, y1, z0, z1 = 0.50, 0.66, 1.10, 1.22               # head: 16 long, 12 tall
    ym, zm = (y0 + y1) / 2, (z0 + z1) / 2
    s = 0.03                                              # stalk half-size
    v = [(x_h0, y0, z0), (x_h0, y1, z0), (x_h0, y1, z1), (x_h0, y0, z1),                  # inner face
         (x_h1, y0 + 0.02, z0 + 0.015), (x_h1, y1 - 0.02, z0 + 0.015),
         (x_h1, y1 - 0.02, z1 - 0.015), (x_h1, y0 + 0.02, z1 - 0.015),                    # outer face
         (x_in, ym - s, zm - s), (x_in, ym + s, zm - s), (x_in, ym + s, zm + s), (x_in, ym - s, zm + s),
         (x_h0, ym - s, zm - s), (x_h0, ym + s, zm - s), (x_h0, ym + s, zm + s), (x_h0, ym - s, zm + s)]
    v = [(sgn * a, b, c) for a, b, c in v]
    f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
         (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15)]
    if sgn < 0:
        f = [tuple(reversed(q)) for q in f]
    return _mesh_obj(name, v, f, [SLOT["black"]] * len(f), coll, mats)


def _boxes_mesh(name, boxes, mat, coll, mats):
    """Several axis-aligned boxes [(size, centre)] as one object."""
    verts, faces = [], []
    for (sx, sy, sz), (cx, cy, cz) in boxes:
        b = len(verts)
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        verts += [(cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz), (cx + hx, cy + hy, cz - hz),
                  (cx - hx, cy + hy, cz - hz), (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
                  (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz)]
        faces += [tuple(b + i for i in q) for q in
                  ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))]
    return _mesh_obj(name, verts, faces, [SLOT[mat]] * len(faces), coll, mats)


def _rail_mesh(name, sgn, coll, mats):
    """Roof rail: a bar on three feet, a finger of daylight under it as on the car."""
    x = sgn * 0.47
    boxes = [((0.05, 1.90, 0.03), (x, -0.75, 1.705))]
    for y in (0.10, -0.75, -1.60):
        boxes.append(((0.06, 0.10, 0.05), (x, y, 1.665)))
    return _boxes_mesh(name, boxes, "black", coll, mats)


def _mudflaps_mesh(name, coll, mats):
    """Factory splash guards behind all four wheels, hanging below the sill."""
    boxes = []
    for yc, r in ARCH_R.items():
        y = yc - r - ARCH_FLARE - 0.01
        for sgn in (1, -1):
            boxes.append(((0.18, 0.012, 0.16), (sgn * 0.78, y, 0.37)))
    return _boxes_mesh(name, boxes, "black", coll, mats)


def _flares_mesh(name, sil, coll, mats):
    """The four black wheel-arch flares as one object: a strip around each opening standing
    22 mm off the panel, with a rolled outer edge back to the skin. Built on the loft skin the
    way the glass panes are, because the loft's row/station grid cannot follow a crescent."""
    verts, faces, mi = [], [], []
    rings = ((0.005, 0.022), (0.045, 0.022), (ARCH_FLARE + 0.006, 0.004))   # (radial offset, proud)
    n = 20
    for yc, r in ARCH_R.items():
        for sgn in (1, -1):
            base = len(verts)
            for (dr, proud) in rings:
                for i in range(n + 1):
                    th = math.radians(15 + 150 * i / n)     # ends at the rocker line, z 0.44
                    y = yc + (r + dr) * math.cos(th)
                    z = ARCH_Z + (r + dr) * math.sin(th)
                    x = _tail_x(sil, y, z)[0] + proud
                    verts.append((sgn * x, y, z))
            for k in range(len(rings) - 1):
                for i in range(n):
                    a = base + k * (n + 1) + i
                    b = base + (k + 1) * (n + 1) + i
                    quad = (a, a + 1, b + 1, b) if sgn < 0 else (a, b, b + 1, a + 1)
                    faces.append(quad)
                    mi.append(SLOT["cladding"])
    return _mesh_obj(name, verts, faces, mi, coll, mats)


def _antenna_mesh(name, coll, mats):
    """Mast antenna on the right front fender, leaning back."""
    (x0, y0, z0), (x1, y1, z1), t = (0.78, 1.06, 1.05), (0.78, 0.86, 1.64), 0.005
    v = [(x0 - t, y0 - t, z0), (x0 + t, y0 - t, z0), (x0 + t, y0 + t, z0), (x0 - t, y0 + t, z0),
         (x1 - t, y1 - t, z1), (x1 + t, y1 - t, z1), (x1 + t, y1 + t, z1), (x1 - t, y1 + t, z1)]
    f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    return _mesh_obj(name, v, f, [SLOT["black"]] * 6, coll, mats)


def _spare_mesh(name, coll, mats):
    """Hard-cover spare: OD 0.70, flat outer ring and a raised centre dome. Axis along +Y."""
    prof = [(0.00, -0.115), (0.25, -0.115), (0.29, -0.09), (0.35, -0.02),
            (0.35, 0.045), (0.29, 0.08), (0.25, 0.105), (0.00, 0.115)]
    seg = 20
    verts, faces, mi = [], [], []
    for (r, a) in prof:
        for i in range(seg):
            t = 2 * math.pi * i / seg
            verts.append((r * math.cos(t), a, r * math.sin(t)))
    for j in range(len(prof) - 1):
        for i in range(seg):
            i2 = (i + 1) % seg
            faces.append((j * seg + i, j * seg + i2, (j + 1) * seg + i2, (j + 1) * seg + i))
            mi.append(SLOT["paint"] if j >= 3 else SLOT["cladding"])
    return _mesh_obj(name, verts, faces, mi, coll, mats)


def build_shell(coll, mats, sil, split=True):
    """Build the shell as one loft, then emit it as the named opening parts plus the body."""
    global _SIL
    _SIL = sil
    stations = _stations(sil)
    rings = [_ring(sil, y, line) for y, line in stations]
    halves = [h for h, _ in rings]
    verts, faces, mats_idx, parts, tags = [], [], [], [], []
    for h, t in rings:
        verts.extend(_verts(h))
        tags.extend(_mirror_tags(t))
    for s in range(len(stations) - 1):
        a, b = s * RING, (s + 1) * RING
        pillar = stations[s][1] is not None and stations[s + 1][1] is not None
        for k in range(RING):
            k2 = (k + 1) % RING
            idx = (a + k, a + k2, b + k2, b + k)
            lo, hi = sorted((_line_of(k), _line_of(k2)))
            quad = tuple(verts[i] for i in idx)
            xmid = sum(p[0] for p in quad) / 4
            ymid = sum(p[1] for p in quad) / 4
            zmid = sum(p[2] for p in quad) / 4
            z_top = sil.side(ymid)[0]
            mat = _material(lo, hi, ymid, xmid, zmid, z_top, pillar)
            name, on_edge = _part(lo, hi, ymid, xmid, zmid, z_top, mat, quad)
            if name == "hole":
                continue                                   # cut away: a glass pane covers this
            if on_edge:
                mat = "black"                              # seal backing around the aperture
            for f in _split(idx, [tags[i] for i in idx]):
                fname = name
                if name == "trunk_top" and any(tags[i] != 'P' for i in f):
                    fname = "body"                         # fold triangles stay with the body
                faces.append(f)
                mats_idx.append(SLOT[mat])
                parts.append(fname)
    _cap(verts, faces, mats_idx, halves[0], n=12, mat_fn=_nose_cap_mat,
         parts=parts, part_fn=lambda zc, xc: "body")
    _cap(verts, faces, mats_idx, halves[-1], n=14, mat_fn=_tailgate_mat,
         parts=parts, part_fn=_tailgate_part)
    if not split:
        return [_mesh_obj("body", verts, faces, mats_idx, coll, mats)]
    return _emit_parts(verts, faces, mats_idx, parts, coll, mats)


def _emit_parts(verts, faces, mats_idx, parts, coll, mats):
    """One mesh object per part name, each carrying its own vertex subset."""
    groups = {}
    for f, mi, pn in zip(faces, mats_idx, parts):
        groups.setdefault(pn, ([], []))[0].append(f)
        groups[pn][1].append(mi)
    out = []
    for name in SHELL_PARTS:
        if name not in groups:
            continue
        fs, ms = groups[name]
        remap, vs, nf = {}, [], []
        for f in fs:
            q = []
            for vi in f:
                if vi not in remap:
                    remap[vi] = len(vs)
                    vs.append(verts[vi])
                q.append(remap[vi])
            nf.append(tuple(q))
        out.append(_mesh_obj(name, vs, nf, ms, coll, mats))
    return out


def _smooth(ob):
    for poly in ob.data.polygons:
        poly.use_smooth = True
    try:
        with bpy.context.temp_override(object=ob, selected_editable_objects=[ob], active_object=ob):
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(SMOOTH_ANGLE))
    except Exception as exc:  # noqa: BLE001
        print("shade_smooth_by_angle unavailable:", exc)


def build():
    sil = Sil()
    mats = _ensure_mats()
    c_body, c_wheels, c_trim = _coll("body"), _coll("wheels"), _coll("trim")
    # "Cube": Blender's startup scene, when a runner is launched without a .blend file
    _purge(list(dict.fromkeys(PART_NAMES + SHELL_PARTS + EXTRA_PARTS + ["Cube"])))
    shell = build_shell(c_body, mats, sil, split=SPLIT_PARTS)
    body = next(o for o in shell if o.name == "body")
    bumper = build_rear_bumper(c_trim, mats, sil)

    xf, xr = TRACK_F / 2, TRACK_R / 2
    wheels = []
    for nm, x, y in (("wheel_FL", -xf, Y_AXF), ("wheel_FR", xf, Y_AXF),
                     ("wheel_RL", -xr, Y_AXR), ("wheel_RR", xr, Y_AXR)):
        w = _wheel_mesh(nm, c_wheels, mats)
        w.location = (x, y, TYRE_R)
        if x < 0:
            w.rotation_euler = (0, 0, math.pi)
        wheels.append(w)

    sp = _spare_mesh("spare", c_trim, mats)               # right of the plate, on the hinge side
    sp.location = (0.28, -2.29, 0.86)                     # 6.5 cm behind the gate face

    for sgn, nm in ((-1, "L"), (1, "R")):
        _mirror_mesh("mirror_" + nm, sgn, c_trim, mats)
        _rail_mesh("roofrail_" + nm, sgn, c_trim, mats)
    _mudflaps_mesh("mudflaps", c_trim, mats)
    _antenna_mesh("antenna", c_trim, mats)
    flares = _flares_mesh("flares", sil, c_trim, mats)

    for ob in list(shell) + [sp, bumper, flares] + wheels:
        _smooth(ob)

    allv = [v.co for o in shell for v in o.data.vertices]
    nv = sum(len(o.data.vertices) for o in shell)
    nf = sum(len(o.data.polygons) for o in shell)
    print("CRV shell: verts %d faces %d  |  W %.3f L %.3f Htop %.3f  |  y %.2f..%.2f" % (
        nv, nf, max(p.x for p in allv) - min(p.x for p in allv),
        max(p.y for p in allv) - min(p.y for p in allv), max(p.z for p in allv),
        max(p.y for p in allv), min(p.y for p in allv)))
    print("  parts: " + ", ".join("%s %dv" % (o.name, len(o.data.vertices)) for o in shell))
    return body


if __name__ == "__main__":
    build()
