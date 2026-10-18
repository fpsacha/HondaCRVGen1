r"""
Cabin interior for the CR-V: the shell you see through the glass and through an open door.

    import build_interior, importlib; importlib.reload(build_interior); build_interior.build()

KI5 ships the interior as one object of about 650 verts (spec/pz-conventions.md section 7), which
is roughly the budget here. It is a single inward-facing shell offset inside the body, plus a
dashboard, four seats and a wheel. Without it every opening panel reveals empty space, because the
body is back-face culled.

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import math
import os

import bpy

from build_body import SLOT, _coll, _ensure_mats, _mesh_obj, _purge
import build_body_hull as bh

NAME = "interior"
PARTS = [NAME]

Y_DASH, Y_BACK = 0.86, -1.96          # cabin ends: bulkhead under the windscreen, boot rear wall
Z_FLOOR_IN = 0.36                     # cabin floor above the underbody
Z_HEAD = 1.53                         # headliner
INSET = 0.055                         # how far the trim sits inside the outer skin
STEP = 0.16                           # ring spacing along the cabin

SEAT_X = 0.36                         # seat centres either side
SEAT_F, SEAT_R = 0.18, -0.86          # front and rear seat cushion centres
CUSHION = (0.50, 0.50, 0.12)
BACK = (0.50, 0.13, 0.58)
Z_CUSHION = 0.62


def _inner(sil, y, z):
    """Half-width of the trimmed cabin at (y, z)."""
    w = min(sil.top(y), sil.front(z)) - INSET
    return max(w, 0.02)


def _ring(sil, y):
    """Half section of the cabin, floor centre up to the headliner centre."""
    z_top = min(Z_HEAD, sil.side(y)[0] - 0.10)
    rows = [(0.0, Z_FLOOR_IN)]
    for z in (Z_FLOOR_IN, 0.60, 0.85, 1.06, 1.30, z_top):
        if z <= z_top:
            rows.append((_inner(sil, y, z), z))
    rows.append((0.0, z_top))
    return [(w, y, z) for w, z in rows]


def _shell(sil, verts, faces, mats):
    ys = []
    y = Y_DASH
    while y >= Y_BACK:
        ys.append(round(y, 3)); y -= STEP
    ys.append(Y_BACK)
    rings = [_ring(sil, v) for v in ys]
    n = len(rings[0])
    ring = 2 * n - 2
    base = len(verts)
    for h in rings:
        right = [(w, yy, z) for (w, yy, z) in h]
        left = [(-w, yy, z) for (w, yy, z) in reversed(h[1:-1])]
        verts.extend(right + left)
    for s in range(len(rings) - 1):
        a, b = base + s * ring, base + (s + 1) * ring
        for k in range(ring):
            k2 = (k + 1) % ring
            faces.append((b + k, b + k2, a + k2, a + k))    # wound to face inward
            zc = (verts[a + k][2] + verts[b + k2][2]) / 2
            mats.append(SLOT["black"] if zc > 1.20 or zc < 0.45 else SLOT["cladding"])
    # end walls, also inward
    for idx, sign in ((0, 1), (len(rings) - 1, -1)):
        a = base + idx * ring
        cen = len(verts)
        yy = rings[idx][0][1]
        verts.append((0.0, yy, (Z_FLOOR_IN + Z_HEAD) / 2))
        for k in range(ring):
            k2 = (k + 1) % ring
            tri = (cen, a + k, a + k2) if sign > 0 else (cen, a + k2, a + k)
            faces.append(tri)
            mats.append(SLOT["cladding"])


def _box(verts, faces, mats, size, loc, slot, tilt=0.0):
    sx, sy, sz = [v / 2 for v in size]
    pts = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
           (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    c, s = math.cos(tilt), math.sin(tilt)
    base = len(verts)
    for (x, y, z) in pts:
        verts.append((x + loc[0], y * c - z * s + loc[1], y * s + z * c + loc[2]))
    for f in [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]:
        faces.append(tuple(base + i for i in f))
        mats.append(slot)


def _wheel(verts, faces, mats, centre, r=0.17, tube=0.022, seg=14, ring=6):
    """Steering wheel: a torus lying in a plane tilted back from vertical."""
    tilt = math.radians(28)
    base = len(verts)
    for i in range(seg):
        a = 2 * math.pi * i / seg
        cx, cz = r * math.cos(a), r * math.sin(a)
        for j in range(ring):
            b = 2 * math.pi * j / ring
            rr, yy = tube * math.cos(b), tube * math.sin(b)
            x = cx + rr * math.cos(a)
            z = cz + rr * math.sin(a)
            verts.append((centre[0] + x,
                          centre[1] + yy * math.cos(tilt) - z * math.sin(tilt),
                          centre[2] + yy * math.sin(tilt) + z * math.cos(tilt)))
    for i in range(seg):
        i2 = (i + 1) % seg
        for j in range(ring):
            j2 = (j + 1) % ring
            faces.append((base + i * ring + j, base + i * ring + j2,
                          base + i2 * ring + j2, base + i2 * ring + j))
            mats.append(SLOT["black"])


def build(coll=None, mats=None):
    sil = bh.Sil()
    mats = mats or _ensure_mats()
    coll = coll or _coll("interior")
    _purge(PARTS)
    verts, faces, mi = [], [], []
    _shell(sil, verts, faces, mi)
    _box(verts, faces, mi, (1.44, 0.34, 0.26), (0.0, 0.66, 1.00), SLOT["black"])          # dash
    _box(verts, faces, mi, (1.40, 0.10, 0.09), (0.0, 0.50, 1.10), SLOT["cladding"])       # dash top
    for x in (-SEAT_X, SEAT_X):
        for y in (SEAT_F, SEAT_R):
            _box(verts, faces, mi, CUSHION, (x, y, Z_CUSHION), SLOT["cladding"])
            _box(verts, faces, mi, BACK, (x, y - 0.26, Z_CUSHION + 0.30), SLOT["cladding"],
                 tilt=math.radians(-12))
    _wheel(verts, faces, mi, (-0.36, 0.50, 1.13))
    _box(verts, faces, mi, (0.06, 0.16, 0.06), (-0.36, 0.58, 1.05), SLOT["black"])        # column
    ob = _mesh_obj(NAME, verts, faces, mi, coll, mats)
    print("CRV interior: verts %d faces %d" % (len(ob.data.vertices), len(ob.data.polygons)))
    return ob


if __name__ == "__main__":
    build()
