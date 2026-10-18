r"""
Side glass as real panes: rounded outlines sitting proud of the body over cut apertures.

    import build_glass, importlib; importlib.reload(build_glass); build_glass.build()

The loft cannot draw a rounded window corner - its faces are 6 cm by 20 cm. So the side glass is
not loft faces any more. build_body_hull cuts an aperture (faces fully inside the pane outline are
dropped, faces along the edge stay and turn black) and this module lays a pane over it: a black
seal 3 mm proud of the skin and the glass 7 mm proud, both following the body's tumblehome. The
outlines are the ones the photographs give (spec/decisions.md 2026-09-05): a vertical front edge
on the front door up to z 1.31, a 37-degree diagonal into a 9 cm radius at the top front, 4-5 cm
radii elsewhere, straight tops along the drip rail.

Door panes become the window_* objects the rig slides down. The quarter panes are fixed and are
joined into the body.

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import math

import bpy

from build_body import SLOT, _coll, _ensure_mats, _mesh_obj, _purge
import build_body_hull as bh
from build_body_hull import round_polygon, offset_polygon

PROUD_SEAL, PROUD_GLASS = 0.006, 0.011
Z_GLASS_BASE = 1.135                  # just above the belt step row (1.13)
SEAL_W = 0.022                        # black seal visible around the glass
ARC_SEG = 4                           # segments per rounded corner


def _pane_mesh(sil, outline, side, proud, verts, faces, mats, slot):
    """Fan-triangulate a (y, z) outline onto the body surface, `proud` metres outboard."""
    pts = round_polygon(outline)
    cy = sum(p[0] for p in pts) / len(pts)
    cz = sum(p[1] for p in pts) / len(pts)

    def x_at(y, z):
        # never seat a pane on the door shoulder below the belt step: the seal's lower edge would
        # sit 4 cm outboard of the glass and its triangles would bulge through it
        return side * (bh.skin_x(sil, y, max(z, Z_GLASS_BASE)) + proud)
    base = len(verts)
    verts.append((x_at(cy, cz), cy, cz))
    for (y, z) in pts:
        verts.append((x_at(y, z), y, z))
    n = len(pts)
    for i in range(n):
        a, b = base + 1 + i, base + 1 + (i + 1) % n
        tri = (base, a, b) if side > 0 else (base, b, a)
        faces.append(tri)
        mats.append(slot)


def pane_object(name, sil, outline, side, coll, mats):
    verts, faces, mi = [], [], []
    _pane_mesh(sil, offset_polygon(outline, SEAL_W), side, PROUD_SEAL, verts, faces, mi, SLOT["black"])
    _pane_mesh(sil, outline, side, PROUD_GLASS, verts, faces, mi, SLOT["glass"])
    return _mesh_obj(name, verts, faces, mi, coll, mats)


def _join(target, others):
    bpy.ops.object.select_all(action='DESELECT')
    for o in others:
        o.select_set(True)
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.join()


def build(coll=None, mats=None):
    sil = bh.Sil()
    mats = mats or _ensure_mats()
    coll = coll or _coll("body")
    _purge(["window_fl", "window_fr", "window_rl", "window_rr"])
    out = {}
    for side, tag in ((-1, "l"), (1, "r")):
        out["window_f" + tag] = pane_object("window_f" + tag, sil, bh.PANE_FRONT, side, coll, mats)
        out["window_r" + tag] = pane_object("window_r" + tag, sil, bh.PANE_REAR, side, coll, mats)
    body = bpy.data.objects.get("body")
    if body is not None:
        quarters = [pane_object("_quarter_%s" % tag, sil, bh.PANE_QUARTER, side, coll, mats)
                    for side, tag in ((-1, "l"), (1, "r"))]
        _join(body, quarters)
    nv = sum(len(o.data.vertices) for o in out.values())
    print("CRV glass: %d door panes, %d verts; quarter panes joined into the body" % (len(out), nv))
    return out


if __name__ == "__main__":
    build()
