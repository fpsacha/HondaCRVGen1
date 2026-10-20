r"""
Game-data checks on the generated mod files (system Python), each one a defect the 2026-10-14 review found:

  1. tuning keys: every top-level key of every CR-V vehicle script is one VehicleScript.Load reads in
     42.21 (gen_scripts.PARSED_KEYS), so no tuning value is silently dead
     (brakingForce was never parsed; frontEndHealth / rearEndHealth are not the parser's names, which are
     frontEndDurability / rearEndDurability), and the crash durability is the tuned 300;
  2. translation routing: the game looks a prefixed key up in ONE file (Translator.getTextInternal:
     Tooltip_ -> Tooltip.json, ContextMenu_ -> ContextMenu.json, IGUI_ -> IG_UI.json, Sandbox_ -> Sandbox.json)
     and shows the raw key on a miss: every key the mod's Lua names that a translation file defines sits
     in the file of its prefix (Tooltip_CRV_GateClosed sat in ContextMenu.json);
  3. literature: every mod literature item that teaches recipes carries vanilla's
     OnCreate = ItemCodeOnCreate.onCreateRecipeMagazine (modData.literatureTitle, which ISReadABook needs to
     put re-reads on the LiteratureCooldown), like all 84 vanilla recipe magazines;
  4. the owner's manual's oil figure (3.8 L / 4 US qt with the filter, not the 3.7 US qt without it);
  5. the cabin (2026-10-19): the interior models sit on part CRVCabin (no item, shown by its Lua init), never on
     an item part such as GloveBox, whose removal hid the whole interior;
  6. suspension (2026-10-20): each wheel can carry enough of the car's weight on the spring (travel) and under
     Bullet's 6000 N limit with a fitted, loaded car, or a hard stop in a corner lands the body on the road.

    python scripts\test_gamedata.py [--mod42 <path to the mod's 42 folder>]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_mod  # noqa: E402
import gen_scripts as gen  # noqa: E402

def fail(msg):
    raise SystemExit("FAIL " + msg)


def check_tuning(mod42):
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    names = sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt"))
    if not names:
        fail("no vehicle scripts in %s" % vdir)
    for fn in names:
        root = audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read())
        for v in root.children[0].all("vehicle"):
            keys = [k for k, _v in v.kv]
            dead = sorted(k for k in keys if k not in gen.PARSED_KEYS)
            if dead:
                fail("%s: vehicle %s has keys the 42.21 parser never reads: %s" % (fn, v.name, ", ".join(dead)))
            for k in ("frontEndDurability", "rearEndDurability"):
                if v.get(k) != "300":
                    fail("%s: %s = %s, want the tuned 300" % (fn, k, v.get(k)))
    print("GAMEDATA tuning: %d vehicle scripts, every key read by VehicleScript.Load, durability 300 front and rear"
          % len(names))


# what one wheel can carry, as a multiple of its static load (spec/pz-conventions.md section 8): the spring
# stops at maxSuspensionTravelCm x model scale, Bullet stops at 6000 N against script mass + parts + cargo
# (FITTED_KG: ~310 vanilla parts + our accessories + some cargo). Below these the outer front wheel gives
# out under a hard stop in a corner and the body lands on the road (2026-10-20)
FITTED_KG, MIN_TRAVEL_CAP, MIN_FORCE_CAP = 680.0, 1.5, 1.7


def check_suspension(mod42):
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    out = []
    for fn in sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt")):
        for v in audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read()).children[0].all("vehicle"):
            scale = float(v.all("model")[0].get("scale"))
            k, mass = float(v.get("suspensionStiffness")), float(v.get("mass"))
            travel = v.get("maxSuspensionTravelCm")
            if travel is None:
                fail("%s: no maxSuspensionTravelCm (the SUV template's 10 cm leaves 2.6 cm of bump)" % fn)
            travel_cap = 4 * k * float(travel) * scale / 100.0 / 9.8
            force_cap = 6000.0 / ((mass + FITTED_KG) * 9.8 / 4)
            if travel_cap < MIN_TRAVEL_CAP or force_cap < MIN_FORCE_CAP:
                fail("%s: a wheel carries %.2f x its static load on the spring, %.2f x at Bullet's 6000 N with %d kg "
                     "fitted (want %.2f / %.2f)" % (fn, travel_cap, force_cap, FITTED_KG, MIN_TRAVEL_CAP, MIN_FORCE_CAP))
            out.append("%s %.2f/%.2f" % (v.name, travel_cap, force_cap))
    print("GAMEDATA suspension: per-wheel capacity (spring / 6000 N with %d kg fitted): %s" % (FITTED_KG, ", ".join(out)))


def check_routes(mod42):
    tdir = os.path.join(mod42, "media", "lua", "shared", "Translate", "EN")
    where = {}
    for fn in os.listdir(tdir):
        if fn.endswith(".json"):
            for k in json.load(open(os.path.join(tdir, fn), encoding="utf-8")):
                where.setdefault(k, set()).add(fn[:-5])
    used = set()
    for dp, _d, fs in os.walk(os.path.join(mod42, "media", "lua")):
        for f in fs:
            if f.endswith(".lua"):
                text = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                used |= set(re.findall(r'["\']((?:UI|IGUI|ContextMenu|Sandbox|Tooltip)_[A-Za-z0-9_]+)["\']', text))
    bad = []
    for k in sorted(used):
        want = gen.translation_file(k)
        if k in where and want not in where[k]:
            bad.append("%s is in %s.json, the game reads it from %s.json" % (k, "/".join(sorted(where[k])), want))
    every = ["%s in %s.json" % (k, f) for k, fs in where.items() for f in fs
             if gen.translation_file(k) and gen.translation_file(k) != f]
    if bad or every:
        fail("translation keys in the wrong file: " + "; ".join(bad + sorted(every)))
    print("GAMEDATA translations: %d keys named in the Lua, every defined one in the file of its prefix" % len(used))


def check_literature(mod42):
    items = audit_mod.parse(open(os.path.join(mod42, "media", "scripts", "items", "%s_items.txt" % gen.VEHICLE),
                                 encoding="utf-8").read())
    lit = [b for b in items.children[0].all("item") if (b.get("ItemType") or "").lower() == "base:literature"]
    teach = [b for b in lit if b.get("LearnedRecipes")]
    if not teach:
        fail("no literature item teaches a recipe (the armour / lift magazines and the manual should)")
    # the owner's manual's OnCreate is our wrapper: vanilla's onCreateRecipeMagazine + its print media mod data
    wrapped = {"HondaCRVGen1.Function.OnCreateManual"}
    missing = [b.name for b in teach if b.get("OnCreate") not in ({"ItemCodeOnCreate.onCreateRecipeMagazine"} | wrapped)]
    fn_lua = open(os.path.join(mod42, "media", "lua", "shared", "HondaCRVGen1_Function.lua"), encoding="utf-8").read()
    if "ItemCodeOnCreate.onCreateRecipeMagazine(item)" not in fn_lua:
        fail("HondaCRVGen1.Function.OnCreateManual no longer calls vanilla's onCreateRecipeMagazine")
    if missing:
        fail("literature without OnCreate = ItemCodeOnCreate.onCreateRecipeMagazine (re-reads give the mood relief "
             "every time): %s" % ", ".join(missing))
    print("GAMEDATA literature: %s carry onCreateRecipeMagazine" % ", ".join(b.name for b in teach))


def check_manual(mod42):
    ui = json.load(open(os.path.join(mod42, "media", "lua", "shared", "Translate", "EN", "IG_UI.json"), encoding="utf-8"))
    pages = " ".join(v for k, v in ui.items() if k.startswith("IGUI_CRV_Function_Manual_Page"))
    if not pages:
        fail("no owner's manual pages in IG_UI.json")
    # 2026-10-17: the manual is in-universe and about the game (feedback: less real-life detail): what the car does,
    # and the facts that must stay true to the mod
    for want in ("Real Time 4WD", "58 litres", "flat floor", "bed", "lift the cargo floor", "picnic table", "50 kg",
                 "jerry can", "jack, a lug wrench, a wrench", "kit comes back", "4x4 Off-Road: CRV Edition",
                 "Armoured windows stay shut"):
        if want not in pages:
            fail("the owner's manual lacks %r" % want)
    for gone in ("gas strut", "swings out to the side", "Dual Pump Fluid", "5W-30"):
        if gone in pages:
            fail("the owner's manual still has %r (cut 2026-10-17)" % gone)
    media = json.load(open(os.path.join(mod42, "media", "lua", "shared", "Translate", "EN", "Print_Media.json"), encoding="utf-8"))
    for sid in ("CRVGen1_Manual", "CRVGen1_Manual2", "CRVGen1_Manual3"):
        if "Print_Media_%s_info" % sid not in media:
            fail("no print media page %s" % sid)
    print("GAMEDATA manual: in-universe pages cover the mod's features, three print media spreads, the cut topics gone")


# the vanilla template parts the CR-V inherits that carry an item (template_glovebox: itemType = Base.GloveBox, and
# the rest): the engine shows or hides EVERY model of such a part with its item (VehiclePart.setInventoryItem ->
# setAllModelsVisible), so a model that must always draw can never sit on one
VANILLA_ITEM_PARTS = {"GloveBox", "EngineDoor", "Battery", "GasTank", "TruckBed", "TrunkDoor", "Windshield",
                      "WindshieldRear", "Muffler", "HeadlightLeft", "HeadlightRight", "HeadlightRearLeft",
                      "HeadlightRearRight"} | {"%s%s" % (k, s) for k in ("Door", "Window", "Tire", "Brake", "Suspension", "Seat")
                                               for s in ("FrontLeft", "FrontRight", "RearLeft", "RearRight")}


def check_cabin(mod42):
    """5. the cabin (round 5, 2026-10-19: taking the glove box out hid the whole interior): the interior shell and the
    cabin furniture are models of part CRVCabin alone, which has no item (own or inherited), never lets the engine
    show or reset its models (setAllModelsVisible = false), and shows them from its init, a Lua function the mod
    defines in a shared file (it runs on every side)."""
    files = {"%s%s" % (gen.VEHICLE, f): mid for mid, f in gen.CABIN_MODELS}
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    shared = os.path.join(mod42, "media", "lua", "shared")
    lua = "".join(open(os.path.join(shared, f), encoding="utf-8").read() for f in os.listdir(shared) if f.endswith(".lua"))
    names = sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt"))
    for fn in names:
        root = audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read())
        for v in root.children[0].all("vehicle"):
            owners = {}
            for part in v.all("part"):
                for pm in part.all("model"):
                    if pm.get("file") in files:
                        owners.setdefault(part.name, []).append(pm.name)
            if sorted(owners) != [gen.CABIN_PART] or sorted(owners[gen.CABIN_PART]) != sorted(files.values()):
                fail("%s: vehicle %s draws the cabin models from %s, want part %s alone (%s)"
                     % (fn, v.name, owners, gen.CABIN_PART, ", ".join(sorted(files.values()))))
            part = [p for p in v.all("part") if p.name == gen.CABIN_PART][0]
            if part.name in VANILLA_ITEM_PARTS or part.get("itemType"):
                fail("%s: part %s carries an item: removing it would hide the cabin" % (fn, part.name))
            if (part.get("setAllModelsVisible") or "").lower() != "false":
                fail("%s: part %s lacks setAllModelsVisible = false" % (fn, part.name))
            init = ([l.get("init") for l in part.all("lua")] + [None])[0]
            if init != gen.CABIN_LUA + ".Init" or not re.search(r"function\s+Cabin\.Init\s*\(", lua) \
                    or 'HondaCRVGen1.Cabin = Cabin' not in lua:
                fail("%s: part %s's init %s is not the shared HondaCRVGen1.Cabin.Init" % (fn, part.name, init))
            for p in v.all("part"):
                if p.name in VANILLA_ITEM_PARTS and p.name.startswith("GloveBox") and p.all("model"):
                    fail("%s: part GloveBox draws models again (%s)" % (fn, ", ".join(m.name for m in p.all("model"))))
    print("GAMEDATA cabin: %d vehicle scripts draw the interior from part %s (no item, init %s.Init)"
          % (len(names), gen.CABIN_PART, gen.CABIN_LUA))


def main():
    a = sys.argv[1:]
    mod42 = a[a.index("--mod42") + 1] if "--mod42" in a else gen.CHECKOUT_MOD42
    check_tuning(mod42)
    check_suspension(mod42)
    check_cabin(mod42)
    check_routes(mod42)
    check_literature(mod42)
    check_manual(mod42)
    print("GAMEDATA TESTS OK")


if __name__ == "__main__":
    main()
