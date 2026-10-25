r"""
Project Viewpoint model pack for the CR-V's placed picnic table (polish feature).

    blender -b --factory-startup --python scripts/features/_polish_viewpoint.py

Viewpoint draws furniture tiles as flat sprites unless a model pack binds a model to the tile. The pack
format (read 2026-10-13 from the PZVoxelStudioViewpoint pack, workshop 3810302175, and the string
table of Viewpoint's PackManifest): a client Lua calls Viewpoint.ModelPacks.register(modId, manifest);
the manifest is a .properties file with id=, name=, version=, `model.<id>=<path to .obj>` (relative to
the manifest's folder) and `bind.<tileset>_<index>=<model id>,<degrees>,<x>,<y>,<z>,<scale>`; models
are Wavefront OBJ, Z up, in tile units centred on the tile, with an .mtl naming a map_Kd PNG.

This exports the shipped world model (WorldItems/CRVGen1_TableStand.fbx: 10 units per metre, Y up in
the FBX, the same mesh spriteModels.txt draws) as metres, Z up, centred on its footprint, with the
shipped texture. A tile is taken as a metre (the game's world grid; vanilla tables in the pack are
~0.67 tall). The bind's facing degrees follow spriteModels.txt and are UNVERIFIED in Viewpoint.
"""
import os
import shutil

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(HERE))   # a scratch build writes its own mod\
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
SRC = os.path.join(MOD, "common", "media", "models_X", "WorldItems", "CRVGen1_TableStand.fbx")
TEX = os.path.join(MOD, "common", "media", "textures", "WorldItems", "CRVGen1_TableStand.png")
OUT = os.path.join(MOD, "common", "media", "viewpoint", "table")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=SRC)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
for o in [o for o in bpy.context.scene.objects if o.type != 'MESH']:
    bpy.data.objects.remove(o)
ob.parent = None
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = ob.data
import numpy as np  # noqa: E402
co = np.empty(len(me.vertices) * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
size = co.max(0) - co.min(0)
k = 1.0 if size.max() < 5 else 0.1                     # the importer may or may not keep the 0.1 unit scale
co = co * k
lo, hi = co.min(0), co.max(0)
co[:, 0] -= (lo[0] + hi[0]) / 2
co[:, 1] -= (lo[1] + hi[1]) / 2
co[:, 2] -= lo[2]
me.vertices.foreach_set("co", co.ravel())
me.update()
os.makedirs(OUT, exist_ok=True)
for m in list(me.materials):
    pass
mats = list(me.materials)
me.materials.clear()
mat = bpy.data.materials.new("table")
me.materials.append(mat)
path = os.path.join(OUT, "table.obj")
bpy.ops.wm.obj_export(filepath=path, export_selected_objects=False, forward_axis='Y', up_axis='Z',
                      export_materials=False, export_normals=True, export_uv=True, apply_modifiers=True)
# our own mtl + header (the exporter writes no mtllib with export_materials off)
body = open(path, encoding="utf-8").read().splitlines()
body = [ln for ln in body if not ln.startswith(("#", "mtllib", "usemtl"))]
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write("# Honda CR-V picnic table for Project Viewpoint: metres = tile units, Z up, centred on the tile\n")
    f.write("mtllib table.mtl\nusemtl table\n")
    f.write("\n".join(body) + "\n")
with open(os.path.join(OUT, "table.mtl"), "w", encoding="utf-8", newline="\n") as f:
    f.write("newmtl table\nKd 1 1 1\nd 1\nmap_Kd texture.png\n")
shutil.copyfile(TEX, os.path.join(OUT, "texture.png"))
print("POLISH viewpoint: table %d verts, size %.3f x %.3f x %.3f m -> %s"
      % (len(me.vertices), hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], path))
