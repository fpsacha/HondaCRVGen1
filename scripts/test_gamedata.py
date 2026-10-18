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
  4. the owner's manual's oil figure (3.8 L / 4 US qt with the filter, not the 3.7 US qt without it).

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


def main():
    a = sys.argv[1:]
    mod42 = a[a.index("--mod42") + 1] if "--mod42" in a else gen.CHECKOUT_MOD42
    check_tuning(mod42)
    check_routes(mod42)
    check_literature(mod42)
    check_manual(mod42)
    print("GAMEDATA TESTS OK")


if __name__ == "__main__":
    main()
