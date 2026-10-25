r"""
The feature plugin points (scripts/features, spec/feature-plugins.md), system Python only:

  1. no feature module: gen_scripts writes exactly what the mod tracks (and, with --base REV, exactly
     what that revision's gen_scripts wrote), every merge helper returns its input unchanged;
  2. the example module (_example) activated: every field lands where the contract says (scripts,
     items, recipes, translations, sandbox options, loot Lua run under Lua 5.1, the extra vehicle
     script and its registration, the Lua copies, the bake / export / rig / icon / overlay / compose
     tables), the audit's feature checks pass on that tree, and a run without it removes its files;
  3. contract violations are refused (collisions, names, shapes, a translation clash with the core).

    python scripts\test_features.py [--base <git rev>] [--keep]
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CHECKOUT = os.path.dirname(HERE)
MOD42 = os.path.join(CHECKOUT, "mod", "Contents", "mods", "HondaCRVGen1", "42")
GENERATED = ["scripts/items/HondaCRVGen1_items.txt", "scripts/vehicles/HondaCRVGen1.txt",
             "lua/shared/Translate/EN/IG_UI.json", "lua/shared/Translate/EN/ItemName.json",
             "lua/shared/Translate/EN/ContextMenu.json", "lua/shared/Translate/EN/Tooltip.json",
             "lua/shared/Translate/EN/UI.json", "scripts/fixing/HondaCRVGen1_fixing.txt"]

import features  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)


def read(path):
    # errors="replace": feature MEDIA copied by gen_scripts --out includes binary files (polish: .ogg, .png)
    with open(path, encoding="utf-8", newline="", errors="replace") as f:
        return f.read()


def files(root):
    out = {}
    for dp, _d, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = read(p)
    return out


def gen_subprocess(out, env_features="none", script=None):
    """gen_scripts --out <out> in a fresh interpreter; env_features None = every discovered feature."""
    env = dict(os.environ)
    env.pop("CRV_ROOT", None)
    env.pop("CRV_FEATURES", None)
    if env_features is not None:
        env["CRV_FEATURES"] = env_features
    p = subprocess.run([sys.executable, script or os.path.join(HERE, "gen_scripts.py"), "--out", out],
                       capture_output=True, text=True, env=env)
    check(p.returncode == 0, "gen_scripts failed:\n" + p.stdout + p.stderr)
    return p.stdout


def no_features(tmp, base):
    # the mod tracks what gen_scripts writes (with every discovered feature; git stores the files with LF)
    every = os.path.join(tmp, "every")
    gen_subprocess(every, env_features=None)
    tracked = files(every)
    for g in GENERATED:
        check(tracked["media/" + g] == read(os.path.join(MOD42, "media", *g.split("/"))).replace("\r\n", "\n"),
              "%s differs from the tracked mod file: run scripts/gen_scripts.py" % g)
    a = os.path.join(tmp, "nofeat")
    gen_subprocess(a)
    got = files(a)
    check(sorted(got) == sorted("media/" + g for g in GENERATED), "no-feature output files: %s" % sorted(got))
    if not features.discovered():
        check(got == tracked, "CRV_FEATURES=none differs from a build without feature modules")
    if base:
        old = os.path.join(tmp, "base_gen")
        os.makedirs(old)
        src = subprocess.run(["git", "-C", CHECKOUT, "show", "%s:scripts/gen_scripts.py" % base],
                             capture_output=True, text=True, encoding="utf-8")
        check(src.returncode == 0, "git show %s: %s" % (base, src.stderr))
        with open(os.path.join(old, "gen_scripts.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(src.stdout)
        b = os.path.join(tmp, "base_out")
        gen_subprocess(b, script=os.path.join(old, "gen_scripts.py"))
        check(files(b) == got, "the generated mod differs from %s's gen_scripts" % base)
        print("FEATURES none: byte-identical to %s's gen_scripts" % base)
    features.activate([])
    base_spaces = {"shell": (["body", "acc_x"], 2048), "wheel": (["wheel_FR"], 512)}
    check(features.spaces(base_spaces) == base_spaces and features.spaces(base_spaces) is not base_spaces, "spaces")
    for fn in (features.skin, features.zones, features.shell_weights, features.texel_weights, features.icons,
               features.overlays, features.translations, features.vehicle_scripts, features.bake_textured,
               features.bake_mat_weights, features.new_spaces):
        check(fn() == {}, "%s not empty" % fn.__name__)
    for fn in (features.body_objects, features.wheel_objects, features.plain_shader, features.lua, features.media, features.sandbox,
               features.distributions, features.item_tables):
        check(fn() == [], "%s not empty" % fn.__name__)
    check(features.texel_attr_objects() == set() and features.blocks("MODELS", None) == [], "blocks")
    features.activate(None)
    print("FEATURES none: generated mod == tracked mod files; every merge returns its input")


def example(tmp, keep):
    import gen_scripts as gen
    features.activate(["_example"])
    stub = os.path.join(tmp, "stubmod")                # the example's LUA / MEDIA files, as a checkout's mod folder tracks them
    for _f, rel in features.media():
        p = os.path.join(stub, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write("-- stub %s\n" % rel)
    gen.CHECKOUT_MOD42 = os.path.join(stub, "42")
    out = os.path.join(tmp, "example")
    with contextlib.redirect_stdout(io.StringIO()):
        gen.main(out)
    import audit_mod
    m = os.path.join(out, "media")
    veh = read(os.path.join(m, "scripts", "vehicles", "HondaCRVGen1.txt"))
    root = audit_mod.parse(veh)
    mods = root.children
    check(not audit_mod.fails, "the generated script does not parse: %s" % audit_mod.fails)
    models = {b.name for b in mods[0].all("model")}
    check({"HondaCRVGen1Acc_example_plate", "HondaCRVGen1Acc_example_sign"} <= models, "MODELS: %s" % sorted(models))
    v = mods[0].all("vehicle")[0]
    parts = {p.name: p for p in v.all("part")}
    check("CRVExamplePlate" in parts, "VEHICLE_PARTS in the stock car")
    plate = parts["CRVExamplePlate"]
    check([pm.name for pm in plate.all("model")] == ["CRVExamplePlate", "ExampleSign"], "part models")
    check(plate.all("lua")[0].get("create") == "HondaCRVGen1.Example.Create", "the feature's Lua namespace")
    check(plate.all("table")[0].get("complete") == "HondaCRVGen1.Example.InstallComplete", "install complete hook")
    check(veh.index("part CRVExamplePlate") < veh.index("part TireFrontLeft"), "feature parts before the tyres")
    lifted = read(os.path.join(m, "scripts", "vehicles", "HondaCRVGen1Example.txt"))
    lv = audit_mod.parse(lifted).children[0].all("vehicle")[0]
    check(lv.name == "HondaCRVGen1Example" and lv.get("offRoadEfficiency") == "1.25", "VEHICLE_SCRIPTS overrides")
    check(lv.all("model")[0].get("offset") == "0.0000 0.6417 0.0000", "second script's model offset")
    check(lv.get("maxSpeed") == "90.0" and lv.get("engineForce") == "3850", "tuning_with")
    check("CRVExamplePlate" in {p.name for p in lv.all("part")}, "VEHICLE_PARTS in the second script too")
    check(not audit_mod.parse(lifted).children[0].all("model"), "the second script redeclares models")
    items = read(os.path.join(m, "scripts", "items", "HondaCRVGen1_items.txt"))
    check("\titem CRVGen1_ExamplePlate\n\t{\n\t\tDisplayCategory = VehicleMaintenance,\n\t\tWeight = 6.0," in items
          and "\t\tMechanicsItem = true,\n" in items and items.endswith("\t}\n\n}\n"), "ITEMS table")
    tr = os.path.join(m, "lua", "shared", "Translate", "EN")
    ui = json.load(open(os.path.join(tr, "IG_UI.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(tr, "ItemName.json"), encoding="utf-8"))
    check(ui["IGUI_VehiclePartCRVExamplePlate"] == "Example Plate" and "IGUI_VehicleNameHondaCRVGen1" in ui, "IG_UI")
    check(list(ui)[0] == "IGUI_VehicleNameHondaCRVGen1", "core keys first")
    check(names["Base.CRVGen1_ExamplePlate"] == "CR-V Example Plate", "ItemName from the item's DisplayName")
    check(not os.path.exists(os.path.join(tr, "IG_UI_EN.txt")), "no IG_UI_EN.txt (42.21 reads the JSON files)")
    fix = read(os.path.join(m, "scripts", "fixing", "HondaCRVGen1_fixing.txt"))
    check("Base.CRVGen1_ExamplePlate" in fix, "the feature's repairable part item has a fixing")
    check(json.load(open(os.path.join(tr, "ContextMenu.json"), encoding="utf-8"))["ContextMenu_CRV_Example_Paint"], "ContextMenu")
    for fname in ("Tooltip", "Recipes", "Sandbox"):
        check(os.path.exists(os.path.join(tr, fname + ".json")), "%s.json" % fname)
    sb = json.load(open(os.path.join(tr, "Sandbox.json"), encoding="utf-8"))
    check(sb["Sandbox_HondaCRVGen1"] == "Honda CRV (RD1)" and sb["Sandbox_HondaCRVGen1_ExampleChance_tooltip"]
          and sb["Sandbox_HondaCRVGen1_ExampleStyle_option2"] == "Striped", "Sandbox.json")
    opts = read(os.path.join(m, "sandbox-options.txt"))
    so = audit_mod.parse(opts)
    check(opts.startswith("VERSION = 1,\n") and len(so.all("option")) == 4, "sandbox-options.txt")
    enum = [o for o in so.all("option") if o.name == "HondaCRVGen1.ExampleStyle"][0]
    check(enum.get("numValues") == "2" and enum.get("valueTranslation") == "HondaCRVGen1_ExampleStyle", "enum option")
    check([o for o in so.all("option") if o.name == "HondaCRVGen1.ExampleOn"][0].get("default") == "true", "boolean default")
    rec = read(os.path.join(m, "scripts", "recipes", "HondaCRVGen1_recipes.txt"))
    check("craftRecipe CRVGen1_MakeExamplePlate" in rec and rec.startswith("/* "), "RECIPES")
    loot = read(os.path.join(m, "lua", "server", "Items", "HondaCRVGen1_Loot.lua"))
    vehicles = read(os.path.join(m, "lua", "shared", "HondaCRVGen1_Vehicles.lua"))
    check('registerVehicle("Base.HondaCRVGen1Example")' in vehicles, "vehicle registration")
    for _f, rel in features.lua():
        check(os.path.exists(os.path.join(m, "lua", *rel.split("/"))), "LUA copy %s" % rel)
    check(os.path.exists(os.path.join(m, "scripts", "sounds", "HondaCRVGen1_ExampleSounds.txt")), "MEDIA copy")
    lua_checks(loot, vehicles)
    # the other consumers' tables (system Python ones imported here; the Blender ones read the same helpers)
    sp = features.spaces({"shell": (["body"], 2048), "interior": (["interior"], 1024)})
    check(sp["shell"][0] == ["body", "acc_example_plate"] and sp["example"] == (["acc_example_sign"], 256), "spaces %s" % sp)
    check(features.zones() == {"acc_example_plate": "head", "acc_example_sign": "head"}, "zones")
    check(features.shell_weights() == {"acc_example_plate": 1.0} and features.texel_weights() == {}, "weights")
    check(features.body_objects() == ["acc_example_plate", "acc_example_sign"] and features.plain_shader() == ["acc_example_sign"],
          "export lists")
    check(features.skin() == {} and features.wheel_objects() == [], "rig / wheel")
    check(features.bake_textured() == {"AccExamplePaint": [("noise", 90.0, 0.05)]} and
          features.bake_mat_weights() == {"AccExamplePaint": 1.0}, "bake tables")
    calls = []
    check([f for f, _r in features.call("COMPOSE", calls.append, {"out": tmp, "bake": tmp, "sheets": {"shell": 2048}})] == ["example"]
          and calls, "COMPOSE hook")
    for mod in ("compose_overlays", "compose_textures"):
        sys.modules.pop(mod, None)
    import compose_overlays as ov
    check(ov.ACC_PARTS["CRVExamplePlate"] == "acc_example_plate" and "acc_example_plate" not in ov.ON_CAR
          and ov.VEHICLES == ["Base.HondaCRVGen1", "Base.HondaCRVGen1Example"], "overlay tables")
    s = ov.Sheet()                                     # the example's icon in the real layout: no overlap, a hit box
    boxes = ov.draw(s)
    for spec in features.overlays().values():
        b = spec["draw"](s, ov)
        if b:
            boxes[spec["img"]] = tuple(b)
    images = s.images()
    rects, _cuts = ov.hit_rects(images, boxes)
    ov.check(images, rects)                            # SystemExit on an overlap or a missing image
    y0 = ov.BOTTOM_BAND[0] + 6
    check(rects["acc_example_plate"] == [111, y0 + 1, 150, y0 + 28], "example hit box %s" % rects.get("acc_example_plate"))
    import compose_textures
    check(compose_textures.AO_K_SPACE["example"] == 0.30 and compose_textures.GRIME["example"] == ((96, 88, 74), 0.0)
          and compose_textures.sheet_sizes()["example"] == 256, "compose tables")
    # the audit's feature checks on this tree
    audit_mod.MOD = os.path.dirname(out) + os.sep + "_mod"
    shutil.rmtree(audit_mod.MOD, ignore_errors=True)
    shutil.copytree(out, os.path.join(audit_mod.MOD, "42"))
    audit_mod.fails.clear()
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        audit_mod.features_audit()
    check(not audit_mod.fails and "AUDIT features: example; 2 Lua files, 1 other files, 4 sandbox options, 1 recipes" in buf.getvalue(),
          "audit on the example tree: %s %s" % (audit_mod.fails, buf.getvalue()))
    # without the feature, its generated files go and the rest is the stock output again
    features.activate([])
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        gen.main(out)
    removed = buf.getvalue().count("REMOVED")
    after = files(out)
    for p in [k for k in after if k.startswith(("media/lua/client/HondaCRVGen1_Example", "media/lua/shared/HondaCRVGen1_Example",
                                               "media/scripts/sounds/HondaCRVGen1_Example"))]:
        after.pop(p)                                    # copies of tracked files stay (their source is the checkout)
    stock = files(os.path.join(tmp, "nofeat"))
    check(after == stock, "after the feature went: extra %s" % sorted(set(after) ^ set(stock)))
    check(removed == 7, "removed %d generated files, want 7 (second script, recipes, sandbox options, loot Lua, vehicles "
          "Lua, Recipes / Sandbox json; Tooltip.json is the core's too)" % removed)
    features.activate(None)
    if keep:
        print("KEPT", out)
    print("FEATURES _example: every field landed (scripts, items, recipes, translations, sandbox, loot, second script, "
          "Lua copies, bake / export / overlay / compose tables, audit); removed cleanly")


def lua_checks(loot, vehicles):
    from lua_harness import Side
    s = Side("server")
    s.run(r'''
ProceduralDistributions = { list = { GarageMechanics = { items = { "Wrench", 4 } }, CrateMechanics = { items = {} } } }
SandboxVars = { HondaCRVGen1 = { ExampleLoot = 3.0 } }
''')
    s.L.execute(loot)
    check(s.trigger("OnPreDistributionMerge") == 1, "loot registers on OnPreDistributionMerge")
    g = list(s.eval("ProceduralDistributions.list.GarageMechanics.items").values())
    c = list(s.eval("ProceduralDistributions.list.CrateMechanics.items").values())
    check(g == ["Wrench", 4, "Base.CRVGen1_ExamplePlate", 1.5] and c == ["Base.CRVGen1_ExamplePlate", 1.0],
          "loot entries %s %s" % (g, c))
    s.load("shared/HondaCRVGen1_State.lua")
    s.L.execute(vehicles)
    check(s.eval("HondaCRVGen1.State.isCRV(newVehicle(1, {}, 'Base.HondaCRVGen1Example'))"), "the second script is a CR-V")


def refusals(tmp):
    def mod(name, **fields):
        m = types.ModuleType(name)
        m.FEATURE = name
        for k, v in fields.items():
            setattr(m, k, v)
        return m

    cases = [
        ([mod("a", OBJECTS={"acc_a_x": {"space": "shell"}}), mod("a_b", OBJECTS={"acc_a_x": {"space": "shell"}})], "declared by both"),
        ([mod("a", OBJECTS={"acc_x": {"space": "shell"}})], "must be named acc_a_"),
        ([mod("a", OBJECTS={"acc_a_x": {"space": "nowhere"}})], "no SPACES declares"),
        ([mod("a", OBJECTS={"acc_a_x": {"space": "shell", "colour": 1}})], "keys are"),
        ([mod("a", OBJECTS={"wheel_a_x": {"space": "wheel", "file": "wheel", "bone": "door_fl_bone"}})], "cannot ride a bone"),
        ([mod("a", SPACES={"shell": {"size": 256, "texture": "X"}})], "core sheet"),
        ([mod("a", VEHICLE_SCRIPTS={"Lifted": str})], "HondaCRVGen1<Something>"),
        ([mod("a", ITEMS={"LiftKit": {}})], "CRVGen1_<Thing>"),
        ([mod("a", LUA=["../x.lua"])], "LUA path"),
        ([mod("a", MEDIA=["media/x.txt"])], "MEDIA path"),
        ([mod("a", MEDIA=["42/media/lua/shared/x.lua"])], "list it in LUA"),
        ([mod("a", OVERLAYS={"CRVA": ("img", ["acc_a_x"])})], "OVERLAYS["),
        ([mod("a", SANDBOX=[{"name": "X", "type": "integer"}])], "need name, type"),
        ([mod("a", OBJECT={})], "did you mean OBJECTS"),
        ([mod("a", TRANSLATIONS={"IG_UI": {"K": "1"}}), mod("b", TRANSLATIONS={"IG_UI": {"K": "2"}})], "declared by both"),
        ([mod("a", BUILD=3)], "must be a function"),
    ]
    for mods, want in cases:
        try:
            features._validate(mods)
        except features.FeatureError as exc:
            check(want in str(exc), "refusal %r: got %s" % (want, exc))
            continue
        raise SystemExit("FAIL no refusal for: %s" % want)
    # a feature translation that redefines a core key stops gen_scripts
    import gen_scripts as gen
    features._active = [mod("a", TRANSLATIONS={"IG_UI": {"IGUI_CRV_SeatsUp": "x"}})]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gen.translations(os.path.join(tmp, "clash"))
    except SystemExit as exc:
        check("redefine IG_UI keys IGUI_CRV_SeatsUp" in str(exc), str(exc))
    else:
        raise SystemExit("FAIL a core translation was redefined")
    finally:
        features.activate(None)
    print("FEATURES refusals: %d contract violations refused, plus a core translation clash" % len(cases))


def main():
    base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else None
    keep = "--keep" in sys.argv
    tmp = tempfile.mkdtemp(prefix="crv_features_")
    try:
        no_features(tmp, base)
        example(tmp, keep)
        refusals(tmp)
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    print("FEATURE PLUGIN TESTS OK")


if __name__ == "__main__":
    main()
