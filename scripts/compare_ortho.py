r"""
Render the model in exactly the blueprint's framing, so ortho can be compared with ortho.

The three blueprint crops (blender/references/blueprints/bp_side.png, bp_front.png, bp_top.png)
are 290.4 px per metre with a known world anchor (see setup in spec/retrospective-2026-09-04.md).
This renders side / front / top with an orthographic camera at the same px/m, same image size and
same world centre, white-on-black, so scripts/ortho_diff.py can overlay and score them.

    import compare_ortho, importlib; importlib.reload(compare_ortho)
    compare_ortho.render_all(prefix="v8_")
"""
import math
import os

import bpy

import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "export", "ortho_cmp")
CAL_PATH = os.path.join(ROOT, "blender", "references", "blueprints", "calibration.json")
Y_AXF = 1.31                                     # front axle in model space


def views_from_calibration():
    """Image size, world centre and camera rotation per view, derived from calibration.json
    (preview px/m, crop boxes, and the anchor pixel = front axle / centreline / ground).
    Camera looks down its local -Z; local +X = image right, local +Y = image up."""
    cal = json.load(open(CAL_PATH))
    up, pxm = cal["up"], cal["pxm_preview"] * cal["up"]
    out = {}
    for name in ("side", "front", "top"):
        x0, y0, x1, y1 = cal["crops"][name]
        w, h = (x1 - x0) * up, (y1 - y0) * up
        a = cal[name]
        ax = (a.get("front_axle_x", a.get("centre_x")) - x0) * up
        ay = (a.get("ground_y", a.get("centre_y")) - y0) * up
        du, dv = (ax - w / 2) / pxm, (h / 2 - ay) / pxm    # anchor offset from image centre, metres
        vs = a.get("vscale", 1.0)                          # drawn height -> model height
        if name == "side":       # +u = -Y, +v = +Z
            out[name] = ((w, h), (-12.0, Y_AXF + du, 0.0 - dv), (90, 0, -90), 1.0)
        elif name == "front":    # +u = -X, +v = +Z
            out[name] = ((w, h), (0.0 + du, 12.0, 0.0 - dv * vs), (90, 0, 180), 1.0 / vs)
        else:                    # +u = -Y, +v = +X
            out[name] = ((w, h), (0.0 - dv, Y_AXF + du, 12.0), (0, 0, -90), 1.0)
    return pxm, out


def _cam():
    scene = bpy.context.scene
    cam = bpy.data.objects.get("_cmp_cam")
    if cam is None:
        cam = bpy.data.objects.new("_cmp_cam", bpy.data.cameras.new("_cmp_cam"))
        coll = bpy.data.collections.get("_reference") or scene.collection
        coll.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.clip_end = 200
    cam.hide_render = True
    return cam


def render_all(prefix="", out_dir=None, views=None):
    pxm, cal_views = views_from_calibration()
    views = views or cal_views
    out_dir = out_dir or DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    cam = _cam()
    prev = (scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y,
            scene.display.shading.light, scene.display.shading.color_type, tuple(scene.display.shading.single_color))
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light, sh.color_type, sh.single_color = 'FLAT', 'SINGLE', (1.0, 1.0, 1.0)
    sh.show_object_outline, sh.show_cavity, sh.show_shadows = False, False, False
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    world_prev = scene.world.color[:] if scene.world else None
    if scene.world:
        scene.world.color = (0, 0, 0)

    paths = []
    for name in views:
        (w, h), loc, rot, aspect_y = views[name]
        scene.render.pixel_aspect_y = aspect_y
        cam.location = loc
        cam.rotation_euler = tuple(math.radians(a) for a in rot)
        cam.data.ortho_scale = w / pxm               # ortho_scale spans the image width
        scene.render.resolution_x, scene.render.resolution_y = w, h
        p = os.path.join(out_dir, "%s%s.png" % (prefix, name))
        scene.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)

    scene.render.pixel_aspect_y = 1.0
    scene.camera, scene.render.engine, scene.render.resolution_x, scene.render.resolution_y = prev[:4]
    sh.light, sh.color_type, sh.single_color = prev[4], prev[5], prev[6]
    if scene.world and world_prev:
        scene.world.color = world_prev
    return paths
