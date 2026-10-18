r"""
Static audit of the mod folder (system Python, no Blender):

    python scripts\audit_mod.py

Checks every reference the vehicle script makes resolves to something that ships: model blocks named
by parts, mesh files and the geometry names inside them (binary FBX scanned for its Geometry
nodes), textures (skins, mask, lights, rust, model textures), shaders (mod or game), the mechanics
overlay images its Lua names, and mod.info's poster; common/media/spriteModels.txt's tilesets, tiles
and model scripts (sprite_models). Accessories: every mod item a part installs is
declared, every item icon ships, every HondaCRVGen1.Acc.* hook the script names is defined in the
mod's Lua, and the JSON translations parse and name every accessory part and item. Prints
`AUDIT ok` or one `AUDIT FAIL` line per problem; exit code 1 on any failure.
"""
import json
import os
import re
import sys
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
GAME = _crv_paths.GAME
fails = []


def fail(msg):
    fails.append(msg)
    print("AUDIT FAIL " + msg)


class Block:
    def __init__(self, kind, name):
        self.kind, self.name, self.kv, self.children = kind, name, [], []

    def get(self, key, default=None):
        for k, v in self.kv:
            if k.lower() == key.lower():
                return v
        return default

    def all(self, kind):
        return [c for c in self.children if c.kind.lower() == kind.lower()]


def parse(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    root = Block("root", "")
    stack, pending = [root], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "{":
            kind, _, name = (pending or "").partition(" ")
            b = Block(kind.strip(), name.strip())
            stack[-1].children.append(b)
            stack.append(b)
            pending = None
        elif line == "}":
            if len(stack) == 1:
                fail("script: unbalanced closing brace")
                continue
            stack.pop()
        elif "=" in line:
            k, _, v = line.partition("=")
            stack[-1].kv.append((k.strip(), v.strip().rstrip(",").strip()))
        else:
            pending = line
    if len(stack) != 1:
        fail("script: %d unclosed block(s)" % (len(stack) - 1))
    return root


def media_file(rel, exts, folders):
    for base in (os.path.join(MOD, "common", "media"), os.path.join(MOD, "42", "media")):
        for folder in folders:
            for ext in exts:
                p = os.path.join(base, folder, *rel.split("/")) + ext
                if os.path.exists(p):
                    return p
    return None


def fbx_geometries(path):
    data = open(path, "rb").read()
    if data[:18] != b"Kaydara FBX Binary":
        return None
    names = set()
    for m in re.finditer(rb"([A-Za-z0-9_.\-]{1,80})\x00\x01Geometry", data):
        names.add(m.group(1).decode("ascii", "replace"))
    return names


def accessories(script_text):
    items = {}
    idir = os.path.join(MOD, "42", "media", "scripts", "items")
    for fn in (os.listdir(idir) if os.path.isdir(idir) else []):
        txt = open(os.path.join(idir, fn), encoding="utf-8").read()
        for m in re.finditer(r"item\s+(\w+)\s*\{([^}]*)\}", txt):
            icon = re.search(r"Icon\s*=\s*([\w]+)", m.group(2))
            items[m.group(1)] = icon.group(1) if icon else None
    for name, icon in items.items():
        if icon is None:
            fail("item %s: no Icon" % name)
        elif not any(os.path.exists(os.path.join(MOD, d, "media", "textures", "Item_%s.png" % icon)) for d in ("common", "42")):
            fail("item %s: icon Item_%s.png not found" % (name, icon))
    wanted = set(re.findall(r"itemType\s*=\s*Base\.(CRVGen1_\w+)", script_text))
    for name in sorted(wanted - set(items)):
        fail("part item Base.%s is not declared in media/scripts/items" % name)
    lua = ""
    for dirpath, _d, files in os.walk(os.path.join(MOD, "42", "media", "lua")):
        lua += "".join(open(os.path.join(dirpath, f), encoding="utf-8").read() for f in files if f.endswith(".lua"))
    # every HondaCRVGen1.<Namespace>.<fn> the script names (Acc, and each feature's own namespace) is
    # defined: function <alias>.<fn> / <alias>.<fn> = ..., where HondaCRVGen1.<Namespace> = <alias>, or spelled out
    hooks = set(re.findall(r"HondaCRVGen1\.(\w+)\.(\w+)", script_text))
    for ns, h in sorted(hooks):
        names = {re.escape("HondaCRVGen1.%s" % ns)}
        names |= {re.escape(a) for a in re.findall(r"HondaCRVGen1\.%s\s*=\s*(\w+)" % ns, lua)}
        alt = "|".join(sorted(names))
        if not re.search(r"function\s+(%s)[.:]%s\b|(%s)\.%s\s*=" % (alt, h, alt, h), lua):
            fail("script names HondaCRVGen1.%s.%s, no such function in the mod's Lua" % (ns, h))
    parts = set(re.findall(r"part\s+(CRV\w+)", script_text))
    tdir = os.path.join(MOD, "42", "media", "lua", "shared", "Translate", "EN")
    for fn, keys in (("IG_UI.json", {"IGUI_VehiclePart" + p for p in parts}), ("ItemName.json", {"Base." + i for i in items})):
        path = os.path.join(tdir, fn)
        try:
            table = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError) as exc:
            fail("%s: %s" % (fn, exc))
            continue
        for k in sorted(keys - set(table)):
            fail("%s: no %s" % (fn, k))
    print("AUDIT accessories: %d parts, %d items with icons, %d Lua hooks" % (len(parts), len(items), len(hooks)))


def _floats(s, n):
    try:
        v = [float(x) for x in (s or "").split()]
    except ValueError:
        return False
    return len(v) == n


def sprite_models():
    """common/media/spriteModels.txt: every tileset is a sheet a shipped .tiles defines, every tile's
    xy (index = col + row * 8, SpriteModelsFile$Tile.getIndex) is a tile of that sheet, every
    modelScript names a model block the mod (or the game) declares, whose mesh and texture ship.
    SpriteModelManager reads only <mod>/common/media/spriteModels.txt (42.21); a 42/media copy is ignored."""
    if os.path.exists(os.path.join(MOD, "42", "media", "spriteModels.txt")):
        fail("42/media/spriteModels.txt is ignored by the game: SpriteModelManager reads common/media only")
    path = os.path.join(MOD, "common", "media", "spriteModels.txt")
    if not os.path.exists(path):
        print("AUDIT spriteModels: none")
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from tilepack import parse_tiles
    sheets = {}
    info = os.path.join(MOD, "42", "mod.info")
    txt = open(info, encoding="utf-8").read() if os.path.exists(info) else ""
    for m in re.finditer(r"^tiledef=(\S+)\s+(\d+)", txt, re.M):
        tp = os.path.join(MOD, "common", "media", m.group(1) + ".tiles")
        if os.path.exists(tp):
            for name, _img, _c, _r, _sid, tiles in parse_tiles(tp)[1]:
                sheets[name] = len(tiles)
    models = {}
    for dirpath, _d, files in os.walk(os.path.join(MOD, "42", "media", "scripts")):
        for fn in files:
            if fn.lower().endswith(".txt"):
                for mod_block in parse(open(os.path.join(dirpath, fn), encoding="utf-8").read()).children:
                    for mb in mod_block.all("model"):
                        models["%s.%s" % (mod_block.name, mb.name)] = mb
    root = parse(open(path, encoding="utf-8").read())
    blocks = root.all("spriteModel")
    if len(blocks) != 1:
        fail("spriteModels.txt: %d spriteModel blocks, want 1" % len(blocks))
        return
    n_tiles, used = 0, set()
    for ts in blocks[0].all("tileset"):
        sheet = ts.get("name")
        if sheet not in sheets:
            fail("spriteModels.txt: tileset %s is not a sheet in the shipped .tiles (%s)" % (sheet, sorted(sheets)))
            continue
        for t in ts.all("tile"):
            n_tiles += 1
            xy = (t.get("xy") or "").split()
            if len(xy) != 2 or not all(c.isdigit() for c in xy):
                fail("spriteModels.txt %s: tile xy %r" % (sheet, t.get("xy")))
                continue
            idx = int(xy[0]) + int(xy[1]) * 8
            if idx >= sheets[sheet]:
                fail("spriteModels.txt %s: tile %d (xy %s) is not in the sheet (%d tiles)" % (sheet, idx, t.get("xy"), sheets[sheet]))
            ms = t.get("modelScript")
            if t.get("runtime"):
                continue
            for key, n in (("translate", 3), ("rotate", 3), ("scale", 1)):
                if t.get(key) is not None and not _floats(t.get(key), n):
                    fail("spriteModels.txt %s_%d: %s = %r is not %d number(s)" % (sheet, idx, key, t.get(key), n))
            if not ms:
                fail("spriteModels.txt %s_%d: no modelScript" % (sheet, idx))
                continue
            used.add(ms)
            mb = models.get(ms)
            if mb is None:
                mod_name, _, short = ms.partition(".")
                game = os.path.join(GAME, "media", "scripts")
                found = any(re.search(r"^\s*model\s+%s\s*$" % re.escape(short), open(os.path.join(dp, f), encoding="utf-8", errors="replace").read(), re.M)
                            for dp, _d, ff in os.walk(game) for f in ff if f.endswith(".txt")) if mod_name == "Base" else False
                if not found:
                    fail("spriteModels.txt %s_%d: modelScript %s is declared neither by the mod nor by the game" % (sheet, idx, ms))
                continue
            mesh = (mb.get("mesh") or "").partition("|")[0]
            if not mesh or media_file(mesh, (".fbx", ".x", ".X", ".glb"), ("models_X",)) is None:
                fail("spriteModels.txt %s_%d: model %s mesh %s not found" % (sheet, idx, ms, mesh))
            tex = mb.get("texture")
            if tex and media_file(tex, (".png",), ("textures",)) is None:
                fail("spriteModels.txt %s_%d: model %s texture %s not found" % (sheet, idx, ms, tex))
    print("AUDIT spriteModels: %d tileset(s), %d tile(s) -> %s" % (len(blocks[0].all("tileset")), n_tiles, ", ".join(sorted(used))))


def features_audit():
    """What the feature plugins ship (scripts/features): their LUA files, the sandbox options' translations,
    the recipes' and loot's mod items, the extra vehicle scripts' registration as CR-Vs."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import features
    feats = features.load()
    lua_dir = os.path.join(MOD, "42", "media", "lua")
    for feat, rel in features.media():                 # LUA (as 42/media/lua/...) and MEDIA
        if not os.path.exists(os.path.join(MOD, *rel.split("/"))):
            fail("feature %s: %s is not in the mod" % (feat, rel))
    items = set()
    idir = os.path.join(MOD, "42", "media", "scripts", "items")
    for fn in (os.listdir(idir) if os.path.isdir(idir) else []):
        items |= set(re.findall(r"^\s*item\s+(\w+)\s*$", open(os.path.join(idir, fn), encoding="utf-8").read(), re.M))
    tdir = os.path.join(lua_dir, "shared", "Translate", "EN")
    sb = os.path.join(MOD, "42", "media", "sandbox-options.txt")
    n_opts = 0
    if os.path.exists(sb):
        txt = open(sb, encoding="utf-8").read()
        if not re.search(r"^VERSION\s*=\s*1,", txt, re.M):
            fail("sandbox-options.txt: no VERSION = 1,")
        try:
            table = json.load(open(os.path.join(tdir, "Sandbox.json"), encoding="utf-8"))
        except (OSError, ValueError) as exc:
            table = {}
            fail("Sandbox.json: %s" % exc)
        root = parse(txt)
        for opt in root.all("option"):
            n_opts += 1
            for key in ("type", "default", "page", "translation"):
                if opt.get(key) is None:
                    fail("sandbox option %s: no %s" % (opt.name, key))
            for k in ("Sandbox_%s" % opt.get("translation"), "Sandbox_%s" % opt.get("page")):
                if k not in table:
                    fail("Sandbox.json: no %s (option %s)" % (k, opt.name))
    rdir = os.path.join(MOD, "42", "media", "scripts", "recipes")
    n_rec = 0
    for fn in (os.listdir(rdir) if os.path.isdir(rdir) else []):
        txt = open(os.path.join(rdir, fn), encoding="utf-8").read()
        parse(txt)                                     # braces
        n_rec += len(re.findall(r"^\s*craftRecipe\s+\w+", txt, re.M))
        for name in sorted(set(re.findall(r"Base\.(CRVGen1_\w+)", txt)) - items):
            fail("recipes %s: item Base.%s is not declared in media/scripts/items" % (fn, name))
    loot = os.path.join(lua_dir, "server", "Items", "HondaCRVGen1_Loot.lua")
    if os.path.exists(loot):
        for name in sorted(set(re.findall(r'item = "(?:Base\.)?(CRVGen1_\w+)"', open(loot, encoding="utf-8").read())) - items):
            fail("HondaCRVGen1_Loot.lua: item %s is not declared in media/scripts/items" % name)
    reg = os.path.join(lua_dir, "shared", "HondaCRVGen1_Vehicles.lua")
    reg_txt = open(reg, encoding="utf-8").read() if os.path.exists(reg) else ""
    for name in features.vehicle_scripts():
        if 'registerVehicle("Base.%s")' % name not in reg_txt:
            fail("vehicle %s is not registered as a CR-V (shared/HondaCRVGen1_Vehicles.lua)" % name)
    print("AUDIT features: %s; %d Lua files, %d other files, %d sandbox options, %d recipes"
          % (", ".join(m.FEATURE for m in feats) or "none", len(features.lua()), len(features.media()) - len(features.lua()),
             n_opts, n_rec))


def main():
    sprite_models()
    sdir = os.path.join(MOD, "42", "media", "scripts", "vehicles")
    scripts = [f for f in os.listdir(sdir) if f.lower().endswith(".txt")]
    if not scripts:
        fail("no vehicle script in " + sdir)
        return
    # model blocks are global to their module: a feature's second vehicle script (the lifted car) uses the
    # models HondaCRVGen1.txt declares
    roots = {fn: parse(open(os.path.join(sdir, fn), encoding="utf-8").read()) for fn in sorted(scripts)}
    all_models = {}
    for root in roots.values():
        for mod_block in root.children:
            all_models.update({b.name: b for b in mod_block.all("model")})
    ui = {}
    try:
        ui = json.load(open(os.path.join(MOD, "42", "media", "lua", "shared", "Translate", "EN", "IG_UI.json"), encoding="utf-8"))
    except (OSError, ValueError):
        pass                                           # accessories() reports it
    for fn in sorted(scripts):
        accessories(open(os.path.join(sdir, fn), encoding="utf-8").read())
        root = roots[fn]
        for mod_block in root.children:
            own = {b.name: b for b in mod_block.all("model")}
            models = all_models
            for name, mb in own.items():
                mesh = mb.get("mesh")
                if not mesh:
                    fail("model %s: no mesh" % name)
                    continue
                rel, _, geo = mesh.partition("|")
                path = media_file(rel, (".fbx", ".x", ".X"), ("models_X",))
                if path is None:
                    fail("model %s: mesh file %s not found" % (name, rel))
                elif geo:
                    geos = fbx_geometries(path)
                    if geos is not None and geo not in geos:
                        fail("model %s: geometry %s not in %s (has %s)" % (name, geo, os.path.basename(path), sorted(geos)))
                tex = mb.get("texture")
                if tex and media_file(tex, (".png",), ("textures",)) is None:
                    fail("model %s: texture %s not found" % (name, tex))
                sh = mb.get("shader")
                if sh and not (os.path.exists(os.path.join(MOD, "common", "media", "shaders", sh + ".frag"))
                               or os.path.exists(os.path.join(GAME, "media", "shaders", sh + ".frag"))):
                    fail("model %s: shader %s not found (mod or game)" % (name, sh))
                if sh and not sh.lower().startswith("vehicle"):
                    # ModelManager.setModelMetaData: only a shader named vehicle* puts the model's
                    # textures under the Vehicle Texture Size option (default 512); any other name
                    # falls under Texture Size (default 256), which halved our sheet twice (2026-10-12)
                    fail("model %s: shader %s does not start with 'vehicle' (its textures would be capped at 256 px by default)" % (name, sh))
            for veh in mod_block.all("vehicle"):
                if ui and "IGUI_VehicleName" + veh.name not in ui:
                    fail("vehicle %s: IG_UI.json has no IGUI_VehicleName%s" % (veh.name, veh.name))
                for key in ("textureMask", "textureLights", "textureRust"):
                    v = veh.get(key)
                    if v and media_file(v, (".png",), ("textures",)) is None:
                        fail("vehicle %s: %s %s not found" % (veh.name, key, v))
                for sk in veh.all("skin"):
                    v = sk.get("texture")
                    if v and media_file(v, (".png",), ("textures",)) is None:
                        fail("vehicle %s: skin %s not found" % (veh.name, v))
                vm = [c for c in veh.children if c.kind.lower() == "model" and not c.name]
                for c in vm:
                    if c.get("file") not in models:
                        fail("vehicle %s: base model %s not declared" % (veh.name, c.get("file")))
                for part in veh.all("part"):
                    for pm in part.all("model"):
                        f = pm.get("file")
                        if f and f not in models and not f.startswith("Vehicles_"):
                            fail("part %s model %s: file %s not declared" % (part.name, pm.name, f))
                print("AUDIT vehicle %s: %d parts, %d wheels, %d skins, %d models declared"
                      % (veh.name, len(veh.all("part")), len(veh.all("wheel")), len(veh.all("skin")), len(own or models)))
    features_audit()
    # mechanics overlay images named by the Lua
    for dirpath, _d, files in os.walk(os.path.join(MOD, "42", "media", "lua")):
        for fn in files:
            if not fn.endswith(".lua"):
                continue
            src = open(os.path.join(dirpath, fn), encoding="utf-8").read()
            pre = re.search(r'imgPrefix\s*=\s*"([^"]+)"', src)
            if pre:
                ui = None
                for base in (os.path.join(MOD, "common", "media", "ui"), os.path.join(MOD, "42", "media", "ui")):
                    for dp, _dd, ff in os.walk(base):
                        if any(f.startswith(pre.group(1)) for f in ff):
                            ui = dp
                if ui is None:
                    fail("%s: overlay images %s* not found" % (fn, pre.group(1)))
                else:
                    n = len([f for f in os.listdir(ui) if f.startswith(pre.group(1))])
                    print("AUDIT overlay %s*: %d images in %s" % (pre.group(1), n, os.path.relpath(ui, MOD)))
    info = os.path.join(MOD, "42", "mod.info")
    if not os.path.exists(info):
        fail("42/mod.info missing")
    else:
        txt = open(info, encoding="utf-8").read()
        for m in re.finditer(r"^pack=(\S+)", txt, re.M):
            if not os.path.exists(os.path.join(MOD, "common", "media", "texturepacks", m.group(1) + ".pack")):
                fail("mod.info pack %s: no common/media/texturepacks/%s.pack" % (m.group(1), m.group(1)))
        for m in re.finditer(r"^tiledef=(\S+)\s+(\d+)", txt, re.M):
            if not os.path.exists(os.path.join(MOD, "common", "media", m.group(1) + ".tiles")):
                fail("mod.info tiledef %s: no common/media/%s.tiles" % (m.group(1), m.group(1)))
        print("AUDIT mod.info: %d pack(s), %d tiledef(s)" % (len(re.findall(r"^pack=", txt, re.M)), len(re.findall(r"^tiledef=", txt, re.M))))
        poster = re.search(r"^poster=(.+)$", txt, re.M)
        if poster and not os.path.exists(os.path.join(MOD, "42", poster.group(1).strip())):
            fail("mod.info poster %s not found" % poster.group(1).strip())
    print("AUDIT ok" if not fails else "AUDIT %d failure(s)" % len(fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
