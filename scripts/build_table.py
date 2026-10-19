r"""
The CR-V's picnic table (the RD1's removable cargo floor) and the well it covers.

    blender -b blender\import\parts_kotris.blend --python scripts\build_table.py -- --save

Built after prep and the accessories (run_rebuild). Three things:
  * `acc_table`: the table as it rides in the car: the grey top flush with the cargo floor, its two
    tubular leg frames folded flat underneath. A removable vehicle part (CRVPicnicTable), baked on
    the shell sheet like the other accessories. The same mesh, moved to the ground, is the dropped
    item's world model (export_fbx writes WorldItems/CRVGen1_Table.fbx).
  * the well: the cargo floor is cut out under the table and a 14 cm recess built in its place, so
    with the table out you look into the empty well (the real car keeps the jack and a bin there).
  * `standing_table(bm, tube_r, top_t, brace_r)`: the table set up on its legs, for render_tile.py
    (the placed sprite). The sprite passes thicker tubes and top than the real part: at the tile's
    90.5 px/m a 12 mm tube is 1.1 px and never reaches full alpha, a 20 mm top is 1.6 px and shows
    no slab edge (measured on the first shipped tile, 2026-10-12). The car part (folded_table)
    keeps the real sizes (TUBE_R, TOP_T and _top's own slot / plug defaults).
  * the placed table's 3D model (export_fbx.export_standing_table): standing_table at its
    defaults (STAND_TUBE_R / STAND_TOP_T / STAND_BRACE_R, a few mm over the real part so the 1x
    chunk render keeps the tubes whole), `standing_uv` maps it onto its own small sheet and
    `paint_standing` paints that sheet (STAND_TEX px): a dark moulded top with the grab slot and
    the umbrella plug painted in, a dark slab-edge cell, a low-contrast aluminium disc the tubes
    look up by normal, flat cells for the slot / plug geometry and the hinge plates.

How the game draws the placed table (measured 2026-10-13 on in-game screenshots of the
placed table and of its placement ghost, same scene and light; a software rasteriser of both paths
with these numbers reproduced the shipped table in both to within ~1 level and 0.98 / 0.93 IoU):
  * placed, IsoObjectModelDrawer into the chunk texture: 90.5 px per metre, no anti-aliasing,
    magnified NEAREST (4x at his zoom), and FLAT light: the top (PNG 87) drew 81.5 and its south
    face (PNG ~83) 77, i.e. RGB = PNG x 0.937 whatever the normal. Geometry less than ~1 mm proud
    of the top (the slot and plug boxes) is lost in the chunk depth: they never drew.
  * placement ghost (IsoSprite.RenderGhostTileColor), full screen resolution: RGB = PNG x 0.413
    x (1 + 0.375 max(N.L, 0)) with L the game's (0, 5, -2): top x0.557 (48.5), sides x0.413 (30),
    so its slab edge reads and the whole table sits at 0.595 of the placed brightness.
  So the placed table carries the form in the PNG (dark top, darker slab edge, slot painted in,
  no bright matcap) at the ghost's levels: PNG = ghost display / 0.937.

Shape from photos of the real 1997-2001 table (samarins.com, Autoweek) and owners' descriptions
("the legs fold out card-table like"): a thin mid-grey moulded top, square, about 78 cm and 2 cm
thick, with a recessed grab slot; two thin chrome tube frames, one along each LONG side, each a
vertical leg at either end joined by a ground bar whose ends curl up into feet, hinged under the
long edge and folding inward flat under the top (the far frame a little narrower so they nest);
a short folding lock strut per frame, no cross brace (eBay listing photos, 2026-10-18). 42 cm high.
Model space: metres, +X vehicle right, +Y forward, +Z up.
"""
import math
import sys

import bmesh
import bpy
from mathutils import Vector

from build_accessories import (PLATE, STEEL, _box, _new_object, _round, _sweep, tris)

TOP_W, TOP_L, TOP_T = 0.778, 0.681, 0.029       # x (across the car), y, thickness: measured on a real table (r/crv,
                                                 # 30-5/8 x 26-13/16 x 1-1/8 in; it was a 0.78 m square, 2 cm thick)
HEIGHT = 0.66                                    # standing: ground to top surface. Measured 2026-10-18 on two eBay listings of
                                                 # the 1997-2001 table standing (top 30.5 x 26.5-27.5 in): about 40-43 cm, a
                                                 # low camp table (the "26 in" quoted online is the top's depth). 0.76 then
                                                 # 0.66 read too high (feedback: "its too high ... real proportion");
                                                 # then 0.42 was "way too small ... too low, looks weird" next to a
                                                 # character: 0.66, a low table (picked 2026-10-18), real top kept
KNEE = (0.12, 0.12)                              # the folding lock strut on each frame: from the top's underside this far inboard
                                                 # of the hinge, to the near leg this far below the top (the photos; no X brace)
FOOT_R = 0.022                                   # the curled feet: a quarter circle of this radius
TOP_R = 0.035                                    # the standing top's rounded corners (a moulded panel), and
TOP_BEV = 0.006                                  # its softened edge: the top and bottom faces inset this much
TUBE_R = 0.006                                   # 12 mm chrome tube
HINGE_X = TOP_W / 2 - 0.045                      # frames hinge this far either side of the centre line (4.5 cm in from the edge)
LEG_Y = (0.29, 0.26)                             # legs this far either side of the middle: near frame, far frame (nests inside)
FOOT = 0.04                                      # ground bar runs this far past each leg, then curls up
FLOOR_Z = 0.766                                  # the kotris cargo floor
CENTRE_Y = -1.58                                 # between the rear seatback (y -1.17) and the gate (y -2.11)
WELL_DEPTH = 0.14                                # (the old box well's depth)
TUB_DEPTH = 0.24                                 # the rounded tub's bottom under the deck (z 0.526; underbody 0.40-0.46)
LEDGE_DROP = 0.031                               # the ledge under the opening's rim: the table (TOP_T) rests on it flush
LEDGE_W = 0.030                                  # ledge width inside the opening
WELL_MAT = "WellTub"                             # bake_atlas.PALETTE: the tub's black plastic
TUB_SEG = 6                                      # points per rounded corner
WELL_GAP = 0.012                                 # well walls past the top's edge
TABLE = "acc_table"
TOP_MAT, CHROME_MAT = "AccTable", "AccChrome"    # added to build_accessories.MATS on first use

# The placed table's model sizes (standing_table's defaults; render_tile passes its own, fatter
# sprite sizes). At the chunk render's 90.5 px/m the real 12 mm tube is 1.09 px and its 6-sided
# section 0.94 px across the flats: the ground bars broke into alternating dots. 16 mm is 1.45 px
# (>= 1.26 px across the flats), so every column of a bar and every row of a leg keeps a pixel
# centre; the 25 mm slab gives the near edges a ~2 px dark band (20 mm alternated 1 and 2 px).
# The slot and plug are drawn bolder than the car part's (11 x 2.8 cm, 3.6 cm): ~8 x 2 px and a
# 3 x 2 px dot at 1x instead of 7 x 1.6 and 2 x 1.5.
STAND_TUBE_R = 0.014                             # 2026-10-19: 16 mm vanished at game zoom ("looks shitty": a slab on the ground)
STAND_TOP_T = 0.029
STAND_BRACE_R = 0.010
STAND_SLOT = (0.065, 0.018)                      # grab slot half length (x), half width (y), metres
STAND_PLUG_R = 0.023                             # umbrella plug radius
SLOT_Y, PLUG_Y = -0.28, 0.0                      # their centres along y (as _top places them): the real top has its grab
                                                 # recess near one long edge (the gate side in the car) and the hole in the middle

# The placed table's own sheet (not the 1024 car shell). A model drawn with no shader line gets the
# game's basicEffect and falls under the Texture Size option (default 256), so 256 is loaded as
# authored. Cells are (x0, y0, x1, y1) in PNG pixels, y down. The top cell spreads the 0.78 m top
# over 192 px (2.5 texels/cm; the 1x chunk render samples it every ~1.1 cm, no mipmaps, so every
# painted mark is >= 2 cm across and the top carries no fine detail).
STAND_TEX = 256
CELL_TOP = (0, 0, 192, 192)
CELL_CHROME = (192, 0, 256, 64)                  # aluminium disc, looked up by the tube's normal
CELL_STEEL = (192, 64, 256, 128)                 # grab slot, round plug geometry: near black
CELL_PLATE = (192, 128, 256, 192)                # hinge brackets: grey steel
CELL_EDGE = (0, 192, 64, 256)                    # the slab's outer sides
CELL_INSET = 2.0                                 # px kept clear inside every cell (linear sampling)
# sRGB levels, chosen so the PLACED table (flat x0.937) shows what the ghost showed in 21.png:
# top 48.5, slab edge 30, slot ~17, legs ~105 (measured). The ghost itself now draws ~0.6x of that.
STAND_TOP = 100.0                                # mid-grey moulded top like the real one (was 52: a black slab);                                 # 48.7 placed (ghost before: 48.5; the old 87 drew 81.5)
STAND_RIM = 1.05                                 # the moulded 1 cm lip, a shade lighter than the top
STAND_EDGE = 70.0                                # was 32;                                # slab sides: 30 placed (ghost before: 30)
STAND_HOLE = 17.0                                # painted slot and plug: 16 placed (ghost before: 17)
STAND_STEEL = 22.0                               # the slot / plug geometry, where it wins the depth test
STAND_PLATE = 74.0
# aluminium tube: one mid grey whatever normal a 1x pixel lands on (the old chrome disc ran
# 30..240 and drew white sticks and dotted bars), lighter on the sun's side, darker on top
STAND_TUBE = 40.0                                # black legs, as on the real table (was a 116 aluminium that vanished on asphalt);                               # horizontal normal (a leg): ~109 placed
STAND_TUBE_SUN = 8.0                             # +- toward / away from the sun
STAND_TUBE_UP = 6.0                              # minus this x n.z (a bar's top: ~96 placed)
SUN_AZ = (-0.67, -0.74)                          # render_tile.SUN_DIR on the ground: the tube's light side


def _mats():
    import build_accessories as A
    for name, col in ((TOP_MAT, (0.21, 0.21, 0.215)), (CHROME_MAT, (0.45, 0.45, 0.47))):
        if name not in A.MATS:
            A.MATS.append(name)
            A.COLOURS[name] = col
    return A.MATS.index(TOP_MAT), A.MATS.index(CHROME_MAT)


def _top(bm, cx, cy, z_top, mat, top_t=None, slot=(0.055, 0.014), plug_r=0.018):
    """The top: a thin panel with a 1 cm lip and the recessed grab slot in the middle.
    `top_t` overrides the slab thickness (None = TOP_T, the real 20 mm); `slot` (half length, half
    width) and `plug_r` default to the car part's sizes (the standing table draws them bolder)."""
    top_t = top_t or TOP_T
    faces = _box(bm, (cx - TOP_W / 2, cy - TOP_L / 2, z_top - top_t), (cx + TOP_W / 2, cy + TOP_L / 2, z_top), mat=mat)
    r, h = 0.010, 0.003
    for x0, x1, y0, y1 in ((-TOP_W / 2, -TOP_W / 2 + r, -TOP_L / 2, TOP_L / 2), (TOP_W / 2 - r, TOP_W / 2, -TOP_L / 2, TOP_L / 2),
                           (-TOP_W / 2, TOP_W / 2, -TOP_L / 2, -TOP_L / 2 + r), (-TOP_W / 2, TOP_W / 2, TOP_L / 2 - r, TOP_L / 2)):
        _box(bm, (cx + x0, cy + y0, z_top - 0.001), (cx + x1, cy + y1, z_top + h), mat=mat)
    sx, sy = slot
    _box(bm, (cx - sx, cy + SLOT_Y - sy, z_top - 0.009), (cx + sx, cy + SLOT_Y + sy, z_top + 0.0006), mat=STEEL)   # grab slot
    _sweep(bm, [(cx, cy + PLUG_Y, z_top - 0.004), (cx, cy + PLUG_Y, z_top + 0.0008)], _round(plug_r, 8), mat=STEEL)   # round plug
    return faces


def _ground_bar(ly):
    """The standing frame's ground bar as (y, z) points from the ground line: straight, each end curling up into a
    foot along a quarter circle (FOOT_R). Round 5 (2026-10-19): the old bar humped 3 cm over its middle through four
    sharp kinks and read as a broken, stepped bar at eye level and as a wobble in the placed tile; a smooth hump
    still read as a sagging wire."""
    e = ly + FOOT
    foot = [(-e + FOOT_R + FOOT_R * math.cos(math.radians(a)), FOOT_R + FOOT_R * math.sin(math.radians(a)))
            for a in (180.0, 210.0, 240.0, 270.0)]                      # from the foot's tip down to the ground
    return foot + [(-y, z) for y, z in reversed(foot)]


def _top_moulded(bm, z_top, mat, top_t, slot, plug_r):
    """The standing table's top (round 5, 2026-10-19: the square box with a 3 mm lip read as a cut sheet at eye
    level): a moulded panel with rounded corners (TOP_R) and a softened edge, its top and underside inset TOP_BEV
    from the full outline, the grab slot and the umbrella plug as _top makes them. Centred on x = y = 0."""
    from build_accessories import _loft, _rr
    a, b = TOP_W / 2, TOP_L / 2

    def ring(d, z):
        return [(x, y, z) for x, y in _rr(a - d, b - d, TOP_R - d, 3)]
    _loft(bm, [ring(TOP_BEV, z_top - top_t), ring(0.0, z_top - top_t + TOP_BEV), ring(0.0, z_top - TOP_BEV),
               ring(TOP_BEV, z_top)], [mat] * 3, cap_mats=(mat, mat))
    sx, sy = slot
    _box(bm, (-sx, SLOT_Y - sy, z_top - 0.009), (sx, SLOT_Y + sy, z_top + 0.0006), mat=STEEL)    # grab slot
    _sweep(bm, [(0.0, PLUG_Y, z_top - 0.004), (0.0, PLUG_Y, z_top + 0.0008)], _round(plug_r, 8), mat=STEEL)   # round plug


def _leg_frame(bm, cx, cy, z_under, side, folded, chrome, tube_r=None, top_t=None):
    """One chrome frame along the long side `side` (+1 / -1 along x): two legs at y = +-LEG_Y under
    the hinge line x = side * HINGE_X, a ground bar between them that runs FOOT past each leg and
    curls up. Folded: the frame lies flat under the top, legs pointing inward across the width.
    `tube_r` / `top_t` override the real sizes for the sprite render (None = TUBE_R / TOP_T)."""
    tube_r = tube_r or TUBE_R
    top_t = top_t or TOP_T
    ly = LEG_Y[0] if side > 0 else LEG_Y[1]
    xh = cx + side * HINGE_X
    leg = HEIGHT - top_t - tube_r
    if folded:
        z = z_under - tube_r - 0.002 - (0.015 if side < 0 else 0.0)     # the far frame nests under the near one
        xe = xh - side * min(leg, TOP_W - 0.05)
        for sy in (-1, 1):                                              # legs lying flat
            _sweep(bm, [(xh, cy + sy * ly, z), (xe, cy + sy * ly, z)], _round(tube_r, 6), mat=chrome)
        _sweep(bm, [(xe, cy - ly - FOOT, z + 0.02), (xe, cy - ly - FOOT, z), (xe, cy + ly + FOOT, z), (xe, cy + ly + FOOT, z + 0.02)],
               _round(tube_r, 6), mat=chrome)                           # the ground bar, feet curled toward the top
    else:
        z0 = tube_r + (z_under - (HEIGHT - top_t))                      # ground
        for sy in (-1, 1):                                              # vertical legs
            _sweep(bm, [(xh, cy + sy * ly, z_under), (xh, cy + sy * ly, z0)], _round(tube_r, 6), mat=chrome)
        _sweep(bm, [(xh, cy + y, z0 + z) for y, z in _ground_bar(ly)], _round(tube_r, 6), mat=chrome)
    for sy in (-1, 1):                                                  # hinge brackets under the top
        _box(bm, (xh - 0.014, cy + sy * ly - 0.018, z_under - 0.014), (xh + 0.014, cy + sy * ly + 0.018, z_under + 0.001), mat=PLATE)


def standing_table(bm, tube_r=STAND_TUBE_R, top_t=STAND_TOP_T, brace_r=STAND_BRACE_R):
    """Table on its legs at the origin (top centred on x = y = 0, ground z = 0). The defaults are
    the placed model's sizes (16 mm tubes, 25 mm top: whole at the chunk render's 1x, see
    STAND_TUBE_R); render_tile.py passes sprite sizes (tubes 22 mm = 2 px, top 30 mm, brace 16 mm)
    so the legs stay continuous after the tile's hard alpha and the slab shows an edge. Both draw
    the bold slot and plug (STAND_SLOT / STAND_PLUG_R)."""
    top, chrome = _mats()
    _top_moulded(bm, HEIGHT, top, top_t, STAND_SLOT, STAND_PLUG_R)
    z_under = HEIGHT - top_t
    for side in (-1, 1):
        _leg_frame(bm, 0.0, 0.0, z_under, side, False, chrome, tube_r, top_t)
        # the folding lock strut (the real table has one per frame, on its near leg; there is no cross brace)
        xh, ly = side * HINGE_X, LEG_Y[0] if side > 0 else LEG_Y[1]
        _sweep(bm, [(xh - side * KNEE[0], ly, z_under - 0.008), (xh, ly, z_under - KNEE[1])], _round(brace_r, 5), mat=chrome)
    return bm


def _cell_uv(cell, fx, fy):
    """Fractions (fx, fy) in 0..1 across a cell (fy down, as the PNG) -> Blender UV, inset."""
    x0, y0, x1, y1 = cell
    px = x0 + CELL_INSET + fx * (x1 - x0 - 2 * CELL_INSET)
    py = y0 + CELL_INSET + fy * (y1 - y0 - 2 * CELL_INSET)
    return px / STAND_TEX, 1.0 - py / STAND_TEX


def standing_uv(me):
    """UVs for the standing table (mesh in metres, top centred on x = y = 0; material slots named as
    build_accessories.MATS). Top and lip: planar from above onto CELL_TOP; the slab's outer sides
    (and the lip's, flush with them) take the middle of CELL_EDGE: the placed table is lit flat, so
    its edge reads only as far as the PNG darkens it. Tubes: smooth, and each corner looks the
    aluminium disc up by its normal's x / y (a matcap baked into the UVs: a vertical leg's normals
    sweep the rim, a bar's the middle). Slot, plug and plates: the middle of their flat cells."""
    uv = me.uv_layers.new(name="UVMap")
    names = [m.name if m else "" for m in me.materials]
    for poly in me.polygons:
        mat = names[poly.material_index] if poly.material_index < len(names) else ""
        if mat == CHROME_MAT:
            poly.use_smooth = True
        c = poly.center
        edge = (mat == TOP_MAT and abs(poly.normal.z) < 0.5                # the slab's sides, rounded corners too
                and max(abs(c.x) - (TOP_W / 2 - 0.02), abs(c.y) - (TOP_L / 2 - 0.02)) > 0)
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index]
            if edge:
                uv.data[li].uv = _cell_uv(CELL_EDGE, 0.5, 0.5)
            elif mat == TOP_MAT:
                fx = min(1.0, max(0.0, v.co.x / TOP_W + 0.5))
                fy = min(1.0, max(0.0, 0.5 - v.co.y / TOP_L))          # north at the top of the cell
                uv.data[li].uv = _cell_uv(CELL_TOP, fx, fy)
            elif mat == CHROME_MAT:
                n = v.normal
                uv.data[li].uv = _cell_uv(CELL_CHROME, 0.5 + 0.5 * n.x, 0.5 - 0.5 * n.y)
            elif mat == "AccPlate":
                uv.data[li].uv = _cell_uv(CELL_PLATE, 0.5, 0.5)
            else:                                                       # AccSteel and anything else: dark
                uv.data[li].uv = _cell_uv(CELL_STEEL, 0.5, 0.5)
    return uv


def paint_standing(path):
    """Paint the standing table's sheet (STAND_TEX square, sRGB, no alpha) and save it as PNG.
    Blender's Python has no PIL: numpy in, bpy image out (a byte image stores what is written).
    Everything is sized for the 1x chunk render (one sample per ~1.1 cm, no mipmaps): no 1-texel
    lines, the slot and plug painted in at full size so they read even where their geometry loses
    the chunk's depth test, a tube disc whose every texel is the same mid grey give or take ~10."""
    import numpy as np
    n = STAND_TEX
    img = np.full((n, n, 3), STAND_PLATE, np.float32)                                   # unused texels: plate grey
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    # top: dark moulded grey with a faint low-frequency mottle, the 1 cm lip a shade lighter, the
    # grab slot and the umbrella plug near black (texel -> metres through _cell_uv's mapping)
    x0, y0, x1, y1 = CELL_TOP
    span = x1 - x0 - 2 * CELL_INSET
    tx, ty = (xx - x0 - CELL_INSET) / span, (yy - y0 - CELL_INSET) / span
    mx, my = (tx - 0.5) * TOP_W, (0.5 - ty) * TOP_L                                     # metres, x east, y north
    texel = TOP_W / span
    qx, qy = np.abs(mx) - (TOP_W / 2 - TOP_R), np.abs(my) - (TOP_L / 2 - TOP_R)          # metres from the top's edge,
    edge = TOP_R - np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) - np.minimum(np.maximum(qx, qy), 0)   # its rounded corners too
    mottle = 1.0 + 0.015 * np.sin(tx * 11.0 + 1.3) * np.sin(ty * 9.0 + 0.4) + 0.01 * np.sin((tx + ty) * 23.0)
    rim = np.clip((0.010 - edge) / texel + 0.5, 0, 1)
    top = STAND_TOP * mottle * (1 + (STAND_RIM - 1) * rim)
    sx, sy = STAND_SLOT
    d_slot = np.maximum(np.abs(mx) - sx, np.abs(my - SLOT_Y) - sy)
    d_plug = np.hypot(mx, my - PLUG_Y) - STAND_PLUG_R
    hole = np.clip(0.5 - np.minimum(d_slot, d_plug) / texel, 0, 1)
    # moulded detail (2026-10-19, first-person feedback): a groove 4 cm in from the edge, and the raised CR-V
    # plate beside the grab slot with its letters (as the stowed table carries, cargo_bay_paint.render_table)
    groove = np.clip(1.0 - np.abs(edge - 0.040) / (0.6 * texel + 0.002), 0, 1)
    top = top * (1 - 0.18 * groove)
    px0, px1, py = 0.085, 0.285, SLOT_Y
    d_plate = np.maximum(np.maximum(px0 - mx, mx - px1), np.abs(my - py) - 0.024)
    plate = np.clip(0.5 - d_plate / texel, 0, 1)
    ring = np.clip(1.0 - np.abs(d_plate) / (0.7 * texel + 0.001), 0, 1)
    top = top * (1 + 0.07 * plate) * (1 - 0.30 * ring)

    def seg(ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        t = np.clip(((mx - ax) * vx + (my - ay) * vy) / (vx * vx + vy * vy), 0, 1)
        return np.hypot(mx - ax - t * vx, my - ay - t * vy)
    x0l = px0 + 0.025
    strokes = [((0.030, 0.012), (0.008, 0.012)), ((0.008, 0.012), (0.0, 0.0)), ((0.0, 0.0), (0.008, -0.012)),
               ((0.008, -0.012), (0.030, -0.012)),                                           # C
               ((0.045, -0.013), (0.050, 0.013)), ((0.050, 0.013), (0.070, 0.010)), ((0.070, 0.010), (0.066, 0.0)),
               ((0.066, 0.0), (0.050, -0.001)), ((0.050, -0.001), (0.074, -0.013)),           # R
               ((0.088, 0.0), (0.104, 0.0)),                                                  # -
               ((0.116, 0.013), (0.132, -0.013)), ((0.132, -0.013), (0.150, 0.013))]          # V
    d_txt = np.min([seg(x0l + a[0], py + a[1], x0l + b[0], py + b[1]) for a, b in strokes], axis=0)
    top = top * (1 - 0.32 * np.clip(1.0 - (d_txt - 0.003) / texel, 0, 1) * plate)
    top = top * (1 - hole) + STAND_HOLE * hole
    in_top = (xx < x1) & (yy < y1)
    for c in range(3):
        img[..., c] = np.where(in_top, top, img[..., c])
    # aluminium disc (by normal, as standing_uv looks it up): mid grey, a little lighter toward the
    # sun's side, a little darker facing up, a faint cool cast; texels past the rim keep the rim's
    x0, y0, x1, y1 = CELL_CHROME
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2 - CELL_INSET
    nx, ny = (xx - cx) / r, -(yy - cy) / r
    k = np.maximum(np.hypot(nx, ny), 1.0)
    nx, ny = nx / k, ny / k
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    az = nx * SUN_AZ[0] + ny * SUN_AZ[1]                                                # -1 .. 1 toward the sun
    val = STAND_TUBE + STAND_TUBE_SUN * az - STAND_TUBE_UP * nz
    in_c = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    for c, tint in enumerate((0.98, 0.99, 1.02)):
        img[..., c] = np.where(in_c, np.clip(val * tint, 0, 255), img[..., c])
    for cell, v in ((CELL_STEEL, STAND_STEEL), (CELL_PLATE, STAND_PLATE), (CELL_EDGE, STAND_EDGE)):
        x0, y0, x1, y1 = cell
        img[y0:y1, x0:x1, :] = v
    rgba = np.concatenate([img / 255.0, np.ones((n, n, 1), np.float32)], axis=2)
    im = bpy.data.images.new("crvgen1_table_stand", n, n, alpha=False)
    im.pixels[:] = rgba[::-1].ravel()                                                   # Blender rows run bottom-up
    im.filepath_raw = path
    im.file_format = 'PNG'
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save()
    bpy.data.images.remove(im)
    return path


def folded_table(bm, cx, cy, z_top):
    top, chrome = _mats()
    _top(bm, cx, cy, z_top, top)
    for side in (-1, 1):
        _leg_frame(bm, cx, cy, z_top - TOP_T, side, True, chrome)


def carve_well(report):
    """Cut the table's footprint out of the interior's cargo floor and build the recess."""
    it = bpy.data.objects.get("interior")
    if it is None:
        report("  well: no interior object")
        return 0
    me = it.data
    names = [m.name if m else "?" for m in me.materials]
    x0, x1 = -(TOP_W / 2 + WELL_GAP), TOP_W / 2 + WELL_GAP
    y0, y1 = CENTRE_Y - (TOP_L / 2 + WELL_GAP), CENTRE_Y + (TOP_L / 2 + WELL_GAP)
    bm = bmesh.new()
    bm.from_mesh(me)
    gl = bm.faces.layers.int.get("gen") or bm.faces.layers.int.new("gen")

    def floor_faces():
        return [f for f in bm.faces if f.is_valid and names[f.material_index] == "Interieur_sol"
                and abs(f.calc_center_median().z - FLOOR_Z) < 0.02 and abs(f.normal.z) > 0.9 and f.calc_center_median().y < -0.9]
    if not floor_faces():
        report("  well: cargo floor not found")
        bm.free()
        return 0
    zb = FLOOR_Z - TUB_DEPTH
    if any(abs(f.calc_center_median().z - zb) < 0.005 and x0 < f.calc_center_median().x < x1 and y0 < f.calc_center_median().y < y1
           for f in bm.faces):
        report("  well: already cut (rerun on a prepared parts file)")
        bm.free()
        return 1
    for co, no in (((x0, 0, 0), (1, 0, 0)), ((x1, 0, 0), (1, 0, 0)), ((0, y0, 0), (0, 1, 0)), ((0, y1, 0), (0, 1, 0))):
        geom = floor_faces()
        edges = {e for f in geom for e in f.edges}
        verts = {v for f in geom for v in f.verts}
        bmesh.ops.bisect_plane(bm, geom=list(verts) + list(edges) + geom, plane_co=co, plane_no=no, dist=1e-5)
    inside = [f for f in floor_faces() if x0 + 1e-4 < f.calc_center_median().x < x1 - 1e-4 and y0 + 1e-4 < f.calc_center_median().y < y1 - 1e-4]
    bmesh.ops.delete(bm, geom=inside, context='FACES')
    # its own black plastic (2026-10-19): on the interior's Plastique_noir (a light leather-grain trim on this sheet)
    # the empty tub read as a flat light-grey panel in the game's flat light (feedback: "there's no hole")
    if WELL_MAT not in names:
        me.materials.append(bpy.data.materials.get(WELL_MAT) or bpy.data.materials.new(WELL_MAT))
        names.append(WELL_MAT)
    mi_wall = names.index(WELL_MAT)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2, (y1 - y0) / 2
    # the rounded tub (2026-10-18, feedback with the samarins photo: "the hole is wrong ... it should be more
    # round"): the rectangular opening drops LEDGE_DROP to a flat ledge the table rests on, then a black plastic
    # tub with rounded corners, walls drawing in and a rounded bottom edge, TUB_DEPTH under the deck (the
    # underbody is at z 0.40-0.46 here: 7 cm to spare). Rings: (inset from the opening, corner radius, depth)
    rings = [(LEDGE_W, 0.090, LEDGE_DROP), (LEDGE_W + 0.020, 0.085, LEDGE_DROP + 0.070),
             (LEDGE_W + 0.050, 0.075, TUB_DEPTH - 0.035), (LEDGE_W + 0.085, 0.050, TUB_DEPTH)]

    def rounded(inset, r):
        """A rounded rectangle inset from the opening: TUB_SEG points per corner, counter-clockwise."""
        ax, ay = hx - inset - r, hy - inset - r
        pts = []
        for qx, qy, a0 in ((1, 1, 0.0), (-1, 1, 90.0), (-1, -1, 180.0), (1, -1, 270.0)):
            for i in range(TUB_SEG):
                a = math.radians(a0 + 90.0 * i / (TUB_SEG - 1))
                pts.append((cx + qx * ax + r * math.cos(a), cy + qy * ay + r * math.sin(a)))
        return pts

    def to_rect(px, py):
        """Where the ray from the centre through (px, py) leaves the opening."""
        dx, dy = px - cx, py - cy
        k = min(hx / abs(dx) if abs(dx) > 1e-9 else 1e9, hy / abs(dy) if abs(dy) > 1e-9 else 1e9)
        return cx + dx * k, cy + dy * k
    first = rounded(*rings[0][:2])
    outer = [to_rect(px, py) for px, py in first]
    vt = [bm.verts.new((px, py, FLOOR_Z)) for px, py in outer]                  # the opening's rim
    vl = [bm.verts.new((px, py, FLOOR_Z - LEDGE_DROP)) for px, py in outer]     # its foot, the ledge's outer edge
    loops = [vt, vl] + [[bm.verts.new((px, py, FLOOR_Z - d)) for px, py in rounded(ins, r)] for ins, r, d in rings]
    new = []
    n = len(first)
    for a, b in zip(loops[:-1], loops[1:]):
        for i in range(n):
            j = (i + 1) % n
            quad = [a[i], a[j], b[j], b[i]]
            if len({v.index for v in quad}) < 4 or len({tuple(round(c, 6) for c in v.co) for v in quad}) < 4:
                quad = [v for k, v in enumerate(quad) if all((v.co - w.co).length > 1e-6 for w in quad[:k])]
            if len(quad) >= 3:
                new.append(bm.faces.new(quad))
    zb = FLOOR_Z - TUB_DEPTH
    mid = bm.verts.new((cx, cy, zb))
    last = loops[-1]
    for i in range(n):
        new.append(bm.faces.new((last[i], last[(i + 1) % n], mid)))
    above = Vector((cx, cy, FLOOR_Z + 0.30))
    for f in new:                                            # facing into the tub (it is seen from inside the car)
        f.material_index = mi_wall
        f.normal_update()
        if f.normal.dot(above - f.calc_center_median()) < 0:
            f.normal_flip()
        f.smooth = True
        f[gl] = 3                                            # generated: baked direct, modest texels
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    me.update()
    report("  well: %d floor faces removed, opening %.2f x %.2f m, rounded tub %.0f mm deep (%d faces)"
           % (len(inside), x1 - x0, y1 - y0, TUB_DEPTH * 1000, len(new)))
    return len(inside)


def build(report=print):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    _mats()
    bm = bmesh.new()
    folded_table(bm, 0.0, CENTRE_Y, FLOOR_Z + 0.002)         # 2 mm proud of the floor: no z-fight at the seam
    ob = _new_object(TABLE, bm)
    ob["table_centre"] = [0.0, CENTRE_Y, FLOOR_Z + 0.002 - TOP_T]
    n = carve_well(report)
    report("  %-13s %4d tris, top %.2f x %.2f at y %.2f; well cut %s" % (TABLE, tris(ob), TOP_W, TOP_L, CENTRE_Y, "ok" if n else "FAILED"))
    return ob


if __name__ in ("__main__", "run"):
    import os
    S = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_")))), "scripts")
    if S not in sys.path:
        sys.path.append(S)
    build()
    if "--save" in sys.argv:
        bpy.ops.wm.save_mainfile()
        print("TABLE saved", bpy.data.filepath)
