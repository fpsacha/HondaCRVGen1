r"""
UVs for the wheel onto its own sheet (tex_layout.WHEEL_*): the rim face is a polar map with the
hub at the centre, the tread runs along a strip. Runs inside Blender.

    import wheel_uv; wheel_uv.assign(obj)

The wheel mesh is a lathe around its local X (build_body._wheel_mesh); by the time the exporter
calls this the object's placement has been folded into the mesh, so the hub is found from the
bounding box rather than assumed at the origin.
"""
import math

import bpy

import tex_layout as L


def assign(ob, r_tyre=0.334):
    me = ob.data
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    hub = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    uvs = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        n = poly.normal
        loops = list(range(poly.loop_start, poly.loop_start + poly.loop_total))
        if abs(n.x) > 0.6:                                 # rim face, inner face, sidewall cone
            for li in loops:
                co = me.vertices[me.loops[li].vertex_index].co
                uvs.data[li].uv = L.wheel_face_uv(co.y - hub[1], co.z - hub[2], r_tyre)
        else:                                              # tread: unwrap around the axle
            angs = []
            for li in loops:
                co = me.vertices[me.loops[li].vertex_index].co
                angs.append(math.atan2(co.z - hub[2], co.y - hub[1]) % (2 * math.pi))
            # keep the quad from wrapping across the seam
            if max(angs) - min(angs) > math.pi:
                angs = [a + 2 * math.pi if a < math.pi else a for a in angs]
            for li, a in zip(loops, angs):
                co = me.vertices[me.loops[li].vertex_index].co
                t = (co.x - hub[0]) / max(max(xs) - min(xs), 1e-6) + 0.5
                uvs.data[li].uv = L.wheel_tread_uv(min(a, 2 * math.pi), min(max(t, 0.0), 1.0))
    return uvs
