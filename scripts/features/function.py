r"""
Function feature (spec/feature-roadmap.md "Function and polish"): the fold-flat rear seats (their look and
their bigger load floor), the hidden under-floor storage, the sandbox options (spawn rate, accessory chance,
loot rarity), the owner's manual. Parts without an item, an item with a hand-made icon, the rear seats'
two models, Lua, translations, loot.

Parts (every CR-V vehicle script, category nodisplay so the mechanics list leaves them out, no item):
  CRVFunctionCargo        the folded load floor, open only while the rear seats are folded as a load floor
  CRVFunctionUnderfloor   the storage well under the cargo floor, hidden until the floor is lifted
  CRVFunctionSeats        the rear bench, drawn upright (InteriorSeatsUp) or folded (InteriorSeatsFolded), and the
                          bedding on it in fold mode "bed" (InteriorBedding)
Lua: shared/HondaCRVGen1_Function.lua (namespace HondaCRVGen1.Function: container tests, Init, the
seats' look, the manual's XP bonus), shared/TimedActions/ISCRVFunctionLiftFloor.lua,
client/HondaCRVGen1_FunctionMenu.lua, server/HondaCRVGen1_FunctionServer.lua (the manual in the glove
box). Core files this feature changed (the fold's multiplayer fix, spawn zones and scaling, the loot
slider, the seats' bake and pzview hooks) say so where they changed.

Folded seats must LOOK folded (2026-10-14, chose fold-flat). The rear bench used to be part of the
static cabin mesh, upright whatever the state. build_cabin now leaves it out of `cabin` and its full-detail
twin while this feature is active (BUILD still lifts out any faces tagged REAR_SEAT_ATTR, e.g. from a parts
file built without the feature) and BUILD builds it twice with build_cabin's own seat code, upright
and folded as the RD1 folds (owner's manual: seat bottom tilted forward, head restraint strapped behind
it, seat-back pivoted down flat, level with the cargo deck): acc_function_seats_up / _fold, each with its
own `_hi` twin, on the interior sheet. Both are models of part CRVFunctionSeats (setAllModelsVisible =
false: nothing but the Lua shows them), and a HondaCRVGen1.State listener on function_folded shows
exactly one of them wherever the car is drawn. The twins carry crv_variant = "rear_seats" (bake_atlas:
one variant never shades another; the upright one, crv_variant_default, shades the car as the bench
always did). pzview draws the upright bench, `--folded` the folded one.

The folded model is a made-up bed (2026-10-19, "make the folded bed LOOK like a bed"): build_cabin.bed_set adds a
thin foam pad over the folded backs and the cargo deck (bridging the riser gap and the picnic table's tub, which it
hides when the table is out), an open rectangular sleeping bag with its top turned back, and a pillow at the front
end, ~250 coarse triangles (twin ~1,700) in materials of their own (build_cabin.BED_MATS; BAKE_TEXTURED below).

Load floor or bed (2026-10-22, the owner: "if the seats are folded, I want to have more trunk space or a bed, should
be able to choose"): the bedding is its own model now, InteriorBedding (build_cabin.rear_bedding ->
acc_function_bedding, the same triangles that rode the folded model), and the fold has a mode (State key
function_foldMode, "cargo" | "bed", default "bed" = every car folded before). Cargo: the bare folded seats, the load
floor CRVFunctionCargo open, no bed. Bed: the bedding drawn, the good-bed sleep rule, the load floor shut. pzview
`--folded` draws the bed, `--folded --fold-mode cargo` the load floor.

A pillow counts on the bed (client/HondaCRVGen1_Menu.lua, getBedQuality): in hand, in the sleeper's seat container
(vanilla's own vehicle rule) or on the cargo deck (TruckBed); not on the folded load floor (CRVFunctionCargo), which
is shut and empty while it is a bed.

The icon is drawn by scripts/function_icon.py (our own pixel art) and shipped as MEDIA.
"""

CARGO_CAPACITY = 60          # keep equal to HondaCRVGen1.Function.CARGO_CAPACITY
FLOOR_CAPACITY = 10
LUA_NS = "HondaCRVGen1.Function"
MANUAL = "CRVGen1_OwnersManual"
KNOW_HOW = "HondaCRVKnowHow"              # the manual's marker recipe (like vanilla's Herbalist), HondaCRVGen1.Function.KNOW_HOW


def _container_part(part, capacity, test):
    t = "\t\t\t"
    return "\n".join([
        "\t\tpart %s" % part, "\t\t{",
        "%sarea = TruckBed," % t,
        "%scategory = nodisplay," % t,
        "%smechanicRequireKey = false," % t,
        "%scontainer" % t, "%s{" % t,
        "%s\tcapacity = %d," % (t, capacity),
        "%s\tconditionAffectsCapacity = false," % t,
        "%s\ttest = %s.%s," % (t, LUA_NS, test),
        "%s\tsoundMap = ContainerPut VehicleTrunkTransferItem," % t,
        "%s\tsoundMap = ContainerTake VehicleTrunkTransferItem," % t,
        "%s}" % t,
        "%slua" % t, "%s{" % t,
        "%s\tinit = %s.Init," % (t, LUA_NS),
        "%s}" % t,
        "\t\t}"])


# ------------------------------------------------------------------------------------- the rear seats
SEATS_PART = "CRVFunctionSeats"                     # HondaCRVGen1.Function.SEATS_PART
SEATS_UP, SEATS_FOLD = "acc_function_seats_up", "acc_function_seats_fold"
SEATS_BED = "acc_function_bedding"                  # the made-up bed on the folded seats (fold mode "bed" only)
# model ids (HondaCRVGen1.Function.SEAT_MODELS; 'Interior' in the name: pzview's cabin ID pass paints them
# with the cabin, as the bench was) -> mesh
SEAT_MODELS = (("InteriorSeatsUp", SEATS_UP), ("InteriorSeatsFolded", SEATS_FOLD), ("InteriorBedding", SEATS_BED))
OBJECTS = {SEATS_UP: {"space": "interior"}, SEATS_FOLD: {"space": "interior"}, SEATS_BED: {"space": "interior"}}
VARIANT_SET = "rear_seats"                          # bake_atlas._bake_hilo: crv_variant / crv_variant_default
# the made-up bed's materials (build_cabin.BED_MATS; base colours in build_cabin.MATERIALS, taken as they are): a
# faint grain on the foam, the nylon and the cotton, a two-pitch weave on the flannel lining (5.0 / 3.2 cm: 3+
# texels a period at ~1 texel/cm, no moire)
BAKE_TEXTURED = {
    "BedPad": [("noise", 60.0, 0.05)],
    "BedBag": [("noise", 35.0, 0.05)],
    "BedLining": [("stripes", 0.050, 0.16), ("stripes", 0.032, 0.08)],
    "BedPillow": [("noise", 45.0, 0.03)],
}
BAKE_MAT_WEIGHTS = {"BedPad": 0.5, "BedBag": 0.7, "BedLining": 0.8, "BedPillow": 0.7}


def BUILD(report):
    import bmesh
    import bpy
    import build_cabin
    # 1. the bench out of the static cabin, coarse and twin (one tag, set where build_cabin builds it)
    coll = None
    for name in ("cabin", "cabin_hi"):
        ob = bpy.data.objects.get(name)
        if ob is None:
            raise RuntimeError("function: no %s to lift the rear bench out of" % name)
        me = ob.data
        if name == "cabin":
            coll = ob.users_collection[0]
        attr = me.attributes.get(build_cabin.REAR_SEAT_ATTR)
        if attr is None:                    # build_cabin leaves the bench out while this feature is active
            report("FEATURE function: %s has no rear bench to lift out (build_cabin left it to the seat models)" % name)
            continue
        vals = [0] * len(me.polygons)
        attr.data.foreach_get("value", vals)
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        gone = [bm.faces[i] for i, v in enumerate(vals) if v]
        bmesh.ops.delete(bm, geom=gone, context='FACES')
        bm.to_mesh(me)
        bm.free()
        me.attributes.remove(me.attributes[build_cabin.REAR_SEAT_ATTR])
        me.update()
        report("FEATURE function: rear bench lifted out of %s (%d faces, %d left)" % (name, len(gone), len(me.polygons)))
    # 2. the bench twice, upright and folded: coarse (ships) and full twin (the bake's projection source)
    for pose, name in (("up", SEATS_UP), ("fold", SEATS_FOLD)):
        hi = build_cabin.rear_seats(pose, True, name + "_hi", coll)
        low = build_cabin.rear_seats(pose, False, name, coll)
        hi["crv_variant"] = VARIANT_SET
        if pose == "up":
            hi["crv_variant_default"] = 1
        hi.hide_render = True
        hi.hide_set(True)
        report("FEATURE function: %s %d tris (twin %d)" % (name, sum(len(p.vertices) - 2 for p in low.data.polygons),
                                                         sum(len(p.vertices) - 2 for p in hi.data.polygons)))
    # 3. the bedding on the folded seats, its own model (2026-10-22: folded = a load floor or a bed). Its twin is one
    # of the bench's variants (never shades the upright bench) that bakes WITH the folded bench under it
    # (crv_variant_with: the contact shade where it lies on the backs); the folded bench bakes without it, as the
    # load floor shows it
    hi = build_cabin.rear_bedding(True, SEATS_BED + "_hi", coll)
    low = build_cabin.rear_bedding(False, SEATS_BED, coll)
    if hi is not None and low is not None:
        hi["crv_variant"] = VARIANT_SET
        hi["crv_variant_with"] = SEATS_FOLD + "_hi"
        hi.hide_render = True
        hi.hide_set(True)
        report("FEATURE function: %s %d tris (twin %d)" % (SEATS_BED, sum(len(p.vertices) - 2 for p in low.data.polygons),
                                                         sum(len(p.vertices) - 2 for p in hi.data.polygons)))


def MODELS(gen):
    return [gen.model_block(gen.acc_model_name(geo), "crvgen1_" + geo, texture="%s_Interior" % gen.TEX, shader="vehiclewheel")
            for _mid, geo in SEAT_MODELS]


def _seats_part(gen):
    t = "\t\t\t"
    lines = ["\t\tpart %s" % SEATS_PART, "\t\t{"]
    for mid, geo in SEAT_MODELS:
        lines += ["%smodel %s" % (t, mid), "%s{" % t, "%s\tfile = %s," % (t, gen.acc_model_name(geo)), "%s}" % t]
    lines += ["%scategory = nodisplay," % t,
              "%ssetAllModelsVisible = false," % t,          # no item: the Lua alone shows one of the two
              "%slua" % t, "%s{" % t, "%s\tinit = %s.Init," % (t, LUA_NS), "%s}" % t, "\t\t}"]
    return "\n".join(lines)


def VEHICLE_PARTS(gen, vehicle):
    return [_container_part("CRVFunctionCargo", CARGO_CAPACITY, "CargoAccess"),
            _container_part("CRVFunctionUnderfloor", FLOOR_CAPACITY, "UnderfloorAccess"),
            _seats_part(gen)]


ITEMS = {
    MANUAL: {
        "DisplayCategory": "RecipeResource",
        "ItemType": "base:literature",
        "Weight": 0.3,
        "Icon": MANUAL,
        "DisplayName": "Honda CRV Owner's Manual",
        "BoredomChange": -5,
        "LearnedRecipes": "Basic Mechanics;%s" % KNOW_HOW,
        "Tooltip": "Tooltip_CRV_Function_Manual",
        "StaticModel": "BookGrey",
        "WorldStaticModel": "BookClosedGrey_Ground",
        # like every vanilla recipe magazine: sets modData.literatureTitle, so ISReadABook puts re-reads on the
        # LiteratureCooldown instead of giving the boredom relief every time
        "OnCreate": "HondaCRVGen1.Function.OnCreateManual",      # the vanilla recipe-magazine OnCreate + the printMedia mod data
    },
}

SANDBOX = [
    {"name": "FunctionSpawnRate", "type": "integer", "default": 100, "min": 0, "max": 500,
     "label": "CRV spawn rate (percent)",
     "tooltip": "How often the CRV turns up in driveways, suburbs, farms, parking lots and traffic jams. "
                "100 is the mod's normal rate, 0 none at all."},
    {"name": "FunctionAccessoryChance", "type": "integer", "default": 100, "min": 0, "max": 500,
     "label": "CRV accessory chance (percent)",
     "tooltip": "Scales the chance that a spawned CRV carries accessories (bull bar, roof rack, window guards, "
                "spare tire cover, and the off-road snorkel, skid plate, rear bumper, ladder and jerry cans). "
                "100 is normal, 0 bare cars. The picnic table is standard equipment."},
    {"name": "FunctionLootRarity", "type": "double", "default": 1.0, "min": 0.0, "max": 4.0,
     "label": "CRV loot multiplier",
     "tooltip": "Multiplies how often the CRV's kits, armor, magazines and owner's manuals are found as loot. "
                "1 is normal, 0 never, 4 four times as often."},
]

# the manual where car people keep paper: dealer desks, car-supply shops, automotive book shelves, garages
# (weights before the loot slider's headroom, gen_scripts.LOOT_RARITY)
DISTRIBUTIONS = [
    {"list": "CarDealerDesk", "item": "Base." + MANUAL, "weight": 2},
    {"list": "CarSupplyLiterature", "item": "Base." + MANUAL, "weight": 3},   # 2 + the 1 that sat in the unused CarSupplyMagazines
    {"list": "BookstoreAutomotive", "item": "Base." + MANUAL, "weight": 1},
    {"list": "MechanicShelfBooks", "item": "Base." + MANUAL, "weight": 0.5},
    {"list": "GarageMechanics", "item": "Base." + MANUAL, "weight": 0.3},
]

# The manual's text, in-universe (2026-10-17, feedback: "remove some real life info ... more info related to the game
# and the feature of the mod ... keep it all RP"): what the car does in the game, told the way its manual, a dealer
# sheet and the last owner's notes would tell it. Two text pages per spread; the designed spreads are drawn by
# scripts/manual_art.py and say the same things.
_PAGES = [
    " <H2> Welcome to your CRV <LINE> <TEXT> Thank you for choosing Honda. Your CRV drives like a car on the highway and "
    "keeps going when the road gives out: Real Time 4WD sends power to the rear wheels the moment the front ones slip. "
    "Inside it is more practical than it looks: the rear seats fold into a flat floor and a bed, the cargo floor lifts out "
    "as a picnic table, and under it is a storage well. Four seats, a 2.0-liter twin-cam engine, regular fuel, 58 liters "
    "in the tank with the filler on the left. Read this manual once, front to back: a mechanic who has read it learns "
    "more from every part fitted, removed or repaired on a CRV. Keep it in the glove box.",

    " <H2> Driving <LINE> <TEXT> Most of the time your CRV drives its front wheels. On ice, mud or loose gravel, the rear "
    "wheels join in by themselves, within moments, and let go again when grip comes back: no lever, nothing to engage. "
    "Paved roads, gravel, dirt tracks, fields and snow are home ground; rocks and deep mud are not. Slow down off the "
    "pavement: the springs are soft and the tires are road tires. Look after the timing belt: if it breaks, the engine "
    "is ruined. A full roof and armor make the car slower to stop, so brake early.",

    " <H2> Rear seats and a night in the car <LINE> <TEXT> Fold the seatbacks down and tumble the seats: the back of the cabin "
    "becomes one long, flat floor, about twice the cargo area, or, made up as a bed, a far better bed than any back seat. Both rear seats "
    "must be in the car and empty, and nobody can sit in the back while they are folded; clear the floor before you put "
    "them back up. For a night in the car: fold the seats before dark, lock up with the windows up, take the picnic table "
    "out for supper and put it back before you drive on, and keep a full jerry can for the morning. The full-size spare "
    "rides on the back; a jack and a lug wrench change a wheel.",

    " <H2> Picnic table, storage well, roof <LINE> <TEXT> Open the tailgate and lift the cargo floor: under it is a well "
    "for the things you would rather keep out of sight, and once you know it is there it is yours to use. The floor panel "
    "has folding legs: take it out, set it up as a table wherever you stop, and put it back before you drive on. The roof "
    "rack takes up to 50 kg, strapped down where everyone can see it. Two jerry cans fit, one on the spare and one on the "
    "rack, and they hold real fuel.",

    " <H2> Accessories and modifications <LINE> <TEXT> From your dealer: the bull bar and the roof rack bolt on with a "
    "wrench, the windshield, window and rear glass guards with a screwdriver, the spare tire cover by hand. Aftermarket: "
    "a snorkel, a steel skid plate, a rear steel bumper with a hitch, a roof ladder and jerry cans, each bolted on and off "
    "again. The Kestrel Trail Claw 3-inch lift puts the car on 30-inch all-terrain tires, on the EX alloys or on black "
    "steel wheels; fitting it takes a jack, a lug wrench, a wrench and an experienced mechanic, with the engine off and "
    "everyone out, and the kit comes back if you take it off. The plans are in \"4x4 Off-Road: CRV Edition\".",

    " <H2> Notes in the back of the manual <LINE> <TEXT> Taped in from \"Survival Armor\": door plates, window mesh, "
    "wheel arch guards and a rear glass plate, welded at a workbench and bolted on with a wrench and a screwdriver. "
    "Armored windows stay shut, and nothing gets an arm in. The steel wears down as it takes the hits, and every plate "
    "makes the car heavier. In pen: plates done at Al's in October; check them after every run. Glove box lid sticks: "
    "lift it and pull. Slept in it three nights at the lake. Storage well: spare keys, flashlight, the good tape.",
]

# The manual is PRINT MEDIA like vanilla's newspapers and magazines, three spreads (one texture each, drawn by
# scripts/manual_art.py at vanilla's spread size). Each spread is its own print media id: the first is the item's
# (reading it opens that one), the client window's page buttons turn to the others (FunctionMenu.lua). Format:
# Print_Media.json (title + layout), Print_Text.json (the text behind the window's text button; "\n" is a newline,
# as in vanilla), item mod data printMedia.
SPREADS = [("CRVGen1_Manual", "CRVGen1_Manual.png", "Welcome and driving", (0, 1)),
           ("CRVGen1_Manual2", "CRVGen1_Manual_2.png", "Load space", (2, 3)),
           ("CRVGen1_Manual3", "CRVGen1_Manual_3.png", "Accessories and modifications", (4, 5))]
PM_ID = SPREADS[0][0]


def _info(png):
    path = "media/textures/printMedia/" + png
    return "<type:parent, width:1616, height:1131><type:texture, texture:%s, x:0, y:0, width:1616, height:1131>" % path


def _plain(page):
    import re
    head = re.search(r"<H2>\s*([^<]+)", page, re.I)
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", re.sub(r"<H2>[^<]*", "", page, flags=re.I))).strip()
    return (head.group(1).strip().upper() + NL if head else "") + body


NL = "\\n"       # a literal backslash and n: the print window turns it into a line break (as vanilla's Print_Text.json)
PM_INFO = _info(SPREADS[0][1])


def _spread_text(i):
    sid, png, title, pages = SPREADS[i]
    return ("HONDA CRV OWNER'S MANUAL  -  %s (%d of %d)" % (title.upper(), i + 1, len(SPREADS)) + NL + NL
            + (NL + NL).join(_plain(_PAGES[k]) for k in pages))


PM_TEXT = _spread_text(0)


def _manual_page_strings():
    """The words on the spreads (H-SAVES-I5): scripts/manual_art.py draws the art without them and writes each string
    with its key (Print_Text_CRVGen1_ManualPage_<id>) to manual_strings.json; client/HondaCRVGen1_FunctionMenu.lua lays
    getText(key) over the art. "**word**" runs are bold; a translation keeps the markers."""
    import json
    import os
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_strings.json"), encoding="utf-8") as f:
        return json.load(f)


TRANSLATIONS = {
    "Print_Media": dict(kv for i, (sid, png, title, _p) in enumerate(SPREADS) for kv in (
        ("Print_Media_%s_title" % sid, "Honda CRV Owner's Manual: %s (%d of %d)" % (title, i + 1, len(SPREADS))),
        ("Print_Media_%s_info" % sid, _info(png)))),
    "Print_Text": dict({"Print_Text_%s_info" % sid: _spread_text(i) for i, (sid, _png, _t, _p) in enumerate(SPREADS)},
                       **_manual_page_strings()),
    "IG_UI": dict({
        "IGUI_VehiclePartCRVFunctionCargo": "Load Floor (seats folded)",
        "IGUI_VehiclePartCRVFunctionUnderfloor": "Under-floor Storage",
        "IGUI_VehiclePartCRVFunctionSeats": "Rear Seats",
        "IGUI_CRV_Function_CargoNotEmpty": "Clear the folded load floor first",
        "IGUI_CRV_Function_SeatsAreFolded": "The rear seats are folded flat",
        "IGUI_CRV_Function_FloorFound": "A storage well under the cargo floor",
        "IGUI_CRV_Function_FloorAlreadyFound": "The storage well is already open",
        "IGUI_CRV_Function_Manual_Title": " <CENTRE> <H1> HONDA CRV <LINE> <TEXT> Owner's Manual, 1997-2001 <LEFT> ",
    }, **{"IGUI_CRV_Function_Manual_Page%d" % (i + 1): p for i, p in enumerate(_PAGES)}),
    "ContextMenu": {
        "ContextMenu_CRV_Function_LiftFloor": "Lift the cargo floor",
        "ContextMenu_CRV_Function_BrowseManual": "Browse the owner's manual",
    },
    "Recipes": {KNOW_HOW: "Honda CRV Know-How"},
    "Tooltip": {
        "Tooltip_Recipe_" + KNOW_HOW: "How the first CRV goes together: more Mechanics experience from work on a CRV.",
        "Tooltip_CRV_Function_Manual": "Honda's owner's manual for the first CRV.<br>Reading it teaches Basic Mechanics, "
                                       "and how this car goes together:<br>more Mechanics experience from work on a CRV.",
    },
}

LUA = ["shared/HondaCRVGen1_Function.lua", "shared/TimedActions/ISCRVFunctionLiftFloor.lua",
       "client/HondaCRVGen1_FunctionMenu.lua", "client/HondaCRVGen1_ManualLayout.lua", "server/HondaCRVGen1_FunctionServer.lua", "server/HondaCRVGen1_BedServer.lua"]
MEDIA = (["common/media/textures/Item_%s.png" % MANUAL] + ["common/media/textures/printMedia/" + png for _i, png, _t, _p in SPREADS]
         + ["common/media/textures/CRVGen1_ManualPrev.png", "common/media/textures/CRVGen1_ManualNext.png"])
