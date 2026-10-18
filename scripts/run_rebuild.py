r"""
Rebuild the parts blend from the imported kotris base: split, engine bay, liners and bay walls, cabin
furniture, prep, the accessories, then every feature plugin's BUILD (scripts/features).

    blender -b blender\import\base_honda_cr-v_2001.blend --python scripts\run_rebuild.py

Writes blender\import\parts_kotris.blend (the bake's input).
"""
import os
import sys

import bpy

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))   # data root (build.py: CRV_ROOT)
# this checkout's own scripts (Blender's --python sets __file__): a worktree rebuilds with its own code
S = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if S not in sys.path:
    sys.path.append(S)
def _run(name, **extra):
    g = {"__name__": "run"}
    g.update(extra)
    exec(compile(open(os.path.join(S, name), encoding="utf-8").read(), name, "exec"), g)


_run("split_base.py")
_run("build_liners.py")                                  # bay walls and towers first: the bay's audit reads them
_run("build_bay.py")                                      # engine bay v2: final poly count, no twin (self bake)
_run("build_cabin.py")                                    # cabin furniture, full detail: the bake source (+ its decals)
full = bpy.data.objects.get("cabin")
if full is not None:
    full.name = "cabin_full"
_run("build_cabin.py", CABIN_LOW=True)                    # coarse: what ships
_run("prep_parts.py")
_run("build_accessories.py")                             # bull bar, roof rack, window guards (on the low parts)
_run("build_table.py")                                   # picnic table in the cargo floor and the well under it
import features  # noqa: E402  (scripts/features: each feature's BUILD makes the meshes its OBJECTS declare)
for feat in features.load():
    if hasattr(feat, "BUILD"):
        feat.BUILD(print)
missing = [n for n in features.objects() if n not in bpy.data.objects]
if missing:
    raise RuntimeError("FEATURE objects declared but not built: " + ", ".join(missing))   # a Traceback stops build.py
if features.load():
    print("FEATURES built: %s (%d objects)" % (", ".join(features.keys()), len(features.objects())))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT, "blender", "import", "parts_kotris.blend"))
print("REBUILD DONE")
