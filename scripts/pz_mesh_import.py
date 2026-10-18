r"""
Import Project Zomboid B42 vehicle meshes into Blender.

B42 ships vehicle meshes as a plain-text format ("# Project Zomboid Mesh"), NOT DirectX .X.
The DirectX X Importer extension will not read them. This does.

Usage inside Blender (or via BlenderMCP execute_code):

    import sys; sys.path.append("scripts")
    import pz_mesh_import as pz
    pz.import_pz_mesh(os.path.join(_crv_paths.GAME, "media", "models", "Vehicles_SUV.txt"))

Standalone (no Blender) to just report geometry:

    python scripts/pz_mesh_import.py <path.txt> [...]

Reference only. Vanilla geometry must never be exported into the mod.
See spec/pz-conventions.md.
"""

import os
import sys
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

PZ_MODELS = os.path.join(_crv_paths.GAME, "media", "models")


def parse_pz_mesh(path):
    """Return (verts, normals, uvs, faces). Coordinates are left in PZ space."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = [l.strip() for l in fh]

    i = 0
    stride_n = None
    stride_types = []
    vcount = fcount = None
    verts, normals, uvs, faces = [], [], [], []

    def nums(s):
        return [float(x) for x in s.split(",") if x.strip() != ""]

    while i < len(lines):
        line = lines[i]

        if line.startswith("# Vertex Stride Element Count:"):
            stride_n = int(lines[i + 1]); i += 2; continue

        if line.startswith("# Vertex Stride Data:"):
            i += 1
            while i < len(lines) and lines[i].startswith("#"):
                i += 1
            for _ in range(stride_n):
                stride_types.append(lines[i + 1])   # offset line, then type line
                i += 2
            continue

        if line.startswith("# Vertex Count:"):
            vcount = int(lines[i + 1]); i += 2; continue

        if line.startswith("# Vertex Buffer:"):
            i += 1
            for _ in range(vcount):
                for t in stride_types:
                    v = nums(lines[i]); i += 1
                    if t == "VertexArray":
                        verts.append(tuple(v[:3]))
                    elif t == "NormalArray":
                        normals.append(tuple(v[:3]))
                    elif t == "TextureCoordArray":
                        uvs.append(tuple(v[:2]))
            continue

        if line.startswith("# Number of Faces:"):
            fcount = int(lines[i + 1]); i += 2; continue

        if line.startswith("# Face Data:"):
            i += 1
            while i < len(lines) and len(faces) < fcount:
                s = lines[i]; i += 1
                if not s or s.startswith("#"):
                    continue
                idx = [int(float(x)) for x in s.replace(",", " ").split()]
                if len(idx) >= 3:
                    faces.append(tuple(idx[:3]))
            continue

        i += 1

    return verts, normals, uvs, faces


def bbox(verts):
    xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


def import_pz_mesh(path, name=None, to_blender_axes=True):
    """Build a Blender object from a PZ mesh file.

    PZ space is +X left, +Y up, +Z front (DirectX-style).
    With to_blender_axes=True the mesh is rotated into this project's Blender convention
    (+Y front, +Z up) so it can be compared against our own geometry directly:
        blender_x =  pz_x
        blender_y =  pz_z
        blender_z =  pz_y
    """
    import bpy  # noqa: F401  (only available inside Blender)

    verts, normals, uvs, faces = parse_pz_mesh(path)
    name = name or os.path.splitext(os.path.basename(path))[0]

    if to_blender_axes:
        verts = [(x, z, y) for (x, y, z) in verts]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()

    if uvs and len(uvs) == len(mesh.vertices):
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            u, v = uvs[loop.vertex_index]
            uv_layer.data[loop.index].uv = (u, 1.0 - v)   # PZ UVs are top-left origin

    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    # Reference geometry: lock it so it cannot be edited by accident.
    obj.hide_select = True
    obj.display_type = 'WIRE'
    return obj


def _report(path):
    verts, normals, uvs, faces = parse_pz_mesh(path)
    (x0, x1), (y0, y1), (z0, z1) = bbox(verts)
    print(
        f"{os.path.basename(path):34s} v={len(verts):5d} f={len(faces):5d}  "
        f"X{x1-x0:7.3f}  Y{y1-y0:7.3f}  Z{z1-z0:7.3f}   "
        f"(PZ: X=width  Y=up  Z=length)"
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = [os.path.join(PZ_MODELS, f) for f in
                ("Vehicles_SUV.txt", "Vehicles_OffRoad.txt", "Vehicles_CarNormal.txt")]
    for p in args:
        _report(p)
