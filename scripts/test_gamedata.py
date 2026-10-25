r"""
Game-data checks on the generated mod files (system Python), each one a defect the 2026-10-14 review found:

  1. tuning keys: every top-level key of every CR-V vehicle script is one VehicleScript.Load reads in
     42.21 (gen_scripts.PARSED_KEYS), so no tuning value is silently dead
     (brakingForce was never parsed; frontEndHealth / rearEndHealth are not the parser's names, which are
     frontEndDurability / rearEndDurability), and the end durability is the vanilla SUV's 150 (2026-10-21:
     it only feeds a debug counter in 42.21, but 300 read as "twice a vanilla car" to players);
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
     Bullet's 6000 N limit with a fitted, loaded car, or a hard stop in a corner lands the body on the road;
  7. the trunk (2026-10-22): part TruckBed takes the Base.BigTrunk family (70 instead of 55);
  8. interaction sounds (2026-10-22): doors, tailgate and hood play the vanilla sounds, no CRVGen1 door clips ship.

    python scripts\test_gamedata.py [--mod42 <path to the mod's 42 folder>]
"""
import inspect
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
                if v.get(k) != "150":
                    fail("%s: %s = %s, want the vanilla SUV's 150" % (fn, k, v.get(k)))
    print("GAMEDATA tuning: %d vehicle scripts, every key read by VehicleScript.Load, durability 150 front and rear"
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
    for want in ("Real Time 4WD", "58 liters", "flat floor", "bed", "lift the cargo floor", "picnic table", "50 kg",
                 "jerry can", "jack, a lug wrench, a wrench", "kit comes back", "4x4 Off-Road: CRV Edition",
                 "Armored windows stay shut"):
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


# toughness (2026-10-21, a player: "the durability is crazy, it's like a tank"): a part's `durability` only
# divides a player's weapon damage (CombatManager.calculateDamageToVehicle), vanilla doors / hoods 5, glass 2;
# none of ours may stand out (the armour plates and arch guards were 25 / 20); and the armour-strength
# sandbox option defaults to 1 (the armour soaks as much as the part it covers: ~2x its life)
MAX_PART_DURABILITY = 10


def check_toughness(mod42):
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    worst = 0
    for fn in sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt")):
        root = audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read())
        for v in root.children[0].all("vehicle"):
            for p in v.all("part"):
                d = p.get("durability")
                if d is None:
                    continue
                worst = max(worst, float(d))
                if float(d) > MAX_PART_DURABILITY:
                    fail("%s: part %s durability %s, over %d (vanilla doors 5)" % (fn, p.name, d, MAX_PART_DURABILITY))
                if p.name.startswith("CRVArmour") and float(d) != MAX_PART_DURABILITY:
                    fail("%s: armour part %s durability %s, want %d" % (fn, p.name, d, MAX_PART_DURABILITY))
    sand = open(os.path.join(mod42, "media", "sandbox-options.txt"), encoding="utf-8").read()
    m = re.search(r"option HondaCRVGen1\.ArmourStrength\s*\{(.*?)\}", sand, re.S)
    if not m or not re.search(r"default\s*=\s*1\.0\s*,", m.group(1)):
        fail("sandbox ArmourStrength: want default = 1.0")
    print("GAMEDATA toughness: part durability <= %d (highest %g), armour plates and arch guards %d, ArmourStrength default 1.0"
          % (MAX_PART_DURABILITY, worst, MAX_PART_DURABILITY))


# 7. the trunk (2026-10-22, feedback "increase the trunk space, it has a lot of room"): part TruckBed's item family
# is Base.BigTrunk (BigTrunk1 = 70 at mechanicType 1; the SUV template's Base.NormalTrunk gave 55)
# 8. interaction sounds (2026-10-22, feedback "please remove or add option to toggle the obnoxious car interaction
# sounds"): the doors, the tailgate and the hood play the vanilla templates' sounds, as on the vanilla SUV: no such
# part names one of our CRVGen1 sounds, and neither the sound scripts nor media/sound ship the old door clips
SOUND_PARTS = {"TrunkDoor", "EngineDoor"} | {"Door%s" % s for s in ("FrontLeft", "FrontRight", "RearLeft", "RearRight")}


def _sounds_in(node):
    out = [v for k, v in node.kv if k.lower().startswith("sound")]
    for child in node.children:
        out += _sounds_in(child)
    return out


def check_trunk_and_sounds(mod42):
    """7 (2026-10-24 rework, H-LUA-I5 / H-LUA-4): the trunk takes BigTrunk FIRST and the NormalTrunk family too (a
    pre-0.4.4 car refits its NormalTrunk1, any standard trunk fits), its create is our Trunk.Create (vanilla's would
    roll either family: about half the new cars would get the 55) and its init our Trunk.Init (the old cars' one-off
    upgrade); BigTrunk1 really is the bigger vanilla trunk at mechanicType 1. 8: no door, gate or hood part, and not
    the horn (2026-10-24: vanilla VehicleHornStandard, I-DATA-2), plays a CRVGen1 sound."""
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    names = sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt"))
    shared = os.path.join(mod42, "media", "lua", "shared")
    tl = os.path.join(shared, "HondaCRVGen1_Trunk.lua")
    trunk_lua = open(tl, encoding="utf-8").read() if os.path.exists(tl) else fail("no %s" % tl)
    for fn_name in ("Create", "Init", "TableInstallTest", "TableUninstallTest"):
        if not re.search(r"function\s+Trunk\.%s\s*\(" % fn_name, trunk_lua) or "HondaCRVGen1.Trunk = Trunk" not in trunk_lua:
            fail("HondaCRVGen1_Trunk.lua does not define HondaCRVGen1.Trunk.%s" % fn_name)
    for fn in names:
        root = audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read())
        for v in root.children[0].all("vehicle"):
            beds = [p for p in v.all("part") if p.name == "TruckBed"]
            trunk = [p.get("itemType") for p in beds if p.get("itemType")]
            if trunk[-1:] != ["Base.BigTrunk;Base.NormalTrunk"]:
                fail("%s: vehicle %s part TruckBed itemType %s, want Base.BigTrunk;Base.NormalTrunk" % (fn, v.name, trunk))
            lua = {k: val for p in beds for lb in p.all("lua") for k, val in lb.kv}
            if lua.get("create") != gen.TRUNK_LUA + ".Create" or lua.get("init") != gen.TRUNK_LUA + ".Init":
                fail("%s: vehicle %s part TruckBed lua %s, want %s.Create / .Init" % (fn, v.name, lua, gen.TRUNK_LUA))
            for p in v.all("part"):
                if p.name in SOUND_PARTS:
                    ours = [s for s in _sounds_in(p) if "CRVGen1" in s]
                    if ours:
                        fail("%s: part %s plays our own sounds %s: the vanilla ones are wanted" % (fn, p.name, ours))
            horns = [s.get("horn") for s in v.all("sound") if s.get("horn")]
            if horns[-1:] != ["VehicleHornStandard"]:
                fail("%s: vehicle %s horn %s, want the vanilla VehicleHornStandard" % (fn, v.name, horns))
    cap = vanilla_item_values("MaxCapacity")
    if not (int(cap.get("BigTrunk1", 0)) > int(cap.get("NormalTrunk1", 999)) and int(cap["BigTrunk1"]) == 70):
        fail("vanilla BigTrunk1 / NormalTrunk1 capacity %s / %s: want 70 > 55" % (cap.get("BigTrunk1"), cap.get("NormalTrunk1")))
    sdir = os.path.join(mod42, "media", "scripts", "sounds")
    for fn in os.listdir(sdir) if os.path.isdir(sdir) else []:
        if re.search(r"\bsound\s+CRVGen1Door", open(os.path.join(sdir, fn), encoding="utf-8").read()):
            fail("%s still defines a CRVGen1Door sound" % fn)
    snd = os.path.join(mod42, "media", "sound")
    old = sorted(f for f in os.listdir(snd) if f.startswith("CRVGen1_Door")) if os.path.isdir(snd) else []
    if old:
        fail("media/sound still ships %s" % ", ".join(old))
    # R2-AUD-2 / H-SAVES-I4 (2026-10-24): no dead sounds. The horn is vanilla's, so no CRVGen1Horn entry and no
    # CRVGen1_Horn.ogg; every clip a sound script names is shipped, every shipped clip is named by a sound script,
    # and the polish feature's SOUND_FILES (what it generates and lists as media) is exactly what ships
    defined, clips = [], []
    for fn in os.listdir(sdir) if os.path.isdir(sdir) else []:
        txt = open(os.path.join(sdir, fn), encoding="utf-8").read()
        defined += re.findall(r"\bsound\s+(\w+)", txt)
        clips += re.findall(r"\bfile\s*=\s*media/sound/([\w.]+)", txt)
    if "CRVGen1Horn" in defined:
        fail("a sound script still defines the unused CRVGen1Horn (the horn is vanilla VehicleHornStandard)")
    shipped = sorted(f for f in os.listdir(snd) if f.lower().endswith(".ogg")) if os.path.isdir(snd) else []
    if "CRVGen1_Horn.ogg" in shipped:
        fail("media/sound still ships the unused CRVGen1_Horn.ogg")
    missing = sorted(set(clips) - set(shipped))
    if missing:
        fail("sound scripts name clips that are not shipped: %s" % missing)
    unused = sorted(set(shipped) - set(clips))
    if unused:
        fail("media/sound ships clips no sound script names: %s" % unused)
    from features import polish, _polish_sounds
    if sorted(polish.SOUND_FILES) != shipped:
        fail("polish.SOUND_FILES %s != shipped %s" % (sorted(polish.SOUND_FILES), shipped))
    if hasattr(_polish_sounds, "horn_loop") or "Horn" in inspect.getsource(_polish_sounds.build):
        fail("_polish_sounds still generates the horn")
    print("GAMEDATA trunk + sounds: %d vehicle scripts: TruckBed is Base.BigTrunk (70, made by Trunk.Create) or "
          "Base.NormalTrunk; doors, gate, hood and horn play vanilla sounds (no door clips shipped)" % len(names))


# ---------------------------------------------------------------------------------------------
# wave 1 (2026-10-24): the vanilla game's own rules, read from the installed game (crv_paths.GAME)

def _game_media():
    import crv_paths
    media = crv_paths.GAME_MEDIA
    if not os.path.isdir(os.path.join(media, "scripts")):
        fail("the game's media folder %s is missing (local_paths.json \"game\"): these checks read vanilla's files" % media)
    return media


class SBlock:
    """A script block with its statements in order: elements = [("kv", key, value) | ("block", SBlock)]."""

    def __init__(self, kind, name):
        self.kind, self.name, self.elements = kind, name, []

    def kv(self):
        return [(e[1], e[2]) for e in self.elements if e[0] == "kv"]

    def blocks(self, kind=None):
        return [e[1] for e in self.elements if e[0] == "block" and (kind is None or e[1].kind == kind)]


def parse_ordered(text):
    """PZ script text -> SBlock tree, statement order kept (VehicleScript.Load runs them in order)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)//.*$", "", text)
    root = SBlock("root", "")
    stack, buf = [root], ""
    for ch in text:
        if ch in "{},":
            stmt = buf.strip()
            buf = ""
            if ch == "{":
                kind, _, name = stmt.partition(" ")
                b = SBlock(kind.strip(), name.strip())
                stack[-1].elements.append(("block", b))
                stack.append(b)
                continue
            if stmt and "=" in stmt:
                k, _, v = stmt.partition("=")
                stack[-1].elements.append(("kv", k.strip(), v.strip()))
            if ch == "}" and len(stack) > 1:
                stack.pop()
        else:
            buf += ch
    return root


_VANILLA = {}


def vanilla_scripts():
    """{"templates": {name: SBlock}, "items": {name: SBlock}} over the game's media/scripts."""
    if _VANILLA:
        return _VANILLA
    templates, items = {}, {}
    for dp, _d, fs in os.walk(os.path.join(_game_media(), "scripts")):
        for f in fs:
            if not f.endswith(".txt"):
                continue
            root = parse_ordered(open(os.path.join(dp, f), encoding="utf-8", errors="replace").read())
            for mod in root.blocks("module"):
                for b in mod.blocks():
                    if b.kind == "template" and b.name.startswith("vehicle "):
                        templates[b.name[len("vehicle "):].strip()] = b
                    elif b.kind == "item":
                        items[b.name] = b
    _VANILLA.update(templates=templates, items=items)
    return _VANILLA


def vanilla_item_values(key):
    return {n: v for n, b in vanilla_scripts()["items"].items() for k, v in b.kv() if k == key}


class Rules:
    """What VehicleScript.Load makes of a vehicle's part tables (42.21 bytecode, 2026-10-24): `template! = X` runs X's
    body in place; `template = X` copies every part of template X, `template = X/part/P` that one part
    (copyPartsFrom: the copy REPLACES a part of the same id); `part P*` merges into every part already there whose id
    matches the glob, `part P` into P (made if new); a table block merges its keys into the part's table of that name
    (LoadTable rawsets each key; an empty value removes it)."""

    def __init__(self):
        self.parts = {}

    def load(self, block):
        import copy
        import fnmatch
        templates = vanilla_scripts()["templates"]
        for e in block.elements:
            if e[0] == "kv":
                k, v = e[1], e[2]
                if k == "template!" and v in templates:
                    self.load(templates[v])
                elif k == "template":
                    name, _, rest = v.partition("/")
                    kind, _, pid = rest.partition("/")
                    if name not in templates or (rest and kind != "part"):
                        continue
                    src = template_rules(name)
                    for sid, part in src.parts.items():
                        if not rest or pid in ("*", sid):
                            self.parts[sid] = copy.deepcopy(part)
            elif e[1].kind == "part":
                pb = e[1]
                ids = [p for p in self.parts if fnmatch.fnmatchcase(p, pb.name)] if "*" in pb.name else [pb.name]
                for pid in ids:
                    tables = self.parts.setdefault(pid, {})
                    for tb in pb.blocks("table"):
                        t = tables.setdefault(tb.name, {})
                        for k, v in tb.kv():
                            if v:
                                t[k] = v
                            else:
                                t.pop(k, None)
        return self


_TEMPLATE_RULES = {}


def template_rules(name):
    if name not in _TEMPLATE_RULES:
        _TEMPLATE_RULES[name] = Rules().load(vanilla_scripts()["templates"][name])
    return _TEMPLATE_RULES[name]


RULE_KEYS = ("skills", "recipes")


def check_install_rules(mod42):
    """H-DATA-1: the CR-V is mechanicType 1 (standard), so every part it shares with a vanilla standard car (the
    CarNormal template) installs and uninstalls under that car's rules (Mechanics level, Basic Mechanics), not
    the heavy-duty ones `template! = SUV` brings in (Seat* 2, GasTank 7, Brake* / Suspension* 6, Intermediate
    Mechanics)."""
    ref = template_rules("CarNormal")
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    names = sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt"))
    compared = set()
    for fn in names:
        root = parse_ordered(open(os.path.join(vdir, fn), encoding="utf-8").read())
        for mod in root.blocks("module"):
            for v in mod.blocks("vehicle"):
                ours = Rules().load(v)
                bad = []
                for pid, tables in sorted(ref.parts.items()):
                    if pid not in ours.parts:
                        continue
                    for kind in ("install", "uninstall"):
                        want = {k: tables.get(kind, {}).get(k) for k in RULE_KEYS}
                        got = {k: ours.parts[pid].get(kind, {}).get(k) for k in RULE_KEYS}
                        if want != got:
                            bad.append("%s %s %s (standard car: %s)" % (pid, kind, got, want))
                        compared.add(pid)
                if bad:
                    fail("%s: vehicle %s installs like a heavy-duty car: %s" % (fn, v.name, "; ".join(bad)))
    for must in ("SeatFrontLeft", "SeatRearRight", "GasTank", "Muffler", "BrakeFrontLeft", "SuspensionRearRight",
                 "DoorFrontLeft", "Windshield", "EngineDoor", "TrunkDoor"):
        if must not in compared:
            fail("install rules: part %s was never compared (the replay lost it)" % must)
    print("GAMEDATA install rules: %d vehicle scripts: %d parts shared with the standard car (CarNormal) take its "
          "Mechanics levels and recipes" % (len(names), len(compared)))


FIX_SKILLS = {"Mechanics", "MetalWelding", "Tailoring"}


def check_fixing(mod42):
    """H-DATA-2: every item a repairMechanic part of a CR-V script takes has a fixing (the mechanics screen offers
    Repair only through one), no fixing targets a vanilla item (it would change that item everywhere: the jerry can
    parts are not repairMechanic), every item a fixing names exists (ours or vanilla), skills are perk names."""
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    texts = [open(os.path.join(vdir, f), encoding="utf-8").read()
             for f in sorted(os.listdir(vdir)) if f.startswith(gen.VEHICLE) and f.endswith(".txt")]
    need = gen.repair_items(texts)
    if len(need) < 20:
        fail("only %d repairable part items found: the repairMechanic scan is broken" % len(need))
    path = os.path.join(mod42, "media", *gen.FIXING_OUT)
    if not os.path.exists(path):
        fail("no fixing scripts at %s" % path)
    ours = {"Base." + it.name for it in audit_mod.parse(open(os.path.join(mod42, "media", "scripts", "items",
            "%s_items.txt" % gen.VEHICLE), encoding="utf-8").read()).children[0].all("item")}
    vanilla = {"Base." + n for n in vanilla_scripts()["items"]}
    covered = set()
    fixes = audit_mod.parse(open(path, encoding="utf-8").read()).children[0].all("fixing")
    for fx in fixes:
        req = [r.strip() for r in (fx.get("Require") or "").split(";") if r.strip()]
        alien = [r for r in req if not r.startswith("Base.CRVGen1_")]
        if alien:
            fail("fixing %s targets vanilla items %s: it would change them everywhere in the game (we never alter "
                 "vanilla items: make their parts repairMechanic = false)" % (fx.name, ", ".join(alien)))
        covered |= set(req)
        named = req + [fx.get("GlobalItem").split("=")[0].strip()] if fx.get("GlobalItem") else list(req)
        for k, val in fx.kv:
            if k != "Fixer":
                continue
            item, *skills = [s.strip() for s in val.split(";")]
            named.append(item.split("=")[0].strip())
            for s in skills:
                if s.split("=")[0].strip() not in FIX_SKILLS:
                    fail("fixing %s: skill %r is not one of %s" % (fx.name, s, sorted(FIX_SKILLS)))
        for it in named:
            if it not in ours and it not in vanilla:
                fail("fixing %s names %s, which no script defines" % (fx.name, it))
    missing = [it for it in need if it not in covered]
    if missing:
        fail("repairable part items with no fixing (no Repair in the mechanics screen): %s" % ", ".join(missing))
    # I-DIFF-2: the picnic table is folding furniture: never welded or patched with sheet metal, only taped, glued
    # or screwed, in a fixing of its own
    for it in sorted(gen.FIX_TABLE):
        if it not in need:
            fail("%s is no longer a repairable part item: drop it from gen_scripts.FIX_TABLE" % it)
        holding = [fx for fx in fixes if it in [r.strip() for r in (fx.get("Require") or "").split(";")]]
        for fx in holding:
            used = [(fx.get("GlobalItem") or "").split("=")[0].strip()] + \
                   [v.split(";")[0].split("=")[0].strip() for k, v in fx.kv if k == "Fixer"]
            metal = [u for u in used if u in ("Base.BlowTorch", "Base.SheetMetal", "Base.SmallSheetMetal")]
            if metal:
                fail("fixing %s repairs %s with %s: a folding table takes duct tape, glue or screws"
                     % (fx.name, it, ", ".join(metal)))
            if [r.strip() for r in fx.get("Require").split(";") if r.strip()] != [it]:
                fail("fixing %s mixes %s with other items: the table has a fixing of its own" % (fx.name, it))
            if not {"Base.DuctTape", "Base.Glue", "Base.Screws"} <= set(used):
                fail("fixing %s for %s offers %s, want duct tape, glue and screws" % (fx.name, it, used))
        if len(holding) != 1:
            fail("%s is in %d fixings, want exactly its own one" % (it, len(holding)))
    print("GAMEDATA fixing: %d repairable part items, every one in one of %d fixing scripts" % (len(need), len(fixes)))


def check_loot_lists(mod42):
    """H-DATA-3: every procedural list the mod's loot goes into is one a vanilla room / container fills from
    (a {name="<list>", ...} entry in the game's distribution Lua): 42.21 never rolls CarSupplyMagazines,
    MechanicShelfMisc or ArmyHangarMechanics, so loot put there never spawned."""
    loot = open(os.path.join(mod42, "media", "lua", "server", "Items", "%s_Loot.lua" % gen.VEHICLE), encoding="utf-8").read()
    lists = sorted(set(re.findall(r'\{ list = "(\w+)", item = "[\w.]+", weight', loot)))
    if len(lists) < 5:
        fail("loot Lua: only %d lists parsed" % len(lists))
    used, defined = set(), set()
    for dp, _d, fs in os.walk(os.path.join(_game_media(), "lua")):
        for f in fs:
            if not f.endswith(".lua"):
                continue
            text = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
            if f == "ProceduralDistributions.lua":
                defined |= set(re.findall(r"(?m)^\t(\w+)\s*=\s*\{", text))
            else:
                used |= set(re.findall(r'name\s*=\s*"(\w+)"', text))
    dead = [l for l in lists if l not in used or l not in defined]
    if dead:
        fail("loot lists no vanilla room or container fills from: %s" % ", ".join(dead))
    print("GAMEDATA loot: %d procedural lists, every one defined and filled by a vanilla room / container" % len(lists))


def check_table_and_tiles(mod42):
    """H-FEATURES-5: the picnic table's install / uninstall tests are Trunk.TableInstallTest / TableUninstallTest (gate
    open or gone). H-DATA-5: every tile Material is a scrap definition of the game's ISMoveableDefinitions."""
    vdir = os.path.join(mod42, "media", "scripts", "vehicles")
    for fn in sorted(f for f in os.listdir(vdir) if f.startswith(gen.VEHICLE) and f.endswith(".txt")):
        for v in audit_mod.parse(open(os.path.join(vdir, fn), encoding="utf-8").read()).children[0].all("vehicle"):
            tables = {t.name: t for p in v.all("part") if p.name == "CRVPicnicTable" for t in p.all("table")}
            want = {"install": gen.TRUNK_LUA + ".TableInstallTest", "uninstall": gen.TRUNK_LUA + ".TableUninstallTest"}
            got = {k: tables[k].get("test") if k in tables else None for k in want}
            if got != want:
                fail("%s: part %s tests %s, want %s (the gate must be open)" % (fn, "CRVPicnicTable", got, want))
    import tilepack
    defs = open(os.path.join(_game_media(), "lua", "shared", "Moveables", "ISMoveableDefinitions.lua"),
                encoding="utf-8", errors="replace").read()
    scrap = set(re.findall(r'addScrapDefinition\(\s*"(\w+)"', defs))
    tiles = os.path.join(os.path.dirname(mod42), "common", "media", tilepack.PACK_NAME + ".tiles")
    _ver, sheets = tilepack.parse_tiles(tiles)
    mats = sorted({val for sh in sheets for props in sh[5] for k, val in props if k.startswith("Material")})
    bad = [m for m in mats if m not in scrap]
    if bad or not mats:
        fail("tile Material %s is not a vanilla scrap definition (%d known)" % (bad or "none", len(scrap)))
    print("GAMEDATA picnic table: gate-open install / uninstall tests; tile materials %s are vanilla scrap definitions"
          % ", ".join(mats))


GAME_FACTS = (42, 21)        # the build the mod's game facts (bytecode, scripts, Lua) were read from


def check_translate_files_and_version(mod42):
    """I-DATA-1: 42.21 reads Translate/EN/*.json only, no IG_UI_EN.txt ships. I-DATA-5: mod.info's versionMin is
    the build the facts were checked against (nothing was verified on 42.15)."""
    old = os.path.join(mod42, "media", "lua", "shared", "Translate", "EN", "IG_UI_EN.txt")
    if os.path.exists(old):
        fail("%s still ships (42.21 reads the JSON files)" % old)
    info = open(os.path.join(mod42, "mod.info"), encoding="utf-8").read()
    m = re.search(r"(?m)^versionMin=(\d+)\.(\d+)", info)
    if not m or (int(m.group(1)), int(m.group(2))) != GAME_FACTS:
        fail("mod.info versionMin %s, want %d.%d (the build the game facts were checked against)"
             % (m and m.group(0), GAME_FACTS[0], GAME_FACTS[1]))
    print("GAMEDATA translations JSON only (no IG_UI_EN.txt); versionMin %d.%d" % GAME_FACTS)


def main():
    a = sys.argv[1:]
    mod42 = a[a.index("--mod42") + 1] if "--mod42" in a else gen.CHECKOUT_MOD42
    check_tuning(mod42)
    check_toughness(mod42)
    check_suspension(mod42)
    check_cabin(mod42)
    check_routes(mod42)
    check_literature(mod42)
    check_manual(mod42)
    check_trunk_and_sounds(mod42)
    check_install_rules(mod42)
    check_fixing(mod42)
    check_loot_lists(mod42)
    check_table_and_tiles(mod42)
    check_translate_files_and_version(mod42)
    print("GAMEDATA TESTS OK")


if __name__ == "__main__":
    main()
