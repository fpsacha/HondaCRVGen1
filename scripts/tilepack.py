r"""
Texture pack (.pack) and tile definition (.tiles) writers for the CR-V's placeable picnic table,
plus common/media/spriteModels.txt (the item icon is gen_icons'), which tells the game to
draw both tiles as the 3D model Base.CRVGen1_TableStand (the sprite stays: it is the fallback when
the model cannot load and the click rectangle; the build ghost draws the model too).

    python scripts\tilepack.py [--check]  (after render_tile.py wrote blender/tiles/_raw_table_*.png)

Two tiles, one per facing (S as built, E the model turned 90 deg). Facing alone does not let the
game rotate a moveable: ISMoveableSpriteProps.hasFaces() wants a non-zero Noffset / Soffset /
Woffset / Eoffset naming the sibling sprite index, so _0 carries Eoffset 1 and _1 Soffset -1
(getFaces / getIndexedFaces / canManuallyRotate / ISMoveableCursor.rotateWhilePlacing all go
through hasFaces; read 2026-10-12).

The composite copies what every vanilla table tile does (Tiles2x.pack, furniture_tables_high_01_4,
measured 2026-10-12): alpha is BINARY, 255 for the object plus exactly 51 for a hard-edged diamond
ground shadow the size of the top's footprint, nothing in between; a 1 px darker rim where the top
meets its sides; top 1.0 : south face 0.72 : east face 0.62. The first shipped tile had a soft
Gaussian blob of alphas 1-13 under the top and legs that never reached alpha 255 (1.1 px tubes),
and read as a flat diamond floating over a smudge.

Formats, read back from the game's own files and a B42 mod's (Neat Building) with the parser below
(`--check` re-parses what was written and a vanilla pack):

  .pack  "PZPK" int32 version=1, int32 pages; per page: str name, int32 entries, int32 hasAlpha,
         per entry: str name, int32 x y w h ox oy ow oh; int32 pngLength, png bytes.
         Strings are int32 length + bytes. Tiles are 128 x 256 (the 2x set B42 draws).
  .tiles "tdef" int32 version=1, int32 sheets; per sheet: str name, str image, int32 columns,
         int32 rows, int32 id, int32 tiles; per tile: int32 properties, (str key, str value)*.
         Strings here are newline-terminated. mod.info: `pack=<name>` and `tiledef=<name> <base id>`.
"""
import io
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
TILES_IN = os.path.join(ROOT, "blender", "tiles")
PACK_NAME = "HondaCRVGen1_Tiles"
PACK_OUT = os.path.join(MOD, "common", "media", "texturepacks", PACK_NAME + ".pack")
TILES_OUT = os.path.join(MOD, "common", "media", PACK_NAME + ".tiles")
TILE_W, TILE_H = 128, 256
TILEDEF_ID = 7361                      # unique per mod among loaded mods (Neat Building uses 7811)
PX = 90.5                              # px per metre at 2x
CX, CY = 64, 224                       # the tile's ground centre
TOP_W, TOP_L = 0.778, 0.681           # build_table.TOP_W / TOP_L: the footprint the shadow diamond covers
ALPHA_T = 96                           # raw alpha >= this is opaque: at 128 the 2 px tubes break into dashes, 64 is slightly fatter
RIM = 0.80                             # 1 px darker rim on every opaque pixel touching a transparent one (vanilla edges are a shade darker)
TOP_TARGET = 52                        # = build_table.STAND_TOP (2026-10-13): the placed model's top, which the sprite must match (was 87, the car's AccTable texel mean)
TOP_PATCH = (44, 84, 160, 178)         # x0, x1, y0, y1 of the top's far half on the canvas, clear of the rim
SHADOW_ALPHA = 51                      # vanilla: exactly 20 %

# tilesheet -> [(tile name, png file, properties)]; properties as the game's own table tiles carry
# them (furniture_tables_high_01). Surface is in 1x pixels, about 42.5 per metre of table height
# (vanilla high_01_0: 0.78 m -> 33, high_01_4: 0.69 m -> 30, round _6: 0.64 m -> 27, heights read
# off each sprite's top-centre row at 78.4 px/m); ours is build_table.HEIGHT 0.66 m -> 28.
_TABLE_PROPS = [
    ("CustomItem", "Base.CRVGen1_PicnicTable"),
    ("CustomName", "Picnic Table"),
    ("GenericCraftingSurface", "true"),
    ("GroupName", "Honda"),
    ("IsLow", ""),
    ("IsMoveAble", ""),
    ("IsTable", ""),
    ("Material", "SmallSheetMetal"),
    ("Material2", "Plastic"),
    ("PickUpWeight", "60"),
    ("Surface", "28"),
    ("solidtrans", ""),
]
SHEETS = {
    "crvgen1_table_01": [
        ("crvgen1_table_01_0", "crvgen1_table_01_0.png", _TABLE_PROPS + [("Facing", "S"), ("Eoffset", "1")]),
        ("crvgen1_table_01_1", "crvgen1_table_01_1.png", _TABLE_PROPS + [("Facing", "E"), ("Soffset", "-1")]),
    ],
}


def _s(txt):
    b = txt.encode("latin-1")
    return struct.pack("<i", len(b)) + b


def write_pack(path, sheets):
    out = [b"PZPK", struct.pack("<ii", 1, len(sheets))]
    for sheet, tiles in sheets.items():
        images = [Image.open(os.path.join(TILES_IN, png)).convert("RGBA") for _n, png, _p in tiles]
        for im in images:
            assert im.size == (TILE_W, TILE_H), (im.size, "tiles are 128 x 256")
        page = Image.new("RGBA", (TILE_W * len(images), TILE_H), (0, 0, 0, 0))
        for k, im in enumerate(images):
            page.paste(im, (k * TILE_W, 0))
        buf = io.BytesIO()
        page.save(buf, "PNG")
        out.append(_s(sheet) + struct.pack("<ii", len(tiles), 1))
        for k, (name, _png, _props) in enumerate(tiles):
            out.append(_s(name) + struct.pack("<8i", k * TILE_W, 0, TILE_W, TILE_H, 0, 0, TILE_W, TILE_H))
        out.append(struct.pack("<i", len(buf.getvalue())) + buf.getvalue())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"".join(out))
    return path


def _t(txt):
    """.tiles strings: the bytes and a newline, NO length prefix (vanilla jumbo_trees.tiles, the
    Logging mod). A length prefix made IsoWorld.readString throw 'unsupported' in 42.21."""
    return txt.encode("latin-1") + b"\n"


def write_tiles(path, sheets):
    out = [b"tdef", struct.pack("<ii", 1, len(sheets))]
    for k, (sheet, tiles) in enumerate(sheets.items()):
        out.append(_t(sheet) + _t(sheet + ".png") + struct.pack("<iiii", len(tiles), 1, k + 1, len(tiles)))
        for _name, _png, props in tiles:
            out.append(struct.pack("<i", len(props)))
            for key, val in props:
                out.append(_t(key) + _t(val))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"".join(out))
    return path


def _lin(v):
    """sRGB [0..1] -> linear."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _lum(a):
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def footprint_shadow(foot=(TOP_W, TOP_L), alpha=SHADOW_ALPHA):
    """The hard-edged diamond every vanilla table tile carries under its top (high_01_4: 1,653 px
    at alpha 51 and 54 px at any other alpha; the round table's shadow bbox equals its top's).
    The footprint's corners under the game's projection: X (east) -> (64, 32) px/m, Y (north) ->
    (64, -32) px/m, so a 0.78 m square spans x 64 +- 49.9 and y 224 +- 25."""
    shadow = Image.new("RGBA", (TILE_W, TILE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(shadow)
    hx, hy = foot[0] / 2, foot[1] / 2
    corners = [(CX + (sx * hx + sy * hy) * 0.707 * PX, CY + (sx * hx - sy * hy) * 0.354 * PX)
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    d.polygon(corners, fill=(0, 0, 0, alpha))             # ImageDraw.polygon does not anti-alias: binary alpha
    return shadow


def compose_sprite(raw, out, foot=(TOP_W, TOP_L)):
    """render_tile.py's raw Eevee render -> a vanilla-style tile (Blender's Python has no PIL, so
    the compositing lives here): (1) hard alpha, raw >= ALPHA_T is opaque, the rest transparent;
    (2) a 1 px darker rim; (3) the top normalised in linear light so its median luminance equals
    the shipped shell texel, because Eevee's absolute level is not predictable from the lamp
    (calibration 2026-10-12: a 0.5-albedo plane under a strength-1 sun straight down renders 87 %
    of its albedo); (4) a hard 20 % footprint diamond under it. Prints the counts the acceptance
    check reads: other-alpha must be 0."""
    sprite = Image.open(os.path.join(TILES_IN, raw)).convert("RGBA")
    a = np.asarray(sprite).astype(np.float32)
    hard = a[..., 3] >= ALPHA_T
    a[..., 3] = np.where(hard, 255.0, 0.0)
    pad = np.pad(hard, 1)
    inside = pad[1:-1, 1:-1] & pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    a[hard & ~inside, :3] *= RIM
    x0, x1, y0, y1 = TOP_PATCH
    patch = _lum(a[y0:y1, x0:x1])[hard[y0:y1, x0:x1]]
    before = float(np.median(patch)) if patch.size else float("nan")
    if patch.size and before > 0:
        gain = _lin(TOP_TARGET / 255.0) / _lin(before / 255.0)
        rgb = a[..., :3] / 255.0
        lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4) * gain
        srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(np.clip(lin, 0, None), 1 / 2.4) - 0.055)
        a[..., :3] = np.clip(srgb * 255.0, 0, 255)
    after = float(np.median(_lum(a[y0:y1, x0:x1])[hard[y0:y1, x0:x1]])) if patch.size else float("nan")
    sprite = Image.fromarray(np.rint(a).astype(np.uint8), "RGBA")
    img = Image.alpha_composite(footprint_shadow(foot), sprite)
    path = os.path.join(TILES_IN, out)
    img.save(path)
    o = np.asarray(img)
    n_op = int((o[..., 3] == 255).sum())
    n_sh = int((o[..., 3] == SHADOW_ALPHA).sum())
    n_other = int(((o[..., 3] > 0) & (o[..., 3] != 255) & (o[..., 3] != SHADOW_ALPHA)).sum())
    print("SPRITE %s opaque %d shadow51 %d other-alpha %d top median %.1f -> %.1f bbox %s"
          % (path, n_op, n_sh, n_other, before, after, img.getbbox()))
    return path


SPRITE_MODELS_OUT = os.path.join(MOD, "common", "media", "spriteModels.txt")
FACING_YAW = {"S": 0.0, "E": 90.0}     # render_tile.FACINGS: the table's turn about +z, degrees, Blender
                                       # world (x east, y north), at which each tile's sprite is rendered


def sprite_rotate_y(yaw):
    """spriteModels.txt `rotate` y for a model turned `yaw` (render_tile convention) on its tile.
    IsoObjectModelDrawer.renderMain (42.21): transform = translate(-tx / 1.5, ty / 1.5, tz / 1.5)
    . rotateXYZ(rx, -ry, rz) . scale(script scale) under the world camera's scale(-1.5, 1.5, 1.5)
    . rotateY(180); with our FBX read as game (x, y, z) = Blender (x, z, y) (pzview's mapping), that
    puts a vertex at Blender world (x, y) -> (-x cos ry + y sin ry, -x sin ry - y cos ry), i.e. a turn
    of ry + 180. So ry = yaw - 180, normalised to (-180, 180]: S 180, E -90 (vanilla's E radio and
    ramps use 0 -90 0 too). translate = east, up, south in tiles (+x east, +z south). Checked by
    scripts/spriteview.py --vanilla: the chain draws the game's ramps_01 onto their sprites at IoU 1.00."""
    ry = (yaw - 180.0) % 360.0
    return ry - 360.0 if ry > 180.0 else ry


def write_sprite_models(path, sheets, model_script):
    """common/media/spriteModels.txt (SpriteModelManager reads ONLY <mod>/common/media/ after the
    scripts, 42.21): one tileset per sheet, one tile per sprite, xy = col row of its index (index =
    col + row * 8), the model at the square centre, turned to the tile's Facing."""
    out = ["spriteModel", "{", "    VERSION = 1,", ""]
    for sheet, tiles in sheets.items():
        out += ["    tileset", "    {", "        name = %s," % sheet, ""]
        for name, _png, props in tiles:
            idx = int(name.rsplit("_", 1)[1])
            ry = sprite_rotate_y(FACING_YAW[dict(props)["Facing"]])
            out += ["        tile", "        {",
                    "            xy = %d %d," % (idx % 8, idx // 8),
                    "            modelScript = %s," % model_script,
                    "            translate = 0.0000 0.0000 0.0000,",
                    "            rotate = 0.0000 %.4f 0.0000," % ry,
                    "            scale = 1.0000,",
                    "        }", ""]
        out += ["    }", ""]
    out += ["}", ""]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    return path


def parse_pack(path):
    b = open(path, "rb").read()
    assert b[:4] == b"PZPK"
    o = 4
    ver, pages = struct.unpack_from("<ii", b, o)
    o += 8
    out = []
    for _p in range(pages):
        n = struct.unpack_from("<i", b, o)[0]
        name = b[o + 4:o + 4 + n].decode("latin-1")
        o += 4 + n
        ents, flag = struct.unpack_from("<ii", b, o)
        o += 8
        names = []
        for _e in range(ents):
            n = struct.unpack_from("<i", b, o)[0]
            en = b[o + 4:o + 4 + n].decode("latin-1")
            o += 4 + n
            vals = struct.unpack_from("<8i", b, o)
            o += 32
            names.append((en, vals))
        plen = struct.unpack_from("<i", b, o)[0]
        o += 4
        im = Image.open(io.BytesIO(b[o:o + plen]))
        o += plen
        out.append((name, flag, names, im.size))
    assert o == len(b), (o, len(b))
    return ver, out


def parse_tiles(path):
    b = open(path, "rb").read()
    assert b[:4] == b"tdef"
    o = 4
    ver, sheets = struct.unpack_from("<ii", b, o)
    o += 8

    def rs(o):
        e = b.index(b"\n", o)
        return b[o:e].decode("latin-1"), e + 1
    out = []
    for _k in range(sheets):
        name, o = rs(o)
        img, o = rs(o)
        cols, rows, sid, ntiles = struct.unpack_from("<iiii", b, o)
        o += 16
        tiles = []
        for _t in range(ntiles):
            npr = struct.unpack_from("<i", b, o)[0]
            o += 4
            props = []
            for _q in range(npr):
                key, o = rs(o)
                val, o = rs(o)
                props.append((key, val))
            tiles.append(props)
        out.append((name, img, cols, rows, sid, tiles))
    assert o == len(b), (o, len(b))
    return ver, out


def main():
    for tiles in SHEETS.values():
        for _name, png, props in tiles:                  # one raw render per facing (render_tile.FACINGS)
            raw = "_raw_table_%s.png" % dict(props).get("Facing", "S")
            if os.path.exists(os.path.join(TILES_IN, raw)):
                facing = dict(props).get("Facing", "S")       # E: the model turned 90 degrees, so is its footprint
                compose_sprite(raw, png, (TOP_W, TOP_L) if facing == "S" else (TOP_L, TOP_W))
            else:
                print("SPRITE %s: no %s, packing the existing composite" % (png, raw))
    p1 = write_pack(PACK_OUT, SHEETS)
    p2 = write_tiles(TILES_OUT, SHEETS)
    # the inventory icon (Item_CRVGen1_PicnicTable.png) is gen_icons' now, rendered and outlined like every
    # other item: the cut of this dark world sprite read as a faint wire box on the inventory row
    from gen_scripts import TABLE_STAND
    p4 = write_sprite_models(SPRITE_MODELS_OUT, SHEETS, "Base." + TABLE_STAND)
    for p in (p1, p2, p4):
        print("WROTE %s (%d bytes)" % (p, os.path.getsize(p)))
    ver, pages = parse_pack(p1)
    print("TILEPACK %s: version %d, %s" % (os.path.basename(p1), ver, [(n, f, [e[0] for e in es], sz) for n, f, es, sz in pages]))
    ver, sheets = parse_tiles(p2)
    print("TILEDEF %s: version %d, %s" % (os.path.basename(p2), ver, [(n, i, c, r, s, len(t)) for n, i, c, r, s, t in sheets]))
    if "--check" in sys.argv:
        g = os.path.join(_crv_paths.GAME, "media", "texturepacks", "Tiles2x.pack")     # the game's 2x set (PZPK)
        ver, pages = parse_pack(g)
        print("vanilla %s: version %d, %d pages, first %r %s" % (os.path.basename(g), ver, len(pages), pages[0][0], pages[0][3]))
        t = os.path.join(_crv_paths.GAME, "media", "jumbo_trees.tiles")             # same reader must parse a vanilla .tiles
        ver, sheets = parse_tiles(t)
        print("vanilla %s: version %d, %d sheets, first %r %r cols %d rows %d id %d tiles %d, tile 0 props %s"
              % (os.path.basename(t), ver, len(sheets), sheets[0][0], sheets[0][1], sheets[0][2], sheets[0][3], sheets[0][4], len(sheets[0][5]), sheets[0][5][0][:3]))


if __name__ == "__main__":
    main()
