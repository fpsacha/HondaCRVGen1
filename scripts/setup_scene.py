r"""
Build blender/crv.blend: an empty, correctly-configured starting scene.

Run headless:
    blender.exe --background --factory-startup --python scripts/setup_scene.py

Creates:
  - metric scene, real-world scale
  - collections matching the PROJECT.md section 6 part list
  - the vanilla PZ SUV imported as a locked wireframe, un-squashed back to real metres,
    so our geometry can be eyeballed against something known-good
  - a wireframe box at the CR-V's real overall dimensions, as a blockout target

Blender convention here (PROJECT.md section 6): +Y front, +Z up, metres.
PZ convention (spec/pz-conventions.md): +X left, +Y up, +Z front, game units.
"""

import os
import sys

import bpy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(PROJECT, "scripts"))

import pz_mesh_import as pz  # noqa: E402

VANILLA_SUV = os.path.join(_crv_paths.GAME, "media", "models", "Vehicles_SUV.txt")
OUT = os.path.join(PROJECT, "blender", "crv.blend")

# PZ game units per real metre — see spec/pz-conventions.md section 4.
# Non-uniform: PZ squashes vehicles vertically for the fixed iso camera.
S_WIDTH, S_HEIGHT, S_LENGTH = 0.52, 0.36, 0.47

# Real RD1 overall dimensions, metres. Book values — replace once the car is measured.
CRV_L, CRV_W, CRV_H = 4.51, 1.75, 1.68

COLLECTIONS = ["body", "doors", "wheels", "glass", "trim", "_reference"]


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_units():
    s = bpy.context.scene
    s.unit_settings.system = 'METRIC'
    s.unit_settings.length_unit = 'METERS'
    s.unit_settings.scale_length = 1.0


def make_collections():
    out = {}
    for name in COLLECTIONS:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
        out[name] = c
    return out


def link_only(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def import_vanilla_reference(coll):
    """Vanilla SUV, converted to Blender axes and un-squashed back to real metres."""
    if not os.path.exists(VANILLA_SUV):
        print(f"CRV: vanilla reference not found at {VANILLA_SUV} — skipping")
        return None

    obj = pz.import_pz_mesh(VANILLA_SUV, name="_ref_vanilla_SUV", to_blender_axes=True)
    # After axis conversion: Blender X = PZ width, Y = PZ length, Z = PZ height.
    obj.scale = (1.0 / S_WIDTH, 1.0 / S_LENGTH, 1.0 / S_HEIGHT)

    # Sit it on the ground so ride height is comparable.
    bpy.context.view_layer.update()
    zs = [(obj.matrix_world @ v.co).z for v in obj.data.vertices]
    obj.location.z -= min(zs)

    link_only(obj, coll)
    obj.hide_select = True
    print(f"CRV: vanilla SUV reference imported ({len(obj.data.vertices)} verts), "
          f"un-squashed to real metres")
    return obj


def make_target_box(coll):
    """Wireframe box at the CR-V's real overall dimensions. Blockout target."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, CRV_H / 2.0))
    box = bpy.context.active_object
    box.name = "_ref_CRV_envelope"
    box.scale = (CRV_W, CRV_L, CRV_H)
    box.display_type = 'WIRE'
    box.hide_select = True
    box.hide_render = True
    link_only(box, coll)
    print(f"CRV: envelope box {CRV_W} W x {CRV_L} L x {CRV_H} H (metres)")
    return box


def main():
    clear()
    setup_units()
    colls = make_collections()
    import_vanilla_reference(colls["_reference"])
    make_target_box(colls["_reference"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print(f"CRV: saved {OUT}")


main()
