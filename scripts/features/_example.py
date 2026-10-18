r"""
Example feature module: EVERY field of the plugin contract (spec/feature-plugins.md), nothing real.

The loader skips it (leading underscore). scripts/test_features.py activates it (features.activate
(["_example"])) and checks that each field lands where the contract says; CRV_FEATURES=_example
would build it. Copy this file to scripts/features/<key>.py and delete what the feature does not need.

The feature key is the module name ("example" here: the underscore is stripped). Prefixes:
  meshes acc_example_*        parts CRVExample*      items CRVGen1_Example*    models HondaCRVGen1Acc_example_*
  Lua    HondaCRVGen1_Example*.lua, namespace HondaCRVGen1.Example, State keys example_*
  translations IGUI_CRV_Example_*, ContextMenu_CRV_Example_*, Tooltip_CRV_Example_*; sandbox options Example*

Top-level imports: standard library only. bpy / bmesh go inside BUILD, BAKE_PAINT and EXPORT.
"""
import os

# ---------------------------------------------------------------------------------------------
# geometry (Blender, run_rebuild.py): BUILD runs after build_accessories and build_table, on the low
# parts, with scripts/ on sys.path. Every mesh it makes is listed in OBJECTS.


def BUILD(report):
    import bmesh
    import build_accessories as BA                       # helpers: _box, _sweep, _slab, _new_object (MATS slots), tris
    bm = bmesh.new()
    BA._box(bm, (-0.30, 2.24, 0.30), (0.30, 2.27, 0.44), mat=BA.PLATE)
    plate = BA._new_object("acc_example_plate", bm)
    bm = bmesh.new()
    BA._box(bm, (-0.10, 2.27, 0.33), (0.10, 2.28, 0.41), mat=BA.PLATE)
    sign = BA._new_object("acc_example_sign", bm)
    report("FEATURE example: acc_example_plate %d tris, acc_example_sign %d tris" % (BA.tris(plate), BA.tris(sign)))


OBJECTS = {
    # space: the sheet it bakes on (shell / interior / wheel / engine, or a SPACES entry below)
    # bone: rig_vehicle bone it rides (door_fl_bone, trunk_bone, ...; its part needs `parent =` the
    #       part whose track weights that bone), None = static
    # zone: the Mask zone it dents and greys with (bake_atlas.ZONE: body, head, door_fl, roof, boot...)
    # weight: texel weight against the sheet's 1.0 (texel_w True: the builder wrote a FLOAT face attribute
    #         texel_w per face instead, build_accessories._texel_weights)
    # file: "body" (Vehicles_HondaCRVGen1_Body.fbx) or "wheel" (..._Wheel.fbx, centred on its own hub)
    "acc_example_plate": {"space": "shell", "bone": None, "zone": "head", "weight": 1.0},
    "acc_example_sign": {"space": "example", "zone": "head"},
}

# a sheet of the feature's own: Vehicles_HondaCRVGen1_<texture>.png at size, drawn with the vehiclewheel
# shader (static meshes only: a mesh on a bone bakes on the shell). ao_k / gain / grime: compose_textures'
# AO depth, brightness gain and dirt (colour, depth) for it
SPACES = {
    "example": {"size": 256, "texture": "Example", "ao_k": 0.30, "gain": 1.0, "grime": ((96, 88, 74), 0.0)},
}

# ---------------------------------------------------------------------------------------------
# bake (Blender, bake_atlas.py)

# bake_atlas.TEXTURED stacks for the feature's own materials (a dict, or a function returning one,
# evaluated after the scene is loaded): ("box", <polyhaven jpg>, scale, tint, mix), ("noise", ...),
# ("decal", png, (axis, a0, a1), (axis, b0, b1), mode[, gates]), ("attr", name) ... see bake_atlas
BAKE_TEXTURED = {"AccExamplePaint": [("noise", 90.0, 0.05)]}
BAKE_MAT_WEIGHTS = {"AccExamplePaint": 1.0}             # bake_atlas.TEXEL_WEIGHT_MAT for those materials


def BAKE_PAINT(decal_dir):
    """Write painted maps the bake reads (decal PNGs named in BAKE_TEXTURED) into decal_dir."""
    return os.path.join(decal_dir, "example_decal.png")


# ---------------------------------------------------------------------------------------------
# textures and export


def COMPOSE(report, ctx):
    """System Python, after compose_textures wrote every sheet: ctx = {"out": textures dir, "bake": bake
    dir, "sheets": {space: size}}. Extra textures (a decal sheet per colourway, ...) go in ctx["out"]."""
    report("FEATURE example: compose (sheets %s)" % sorted(ctx["sheets"]))


def EXPORT(report, ctx):
    """Blender, run_export.py, before the car's meshes are scaled for the FBX: ctx = {"out": the
    vehicles models dir, "world_items": the WorldItems models dir}. Extra FBX files (an item's world
    model) go there; export_fbx.export_table is the pattern."""
    report("FEATURE example: export -> %s" % ctx["world_items"])


ICONS = {"CRVGen1_ExamplePlate": ("acc_example_plate", 72.0, 14.0)}       # item -> (object, azimuth, elevation)


def _overlay(s, ov):
    """The part's mechanics-window image (compose_overlays, the vanilla line-art style): a framed icon
    in the band under the bottom row (ov.BOTTOM_BAND; ov.TOP_BAND is the one over the engine row). s = the
    Sheet (cell / frame_box / leader), ov = compose_overlays (px, to_px, sym, mirror, outline_x, WHEEL_Y...).
    Return the frame box, or None for a cell drawn on the car (its own bounds are then the hit box).
    compose_overlays.check fails the build on overlaps and on anything outside rows SAFE_Y0..SAFE_Y1 - 1
    (the window's title bar and status strip cover the rest)."""
    x0, x1 = 110, 150
    y0 = ov.BOTTOM_BAND[0] + 6
    y1 = y0 + 28
    s.frame_box(x0, y0, x1, y1)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    s.cell([("rrect", cx - 14, cy - 6, cx + 14, cy + 6, 2.0)], "acc_example_plate",
           details=[[(cx - 9, cy), (cx + 9, cy)]], dlw=1.2)
    return (x0, y0, x1, y1)


# part -> img (crv1_<img>.png), draw, objects (optional: meshes rendered top-down to check an on-car cell's place)
OVERLAYS = {"CRVExamplePlate": {"img": "acc_example_plate", "draw": _overlay}}

# ---------------------------------------------------------------------------------------------
# scripts (gen_scripts.py): text, or a function given gen_scripts as `gen`


def MODELS(gen):
    return [gen.model_block(gen.acc_model_name("acc_example_plate"), "crvgen1_acc_example_plate"),
            gen.model_block(gen.acc_model_name("acc_example_sign"), "crvgen1_acc_example_sign",
                            texture="%s_Example" % gen.TEX, shader="vehiclewheel")]


def VEHICLE_PARTS(gen, vehicle):
    """Added to EVERY CR-V vehicle script (vehicle = its name): a part that fits any CR-V."""
    return gen.accessory_part("CRVExamplePlate", "acc_example_plate", "CRVGen1_ExamplePlate", "Engine",
                              tool="base:wrench", time=600, level=2, lua="HondaCRVGen1.Example",
                              models=[("ExampleSign", "acc_example_sign")])


# a whole second vehicle script (the lifted car is one): the stock car with what changes
VEHICLE_SCRIPTS = {
    "HondaCRVGen1Example": lambda gen: gen.vehicle_script("HondaCRVGen1Example", model_offset="0.0000 0.6417 0.0000",
                                                          off_road="1.25", tuning=gen.tuning_with(maxSpeed="90.0")),
}

ITEMS = {
    "CRVGen1_ExamplePlate": {"DisplayCategory": "VehicleMaintenance", "Weight": 6.0, "ItemType": "base:normal",
                             "DisplayName": "CR-V Example Plate", "Icon": "CRVGen1_ExamplePlate", "ConditionMax": 100,
                             "MechanicsItem": True, "Tags": "base:hasmetal"},
}

RECIPES = """\tcraftRecipe CRVGen1_MakeExamplePlate
\t{
\t\ttimedAction = Making,
\t\ttime = 200,
\t\tcategory = Metalworking,
\t\tTags = AnySurfaceCraft,
\t\tinputs
\t\t{
\t\t\titem 2 [Base.SheetMetal],
\t\t\titem 1 tags[base:hammer] mode:keep,
\t\t}
\t\toutputs
\t\t{
\t\t\titem 1 Base.CRVGen1_ExamplePlate,
\t\t}
\t}"""

TRANSLATIONS = {
    "IG_UI": {"IGUI_VehiclePartCRVExamplePlate": "Example Plate",
              "IGUI_VehicleNameHondaCRVGen1Example": "Honda CR-V (example)",
              "IGUI_CRV_Example_Painted": "Plate painted"},
    "ContextMenu": {"ContextMenu_CRV_Example_Paint": "Paint the example plate"},
    "Tooltip": {"Tooltip_CRV_Example_NeedPaint": "Needs a can of paint"},
    "Recipes": {"Recipe_CRVGen1_MakeExamplePlate": "Make CR-V Example Plate"},
}

# the feature's Lua, tracked under mod/Contents/mods/HondaCRVGen1/42/media/lua (paths from there)
LUA = ["shared/HondaCRVGen1_Example.lua", "client/HondaCRVGen1_ExampleMenu.lua"]
# any other hand-made file it ships, tracked under mod/Contents/mods/HondaCRVGen1 (paths from there):
# sound scripts and banks, a hand-drawn icon (common/media/textures/Item_<icon>.png) ...
MEDIA = ["42/media/scripts/sounds/HondaCRVGen1_ExampleSounds.txt"]

SANDBOX = [
    {"name": "ExampleChance", "type": "integer", "default": 10, "min": 0, "max": 100,
     "label": "Example plate spawn chance (%)", "tooltip": "Share of CR-Vs that spawn with the example plate."},
    {"name": "ExampleLoot", "type": "double", "default": 1.0, "min": 0.0, "max": 10.0, "label": "Example plate loot"},
    {"name": "ExampleStyle", "type": "enum", "default": 1, "values": ["Plain", "Striped"], "label": "Example style"},
    {"name": "ExampleOn", "type": "boolean", "default": True, "label": "Example enabled"},
]

DISTRIBUTIONS = [
    # list: a ProceduralDistributions.list name (media/lua/server/Items/ProceduralDistributions.lua);
    # sandbox: a double option of this page that multiplies the weight
    {"list": "GarageMechanics", "item": "Base.CRVGen1_ExamplePlate", "weight": 0.5, "sandbox": "ExampleLoot"},
    {"list": "CrateMechanics", "item": "Base.CRVGen1_ExamplePlate", "weight": 1.0},
]
