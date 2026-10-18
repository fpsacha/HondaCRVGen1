r"""
Showcase renders for the Workshop gallery: the car assembled from the SHIPPED files exactly as pzview does it
(scripts, FBX, textures, poses, accessories, culling), rendered in EEVEE with a physical sky, a sun, soft shadows,
ambient occlusion and an asphalt ground, from perspective photo angles. pzview stays the game-faithful checker;
this is the brochure.

    blender -b --factory-startup --python scripts\beauty.py -- --shots FILE.json --out DIR [pzview options:
            --skin red --script HondaCRVGen1LiftAlloy --acc --acc-parts ... --rack 2 --folded --hide-models ...]

FILE.json: [[name, pose, [eye x, y, z], [look-at x, y, z], fov, {options}], ...] in metres above the ground
(Blender axes: +x the car's right, +y forward), pose a pzview pose name. Options (all optional):
  "sun": [elevation deg, azimuth deg]  the sun (default 32, 215: high over the rear left)
  "table": [x, y, rot deg]             the picnic table set up on the ground (its placed-tile model)
  "res": [w, h]                        (default 1920 x 1080)
  "interior": true                     a softer, brighter exposure for views inside the car
Writes DIR/<name>.png.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


OUT = _arg("--out")
SHOTS = _arg("--shots")
SAMPLES = int(_arg("--samples", "64"))
import pzview  # noqa: E402  (parses the same argv: --skin, --script, --acc ... apply)

U = pzview.U


def ground_z():
    return -(pzview.EXPORT_LIFT + pzview.GROUND_DROP) * U


def setup_scene():
    sc = bpy.context.scene
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            sc.render.engine = eng
            break
        except TypeError:
            continue
    ee = sc.eevee
    for attr, val in (("taa_render_samples", SAMPLES), ("use_shadows", True), ("use_raytracing", "--no-rt" not in argv),
                      ("shadow_ray_count", 2), ("shadow_step_count", 8), ("use_gtao", True), ("gtao_distance", 1.5 * U),
                      ("fast_gi_method", 'GLOBAL_ILLUMINATION'), ("use_shadow_jitter_viewport", True)):
        try:
            setattr(ee, attr, val)
        except (AttributeError, TypeError):
            pass
    try:
        sc.view_settings.view_transform = 'AgX'
        sc.view_settings.look = 'AgX - Medium High Contrast'
    except TypeError:
        sc.view_settings.view_transform = 'Filmic'
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.film_transparent = False
    # world: a physical sky
    world = bpy.data.worlds.new("beauty")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = next(n for n in nt.nodes if n.type == 'BACKGROUND')
    sky = nt.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = 'NISHITA'
        sky.sun_disc = False
        sky.air_density, sky.dust_density = 1.0, 2.0
    except (AttributeError, TypeError):
        pass
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.35
    # the ground: dark asphalt with fine grain and a little bump, out to the horizon
    me = bpy.data.meshes.new("beauty_ground")
    s = 400.0 * U
    gz = ground_z()
    me.from_pydata([(-s, -s, gz), (s, -s, gz), (s, s, gz), (-s, s, gz)], [], [(0, 1, 2, 3)])
    g = bpy.data.objects.new("beauty_ground", me)
    sc.collection.objects.link(g)
    m = bpy.data.materials.new("beauty_asphalt")
    m.use_nodes = True
    mt = m.node_tree
    bsdf = next(n for n in mt.nodes if n.type == 'BSDF_PRINCIPLED')
    noise = mt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.9 / U * 100
    noise.inputs["Detail"].default_value = 8.0
    ramp = mt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.030, 0.030, 0.032, 1)
    ramp.color_ramp.elements[1].color = (0.075, 0.074, 0.072, 1)
    mt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    mt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.92
    bump = mt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.15
    mt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    mt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    me.materials.append(m)
    # the sun
    sun = bpy.data.lights.new("beauty_sun", 'SUN')
    sun.energy = 3.2
    sun.angle = math.radians(1.5)
    so = bpy.data.objects.new("beauty_sun", sun)
    sc.collection.objects.link(so)
    cam = bpy.data.objects.new("beauty_cam", bpy.data.cameras.new("beauty_cam"))
    cam.data.clip_end = 600.0 * U
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam, so, sky, bg


def car_materials():
    """The game culls back faces: so does the brochure. The paint gets a little gloss, everything else stays
    satin (the bake already carries the shading)."""
    for png, mat in pzview._mats.items():
        tune(mat, "Shell" in os.path.basename(png))


def tune(mat, shell):
    if mat.get("beauty_tuned"):
        return
    mat["beauty_tuned"] = True
    mat.use_backface_culling = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        bsdf.inputs["Roughness"].default_value = 0.38 if shell else 0.7
        # specular scaled by the texel's brightness (and ambient occlusion): at a flat 0.45 the sills, arch walls
        # and bumper undersides (texels 20..50 grey) mirrored the bright horizon at grazing angles and drew tan,
        # and the paint read hazy. Bright paint keeps its gloss, dark plastic goes matte.
        nt = mat.node_tree
        ao = nt.nodes.new("ShaderNodeAmbientOcclusion")
        ao.inputs["Distance"].default_value = 0.6 * U
        ao.samples = 16
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = 'MULTIPLY'
        nt.links.new(ao.outputs["AO"], mul.inputs[0])
        tex = next(n for n in nt.nodes if n.type == 'TEX_IMAGE')
        lum = nt.nodes.new("ShaderNodeRGBToBW")
        ramp = nt.nodes.new("ShaderNodeMapRange")             # linear luminance 0.04 -> 0, 0.20 -> full
        ramp.inputs["From Min"].default_value = 0.04
        ramp.inputs["From Max"].default_value = 0.20
        ramp.inputs["To Max"].default_value = 0.0 if "--no-spec" in argv else (0.30 if shell else 0.15)
        nt.links.new(tex.outputs["Color"], lum.inputs[0])
        nt.links.new(lum.outputs[0], ramp.inputs["Value"])
        nt.links.new(ramp.outputs["Result"], mul.inputs[1])
        for name in ("Specular IOR Level", "Specular"):
            if name in bsdf.inputs:
                nt.links.new(mul.outputs["Value"], bsdf.inputs[name])
                break
        if "--flat" in argv:                      # debug: the raw texture, unlit
            out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
            tex = next(n for n in nt.nodes if n.type == 'TEX_IMAGE')
            em = nt.nodes.new("ShaderNodeEmission")
            nt.links.new(tex.outputs["Color"], em.inputs["Color"])
            nt.links.new(em.outputs[0], out.inputs["Surface"])
        if "--cull-shader" in argv:
            out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            tr = nt.nodes.new("ShaderNodeBsdfTransparent")
            mix = nt.nodes.new("ShaderNodeMixShader")
            nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
            nt.links.new(bsdf.outputs[0], mix.inputs[1])
            nt.links.new(tr.outputs[0], mix.inputs[2])
            nt.links.new(mix.outputs[0], out.inputs["Surface"])


def add_table(x, y, rot_deg):
    media = os.path.join(pzview.MOD, "common", "media")
    fbx = os.path.join(media, "models_X", "WorldItems", "CRVGen1_TableStand.fbx")
    png = os.path.join(media, "textures", "WorldItems", "CRVGen1_TableStand.png")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=fbx)
    new = [o for o in bpy.data.objects if o not in before]
    mat = pzview.material(png, cap=False)
    tune(mat, False)                             # satin like the car (untuned, its dark top mirrored the sky white)
    root = [o for o in new if o.parent is None]
    for o in new:
        if o.type == 'MESH':
            o.data.materials.clear()
            o.data.materials.append(mat)
    # sit it on the ground at (x, y) metres, turned rot_deg
    mesh = [o for o in new if o.type == 'MESH']
    bpy.context.view_layer.update()
    for o in root:                               # world items ship at 10 units/m (export_fbx.WORLD_UNITS_PER_M)
        o.scale = tuple(s * U / 10.0 for s in o.scale)
        o.rotation_euler.z += math.radians(rot_deg)
    bpy.context.view_layer.update()
    xs = [(o.matrix_world @ Vector(c)) for o in mesh for c in o.bound_box]
    cx, cy = sum(p.x for p in xs) / len(xs), sum(p.y for p in xs) / len(xs)
    zmin = min(p.z for p in xs)
    for o in root:
        o.location += Vector((x * U - cx, y * U - cy, ground_z() - zmin))
    return new


def aim_sun(so, sky, elev, az):
    e, a = math.radians(elev), math.radians(az)
    d = Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    so.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    try:
        sky.sun_elevation = e
        sky.sun_rotation = a - math.pi / 2
    except AttributeError:
        pass


def main():
    if not OUT or not SHOTS:
        raise SystemExit("beauty: --out DIR --shots FILE.json")
    os.makedirs(OUT, exist_ok=True)
    pzview.OUT = OUT
    bpy.ops.wm.read_factory_settings(use_empty=True)
    vehicle_mod = pzview.find_script()
    drawn, _anims = pzview.build(vehicle_mod)
    arms = [arm for (_g, arm) in pzview._imported.values()]
    dm = pzview.drive_map(vehicle_mod)
    pzview.check_driven(drawn, dm, arms)
    cam, so, sky, bg = setup_scene()
    car_materials()
    with open(SHOTS, encoding="utf-8") as f:
        shots = json.load(f)
    sc = bpy.context.scene
    table_objs = []
    current = None
    for row in shots:
        name, pose, loc, look, fov = row[:5]
        opt = row[5] if len(row) > 5 else {}
        if pose != current:
            pzview.pose(arms, dm, pose)
            current = pose
        for o in table_objs:
            bpy.data.objects.remove(o, do_unlink=True)
        table_objs = add_table(*opt["table"]) if "table" in opt else []
        elev, az = opt.get("sun", (32.0, 215.0))
        aim_sun(so, sky, elev, az)
        interior = bool(opt.get("interior"))
        bg.inputs["Strength"].default_value = 0.0 if "--no-world" in argv else (0.9 if interior else 0.35)
        so.data.energy = 0.0 if "--no-sun" in argv else (2.0 if interior else 3.2)
        sc.view_settings.exposure = float(opt.get("exposure", 0.4 if interior else 0.0))
        w, h = opt.get("res", (1920, 1080))
        sc.render.resolution_x, sc.render.resolution_y = w, h
        sc.render.resolution_percentage = 100
        pzview.aim_eye(cam, loc, look, fov)
        cam.data.clip_start = 0.02 * U
        sc.render.filepath = os.path.join(OUT, name + ".png")
        bpy.ops.render.render(write_still=True)
        print("BEAUTY wrote", sc.render.filepath)
    print("BEAUTY DONE")


main()
