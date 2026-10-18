"""Engine bay v2 (spec/engine-bay-v2.md): the kit, the envelope and one module per part group.

Blender side: kit.py, envelope.py and the group modules (engine, intake, front, sides) import bpy.
System-Python side: painting.py and the paint_<group>.py modules (Pillow only), run by
scripts/paint_bay_decals.py. Keep this file free of imports so both sides can load the package.
"""
GROUPS = ("engine", "intake", "front", "sides")
