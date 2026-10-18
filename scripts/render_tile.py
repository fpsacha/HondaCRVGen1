r"""
Render the picnic table standing on its legs as Project Zomboid 2x tile sprites (128 x 256), one
per facing.

    blender -b --factory-startup --python scripts\render_tile.py [-- --out DIR] [--model-out DIR]

Writes blender/tiles/_raw_table_S.png and _raw_table_E.png (straight alpha, no shadow);
scripts/tilepack.py hardens the alpha, normalises the top, adds the footprint shadow and packs them.
Then writes the placed table's 3D model, WorldItems/CRVGen1_TableStand.fbx and its 256 px texture
(export_fbx.export_standing_table), which spriteModels.txt draws on both tiles instead of the sprite.

Camera. The game's screen transform (screen x = (x - y) * 32, screen y = (x + y) * 16 - z * 96 at
1x) is an orthographic view at 30 degrees elevation, 45 degrees azimuth, 45.25 px per metre at 1x
(90.5 at 2x): a metre east lands 64 px right and 32 px down on the 2x canvas, a metre up 78 px up.
The game's world is left-handed on screen (y runs south), so Blender's +Y here is the game's north.
The tile's ground diamond sits in the bottom 64 px of the canvas, centre at (64, 224).

Light. Every vanilla table tile is lit from the screen's upper left, i.e. from the south-west and
high (furniture_tables_high_01_4: top 1.0, south face 0.72, east face 0.62; measured 2026-10-12),
so the sun here points up and to the south-west. Eevee, not Workbench: Workbench's studio light
favours vertical faces, and with the same upper-left direction it rendered the sides 1.38x
BRIGHTER than the top; the shipped Workbench light_direction (0.35, 0.35, 0.87) even cast the
ground shadow to the upper right, lit from the opposite side to vanilla. Absolute brightness is not
tuned here (a 0.5-albedo plane under a strength-1 sun renders 87 % of its albedo, and sun 1.15 vs
1.30 moved the top only 81.7 -> 83.1): tilepack normalises the top to the shell texel instead.

Thickness. The sprite is built with 11 mm tubes (2.0 px), a 30 mm top and an 8 mm brace, not the
real 12 / 20 / 4.5 mm: at 90.5 px/m a 1.1 px tube never reaches full alpha and breaks into dashes
once the alpha is hardened, and a 1.6 px slab shows no edge. Vanilla stylises the same way (4-6 px
wooden legs). The car part (build_table.build) keeps the real sizes.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
S = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if S not in sys.path:
    sys.path.append(S)
import build_table  # noqa: E402

OUT = os.path.join(ROOT, "blender", "tiles")
W, H = 128, 256
PX_PER_M = 90.5
UP = Vector((-0.5 / math.sqrt(2), 0.5 / math.sqrt(2), math.sqrt(3) / 2))      # screen up, world space
D = Vector((-math.sqrt(3) / 2 / math.sqrt(2), math.sqrt(3) / 2 / math.sqrt(2), -0.5))   # view direction

SPRITE_TUBE_R = 0.011                      # 2.0 px at 90.5 px/m: legs survive tilepack's alpha >= 96 unbroken (0.009 does not)
SPRITE_TOP_T = 0.030                       # 2.4 px slab edge under the top's near edges
SPRITE_BRACE_R = 0.008
FACINGS = [("S", 0.0, "_raw_table_S.png"),                  # frames under the east and west edges (as built)
           ("E", math.radians(90.0), "_raw_table_E.png")]   # model turned 90 deg: frames under north and south, legs at the side corners
SUN_DIR = Vector((-0.50, -0.55, 0.67)).normalized()         # TOWARD the sun: from the south-west, 42 deg up = the screen's upper left
SUN_ENERGY = 1.15
SUN_ANGLE = 2.0                                             # degrees; a near-point sun keeps the slab's shadow edge crisp
WORLD = (0.55, 0.30, 0.10)                                  # sky gradient zenith / horizon / ground: fills the shadowed sides

# Principled albedos, linear. The top is the shipped shell texel (Vehicles_HondaCRVGen1_Shell.png,
# the AccTable island: mean (87.6, 86.7, 86.2) sRGB, std 3.8, a flat grey at tile scale), so the
# placed table matches the one in the car; chrome is a dull metal (a mirror chrome reads as noise
# at 2 px); steel is the slot and plug, plate the hinge brackets.
MATERIALS = {"AccTable": ((0.098, 0.095, 0.093), 0.0, 0.55),
             "AccChrome": ((0.62, 0.62, 0.65), 1.0, 0.22),
             "AccSteel": ((0.03, 0.03, 0.032), 0.0, 0.50),
             "AccPlate": ((0.19, 0.19, 0.20), 0.0, 0.55)}


def _materials(me):
    """One Principled material per build_accessories.MATS slot, in MATS order (the mesh's material
    indices are positions in that list; build_table._mats() appended AccTable and AccChrome)."""
    import build_accessories as A
    for name in A.MATS:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        col, metal, rough = MATERIALS.get(name, ((0.3, 0.3, 0.3), 0.0, 0.55))
        b.inputs['Base Color'].default_value = tuple(col) + (1.0,)
        b.inputs['Metallic'].default_value = metal
        b.inputs['Roughness'].default_value = rough
        me.materials.append(m)


def _world(scene):
    """Sky gradient: TexCoord.Generated.z (the view direction) -> 0.5 z + 0.5 -> ramp ground /
    horizon / zenith -> Background. Lights the faces the sun misses so the east side is not black."""
    w = bpy.data.worlds.new("World")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Strength'].default_value = 1.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    tex = nt.nodes.new('ShaderNodeTexCoord')
    mad = nt.nodes.new('ShaderNodeMath')
    mad.operation = 'MULTIPLY_ADD'
    mad.inputs[1].default_value = 0.5
    mad.inputs[2].default_value = 0.5
    nt.links.new(tex.outputs['Generated'], sep.inputs[0])
    nt.links.new(sep.outputs['Z'], mad.inputs[0])
    nt.links.new(mad.outputs[0], ramp.inputs['Fac'])
    zen, hor, gnd = WORLD
    e = ramp.color_ramp.elements
    e[0].position, e[0].color = 0.0, (gnd,) * 3 + (1.0,)
    e[1].position, e[1].color = 0.5, (hor,) * 3 + (1.0,)
    e2 = e.new(1.0)
    e2.color = (zen,) * 3 + (1.0,)
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    nt.links.new(bg.outputs[0], out.inputs['Surface'])


def _sun(scene):
    la = bpy.data.lights.new("sun", 'SUN')
    la.energy = SUN_ENERGY
    la.angle = math.radians(SUN_ANGLE)
    ob = bpy.data.objects.new("sun", la)
    ob.rotation_euler = (-SUN_DIR).to_track_quat('-Z', 'Y').to_euler()   # a sun shines down its -Z
    ob.location = SUN_DIR * 5.0
    scene.collection.objects.link(ob)
    return ob


def _eevee(scene):
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except TypeError:
        scene.render.engine = 'BLENDER_EEVEE'
    ev = scene.eevee
    ev.taa_render_samples = 64
    ev.use_shadows = True
    ev.use_raytracing = True
    ev.use_fast_gi = True
    ev.fast_gi_method = 'AMBIENT_OCCLUSION_ONLY'
    ev.fast_gi_distance = 0.6
    scene.render.filter_size = 1.0                    # tight pixel filter: tilepack hardens the alpha anyway
    scene.view_settings.view_transform = 'Standard'   # no filmic curve between the albedo and the PNG
    scene.view_settings.look = 'None'


def main():
    out = OUT
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bm = bmesh.new()
    build_table.standing_table(bm, SPRITE_TUBE_R, SPRITE_TOP_T, SPRITE_BRACE_R)
    me = bpy.data.meshes.new("table")
    bm.to_mesh(me)
    bm.free()
    _materials(me)
    tables = []
    for facing, rot, _png in FACINGS:
        ob = bpy.data.objects.new("table_" + facing, me)
        ob.rotation_euler = (0.0, 0.0, rot)
        scene.collection.objects.link(ob)
        tables.append(ob)
    # camera: the ground centre must land at canvas (64, 224), i.e. 96 px below the frame centre
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = 'ORTHO'
    cam.data.sensor_fit = 'VERTICAL'
    cam.data.ortho_scale = H / PX_PER_M
    cam.data.clip_end = 100
    target = UP * (96.0 / PX_PER_M)
    cam.location = target - D * 20.0
    cam.rotation_euler = D.to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = W, H
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    _eevee(scene)
    _world(scene)
    _sun(scene)
    # ground-truth of the projection: where the table top's centre lands (evaluate first: a fresh
    # object's matrix_world is identity until the depsgraph runs, which printed (64, 128) once)
    bpy.context.view_layer.update()
    inv = cam.matrix_world.inverted()
    v = inv @ Vector((0.0, 0.0, build_table.HEIGHT))
    px = 64 + v.x * PX_PER_M
    py = 128 - v.y * PX_PER_M
    for (facing, _rot, png), ob in zip(FACINGS, tables):
        for other in tables:
            other.hide_render = other is not ob
        raw = os.path.join(out, png)
        scene.render.filepath = raw
        bpy.ops.render.render(write_still=True)
        print("TILE raw %s facing %s; table top centre at canvas (%.1f, %.1f), expected (64.0, %.1f)"
              % (raw, facing, px, py, 224 - build_table.HEIGHT * 78.4))
    # the placed table's 3D model and its sheet (the sprite stays: it is the fallback and the
    # click rectangle); --model-out DIR writes both there instead of the mod
    import export_fbx
    mdir = argv[argv.index("--model-out") + 1] if "--model-out" in argv else None
    export_fbx.export_standing_table(mdir, mdir)
    print("TILE DONE")


main()
