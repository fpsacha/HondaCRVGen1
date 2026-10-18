r"""
Export the CR-V to the FBX layout Project Zomboid B42 loads, matching KI5's files.

    import export_fbx, importlib; importlib.reload(export_fbx); export_fbx.export_all()

Every number here was measured, not guessed, by importing KI5's shipped
`Vehicles_89fordBronco_Body.fbx` with Blender's DEFAULT FBX settings (scripts/probe notes in
spec/pz-conventions.md section 7):

  * `89bronco_hood`    lands at Y +0.0075..+0.0219  -> the nose is on **+Y**
  * `89bronco_door_fl` lands at X -0.0120..-0.0075  -> the left side is on **-X**
  * body Z -0.0032..+0.0101                          -> up is **+Z**

That is exactly this project's Blender convention, so the default import is the identity for us,
and therefore the DEFAULT export settings write the axis layout the game expects. This settles the
"UNVERIFIED" note in spec/pz-conventions.md section 3: no axis_forward / axis_up override.

Scale, from the same file: the Bronco body spans 0.04335 along Y for a 4.59 m truck, i.e.
**0.00944 units per metre horizontally**, and 0.01334 in Z for 1.87 m, i.e. 0.00713 per metre.
The ratio 0.755 is the vertical squash PZ vehicles use for the fixed isometric camera, and it
agrees with the 0.72-0.75 derived independently from the vanilla SUV.

KI5 bakes the squash into the mesh and leaves a **uniform** object scale, so this does the same:
mesh Z is multiplied by 0.755, then every object carries scale 0.00944.
"""
import math
import os

import bpy
from mathutils import Matrix, Vector

import build_body_hull as bh
import build_interior
import features                       # scripts/features: the plugins' meshes (OBJECTS file body / wheel) and EXPORT hooks
import rig_vehicle
import uv_atlas
import uv_project
import wheel_uv

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1",
                       "common", "media", "models_X", "vehicles")
PREFIX = "crvgen1_"
MODEL_NAME = "Vehicles_HondaCRVGen1"

UNITS_PER_M = 0.5                     # raw vertex units per metre, with model scripts at scale 1 / UNITS_PER_M
                                      # (gen_scripts.SCALE "2.0"). Baked into the VERTICES, not the node: the game
                                      # ignores node transforms in the rigged body file (first load: the metre-sized
                                      # interior rendered 10x too small under a 0.944 node scale). Any units work in
                                      # game (KI5 ships 10/m at 0.1, the vanilla Martin 100/m at 0.01); 0.5 is for
                                      # Project Viewpoint: the game computes ModelMesh.minXyz / maxXyz only for STATIC
                                      # meshes (ProcessedAiScene.applyToMesh), so Viewpoint culls every skinned part
                                      # (doors, windows, hood, gate) with a sphere at the model's origin of radius
                                      # 2 x the model matrix's scale (ModelDraws.bounds): 0.1 x 0.9 -> 0.18 m at the
                                      # car's centre, and the doors vanished whenever the middle of the car was off
                                      # screen (feedback, 2026-10-18). At 2.0 x 0.9 the sphere is 3.6 m: the whole car.
WORLD_UNITS_PER_M = 10.0              # world items (the picnic table FBXs): scale 0.1 + undoCoreScale, unchanged
SQUASH = 1.0                          # no vertical squash: KI5 meshes are 10 units/m in every axis (the Bronco's
                                      # apparent 0.755 was its mesh stopping at the rocker, not a squash)
ORIGIN_Z = 0.80                       # model-space height that becomes the FBX origin (Bronco: 0.39 m above its rocker)
NODE_SCALE = 1.0                      # identity nodes: KI5 files carry no Lcl Scaling at all, the vertices are the size

# what goes in the body file, and what rides the armature
ACCESSORIES = ["acc_bullbar", "acc_roofrack", "acc_guard_ws", "acc_guard_rear",      # build_accessories.py: each its
               "acc_guard_fl", "acc_guard_fr", "acc_guard_rl", "acc_guard_rr",       # own geometry, shown per part
               "acc_rack_load1", "acc_rack_load2", "acc_rack_load3",                 # rack cargo states (static, Lua-toggled)
               "acc_table",                                                          # build_table.py
               "acc_spare_cover"]                                                    # rides trunk_bone
ACCESSORIES += features.body_objects()                                               # the feature plugins' meshes
WORLD_ITEMS_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "models_X", "WorldItems")
# "cabin" (build_cabin.py): its own geometry crvgen1_cabin like the interior, on the interior sheet
BODY_OBJECTS = (bh.SHELL_PARTS + [build_interior.NAME, "cabin", "bumper_rear", "engine_block", "arch_liners", "bay_walls",
                                  "mirror_L", "mirror_R", "roofrail_L", "roofrail_R", "mudflaps", "antenna", "flares"]
                + ACCESSORIES)
WHEEL_OBJECTS = ["wheel_FR"]          # one wheel; the game mirrors and repeats it
WHEEL_OBJECTS += features.wheel_objects()   # feature wheels (wheel_<key>_*: the lifted car's tyres), same file, own hub
SHEET_OBJECTS = set(bh.SHELL_PARTS + ["bumper_rear", "engine_block", "arch_liners", "bay_walls", "mirror_L", "mirror_R",
                                      "roofrail_L", "roofrail_R", "mudflaps", "antenna", "flares"] + ACCESSORIES)
STATIC_INTO_BODY = {"bumper_rear", "arch_liners", "bay_walls", "mirror_L", "mirror_R", "roofrail_L", "roofrail_R", "mudflaps", "antenna", "flares"}
ANIMATED = set(rig_vehicle.SKIN) - {"body"}   # KI5: the body is a plain static mesh; only the panels ride bones
STATIC_MATERIAL = "crvgen1_static"


def _single_material(ob):
    """One material slot per mesh. Assimp emits one aiMesh per material, all carrying the geometry
    name, and the game takes the first one it finds under that name: with 26 kotris slots the body
    came through as its first slot's handful of faces (an indicator lamp), everything else vanished."""
    me = ob.data
    mat = bpy.data.materials.get(STATIC_MATERIAL) or bpy.data.materials.new(STATIC_MATERIAL)
    me.materials.clear()
    me.materials.append(mat)
    for poly in me.polygons:
        poly.material_index = 0


GLASS_MATS = ("Vitre", "Vitre_noir")


def _inner_glass(ob):
    """An inward-facing copy of every pane (2026-10-18). Panes are single-sided and every renderer here culls
    back faces, Project Viewpoint included (ModelPass.cull), so from the seats no window had glass: no tint,
    they read as open. The copy shares the pane's texels (same window zone: Viewpoint draws it at its glass
    opacity, an open or removed window discards it with the pane) and its bone weights (a door glass winds
    down with it); its corner normals are the pane's, negated. From outside it faces away and is culled."""
    import bmesh
    me = ob.data
    names = [m.name if m else "" for m in me.materials]
    if not any(n in GLASS_MATS for n in names):
        return 0
    before = [tuple(c.vector) for c in me.corner_normals]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    src = [f for f in bm.faces if f.material_index < len(names) and names[f.material_index] in GLASS_MATS]
    if not src:
        bm.free()
        return 0
    n_old = len(bm.faces)
    old_loops = sum(len(f.loops) for f in bm.faces)
    dup = bmesh.ops.duplicate(bm, geom=src)
    fmap = {new: old for old, new in dup["face_map"].items() if isinstance(new, bmesh.types.BMFace)}
    new_faces = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)]
    vback = {new: old for old, new in dup["vert_map"].items()}
    bmesh.ops.reverse_faces(bm, faces=new_faces)
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    # the pane's corner normal per (source face, source vertex), negated for the copy
    loop_index = {}
    i = 0
    for f in sorted(bm.faces, key=lambda f: f.index)[:n_old]:
        for lp in f.loops:
            loop_index[(f.index, lp.vert.index)] = i
            i += 1
    copy_normals = []
    for f in sorted(new_faces, key=lambda f: f.index):
        s = fmap[f]
        for lp in f.loops:
            sv = vback[lp.vert]
            j = loop_index.get((s.index, sv.index))
            n = before[j] if j is not None and j < len(before) else tuple(-c for c in s.normal)
            copy_normals.append(tuple(-c for c in n))
    bm.to_mesh(me)
    bm.free()
    me.update()
    normals = list(before[:old_loops]) + copy_normals
    if len(normals) == len(me.loops):
        me.normals_split_custom_set(normals)
    return len(new_faces)


def _unskin(ob):
    for m in list(ob.modifiers):
        if m.type == 'ARMATURE':
            ob.modifiers.remove(m)
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    if ob.parent is not None:
        mw = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = mw


def _bake_body(ob):
    """Model metres -> game vertex units, squashed, origin dropped to ORIGIN_Z."""
    for v in ob.data.vertices:
        v.co.x *= UNITS_PER_M
        v.co.y *= UNITS_PER_M
        v.co.z = (v.co.z - ORIGIN_Z) * SQUASH * UNITS_PER_M


def _bake_wheel(ob):
    """KI5 wheels are round, unsquashed and centred on the hub; the script places them."""
    me = ob.data
    lo = Vector((min(v.co.x for v in me.vertices), min(v.co.y for v in me.vertices), min(v.co.z for v in me.vertices)))
    hi = Vector((max(v.co.x for v in me.vertices), max(v.co.y for v in me.vertices), max(v.co.z for v in me.vertices)))
    centre = (lo + hi) / 2
    for v in me.vertices:
        v.co = (v.co - centre) * UNITS_PER_M


def _squash_bones(arm):
    prev = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for b in arm.data.edit_bones:
        h, t = b.head.copy(), b.tail.copy()
        for p in (h, t):
            p.x *= UNITS_PER_M
            p.y *= UNITS_PER_M
            p.z = (p.z - ORIGIN_Z) * SQUASH * UNITS_PER_M
        if b.name == "body_bone":                          # KI5 keeps the root bone at the FBX origin with NO rotation:
            h, t = h * 0.0, h * 0.0                        # a Blender bone along +Y exports as identity under the
            t.y = 0.3 * UNITS_PER_M                        # armature's axis conversion, so an unkeyed root = rest pose
        if (t - h).length < 1e-6 * UNITS_PER_M:            # a purely vertical bone can collapse
            t = h + (b.tail - b.head).normalized() * 0.005 * UNITS_PER_M
        b.head, b.tail = h, t
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = prev


def _scale_clip_translations():
    """The clips key bone translations in metres (rig_vehicle: windows slide 0.40-0.44 m) but
    _squash_bones puts the skeleton at UNITS_PER_M units per metre, and Blender never rescales
    action keys: the windows shipped dropping 0.44 FILE units = 4.4 cm (research, 2026-10-12;
    KI5 windows drop 4.4-4.8 file units). Scale every location key of the panel clips to match."""
    n = 0
    for clip in rig_vehicle.CLIPS:
        act = bpy.data.actions.get(clip)
        if act is None:
            continue
        for fc in _fcurves(act):
            if fc.data_path.endswith(".location") or fc.data_path == "location":
                for kp in fc.keyframe_points:
                    kp.co.y *= UNITS_PER_M
                    kp.handle_left.y *= UNITS_PER_M
                    kp.handle_right.y *= UNITS_PER_M
                n += 1
    print("EXPORT clip translations scaled x%g on %d location curves" % (UNITS_PER_M, n))
    return n


def _fcurves(act):
    """Action f-curves, also through Blender 4.4+ layered actions (layers -> strips -> channelbags)."""
    if getattr(act, "fcurves", None) is not None and len(act.fcurves):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", []):
                out.extend(bag.fcurves)
    return out


def _place(ob):
    ob.scale = (NODE_SCALE, NODE_SCALE, NODE_SCALE)
    ob.location = (0.0, 0.0, 0.0)
    ob.rotation_euler = (0.0, 0.0, 0.0)


def _bake_transform(ob):
    """Fold the object's own placement into its vertices; _place() then owns the transform."""
    ob.data.transform(ob.matrix_basis)
    ob.matrix_basis = Matrix.Identity(4)


# Meshes the script draws with the game's `vehiclewheel` shader (gen_scripts: interior, engine,
# wheels). The game binds vertex attributes by position in the mesh's element list
# (VertexBufferObject.BeginDraw): an FBX static mesh is [position, normal, uv, uv2], so uv is slot
# 2, which vehicle_static.vert reads. vehiclewheel_static.vert reads slot 3 (written for the
# game's .txt meshes: [position, normal, tangent, uv]), i.e. OUR SECOND UV LAYER: in 42.21 the
# interior, engine and wheels drew as white shards until that layer was a copy of the first.
PLAIN_SHADER = ("interior", "engine_block", "cabin") + tuple(features.plain_shader())   # + feature meshes off the shell


def _mirror_uv(ob):
    """Second UV layer = first (see PLAIN_SHADER)."""
    uvs = ob.data.uv_layers
    if not uvs:
        return
    if len(uvs) < 2:
        uvs.new(name="UVMap1")
    buf = [0.0] * (2 * len(ob.data.loops))
    ob.data.uv_layers[0].data.foreach_get("uv", buf)
    ob.data.uv_layers[1].data.foreach_set("uv", buf)
    ob.data.uv_layers[0].active_render = True
    ob.data.uv_layers.active_index = 0


def prepare():
    """Rename to the KI5 pattern, bake the squash, and put everything at export scale."""
    arm = bpy.data.objects.get(rig_vehicle.ARMATURE)
    meshes = [bpy.data.objects[n] for n in BODY_OBJECTS + WHEEL_OBJECTS if n in bpy.data.objects]
    for ob in meshes:
        if ob.name not in ANIMATED:
            _unskin(ob)
        _bake_transform(ob)
        ng = _inner_glass(ob)
        if ng:
            print("EXPORT %s: %d inward glass faces (seen from the seats)" % (ob.name, ng))
        _single_material(ob)
        if ob.data.get("uv_baked"):
            pass                                           # bake_atlas.py already unwrapped and baked this mesh
        elif ob.name in SHEET_OBJECTS:
            uv_project.assign(ob, Matrix.Identity(4))      # planar sheet, in model metres
        elif ob.name.startswith("wheel"):
            wheel_uv.assign(ob)                            # polar rim + tread strip
        else:
            uv_atlas.assign(ob)                            # interior: flat-colour cells
        if ob.name.startswith("wheel"):
            _bake_wheel(ob)
        else:
            _bake_body(ob)
        if ob.name in PLAIN_SHADER or ob.name.startswith("wheel"):
            _mirror_uv(ob)
            print("EXPORT %s: second UV layer mirrored for the vehiclewheel shader" % ob.name)
    if arm:
        _squash_bones(arm)
        _scale_clip_translations()
        _place(arm)
    for ob in meshes:
        if ob.name in ANIMATED and arm and ob.parent is arm:
            ob.matrix_parent_inverse = Matrix.Identity(4)  # the armature carries the transform
            ob.location = (0.0, 0.0, 0.0)
            ob.scale = (1.0, 1.0, 1.0)
        else:
            ob.parent = None
            _place(ob)
    # The script references sub-objects by name; anything not referenced is invisible in game.
    # Bumper, spare, mirrors and rails are not removable parts in v1, so they become body.
    body = bpy.data.objects.get("body")
    extras = [ob for ob in meshes if ob.name in STATIC_INTO_BODY]
    keep = [ob.name for ob in meshes if ob.name not in STATIC_INTO_BODY]
    if body is not None and extras:
        bpy.ops.object.select_all(action='DESELECT')
        for ob in extras:
            ob.select_set(True)
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.join()                              # the extras' objects are gone now
        meshes = [bpy.data.objects[n] for n in keep]
    for ob in meshes:                                      # KI5 names every sub-object
        if not ob.name.startswith(PREFIX):
            ob.name = PREFIX + ob.name
        # The game resolves "file|name" against the FBX *Geometry* name (Assimp aiMesh.mName),
        # which the Blender exporter takes from the mesh datablock, not the object. Keep them equal.
        ob.data.name = ob.name
    return arm, meshes


def _select(objs):
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def _write(path, objs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _select(objs)
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={'MESH', 'ARMATURE'},
        mesh_smooth_type='FACE',
        use_mesh_modifiers=False,                          # keep the armature deform live
        add_leaf_bones=False,
        primary_bone_axis='Y', secondary_bone_axis='X',
        bake_anim=True,
        bake_anim_use_all_bones=True,                      # KI5's Bronco and the vanilla Martin both key EVERY bone in EVERY
                                                           # clip; a bone left unkeyed in the active clip has no defined value
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=True,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode='COPY', embed_textures=False,
        apply_scale_options='FBX_SCALE_ALL',               # unit factor goes to the header (ignored by the game), nodes stay identity
        global_scale=1.0,
    )
    return path


def export_table(src, out_dir=None):
    """The picnic table as a dropped item: the baked acc_table mesh (top + folded legs) on the
    ground at the origin, 10 units per metre like the car (model script scale 0.1), one material.
    WorldItems/CRVGen1_Table.fbx; the item's WorldStaticModel names it."""
    out_dir = out_dir or WORLD_ITEMS_DIR
    me = src.data.copy()
    ob = bpy.data.objects.new("CRVGen1_Table", me)
    bpy.context.scene.collection.objects.link(ob)
    me.name = ob.name
    _single_material(ob)
    centre = src.get("table_centre") or (0.0, 0.0, 0.0)
    zmin = min(v.co.z for v in me.vertices)
    for v in me.vertices:
        v.co.x = (v.co.x - centre[0]) * WORLD_UNITS_PER_M
        v.co.y = (v.co.y - centre[1]) * WORLD_UNITS_PER_M
        v.co.z = (v.co.z - zmin) * WORLD_UNITS_PER_M
    _place(ob)
    path = _write(os.path.join(out_dir, "CRVGen1_Table.fbx"), [ob])
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(me)
    print("EXPORTED %s  (%.1f KB, %d tris)" % (path, os.path.getsize(path) / 1024.0, 0))
    return path


STAND_NAME = "CRVGen1_TableStand"     # gen_scripts.TABLE_STAND: model script, FBX and texture share the name
WORLD_TEX_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures", "WorldItems")


def export_standing_table(out_dir=None, tex_dir=None):
    """The PLACED picnic table as a 3D model (common/media/spriteModels.txt maps both tile facings
    onto model script Base.CRVGen1_TableStand): build_table.standing_table at the real sizes (12 mm
    tubes, 20 mm top; the sprite alone is drawn fatter), top centred on the origin, feet on z = 0,
    10 units per metre with one material like every mesh here, and its own 256 px sheet
    (build_table.standing_uv / paint_standing) instead of the 1024 car shell. The model script says
    `scale = 0.1, undoCoreScale = true`: IsoObjectModelDrawer draws world models 1.5x (the camera's
    scale(-1.5, 1.5, 1.5)) and undoCoreScale multiplies the script scale by 2/3, so 10 units = 1 tile."""
    import bmesh
    import build_table
    out_dir = out_dir or WORLD_ITEMS_DIR
    tex_dir = tex_dir or WORLD_TEX_DIR
    bm = bmesh.new()
    build_table.standing_table(bm)                         # real sizes (the defaults)
    from build_accessories import _new_object
    ob = _new_object(STAND_NAME, bm)                       # material slots in build_accessories.MATS order
    me = ob.data
    me.name = ob.name
    build_table.standing_uv(me)
    tex = build_table.paint_standing(os.path.join(tex_dir, STAND_NAME + ".png"))
    for v in me.vertices:
        v.co *= WORLD_UNITS_PER_M
    _single_material(ob)
    _place(ob)
    path = _write(os.path.join(out_dir, STAND_NAME + ".fbx"), [ob])
    ntri = sum(len(p.vertices) - 2 for p in me.polygons)
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.meshes.remove(me)
    print("EXPORTED %s  (%.1f KB, %d tris); texture %s" % (path, os.path.getsize(path) / 1024.0, ntri, tex))
    return path, tex


def export_all(out_dir=None):
    out_dir = out_dir or OUT_DIR
    table = bpy.data.objects.get("acc_table")
    if table is not None:
        export_table(table)                                # before prepare() scales the car's meshes
    for feat, _r in features.call("EXPORT", print, {"out": out_dir, "world_items": WORLD_ITEMS_DIR}):
        print("EXPORTED feature %s's own files" % feat)    # also before prepare(): model metres
    arm, meshes = prepare()
    wheels = {PREFIX + n for n in WHEEL_OBJECTS}
    body = [ob for ob in meshes if ob.name not in wheels]
    wheel = [ob for ob in meshes if ob.name in wheels]
    paths = []
    paths.append(_write(os.path.join(out_dir, "%s_Body.fbx" % MODEL_NAME),
                        ([arm] if arm else []) + body))
    if wheel:
        paths.append(_write(os.path.join(out_dir, "%s_Wheel.fbx" % MODEL_NAME), wheel))
    for p in paths:
        print("EXPORTED %s  (%.1f KB)" % (p, os.path.getsize(p) / 1024.0))
    print("  objects: " + ", ".join(sorted(ob.name for ob in meshes)))
    return paths


if __name__ == "__main__":
    export_all()
