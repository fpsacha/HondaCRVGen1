r"""
Draw the mod's sprite models (common/media/spriteModels.txt) the way the game draws them, on their
tile at the game's 2x tile camera, next to the tile sprite they replace.

    blender -b --factory-startup --python scripts\spriteview.py -- [--mod DIR] [--out DIR] [--vanilla]

Reads only what ships: spriteModels.txt, the model scripts under 42/media/scripts, the FBX and
texture they name, the sprites in the mod's .pack and their properties in its .tiles. Writes
<out>/<sprite>.png (sprite | model | sprite with the model's outline in red, 2x) and one
`SPRITEVIEW` line per tile: IoU of the opaque pixels, both bounding boxes, the centroid offset.
The sprite is what the player clicks (IsoObject.updateRenderInfoForObjectPicker keeps the sprite's
rectangle when a model draws), so the model must sit inside its footprint.

The chain, read from the 42.21 bytecode (IsoObjectModelDrawer.renderMain and $WorldModelCamera):
  model = translate(-tx / 1.5, (ty + dy) / 1.5, tz / 1.5) . rotateXYZ(rx, -ry, rz)
          . scale(script scale [x 2/3 with undoCoreScale, ModelScript.Load]) . scale(tile scale)
  world = scale(-1.5, 1.5, 1.5) . rotateY(180) . translate(0, -0.48, 0) . model, at the square's
          centre; dy = Surface / 96 * 2.44949 only when the tile has IsSurfaceOffset.
The camera's translate(0, -0.48, 0) does not move the model against the sprites (the projection
centre carries the same offset): with it the vanilla ramps land 56 px low, without it on their
sprites. FBX meshes are read as game (x, y, z) = Blender import (x, z, y) (pzview.py's mapping).
--vanilla runs the same chain on the game's ramps_01 and appliances_radio_01 as the proof: the four
ramp rotations land on their sprites at IoU 1.00 (2026-10-12); the radio model is drawn smaller
than its old sprite (IoU ~0.3, centred), a vanilla art mismatch, not the chain.
"""
import math
import os
import re
import struct
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
GAME = _crv_paths.GAME
S = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if S not in sys.path:
    sys.path.append(S)
from audit_mod import parse  # noqa: E402  (the same block parser the audit uses)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _arg(flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


MOD = _arg("--mod", os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1"))
OUT = _arg("--out", os.path.join(ROOT, "blender", "spriteview"))
VANILLA = "--vanilla" in argv
W, H = 128, 256
PX = 90.5                                    # px per metre (tile) at 2x
UP = Vector((-0.5 / math.sqrt(2), 0.5 / math.sqrt(2), math.sqrt(3) / 2))
D = Vector((-math.sqrt(3) / 2 / math.sqrt(2), math.sqrt(3) / 2 / math.sqrt(2), -0.5))
SUN_DIR = Vector((-0.50, -0.55, 0.67)).normalized()      # render_tile.SUN_DIR: the screen's upper left
VANILLA_TILES = {"ramps_01": (0, 24, 48, 72), "appliances_radio_01": (0, 1, 2, 3)}


# ---------------------------------------------------------------------------------------------
# shipped files


def read_tiles(path):
    """.tiles -> {sprite name: {prop: value}} (strings are bytes + newline, tilepack.parse_tiles)."""
    b = open(path, "rb").read()
    o = 12
    nsheets = struct.unpack_from("<i", b, 8)[0]

    def rs(o):
        e = b.index(b"\n", o)
        return b[o:e].decode("latin-1"), e + 1
    out = {}
    for _k in range(nsheets):
        name, o = rs(o)
        _img, o = rs(o)
        _c, _r, _sid, ntiles = struct.unpack_from("<iiii", b, o)
        o += 16
        for t in range(ntiles):
            npr = struct.unpack_from("<i", b, o)[0]
            o += 4
            props = {}
            for _q in range(npr):
                key, o = rs(o)
                val, o = rs(o)
                props[key] = val
            out["%s_%d" % (name, t)] = props
    return out


def read_sprites(path, want, tmp):
    """.pack -> {sprite name: 128 x 256 RGBA float array, row 0 at the top} for the names in want."""
    b = open(path, "rb").read()
    o = 8
    pages = struct.unpack_from("<i", b, o)[0]
    o += 4
    found = {}
    for _p in range(pages):
        n = struct.unpack_from("<i", b, o)[0]
        o += 4 + n
        ents = struct.unpack_from("<i", b, o)[0]
        o += 8
        hits = []
        for _e in range(ents):
            n = struct.unpack_from("<i", b, o)[0]
            en = b[o + 4:o + 4 + n].decode("latin-1")
            o += 4 + n
            vals = struct.unpack_from("<8i", b, o)
            o += 32
            if en in want:
                hits.append((en, vals))
        plen = struct.unpack_from("<i", b, o)[0]
        o += 4
        if hits:
            page = os.path.join(tmp, "_page.png")
            with open(page, "wb") as f:
                f.write(b[o:o + plen])
            img = bpy.data.images.load(page)
            pw, ph = img.size
            a = np.array(img.pixels[:], np.float32).reshape(ph, pw, 4)[::-1]
            bpy.data.images.remove(img)
            for en, (x, y, w, h, ox, oy, ow, oh) in hits:
                canvas = np.zeros((oh, ow, 4), np.float32)
                canvas[oy:oy + h, ox:ox + w] = a[y:y + h, x:x + w]
                found[en] = canvas
        o += plen
    return found


def model_scripts(dirs):
    """{'Module.Name': {key: value}} from every model block in the script folders."""
    out = {}
    for d in dirs:
        for dp, _dd, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith(".txt"):
                    txt = open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read()
                    if not re.search(r"^\s*model\s", txt, re.M):
                        continue
                    for mb in parse(txt).children:
                        for m in mb.all("model"):
                            out["%s.%s" % (mb.name, m.name)] = {k.lower(): v for k, v in m.kv}
    return out


def find_media(rel, exts, folder, bases):
    for base in bases:
        for ext in exts:
            p = os.path.join(base, folder, *rel.split("/")) + ext
            if os.path.exists(p):
                return p
    return None


# ---------------------------------------------------------------------------------------------
# the game's chain


def chain(translate, rotate, scale, dy):
    """Game model space -> this scene (x east, y north, z up, metres; the square's centre at the
    origin, its floor at z = 0), from Blender-imported mesh coordinates."""
    tx, ty, tz = translate
    rx, ry, rz = (math.radians(a) for a in rotate)
    m = Matrix.Translation((-tx / 1.5, (ty + dy) / 1.5, tz / 1.5))
    m = m @ Matrix.Rotation(rx, 4, 'X') @ Matrix.Rotation(-ry, 4, 'Y') @ Matrix.Rotation(rz, 4, 'Z')
    m = m @ Matrix.Scale(scale, 4)
    world = Matrix(((-1.5, 0, 0, 0), (0, 0, -1.5, 0), (0, 1.5, 0, 0), (0, 0, 0, 1)))   # east = -1.5 x, north = -1.5 z
    swap = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))            # Blender (x, y, z) -> game (x, z, y)
    return world @ m @ swap


_meshes = {}


def import_model(path, geo, tex):
    """The model's mesh (`file|geo` keeps only that geometry; joined, transforms applied) with its
    texture, sampled Linear like the game."""
    key = (path, geo, tex)
    if key in _meshes:
        return _meshes[key]
    before = set(bpy.data.objects)
    if path.lower().endswith(".glb"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if geo:
        new = [o for o in new if geo.lower() in (o.name.lower(), o.data.name.lower())]
    me = bpy.data.meshes.new(os.path.basename(path))
    import bmesh
    bm = bmesh.new()
    for o in new:
        o.data.transform(o.matrix_world)
        bm.from_mesh(o.data)
    bm.to_mesh(me)
    bm.free()
    for o in list(bpy.data.objects):
        if o not in before:
            bpy.data.objects.remove(o)
    mat = bpy.data.materials.new("m_" + os.path.basename(path))
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Roughness'].default_value = 0.6
    if tex:
        node = mat.node_tree.nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(tex, check_existing=True)
        node.image.alpha_mode = 'NONE'
        node.interpolation = 'Linear'
        mat.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    me.materials.clear()
    me.materials.append(mat)
    _meshes[key] = me
    return me


def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    try:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    except TypeError:
        sc.render.engine = 'BLENDER_EEVEE'
    sc.eevee.taa_render_samples = 16
    sc.render.filter_size = 1.0
    sc.view_settings.view_transform = 'Standard'
    sc.render.resolution_x, sc.render.resolution_y = W, H
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (0.35, 0.35, 0.35, 1)
    sc.world = w
    la = bpy.data.lights.new("sun", 'SUN')
    la.energy = 1.15
    sun = bpy.data.objects.new("sun", la)
    sun.rotation_euler = (-SUN_DIR).to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = 'ORTHO'
    cam.data.sensor_fit = 'VERTICAL'
    cam.data.ortho_scale = H / PX
    cam.data.clip_end = 100
    cam.location = UP * (96.0 / PX) - D * 20.0       # the square's centre lands at canvas (64, 224)
    cam.rotation_euler = D.to_track_quat('-Z', 'Y').to_euler()
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc


def render_model(sc, me, matrix, tag):
    ob = bpy.data.objects.new("model", me)
    sc.collection.objects.link(ob)
    ob.matrix_world = matrix
    path = os.path.join(OUT, "_model_%s.png" % tag)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(ob)
    img = bpy.data.images.load(path)
    a = np.array(img.pixels[:], np.float32).reshape(H, W, 4)[::-1].copy()
    bpy.data.images.remove(img)
    os.remove(path)
    return a


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if xs.size else None


def save_rgba(a, path):
    h, w = a.shape[:2]
    img = bpy.data.images.new("out", w, h, alpha=True)
    img.pixels[:] = np.ascontiguousarray(a[::-1]).ravel()
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def panel(sprite, model):
    """sprite | model | sprite dimmed with the model's outline in red, on a mid grey, 2x nearest."""
    bg = np.ones((H, W, 4), np.float32) * np.array([0.42, 0.42, 0.42, 1.0], np.float32)

    def over(top, base):
        a = top[..., 3:4]
        out = base.copy()
        out[..., :3] = top[..., :3] * a + base[..., :3] * (1 - a)
        return out
    left = over(sprite, bg)
    mid = over(model, bg)
    m = model[..., 3] > 0.5
    pad = np.pad(m, 1)
    edge = m & ~(pad[1:-1, :-2] & pad[1:-1, 2:] & pad[:-2, 1:-1] & pad[2:, 1:-1])
    right = left.copy()
    right[..., :3] = 0.55 * right[..., :3] + 0.45 * 0.42
    right[edge] = (1.0, 0.1, 0.1, 1.0)
    row = np.concatenate([left, mid, right], axis=1)
    return row.repeat(2, axis=0).repeat(2, axis=1)


def main():
    os.makedirs(OUT, exist_ok=True)
    if VANILLA:
        media = os.path.join(GAME, "media")
        sm_path = os.path.join(media, "spriteModels.txt")
        packs = [os.path.join(media, "texturepacks", p) for p in ("Tiles2x.pack", "B42ChunkCaching2x.pack")]
        tiles_files = [os.path.join(media, t) for t in ("newtiledefinitions.tiles", "tiledefinitions_b42chunkcaching.tiles")]
        scripts = [os.path.join(media, "scripts", "generated")]          # models_items.txt, models_isoobject.txt
        bases = [media]
    else:
        common = os.path.join(MOD, "common", "media")
        sm_path = os.path.join(common, "spriteModels.txt")
        info = open(os.path.join(MOD, "42", "mod.info"), encoding="utf-8").read()
        packs = [os.path.join(common, "texturepacks", p + ".pack") for p in re.findall(r"^pack=(\S+)", info, re.M)]
        tiles_files = [os.path.join(common, t + ".tiles") for t in re.findall(r"^tiledef=(\S+)", info, re.M)]
        scripts = [os.path.join(MOD, "42", "media", "scripts")]
        bases = [common, os.path.join(MOD, "42", "media")]
    root = parse(open(sm_path, encoding="utf-8").read())
    jobs = []
    for ts in root.all("spriteModel")[0].all("tileset"):
        name = ts.get("name")
        for t in ts.all("tile"):
            if not t.get("modelScript"):
                continue
            c, r = (int(v) for v in t.get("xy").split())
            idx = c + r * 8
            if VANILLA and idx not in VANILLA_TILES.get(name, ()):
                continue
            vec = lambda k, d: tuple(float(v) for v in (t.get(k) or d).split())
            jobs.append(("%s_%d" % (name, idx), t.get("modelScript"), vec("translate", "0 0 0"), vec("rotate", "0 0 0"),
                         float(t.get("scale") or 1.0)))
    props = {}
    for tf in tiles_files:
        props.update(read_tiles(tf))
    sprites = {}
    sc = setup_scene()
    for p in packs:
        sprites.update(read_sprites(p, {j[0] for j in jobs} - set(sprites), OUT))
    models = model_scripts(scripts)
    rows = []
    for sprite, ms, tr, rot, smscale in jobs:
        mb = models.get(ms)
        if mb is None:
            print("SPRITEVIEW %s: model script %s not found" % (sprite, ms))
            continue
        rel, _, geo = mb["mesh"].partition("|")
        mesh = find_media(rel, (".fbx", ".glb", ".X", ".x"), "models_X", bases)
        tex = find_media(mb["texture"], (".png",), "textures", bases) if mb.get("texture") else None
        scale = float(mb.get("scale", "1").rstrip("f")) * smscale
        if mb.get("undocorescale", "false").lower() == "true":
            scale *= 2.0 / 3.0
        pr = props.get(sprite, {})
        dy = float(pr.get("Surface", 0)) / 96.0 * 2.44949 if "IsSurfaceOffset" in pr else 0.0
        me = import_model(mesh, geo, tex)
        model = render_model(sc, me, chain(tr, rot, scale, dy), sprite)
        spr = sprites.get(sprite)
        if spr is None:
            print("SPRITEVIEW %s: sprite not in %s" % (sprite, [os.path.basename(p) for p in packs]))
            spr = np.zeros((H, W, 4), np.float32)
        sm = spr[..., 3] > 0.99                     # the object; tilepack's ground shadow is alpha 0.2
        mm = model[..., 3] > 0.5
        iou = (sm & mm).sum() / max((sm | mm).sum(), 1)
        cs = np.argwhere(sm).mean(axis=0) if sm.any() else np.array([np.nan, np.nan])
        cm = np.argwhere(mm).mean(axis=0) if mm.any() else np.array([np.nan, np.nan])
        inside = (mm & (spr[..., 3] > 0.1)).sum() / max(mm.sum(), 1)
        print("SPRITEVIEW %s model %s rotate %s scale %.4f: IoU %.2f, model px inside the sprite %.0f%%, bbox model %s sprite %s, "
              "centroid offset (%.1f, %.1f) px" % (sprite, ms, "/".join("%g" % a for a in rot), scale, iou, 100 * inside,
                                                    bbox(mm), bbox(sm), cm[1] - cs[1], cm[0] - cs[0]))
        row = panel(spr, model)
        save_rgba(row, os.path.join(OUT, sprite + ".png"))
        rows.append(row)
    if rows:
        save_rgba(np.concatenate(rows, axis=0), os.path.join(OUT, "_all.png"))
    page = os.path.join(OUT, "_page.png")
    if os.path.exists(page):
        os.remove(page)
    print("SPRITEVIEW DONE %d tile(s) -> %s" % (len(rows), OUT))


main()
