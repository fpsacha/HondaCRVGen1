r"""
Door cards (inner trim panels) of the 1997-2001 Honda CR-V (RD1), v7, and the tailgate's card.

Reference photos: wreckers' listings of RD1 door trims (grey interior, 2026-10-10) and the Commons
"MG 87xx-88xx" series of one RD1 (blender/references/commons/unclear): MG 8776 / 8779 / 8782 / 8786
(all four door cards, nearly square on), MG 8826 / 8829 / 8834 (the swing gate's card and the cargo
bay). Measured on those (u, v fractions of the card):
  * a mid-grey moulded card over the whole door below the window, its edge rolled toward the frame;
  * a charcoal, finely dimpled upper insert from the rear edge forward, sunk in the grey frame; the
    inside handle (a dark lever in a dark cup with a lighter bezel) at its front;
  * a charcoal armrest that sweeps down from the front (the pull) and runs level to the rear;
  * a raised lower moulding along the bottom with the map pocket (dark opening under a lip); front
    doors carry the speaker grille in its front corner, rear doors the ashtray; a small lock switch
    under the front armrest (the window switches sit on the armrest's top, which the relief cannot
    show: see _door); a maintenance sticker on the driver's card;
  * the gate (MG 8829, square on): a large service lid near the hinge, a long recessed pull panel along
    the bottom with two round spare-carrier bolt covers, a small square jack/tool lid, a bag hook in a
    recess near the latch, a stop tab and the glass seal along the top, a moulded rib at the latch.

v7 (2026-10-13, feedback: "better texture ... with more details"; screenshot 34.png: the open gate's card a
flat light-grey slab): the cards are drawn with trim_paint's relief terms, KI5's way (their Touran,
Trooper and XJ door cards): lit top edges and dark bottom edges on every moulding, panel lines as a
dark line with a light one beside it, soft shadows under the armrest and lever. Levels come down
to the cabin's (bake_atlas PALETTE: trims sRGB ~70, carpet 48, dash 52-64), which the author called "very
nice": the gate's grey shipped at ~138 against them (165 painted), the doors' at 100-130 under a
blotchy shut-pose AO (x0.5-0.6 over the pocket and under the armrest; bake_atlas TRIM_PREFIXES now
floors it as for the other trims, the relief and its shadows being painted here).

prep_parts builds each card (the traced panel + an edge band to the skin) and calls `relief` for
the raised armrest and pocket lip, then `paint` writes the card's colour texture; bake_atlas calls
`paint_all` again at the start of every bake, so a change here needs a rebake, not a rebuild, and
the bake's copy follows each card's TRUE outline (the panel's faces) instead of its bounding box.
Layouts are in (u, v): u = 0 at the door's rear edge, 1 at its front (hinge) edge, for every door;
v = 0 at the bottom, 1 at the window sill. The gate's u runs from its latch (vehicle left, u 0) to
its hinge (u 1). bake_atlas maps the texture by object y / z (x / z on the gate) over the card's
bounding box (custom properties card_bbox, card_axis) and bakes it flat onto the card (gen 5).
`arm`, `arm_w` and `pocket` are geometry (relief): changing them moves the armrest and pocket lip at
the next rebuild, so the painted ones stay in register only through a full rebuild.
"""
import os

import numpy as np

import trim_paint as tp

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
BAKE_PNG = os.path.join(ROOT, "blender", "bake")
PX_PER_M = 1000.0            # painted map density: 10 px/cm against the bake's ~2.8 texels/cm
PREFILTER = 0.0008           # metres: half a BAKE texel (the 2x bake samples the cards every ~1.8 mm; 1.6 mm,
                             # 0.45 of a shipped texel, predates it; texture fix 2026-10-13)

# colours, sRGB 0-255, painted. compose takes ~x0.92 off (the trim mask's AO floor and the dirt;
# bake_atlas TRIM_PREFIXES), so the grey ships at ~80: the cabin's trims ship at ~70 and KI5's door
# cards at a median 55 (Touran) to 69 (Trooper). Ratios from the photos (grey card : charcoal insert :
# pocket ~ 1 : 0.5 : 0.25)
GREY = (88, 90, 93)
INSERT = (47, 49, 52)
ARM = (42, 44, 47)
CUP = (22, 23, 25)
OPENING = (19, 20, 22)
SPEAKER = (38, 39, 42)
LEVER = (100, 102, 106)
SWITCH = (28, 29, 31)
ROCKER = (64, 66, 69)
LABEL = (186, 186, 180)
LABEL_BLUE = (62, 90, 148)
LABEL_AMBER = (196, 150, 42)
TEXT = (66, 66, 70)
SEAL = (24, 24, 26)
HOOK = (118, 120, 124)

LAYOUT = {
    "front": {
        "handle": (0.48, 0.61, 0.76, 0.88),
        "arm": [(0.82, 0.88), (0.77, 0.76), (0.71, 0.66), (0.58, 0.61), (0.32, 0.59), (0.04, 0.58)],
        "arm_w": 0.075,
        "switch": (0.46, 0.53, 0.43, 0.49),         # the lock switch under the armrest (photo MG 8776)
        "pocket": (0.24, 0.96, 0.03, 0.33),
        "opening": (0.30, 0.71, 0.11, 0.21),
        "lower": (0.085, 1.08, 0.03, 0.40),         # the raised lower moulding the pocket sits in
        "speaker": (0.74, 0.93, 0.07, 0.31),
        "ashtray": None,
        "plug": (0.905, 0.875),                     # screw cover in the upper front corner
        "label": (0.880, 0.945, 0.700, 0.780),      # maintenance sticker (driver's card only)
        "insert_top": 0.965,
    },
    "rear": {
        "handle": (0.62, 0.79, 0.745, 0.855),
        "arm": [(0.92, 0.82), (0.87, 0.69), (0.79, 0.60), (0.52, 0.58), (0.14, 0.56)],
        "arm_w": 0.08,
        "switch": None,
        "pocket": (0.46, 0.94, 0.03, 0.30),
        "opening": (0.52, 0.78, 0.08, 0.18),
        "lower": (0.27, 1.08, 0.03, 0.42),
        "speaker": None,
        "ashtray": (0.82, 0.91, 0.10, 0.21),
        "plug": None,
        "label": None,
        "insert_top": 0.965,
    },
}
LABEL_DOORS = ("door_fl",)                 # the driver's card (left-hand drive) carries the sticker
ARM_OUT = 0.030          # metres the armrest stands proud of the card
POCKET_OUT = 0.015
# the side-hinged tailgate's trim (photo MG 8829, square on; MG 8826 / 8834 for the relief): the hinge
# is at +x, so the latch is at low u
LAYOUT["gate"] = {
    "lid": (0.63, 0.945, 0.20, 0.72),               # service lid near the hinge
    "lid_small": (0.244, 0.367, 0.455, 0.70),       # jack / tool lid
    "hook": (0.160, 0.228, 0.56, 0.79),             # bag hook in its recess, near the latch
    "pull": (0.107, 0.605, 0.046, 0.446),           # long recessed pull panel along the bottom
    "knobs": [(0.493, 0.354), (0.247, 0.354)],      # spare-carrier bolt covers (r KNOB_R)
    "label": (0.425, 0.505, 0.58, 0.80),            # caution label (spare-carrier load)
    "tab": (0.51, 0.60, 0.925, 1.05),               # the stop tab on the top edge
    "rib": 0.045,                                   # moulded rib along the latch edge (u)
    "roll": 0.875,                                  # the top roll's moulded line (v)
    "seal": 0.968,                                  # the glass seal along the top edge (v up)
}
KNOB_R = 0.022


def kind(door):
    if door == "trunk":
        return "gate"
    return "front" if door in ("door_fl", "door_fr") else "rear"


def material(door):
    import bpy
    name = "DoorCard_" + door
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        b = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if b is not None:
            b.inputs['Base Color'].default_value = (0.30, 0.31, 0.32, 1.0)
            b.inputs['Roughness'].default_value = 0.8
    return mat


# ----------------------------------------------------------------------------------------- paint

def render(door, bbox, outline=None, px_per_m=PX_PER_M):
    """The card's colour map as RGBA floats (H, W, 4), rows bottom-up (Blender's pixel order).
    bbox = a0, a1, z0, z1 (a = y on the doors, x on the gate); outline = (tris, segs) in metres from
    (a0, z0) (paint_all), else the bbox with rounded corners stands in for the card's edge."""
    a0, a1, z0, z1 = bbox
    W, H = a1 - a0, z1 - z0
    c = tp.Canvas(W, H, px_per_m, GREY)
    k = kind(door)
    lay = LAYOUT[k]

    def P(u, v):
        return (u * W, v * H)

    def R(r):
        return (r[0] * W, r[2] * H, r[1] * W, r[3] * H)

    if outline is not None:
        card = c.outline(*outline)
    else:
        card = c.rrect(0.0, 0.0, W, H, 0.03)
    c.grain(0.035, 0.020, seed=11)                        # moulded plastic: soft mottling, no speckle
    if k == "gate":
        _gate(c, lay, P, R, W, H)
    else:
        _door(c, door, lay, P, R, W, H)
    # the card's rolled edge toward the door frame: lit along the top, dark along the bottom, and a
    # dark line at the very edge (the gap the card's edge leaves against the frame)
    c.grain(0.02, 0.012, seed=5)                          # one soft mottle over every part of the card
    c.bevel(card, 0.022, hi=1.14, lo=0.68, raised=True, edge=0.97)
    c.scale(np.maximum(card, -(card + 0.005)), 0.80)      # the outer 5 mm: the gap against the frame
    c.prefilter(PREFILTER)
    return c.to_rgba()


def _door(c, door, lay, P, R, W, H):
    arm_pts = [P(u, v) for u, v in lay["arm"]]
    arm_hw = lay["arm_w"] * H / 2.0
    # mid section between armrest and lower moulding: a shallow dish, darker toward the bottom
    c.gradient_v(c.rrect(-1, -1, W + 1, H + 1), 1.03, 0.94, 0.05 * H, 0.60 * H)
    # lower moulding (pocket and speaker sit in it): a raised panel with its panel line
    low = c.rrect(*R(lay["lower"]), 0.05)
    c.bevel(low, 0.016, hi=1.15, lo=0.72, raised=True)
    c.groove(low, 0.007, k=0.60, hi=1.12, hw=0.006)
    c.gradient_v(low, 1.04, 0.93, lay["lower"][2] * H, lay["lower"][3] * H)
    # scuffs: kick marks low on the moulding, broad and faint
    c.grain(0.06, 0.07, seed=sum(map(ord, door)), d=c.rrect(0.0, 0.0, W, 0.13 * H, 0.03))
    if lay["opening"]:
        _pocket(c, R(lay["opening"]))
    if lay["speaker"]:
        _speaker(c, R(lay["speaker"]))
    if lay["ashtray"]:
        at = c.rrect(*R(lay["ashtray"]), 0.008)
        c.fill(at, (70, 72, 75))
        c.bevel(at, 0.008, hi=1.20, lo=0.70, raised=True)
        c.groove(at, 0.006, k=0.55, hi=1.10, hw=0.005)
        x0, y0, x1, y1 = R(lay["ashtray"])
        c.fill(c.rrect(x0 + 0.012, y1 - 0.024, x1 - 0.012, y1 - 0.012, 0.004), CUP)   # finger notch
    # upper insert: sunk in the grey frame, its front edge following the pull, its bottom the armrest
    top = lay["insert_top"] * H
    rear = 0.03 * W
    below = [(arm_pts[0][0] + 0.02, H + 1.0)] + arm_pts + [(-1.0, arm_pts[-1][1]), (-1.0, -1.0), (W + 1.0, -1.0), (W + 1.0, H + 1.0)]
    keep_out = c.polygon(below) - (arm_hw + 0.012)
    ins = c.cut(c.rrect(rear, 0.40 * H, W, top, 0.035), keep_out)
    c.fill(ins, INSERT)
    c.gradient_v(ins, 1.07, 0.93, 0.55 * H, top)
    c.bevel(ins, 0.014, hi=1.22, lo=0.62, raised=False)  # sunk: the frame's lip shades its top
    c.groove(ins, 0.006, k=0.62, hi=1.14, hw=0.006)
    c.dashes(_offset_line(arm_pts, arm_hw + 0.012 + 0.012, W, H, rear), length=0.010, gap=0.007, w=0.0035, k=0.80)
    # inside handle in the insert's front
    _handle(c, R(lay["handle"]), child_lock=kind(door) == "rear")
    # armrest and pull: charcoal, its top edge lit, a soft shadow on the card under it
    arm = c.band(arm_pts, arm_hw)
    c.shadow(lambda X, Y: c.band(arm_pts, arm_hw, X, Y), off=0.016, soft=0.016, k=0.62)
    c.fill(arm, ARM)
    c.bevel(arm, 0.010, hi=1.30, lo=0.70, raised=True)
    c.gradient_v(arm, 1.06, 0.95, min(p[1] for p in arm_pts) - arm_hw, max(p[1] for p in arm_pts) + arm_hw)
    # stitching where the armrest's vinyl meets the card, just above the relief box. Nothing is drawn
    # inside the box's height (its middle 72 %, ARM_OUT proud): the decal maps by y / z only, so the
    # card BEHIND the box carries the same marks, and the game camera sees that card over the box's
    # top: window switches painted on the armrest's face showed twice on the driver's door (pzview
    # left_240, 2026-10-13). The switches sit on the armrest's top on the RD1, which the relief's top
    # face (one texture row) cannot show.
    c.dashes(arm_pts, offset=-0.86 * arm_hw, length=0.010, gap=0.006, w=0.0035, k=0.78)
    if lay["switch"]:                                    # lock switch under the armrest
        s = c.rrect(*R(lay["switch"]), 0.006)
        c.fill(s, SWITCH)
        c.bevel(s, 0.005, hi=1.30, lo=0.70, raised=True)
        x0, y0, x1, y1 = R(lay["switch"])
        rk = c.rrect((x0 + x1) / 2 - 0.009, (y0 + y1) / 2 - 0.007, (x0 + x1) / 2 + 0.009, (y0 + y1) / 2 + 0.007, 0.003)
        c.fill(rk, ROCKER)
        c.bevel(rk, 0.004, hi=1.30, lo=0.65, raised=True)
    if lay["plug"]:                                      # screw cover: a small recessed disc
        px, py = P(*lay["plug"])
        d = c.circle(px, py, 0.010)
        c.scale(d, 0.86)
        c.bevel(d, 0.004, hi=1.20, lo=0.70, raised=False)
    if lay["label"] and door in LABEL_DOORS:
        _label(c, R(lay["label"]), header=LABEL_BLUE)


def _offset_line(arm_pts, off, W, H, rear):
    """The insert's lower border, `off` above the armrest's level run, from its rear end to where
    the pull starts to rise (stitching runs along it)."""
    level = [p for p in arm_pts if p[1] <= min(q[1] for q in arm_pts) + 0.06 * H]
    level = sorted(level)
    pts = [(max(rear + 0.02, x), y + off) for x, y in level]
    return pts if len(pts) >= 2 else [(rear + 0.02, arm_pts[-1][1] + off), (0.5 * W, arm_pts[-1][1] + off)]


def _pocket(c, r):
    """Map pocket: a dark opening under the moulding's lip, darkest under the lip."""
    x0, y0, x1, y1 = r
    op = c.rrect(x0, y0, x1, y1, 0.02)
    c.fill(op, OPENING)
    c.gradient_v(op, 0.70, 1.35, y0, y1)                 # the lip shades the top of the opening
    c.bevel(op, 0.006, hi=1.25, lo=0.70, raised=False)
    lip = c.rrect(x0 - 0.004, y1 + 0.002, x1 + 0.004, y1 + 0.012, 0.005)
    c.scale(np.maximum(lip, -op), 1.20)                   # the lip's rounded top edge catches the light


def _speaker(c, r):
    x0, y0, x1, y1 = r
    ring = c.rrect(x0 - 0.008, y0 - 0.008, x1 + 0.008, y1 + 0.008, 0.035)
    c.bevel(ring, 0.009, hi=1.18, lo=0.70, raised=True)
    c.groove(ring, 0.006, k=0.62, hi=1.10, hw=0.005)
    g = c.rrect(x0, y0, x1, y1, 0.028)
    c.fill(g, SPEAKER)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rad = np.clip(np.hypot(c.X - cx, c.Y - cy) / (0.5 * max(x1 - x0, y1 - y0)), 0.0, 1.0)
    c.scale(g, 0.86 + 0.14 * rad)                          # the cone behind reads darker in the middle
    c.dots(g, 0.011, 0.0030, 0.72, offset=(x0, y0))        # perforation, coarse enough not to shimmer
    c.bevel(g, 0.006, hi=1.20, lo=0.72, raised=False)


def _handle(c, r, child_lock=False):
    x0, y0, x1, y1 = r
    bez = c.rrect(x0, y0, x1, y1, 0.012)
    c.fill(bez, (60, 62, 65))
    c.bevel(bez, 0.006, hi=1.30, lo=0.70, raised=True)
    cup = c.rrect(x0 + 0.008, y0 + 0.008, x1 - 0.008, y1 - 0.008, 0.008)
    c.fill(cup, CUP)
    c.bevel(cup, 0.010, hi=1.40, lo=0.55, raised=False)
    # lever: pivots at the cup's front (+u) end and reaches toward the rear
    ly = y0 + 0.47 * (y1 - y0)
    pts = [(x1 - 0.020, ly), (x0 + 0.030, ly)]
    c.shadow(lambda X, Y: c.band(pts, 0.006, X, Y), off=0.008, soft=0.008, k=0.55)
    lever = c.band(pts, 0.006)
    c.fill(lever, LEVER)
    c.bevel(lever, 0.004, hi=1.30, lo=0.65, raised=True)
    c.fill(c.circle(x1 - 0.020, ly, 0.008), (80, 82, 86))
    if child_lock:                                         # the child-lock tab at the cup's rear
        t = c.rrect(x0 + 0.012, ly - 0.012, x0 + 0.024, ly + 0.012, 0.003)
        c.fill(t, (150, 152, 156))
        c.bevel(t, 0.003, hi=1.15, lo=0.70, raised=True)


def _label(c, r, header):
    x0, y0, x1, y1 = r
    lab = c.rrect(x0, y0, x1, y1, 0.002)
    c.shadow(lambda X, Y: c.rrect(x0, y0, x1, y1, 0.002, X, Y), off=0.002, soft=0.003, k=0.80)
    c.fill(lab, LABEL)
    hh = min(0.012, 0.28 * (y1 - y0))
    c.fill(c.rrect(x0, y1 - hh, x1, y1, 0.0), header)
    # text: a few dark lines (no glyphs: they could only alias)
    ty = y1 - hh - 0.008
    i = 0
    while ty - 0.005 > y0 + 0.004 and i < 4:
        w = (x1 - x0 - 0.010) * (0.92, 0.70, 0.85, 0.55)[i]
        c.fill(c.rrect(x0 + 0.005, ty - 0.005, x0 + 0.005 + w, ty, 0.0), TEXT)
        ty -= 0.010
        i += 1


def _gate(c, lay, P, R, W, H):
    c.gradient_v(c.rrect(-1, -1, W + 1, H + 1), 1.04, 0.95, 0.0, H)
    # the top roll: a moulded line across the card under the glass seal, the seal itself
    roll = lay["roll"] * H
    c.groove(c.Y - roll, 0.007, k=0.62, hi=1.14, hw=0.007)
    c.gradient_v(c.rrect(-1, roll, W + 1, H + 1), 1.10, 1.0, roll, lay["seal"] * H)
    seal = c.rrect(-1.0, lay["seal"] * H, W + 1.0, H + 1.0)
    c.fill(seal, SEAL)
    c.scale(c.rrect(-1.0, lay["seal"] * H, W + 1.0, lay["seal"] * H + 0.004), 1.6)   # its rounded lower edge
    # moulded rib along the latch edge
    rx = lay["rib"] * W
    rib = c.rrect(rx - 0.012, 0.06 * H, rx + 0.012, (lay["roll"] - 0.03) * H, 0.012)
    c.bevel(rib, 0.010, hi=1.18, lo=0.72, raised=True)
    # service lid near the hinge: a recessed panel outlined by its gap
    lid = c.rrect(*R(lay["lid"]), 0.04)
    c.groove(lid, 0.008, k=0.55, hi=1.14, hw=0.007)
    c.bevel(lid, 0.016, hi=1.18, lo=0.74, raised=False)
    x0, y0, x1, y1 = R(lay["lid"])
    c.fill(c.rrect((x0 + x1) / 2 - 0.020, y0 + 0.006, (x0 + x1) / 2 + 0.020, y0 + 0.016, 0.004), CUP)   # pry notch
    # jack / tool lid: smaller, its finger notch at the top
    sl = c.rrect(*R(lay["lid_small"]), 0.012)
    c.groove(sl, 0.007, k=0.55, hi=1.14, hw=0.006)
    c.bevel(sl, 0.012, hi=1.16, lo=0.76, raised=False)
    x0, y0, x1, y1 = R(lay["lid_small"])
    notch = c.rrect((x0 + x1) / 2 - 0.016, y1 - 0.018, (x0 + x1) / 2 + 0.016, y1 - 0.006, 0.005)
    c.fill(notch, CUP)
    c.bevel(notch, 0.004, hi=1.4, lo=0.6, raised=False)
    # long pull panel along the bottom: recessed, its lower lip is what a hand pulls the gate shut by
    pull = c.rrect(*R(lay["pull"]), 0.035)
    c.groove(pull, 0.008, k=0.55, hi=1.14, hw=0.007)
    c.bevel(pull, 0.020, hi=1.20, lo=0.66, raised=False)
    x0, y0, x1, y1 = R(lay["pull"])
    grip = c.rrect(x0 + 0.05, y0 + 0.008, x1 - 0.05, y0 + 0.030, 0.010)
    c.fill(grip, (40, 41, 44))
    c.gradient_v(grip, 0.55, 1.15, y0 + 0.008, y0 + 0.030)
    c.bevel(grip, 0.006, hi=1.3, lo=0.6, raised=False)
    # spare-carrier bolt covers: round caps standing proud of the pull panel
    for u, v in lay["knobs"]:
        kx, ky = P(u, v)
        c.shadow(lambda X, Y, kx=kx, ky=ky: c.circle(kx, ky, KNOB_R, X, Y), off=0.006, soft=0.008, k=0.60)
        kn = c.circle(kx, ky, KNOB_R)
        c.fill(kn, (84, 86, 89))
        c.bevel(kn, 0.008, hi=1.30, lo=0.62, raised=True)
        slot = c.rrect(kx - 0.013, ky - 0.0025, kx + 0.013, ky + 0.0025, 0.002)   # the cap's screwdriver slot
        c.fill(slot, CUP)
    # bag hook in its recess near the latch
    hk = c.rrect(*R(lay["hook"]), 0.010)
    c.fill(hk, (70, 72, 75))
    c.bevel(hk, 0.010, hi=1.25, lo=0.60, raised=False)
    c.groove(hk, 0.006, k=0.60, hi=1.12, hw=0.005)
    x0, y0, x1, y1 = R(lay["hook"])
    cx = (x0 + x1) / 2.0
    hook = [(cx, y1 - 0.018), (cx, y0 + 0.030), (cx - 0.006, y0 + 0.020), (cx - 0.016, y0 + 0.020), (cx - 0.020, y0 + 0.032)]
    c.shadow(lambda X, Y: c.band(hook, 0.0055, X, Y), off=0.007, soft=0.007, k=0.55)
    hb = c.band(hook, 0.0055)
    c.fill(hb, HOOK)
    c.bevel(hb, 0.004, hi=1.25, lo=0.65, raised=True)
    # stop tab on the top edge
    tab = c.rrect(*R(lay["tab"]), 0.010)
    c.fill(tab, (100, 102, 105))
    c.bevel(tab, 0.010, hi=1.25, lo=0.65, raised=True)
    # caution label (amber header with the warning triangle)
    x0, y0, x1, y1 = R(lay["label"])
    _label(c, (x0, y0, x1, y1), header=LABEL_AMBER)
    hh = min(0.012, 0.28 * (y1 - y0))
    tri = [(x0 + 0.006, y1 - hh + 0.002), (x0 + 0.020, y1 - hh + 0.002), (x0 + 0.013, y1 - 0.002)]
    c.fill(c.polygon(tri), (30, 30, 32))


# ------------------------------------------------------------------------------- bake-time painting

def _card_outline(ob, bbox):
    """(tris, segs) of the card panel in canvas metres: the largest connected set of the card
    material's faces (the traced panel; the armrest and pocket relief are separate pieces)."""
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    mi = names.index("DoorCard_" + ob.name) if ("DoorCard_" + ob.name) in names else -1
    if mi < 0:
        return None
    polys = [p for p in me.polygons if p.material_index == mi]
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for p in polys:
        vs = list(p.vertices)
        for v in vs[1:]:
            ra, rb = find(vs[0]), find(v)
            if ra != rb:
                parent[ra] = rb
    groups = {}
    for p in polys:
        groups.setdefault(find(p.vertices[0]), []).append(p)
    panel = max(groups.values(), key=lambda g: sum(p.area for p in g))
    ax = 0 if ob.get("card_axis", "y") == "x" else 1
    a0, _a1, z0, _z1 = bbox
    mw = ob.matrix_world

    def pt(vi):
        co = mw @ me.vertices[vi].co
        return (co[ax] - a0, co.z - z0)
    tris, count = [], {}
    for p in panel:
        vs = list(p.vertices)
        for i in range(1, len(vs) - 1):
            tris.append((pt(vs[0]), pt(vs[i]), pt(vs[i + 1])))
        for i in range(len(vs)):
            e = tuple(sorted((vs[i], vs[(i + 1) % len(vs)])))
            count[e] = count.get(e, 0) + 1
    segs = [(pt(a), pt(b)) for (a, b), n in count.items() if n == 1]
    return tris, segs


def paint_all(out_dir=None):
    """Repaint every card in the open .blend (objects carrying card_bbox) along its true outline;
    bake_atlas calls this before its colour bake. Returns the written paths."""
    import bpy
    paths = []
    for ob in bpy.data.objects:
        bb = ob.get("card_bbox") if ob.type == 'MESH' else None
        if bb is None:
            continue
        bbox = tuple(bb)
        paths.append(paint(ob.name, bbox, out_dir=out_dir, outline=_card_outline(ob, bbox)))
    print("door_cards: painted %s" % ", ".join(os.path.basename(p) for p in paths))
    return paths


def paint(door, bbox, out_dir=None, outline=None, px_per_m=PX_PER_M):
    """Write doorcard_<door>.png (sRGB) into out_dir (default blender/bake) through Blender."""
    import bpy
    rgba = render(door, bbox, outline, px_per_m)
    H, W = rgba.shape[:2]
    path = os.path.join(out_dir or BAKE_PNG, "doorcard_%s.png" % door)
    name = "doorcard_" + door
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    im = bpy.data.images.new(name, W, H, alpha=False, float_buffer=False)
    im.pixels[:] = rgba.ravel()
    im.filepath_raw = path
    im.file_format = 'PNG'
    im.save()
    bpy.data.images.remove(im)
    return path


# ---------------------------------------------------------------------------------------- relief

def relief(bm, gl, mi, door, bbox, plane, side):
    """Raised armrest (following LAYOUT's sweep) and pocket lip on the card. plane(y, z) -> |x| of
    the card surface. New faces: material mi, gen 5; returns their count (triangles)."""
    from mathutils import Vector
    lay = LAYOUT[kind(door)]
    y0, y1, z0, z1 = bbox

    def P(uu, vv, out=0.0):
        y = y0 + uu * (y1 - y0)
        z = z0 + vv * (z1 - z0)
        return Vector((side * (plane(y, z) - out), y, z))

    faces = []

    def quad(a, b, c, d, want):
        try:
            f = bm.faces.new((a, b, c, d))
        except ValueError:
            return
        f.material_index = mi
        f.smooth = False
        f[gl] = 5
        f.normal_update()
        if f.normal.dot(want) < 0:
            f.normal_flip()
        faces.append(f)

    cabin = Vector((-side, 0.0, 0.0))
    # armrest: a band along the sweep, ARM_OUT proud, top / front / bottom faces and end caps
    pts = lay["arm"]
    hw = lay["arm_w"] / 2 * 0.72      # narrower than the painted band: its top and underside then sample
                                      # solid charcoal (at the band's edge line they striped)
    rows = []
    for (uu, vv) in pts:
        rows.append([bm.verts.new(P(uu, vv + hw, 0.0)), bm.verts.new(P(uu, vv + hw, ARM_OUT)),
                     bm.verts.new(P(uu, vv - hw, ARM_OUT)), bm.verts.new(P(uu, vv - hw, 0.0))])
    for r0, r1 in zip(rows[:-1], rows[1:]):
        quad(r0[0], r1[0], r1[1], r0[1], Vector((0, 0, 1)) + cabin * 0.2)      # top
        quad(r0[1], r1[1], r1[2], r0[2], cabin)                                 # front
        quad(r0[2], r1[2], r1[3], r0[3], Vector((0, 0, -1)) + cabin * 0.2)     # underside
    for r, toward in ((rows[0], Vector((0, 1, 0))), (rows[-1], Vector((0, -1, 0)))):
        quad(r[0], r[1], r[2], r[3], toward)                                    # end caps
    # pocket lip: a low box across the bottom, POCKET_OUT proud, front and top faces + ends
    u0, u1, v0, v1 = lay["pocket"]
    u0, u1, v0, v1 = u0 + 0.012, u1 - 0.012, v0 + 0.015, v1 - 0.03       # inside the painted lip
    a, b = bm.verts.new(P(u0, v1, 0.0)), bm.verts.new(P(u1, v1, 0.0))
    c, d = bm.verts.new(P(u1, v1, POCKET_OUT)), bm.verts.new(P(u0, v1, POCKET_OUT))
    e, f = bm.verts.new(P(u0, v0, POCKET_OUT)), bm.verts.new(P(u1, v0, POCKET_OUT))
    g, h = bm.verts.new(P(u0, v0, 0.0)), bm.verts.new(P(u1, v0, 0.0))
    quad(a, b, c, d, Vector((0, 0, 1)) + cabin * 0.2)
    quad(d, c, f, e, cabin)
    quad(a, d, e, g, Vector((0, -1, 0)))
    quad(b, c, f, h, Vector((0, 1, 0)))
    quad(g, e, f, h, Vector((0, 0, -1)))
    return 2 * len(faces)
