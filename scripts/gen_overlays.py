r"""
Render the raw top-down masks for the mechanics-window overlay (step 1 of 2, runs in Blender).

    blender -b blender\crv_kotris.blend --python scripts\gen_overlays.py

The game draws media/ui/vehicles/mechanic overlay/<prefix><img>.png at 263x600 for the base car
and for every part in ISCarMechanicsOverlay.PartList; vanilla ships a generic set per body style
and nothing for a modded script name. This renders the CR-V's real top view, one part at a time:
an orthographic camera looks straight down, front of the car at the top, PX_PER_M pixels per metre
about the canvas centre, each named group alone as flat white on a transparent film into
blender/overlay_raw/. These masks are the MEASUREMENT, not the picture: compose_overlays.py draws
the vanilla-style schematic from cell outlines taken off them (its geometry constants) and checks
every on-car cell's centre against its mask on each build, so a moved part fails the build.
"""
import bmesh
import bpy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
if HERE and HERE not in sys.path:
    sys.path.insert(0, HERE)
import features  # noqa: E402  (scripts/features: the plugins' OVERLAYS objects, rendered for compose's align check)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
RAW = os.path.join(ROOT, "blender", "overlay_raw")
W, H = 263, 600
PX_PER_M = 93.0                      # 600 px = 6.45 m; the 4.52 m car fills 420 px

GLASS = {"Vitre", "Vitre_noir"}
LAMPS = {"Phare", "Phare_vitre", "Phare_orange"}


def _subset(name, src, pred):
    """Temporary object holding the faces of src that satisfy pred(poly)."""
    me = src.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    kill = [f for f in bm.faces if not pred(me.polygons[f.index])]
    bmesh.ops.delete(bm, geom=kill, context='FACES')
    out = bpy.data.meshes.new(name)
    bm.to_mesh(out)
    bm.free()
    ob = bpy.data.objects.new(name, out)
    ob.matrix_world = src.matrix_world.copy()
    bpy.context.scene.collection.objects.link(ob)
    return ob


def main():
    os.makedirs(RAW, exist_ok=True)
    scene = bpy.context.scene
    base = bpy.data.objects.get("base")
    if base:
        bpy.data.objects.remove(base, do_unlink=True)
    objs = {o.name: o for o in bpy.data.objects if o.type == 'MESH'}
    body = objs["body"]
    names = [m.name if m else "?" for m in body.data.materials]
    temps = {
        "window_windshield": _subset("_ws", body, lambda p: names[p.material_index] in GLASS and p.center.y > 0.25 and p.center.z > 1.05),
        "headlight_left": _subset("_hl", body, lambda p: names[p.material_index] in LAMPS and p.center.y > 1.5 and p.center.x < 0),
        "headlight_right": _subset("_hr", body, lambda p: names[p.material_index] in LAMPS and p.center.y > 1.5 and p.center.x > 0),
    }
    # doors: the outer skin only. Since v5 a door object also carries its trim panel (moved from the
    # interior), its painted inner side and the mirror; top-down they drew a ragged shape.
    for d in ("door_fl", "door_fr", "door_rl", "door_rr"):
        dm = [m.name if m else "?" for m in objs[d].data.materials]
        temps["_skin_" + d] = _subset("_skin_" + d, objs[d], lambda p, dm=dm: dm[p.material_index] in ("Body", "Body_plastique"))
    groups = {
        "base": ["body", "hood", "door_fl", "door_fr", "door_rl", "door_rr", "window_fl", "window_fr", "window_rl",
                 "window_rr", "trunk", "trunk_top", "antenna", "bay_walls"],
        "wheels": ["wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR"],
        "hood": ["hood"],
        "trunk": ["trunk"],
        "door_front_left": ["_skin_door_fl"], "door_front_right": ["_skin_door_fr"],
        "door_rear_left": ["_skin_door_rl"], "door_rear_right": ["_skin_door_rr"],
        "window_front_left": ["window_fl"], "window_front_right": ["window_fr"],
        "window_rear_left": ["window_rl"], "window_rear_right": ["window_rr"],
        "window_rear_windshield": ["trunk_top"],
        "wheel_front_left": ["wheel_FL"], "wheel_front_right": ["wheel_FR"],
        "wheel_rear_left": ["wheel_RL"], "wheel_rear_right": ["wheel_RR"],
        "engine": ["engine_block"],
        "window_windshield": ["_ws"], "headlight_left": ["_hl"], "headlight_right": ["_hr"],
        # accessories (build_accessories.py), one hit image each
        "acc_bullbar": ["acc_bullbar"], "acc_roofrack": ["acc_roofrack"],
        "acc_guard_ws": ["acc_guard_ws"], "acc_guard_rear": ["acc_guard_rear"],
        "acc_guard_fl": ["acc_guard_fl"], "acc_guard_fr": ["acc_guard_fr"],
        "acc_guard_rl": ["acc_guard_rl"], "acc_guard_rr": ["acc_guard_rr"],
        "acc_table": ["acc_table"], "acc_spare_cover": ["acc_spare_cover"],
    }
    for spec in features.overlays().values():          # feature parts drawn on the car: their mask for the align check
        if spec["objects"]:
            groups[spec["img"]] = list(spec["objects"])
    objs.update({o.name: o for o in temps.values()})
    # camera and flat white workbench
    cam_data = bpy.data.cameras.new("ovl")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = H / PX_PER_M
    cam = bpy.data.objects.new("ovl", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, 12.0)
    cam.rotation_euler = (0.0, 0.0, 0.0)          # looking down -Z, image up = +Y = the nose
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.film_transparent = True
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.display.render_aa = '8'
    sh = scene.display.shading
    sh.light = 'FLAT'
    sh.color_type = 'SINGLE'
    sh.single_color = (1.0, 1.0, 1.0)
    sh.show_shadows = False
    sh.show_cavity = False
    sh.show_object_outline = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    for name, members in groups.items():
        for o in bpy.data.objects:
            if o.type == 'MESH':
                o.hide_render = o.name not in members
        scene.render.filepath = os.path.join(RAW, name + ".png")
        bpy.ops.render.render(write_still=True)
        print("OVERLAY RAW", name)
    print("OVERLAY RAW DONE", RAW)


main()
