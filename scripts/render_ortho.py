r"""
Render the comparison set for the viewport-correction loop (PROJECT.md section 5):
orthographic side / front / rear / top plus two 3/4 perspective views, Workbench,
material colours, outlines. Reference objects are hidden from render.

    import render_ortho, importlib; importlib.reload(render_ortho)
    render_ortho.render(prefix="v3_")

Compare like against like: ortho renders against ortho-style photos only.
"""
import os

import bpy
from mathutils import Vector

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "export", "renders")


def render(prefix="", out_dir=None, views=None):
    out_dir = out_dir or DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    ref_c = bpy.data.collections.get("_reference")
    if ref_c:
        for o in ref_c.objects:
            o.hide_render = True

    cam = bpy.data.objects.get("_ortho_cam")
    if cam is None:
        cam = bpy.data.objects.new("_ortho_cam", bpy.data.cameras.new("_ortho_cam"))
        (ref_c or scene.collection).objects.link(cam)
    cam.hide_render = True
    cam.data.clip_end = 200
    prev_cam, prev_engine = scene.camera, scene.render.engine
    scene.camera = cam
    scene.render.engine = 'BLENDER_WORKBENCH'
    sh = scene.display.shading
    sh.light = os.environ.get('CRV_RENDER_LIGHT', 'STUDIO')
    sh.color_type = os.environ.get('CRV_RENDER_COLOR', 'MATERIAL')
    sh.show_object_outline, sh.show_shadows, sh.show_cavity = True, True, False
    sh.shadow_intensity = 0.35
    scene.display.render_aa = '32'
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'

    def aim(loc, target, up='Y'):
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', up).to_euler()

    T = (0, 0, 0.85)
    views = views or [
        ("side_left", 'ORTHO', (-12, 0, 0.85), T, 5.2, (1800, 900)),
        ("front",     'ORTHO', (0, 12, 0.85),  T, 2.6, (1200, 1000)),
        ("rear",      'ORTHO', (0, -12, 0.85), T, 2.6, (1200, 1000)),
        ("top",       'ORTHO', (0, 0, 12), (0, 0, 0), 5.2, (900, 1800)),
        ("persp_fl",  'PERSP', (-5.2, 6.4, 2.4), T, None, (1600, 1000)),
        ("persp_rr",  'PERSP', (5.4, -6.2, 2.3), T, None, (1600, 1000)),
    ]
    paths = []
    for name, typ, loc, target, oscale, res, *rest in views:
        cam.data.type = typ
        cam.data.sensor_width = 36
        if typ == 'ORTHO':
            cam.data.ortho_scale = oscale
        else:
            cam.data.lens = rest[0] if rest else 45       # optional 7th element: focal length mm
        aim(loc, target)
        scene.render.resolution_x, scene.render.resolution_y = res
        pth = os.path.join(out_dir, prefix + name + ".png")
        scene.render.filepath = pth
        bpy.ops.render.render(write_still=True)
        paths.append(pth)

    scene.render.engine = prev_engine
    if prev_cam:
        scene.camera = prev_cam
    return paths
