r"""
Planar-projection UVs for the shell parts, onto the sheet described by tex_layout.

    import uv_project; uv_project.assign(obj)          # inside Blender

Every face picks one of four projections by its world normal (top / side / front / rear) and maps
its corners straight from model-space metres into that region of the sheet. Both flanks land on
the same side strip (the right one mirrored), so a detail painted once shows on both sides. The
door, window, hood and tailgate objects are cut from the same shell, so their UVs line up with
the body's seamlessly.

Model space: metres, +Y front, +Z up, +X vehicle right, origin at ground level between the axles.
"""
import bpy
from mathutils import Vector

import tex_layout as L


def assign(ob, matrix=None):
    """Assign projected UVs to every face of `ob`. `matrix` maps mesh coords to model metres
    (defaults to the object's world matrix)."""
    me = ob.data
    mw = matrix if matrix is not None else ob.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    uvs = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    name = ob.name.replace("crvgen1_", "")
    for poly in me.polygons:
        n = nm @ poly.normal
        c = mw @ poly.center
        patch = None
        if name == "spare" and abs(n.y) < 0.75:
            patch = "tyre"                                 # tread and cover rim
        elif name.startswith("roofrail") or name in ("mudflaps", "antenna"):
            patch = "black"
        elif name == "bumper_rear" and abs(n.z) > 0.55:
            patch = "clad"                                 # top ledge and underside
        elif name.startswith("mirror"):
            patch = "black"
        if patch:
            for k, li in enumerate(range(poly.loop_start, poly.loop_start + poly.loop_total)):
                u, v = ((0, 0), (1, 0), (1, 1), (0, 1))[k % 4]
                uvs.data[li].uv = L.patch_uv(patch, u, v)
            continue
        region = L.project(n.x, n.y, n.z, c.y, c.x, c.z)
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            co = mw @ me.vertices[me.loops[li].vertex_index].co
            uvs.data[li].uv = L.uv_for(region, co.x, co.y, co.z)
    return uvs


def assign_all(names):
    done = []
    for n in names:
        ob = bpy.data.objects.get(n)
        if ob and ob.type == 'MESH':
            assign(ob)
            done.append(n)
    return done
