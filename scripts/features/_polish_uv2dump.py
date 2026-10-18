r"""
Blender side of the polish feature's damage sheets (scripts/features/polish.py, COMPOSE): dump every
shell triangle with BOTH UV layouts, so the painter can work in the game's damage space.

    blender -b <root>/blender/crv_kotris.blend --python scripts/features/_polish_uv2dump.py -- <out.npz> <names>

The vehicle shader samples rust, dents, scratches and blood through texCoords1 = the mesh's SECOND UV
layer (bake_atlas writes "UVMap1": an even xatlas layout, the shell's own, not vanilla's), and the zone
Mask, the paint and the gloss through the first ("UVMap", the planar sheet). The painter rasterises
each triangle into UVMap1 and needs, per texel, where it is on the car (model metres: +X right, +Y
forward, +Z up, ground 0), which way it faces and its UVMap texel (to read the Mask's zone and gloss).

A mesh with the custom property `uv2_host` (the decals: bake_atlas._uv2_from_host gives each of its
corners the host panel's UVMap1 at the nearest host point) has no chart of its own in this layout: its
texels ARE the host's, and a decal triangle that crosses a host chart seam spans unrelated charts. It is
left out, so the host panel alone decides its texels (the decal then samples the host's damage).

Leading underscore: the feature loader never imports this file (it needs bpy); polish.COMPOSE runs it.
"""
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
NAMES = set(argv[1].split(","))

uv0s, uv1s, poss, nrms, objs, names, borrowed = [], [], [], [], [], [], []
for ob in bpy.data.objects:
    if ob.type != 'MESH' or ob.name not in NAMES:
        continue
    if ob.get("uv2_host"):
        borrowed.append(ob.name)
        continue
    me = ob.data
    if "UVMap" not in me.uv_layers or "UVMap1" not in me.uv_layers:
        print("POLISH uv2dump: %s has no UVMap / UVMap1, skipped" % ob.name)
        continue
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    if nt == 0:
        continue
    loops = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("loops", loops)
    verts = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", verts)
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    m = np.array(ob.matrix_world, dtype=np.float64)
    co = co.reshape(-1, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
    pos = co[verts].reshape(nt, 3, 3)
    n = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.maximum(ln, 1e-12)
    uv = {}
    for layer in ("UVMap", "UVMap1"):
        d = np.empty(len(me.loops) * 2, dtype=np.float32)
        me.uv_layers[layer].data.foreach_get("uv", d)
        uv[layer] = d.reshape(-1, 2)[loops].reshape(nt, 3, 2)
    uv0s.append(uv["UVMap"])
    uv1s.append(uv["UVMap1"])
    poss.append(pos.astype(np.float32))
    nrms.append(n.astype(np.float32))
    objs.append(np.full(nt, len(names), dtype=np.int16))
    names.append(ob.name)

if not names:
    raise SystemExit("POLISH uv2dump: none of the shell objects found")
np.savez_compressed(OUT, uv0=np.concatenate(uv0s), uv1=np.concatenate(uv1s), pos=np.concatenate(poss),
                    nrm=np.concatenate(nrms), obj=np.concatenate(objs), names=np.array(names))
print("POLISH uv2dump: %d objects, %d triangles, %d meshes with a borrowed UVMap1 (uv2_host) left out -> %s"
      % (len(names), sum(len(o) for o in objs), len(borrowed), OUT))
