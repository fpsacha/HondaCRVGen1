r"""
The 2D paint pass on the shell sheet (spec/planar-texture-plan.md, Part B: B2, B3), run by
compose_textures.py when the bake directory holds shell_uvmesh.npz (written by uvmesh_dump.py).

Why: KI5 puts the car's form in the texture and lets the game's 3-step light work on top: dark-ish
sides, brighter tops, subtle crisp seams with a faint highlight on both sides, a highlight on the
real character lines, glass darker at the bottom. Our sheet was the bake's flat paint from roof to
sill, shipped at sRGB ~195 for white where KI5's white sides sit at 102-114. Every term here is
computed per texel from the triangle under it, with lengths in metres on the car, so the same
constants hold at any texel density and on any layout (the xatlas sheet of 2026-10-12 as well as
Part A's planar islands). numpy / scipy only: a paint change is a compose run (seconds), not a bake.

Per texel, in compose's order: shade (the baked AO, lighter on paint) -> level / recolour (KI5's
absolute levels per skin) -> form terms (height ramp, normal elevation) -> lines (seams +
highlights, creases, lamp bezels, drop-glass edges) -> undersides ramped to the dark blocks ->
micro-detail (2026-10-13: plastic grain, dust streaks and crease dust, hand wear, stone chips, then
lock cylinders, washer nozzles and the REALTIME 4WD badge; constants "micro-detail"; then the EX trim's
handle pockets, the Kentucky rear plate and the garnish's CR-V, constants after them) -> rubber
(glued glass seal and frit, with its lip highlight) -> weather -> dark-block fill.

Every drawn line is continuous along its whole edge or not drawn at all (2026-10-13, the author's
"some lines i can see in the texture"): creases are decided per twin chain (CREASE_NEAR), the door
mouldings' welded outline is a seam like their open one, tops under other geometry are not lifted
(OVERHANG_SHARE), undersides fade into the dark blocks instead of zigzagging against them (UNDER_N),
the twins' paint bleeding onto plastic and trim edges takes the part's own colour (base()), and the
glued panes' frit ring is seal (FRIT_MATS).

Every KI5 figure below is from scratch planar/ki5_measure (four cars: Touran, XJ, Trooper, W460;
1,832 seam profiles, 26 skins); "plan" means spec/planar-texture-plan.md v2.

Aux maps (B2): the dump is rasterised at the bake images' size (bake_atlas.SUPERSAMPLE x the sheet,
compose reduces the result) with exact coverage (texel centre inside the triangle; on overlap the
higher island layer loses). Texels no triangle covers take the fields
of the texel compose's Dilate copied their colour from (`fill.idx`), so paint and colour stay in
register into the padding.
"""
import ast
import json
import os

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))


def _bake_const(name):
    """A literal constant of bake_atlas.py (importing it would need bpy and run its bake)."""
    tree = ast.parse(open(os.path.join(HERE, "bake_atlas.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


LAMP_MATS = set(_bake_const("LAMP_MATS"))
GLASS_MATS = set(_bake_const("GLASS_MATS"))
ZONE = _bake_const("ZONE")

# ================================================================================================
# Constants (each with the measurement that set it)
# ================================================================================================
# --- levels (plan B3 "Levels"; ki5_measure out_gradtable.txt, out_trim.txt) ---------------------
# vertical paint at the belt: KI5 white 102-114, silver 64-95, mid colours 40-60, black 26-38 for
# skin colours whose own luma spans ~35-230: L_v = 26 + 0.36 * L(skin), one RGB scale per skin
LEVEL_BASE = 26.0
LEVEL_GAIN = 0.36
# KI5 bumpers / cladding at the belt ~36 (ours baked Body_plastique ~77); 36 -> 58 in polish round 1 (2026-10-17):
# the RD1's unpainted bumpers, flares, rocker and mouldings are a textured DARK GREY (photos 97-170 in daylight),
# and at 36 they shipped black (front 55 with its tops lifted, rear 30, mouldings 34)
PLASTIC_L = 58.0
# glass, per pane: L = top * (GLASS_BOTTOM + (1 - GLASS_BOTTOM) * f^2), f = height fraction in the
# pane. KI5 top quarters: side panes 44-54, windshields 66-78, rear glass 42-54; bottom / top
# 0.64-0.77 on all four cars
GLASS_TOP = {"side": 52.0, "front": 72.0, "rear": 48.0}
GLASS_BOTTOM = 0.67
# lamp lenses, target luma (scale down only; the lens decals multiply inside them): KI5 tail lenses
# (64-77, 16-19, 16-19) = L 31-33, head lenses neutral L 66-101 (Touran 93-95). Phare (the headlamp's
# housing round the lens) takes the head-lens level: it shipped at 61 under the gap AO, and at 144 once
# the lamps left the gap AO (their bezel is their outline). Each is reached on the shaded sheet outside
# the bezel (PaintPass._levels). Since 2026-10-13 the lenses bake opaque (bake_atlas, lens Alpha): the
# head lens bakes its decal (tyre_paint.headlamp_map) at ~165 instead of 36 (screenshot 25.png, "black"
# headlamp) and every lens has headroom to reach its target. Head lens at the top of KI5's range: the
# RD1's clear lens over a chrome reflector reads light in daylight. Amber: KI5's indicators read
# orange; at 70 against the old half-transparent bake it shipped brown (94, 60, 13); 88 lands about
# (125, 80, 17) with the lens map's frame and block. The bumper markers (Reflect_orange, Phare_orange)
# are the same amber
# Feux_rouge / Feux_stop 32 -> 44 (2026-10-17 polish review EXT-12: the unlit tails read maroon (76, 14, 12)
# against the photos' clear red; 44 is the middle ground between KI5's 31-33 and an orange-red daylight lens)
LAMP_L = {"Feux_rouge": 44.0, "Feux_stop": 44.0, "Reflect_red": 28.0,
          "Feux_orange": 88.0, "Phare_orange": 88.0, "Reflect_orange": 88.0,
          "Phare_vitre": 170.0, "Feux_blanc": 150.0, "Phare": 170.0}
# 2026-10-17 lighting pass (feedback: "really upgrade ... the headlights, the lights"): the RD1's headlamp is
# clear glass over bright chrome reflectors (commons: the 2000 EX, front right), not the smoky grey of
# the 100 target; Project Viewpoint shows it up close. Head lenses 100 -> 170, the clear reverse lens 95 -> 150
# kotris's low lamps show a Feux_chrome face in front of a lens in places (the high stop lamp's whole
# face, slivers round the tail and reverse lenses, most of each bumper marker): the projection bake puts
# the lens behind on it, at full strength, and it shipped brighter than the lens it shows (the stop
# lamp (147, 27, 24) beside tail lenses at 72, a white sliver under the reverse lens). A cover texel
# takes the level scale of the nearest lens within LAMP_COVER_R (a plain chrome wall beside a lens goes
# darker with it, as the lamp's housing)
# Chrome too (2026-10-13): kotris rings each headlamp in Chrome (70 body faces, sRGB ~207), a bright
# white frame the real RD1 lamp does not have (its housing reads as a dark gasket in the 2000 EX photo);
# within LAMP_COVER_R of a lens it now takes the lens's level. Badges are far from any lens: untouched.
LAMP_COVER_MATS = {"Feux_chrome", "Chrome"}
LAMP_COVER_R = 0.02
# kotris builds its lenses from unwelded pieces: their open edges inside a lens drew the bezel as dark
# lines across it (the tail lens's middle fold, rectangles above the reverse lens). An open lamp edge
# where a lamp face continues just beyond it (LAMP_INNER[0] out of the face in its plane, within
# LAMP_INNER[1] along its normal: the headlamp's lens lies ~5 mm over its reflector) is no outline;
# lamp / lamp boundaries (amber / red, the reverse lens) are drawn by the lens map instead
LAMP_INNER = (0.003, 0.015)
# trims, target luma (scale down only): KI5's non-paint exterior texels L p10/p50/p90 15/35/74.
# Exterior Plastique_noir (frames, B-pillars, mirrors, handles, rails, wipers) bakes at ~103: the
# cabin's leather layer TEXTURED["Plastique_noir"] (tint 0.22, flat 0.60) also runs on the shell
TRIM_L = {"Plastique_noir": 40.0}

# --- form terms (plan B3; ki5_measure out_gradnormal.txt, out_gradtable.txt) --------------------
# height ramp on non-up-facing paint: KI5 low verticals (z < 0.3 H) x0.70-0.80 of the belt, the
# ramp ending ~0.9 of the sill height; CR-V rocker bottom ~0.35 m, belt 1.10 m
SILL_K = 0.75
RAMP_Z0 = 0.35
RAMP_Z1 = 1.00
RAMP_UP = (0.30, 0.60)           # smooth n.z over which the ramp fades out (hood, roof, sill tops stay bright)
# normal elevation, n = smooth normal z. Up: c * (1 + UP_GAIN n+), then towards white by UP_WHITE n+
# (KI5 tops x1.41-2.75 against the belt, +34..64 levels: nearly additive). Down: c * max(DOWN_MIN,
# 1 + DOWN_GAIN n), on top of the height ramp. KI5's x0.70 at n.z -0.1..-0.3 and x0.49 below
# (out_gradnormal) include the height ramp: those faces sit low. Against vertical faces at the same
# height (out_gradtable) they are x0.88 (XJ z 0.4-0.5), x1.05 (Touran 0.4-0.5); the underside band
# is x0.47 against x0.75 on the Touran's low verticals, i.e. x0.63. The plan's 1.2 / 0.45, multiplied
# by the ramp, left the CR-V's lower doors (n.z -0.14 to -0.27) at 0.64-0.68 of the belt (2026-10-12).
# 0.5 / 0.6 give 0.72-0.76 clean and 0.69-0.72 weathered (KI5's low verticals: x0.70-0.77)
UP_GAIN = 0.25
UP_WHITE = 0.18
UP_FULL = 0.85                   # n+ saturates here: KI5 tops are flat from n.z 0.85 (x1.94), and a linear n+ made the
                                 # decimated roof ribs (smooth n.z 0.9-1.0) read as streaks (2026-10-12)
DOWN_GAIN = 0.5
DOWN_MIN = 0.6
# plastics: half the depth of both terms (plan); a quarter since polish round 1 (2026-10-17): on the decimated
# bumper and rocker (smooth normals varying vertex by vertex) the half-depth up-lift and down term made every
# fallback chart its own grey, "blotchy concrete" (bumper face std 9-15 levels against the paint's 0.4)
PLASTIC_FORM = 0.25
AO_K_PAINT = 0.20                # the baked AO, lighter on paint and plastics so the drawn form leads (plan)
CAVITY_PAINT = 0.25              # the 4 cm cavity AO on paint and plastics: compose's CAVITY; on the 2026-10-12
                                 # bake it is ~1 (p10 1.00) on paint away from the drawn seams, so it costs nothing
AO_K_PLASTIC = 0.12              # ... and on the plastics (polish round 1): the projected AO of kotris's bumper insides
CAVITY_PLASTIC = 0.15            # printed per-face patches
# the bay walls (polish round 1, BAY-1): baked open (bake_atlas.REBAKE_OPEN) their AO still has the engine in front of
# every wall (area-weighted 0.18, the visible walls ~0.3); compose's shell 0.30 / 0.25 left the firewall at ~0.7 of
# the paint beside it. Shallower, so the bay reads body colour with the engine's shadow in it
# Polish round 2 (R2-BAY-2): at 0.15 / 0.12 the walls shipped at paint x ~0.7 +-8 %, no darkening where they meet the
# booster, battery, towers and fuse box (the white car's photos: clear contact shadows). A strong 4 cm cavity (the
# contact pass: baked hood-up like the AO, REBAKE_OPEN) and a little more AO, with the walls' median shading held
# where it was (BAY_KEEP, PaintPass.bay_gain): the walls keep their average colour and gain their shadows
AO_K_BAY = 0.20                  # the 0.6 m AO: 0.40 greyed the big apron flats (the engine in front of every wall)
CAVITY_BAY = 0.60                # the 4 cm contact pass carries the shadows at the parts' feet
BAY_KEEP = (0.15, 0.12)          # the old depths whose median shading bay_gain keeps
BAY_GAIN_MAX = 1.35
PLASTIC_STRAY = 1.5             # plastic texels not of the plastic's own colour and this much lighter than its median
                                 # (projection strays from the twin) take the median
# the form terms read the SMOOTH normal; where a big flat face shares its vertices with a fold, its smooth normal
# tilts far from the face (the gate's skin under the plate: face n.z -0.04, smooth -0.64, so the down term took it
# to 0.6 of the paint above, a dark band, polish round 1 EXT-8). The form's n.z stays within this of the face's
FORM_NZ_TOL = 0.30
# faces whose texels take a flat colour of their own (the bake's shading kept): (what, objects, materials, rules,
# sRGB). Rules on the face: nz_min (face normal z >=), z_min / z_max (centre z), absx_min, y (centre y range),
# outward (face normal x along the side's own x >=). Polish round 1 (2026-10-17):
OVERRIDES = [
    # CAB-5: the inner top of each door under the glass (the belt cap, the door's painted edge band where it turns
    # up to the glass) is the black window felt on the RD1, not body colour
    ("door belt caps", ("door_fl", "door_fr", "door_rl", "door_rr"), ("BodyInner",), {"nz_min": 0.7, "z_min": 1.0}, (30, 30, 32)),
    # EXT-5: kotris's "chrome" pieces at the rear corner of each rear door's glass belt line are its black glass
    # channel (a light grey sliver at 141)
    ("rear door glass channels", ("door_rl", "door_rr"), ("Feux_chrome",), {}, (30, 30, 32)),
    # WHL-1: the bay walls' faces that look outboard inside the FRONT wheelhouses (the strut towers' outer halves,
    # the arch's front and rear walls) take the arch liners' dark grey; the bay side keeps the body colour
    ("front wheelhouse walls", ("bay_walls",), ("Body",), {"absx_min": 0.55, "y": (0.85, 1.80), "z_max": 0.95, "outward": 0.3},
     (28, 28, 29)),
    # EXT-11: build_details' 7 mm seam ring round the fuel flap (black trim) read as a heavy ~1 cm dark bevelled rim;
    # on the car it is the body's own pressed edge round a thin shut line. "paint": the ring takes the body colour
    # (the paint class, recoloured per skin with the form terms); the 1.2 cm gap pass draws the line in its recess
    ("fuel flap ring", ("body",), ("Plastique_noir",), {"gen": 7, "flap": 0.025}, "paint"),
    # polish round 2, R2-OC-6: the outer skin's top return under each window (n.z 0.6-0.96 from z ~1.05 up to the
    # belt moulding) is the RD1's black outer belt weatherstrip; in body colour its backfill copy drew a blue line
    # along the sill seen from the seats with the window down. Black like the belt caps (CAB-5)
    ("door belt top returns", ("door_fl", "door_fr", "door_rl", "door_rr"), ("Body",),
     {"nz_min": 0.45, "z_min": 1.04, "z_max": 1.20, "gen": 0}, (30, 30, 32)),
    # R2-EXT-4: the headlamp housing's floor (kotris Phare, up-facing under the lens) shows below the lens as a
    # light-grey jagged ledge (shipped 146-170, the reflector decal): the lamp's dark lower gasket
    ("headlamp floors", ("body",), ("Phare", "Phare_vitre"), {"nz_min": 0.90, "z_max": 0.76, "y": (1.70, 2.00)}, (44, 44, 46)),
]

# --- lines (plan B3 "Lines"; ki5_measure out_seams3.txt, out_creases.txt) ------------------------
# seam: dark band SEAM_W a side (a gap reads ~1.6 cm + the gap: KI5's 1 texel of 1.3-1.6 cm; the
# design review found ~2 cm total stops beading at the 512 cap), x(1 - SEAM_DARK), darkest at the
# edge (KI5 door/door pooled median x0.77)
SEAM_W = 0.008
SEAM_DARK = 0.25
SEAM_GRAD = 0.30                 # the band lightens by this share from the edge to its outer side
SEAM_FLOOR_TX = 1.5              # the whole band (both sides) never under 1.5 texels of the local density
HI_W = 0.013                     # highlight beyond the dark band, both sides
HI_K = 1.08                      # KI5 door/door highlights x1.08 both sides (Touran 99 % / 88 % present)
# the flush gate (see PaintPass._gate). Joints between objects (doors, hood, gate, body) are always
# drawn: their open edges run 0-10 mm apart (door / body p10-p90 0.5-9 mm), and a 1-2 mm ramp left
# 18-42 % of them highlight-only. Within one object only coincident pieces are flush: their exact
# distance is under the 0.1 mm weld for 1.1 m of seam and spreads evenly from there (0.1-0.5 mm 7.8 m,
# 0.5-1 mm 11.5 m), so 0.5 mm keeps the hairlines and draws the separately modelled mouldings
FLUSH_D = 0.0005
FLUSH_FACING = 0.866             # partners face within 30 degrees ...
FLUSH_PARALLEL = 0.8             # ... and run within 37 degrees of each other
JOINT_R = 0.010                  # an open edge with another object's open edge this close is a shut line
JOINT_FACING = 0.5               # (an12: door / body joints p90 9 mm, facing within 60 degrees)
CHAIN_TURN = 40.0                # degrees: a sharper turn ends an open-edge chain (lamp and window corners)
MIRROR_TOL = 0.003               # metres between a sample and its mirror image on the other side
# creases (twin polylines, Body / Body_plastique): KI5 convex folds x1.16 base + 9 levels, 1-2
# texels; concave x0.88
CREASE_W = 0.007
CREASE_CVX = (1.16, 9.0)
CREASE_CCV = 0.88
CREASE_FLOOR_TX = 1.5            # whole crease line never under 1.5 texels
# crease strength by fold angle: KI5 highlights 35-60 degree folds on 69-88 % of samples, 20-35
# on 8-86 %, 8-20 rarely (Touran 6 %); the CR-V's shallow roof ribs at full strength read as scratches
CREASE_ANG = (20.0, 45.0)
# KI5 draws a crease highlight on a real character line along its whole length, or not at all. Per
# sample (the shipped 2026-10-12 sheet) the twin's creases came out in pieces: the strength followed
# each edge's own fold (a moulding's top edge 22-53 degrees along one chain), chains changed
# convex / concave half way, and the door mouldings carried three parallel creases (convex, concave,
# convex, 1-3 cm apart) beside the moulding's own drawn outline, partly hidden under its dark band
# (the author 2026-10-13, 24.png: "some lines i can see in the texture, its weird"). So a chain is drawn
# whole, at the strength of its median fold and its majority convexity, or dropped when
CREASE_NEAR = 0.5                # ... more of it than this runs within SEAM_W + HI_W + CREASE_W of a drawn seam (the
                                 # seam already is that line: 164 of 310 chains, 79 of 147 m, every moulding and belt crease)
CREASE_LANDED = 0.85             # ... or less of it than this lands on painted texels of its object (the decimated
                                 # surface strays > 1 cm from the twin: 39 chains, 17 m, e.g. the front bumper's at 15 %)
CREASE_MIRROR_TOL = 0.006        # and its mirror image's chain (door_fl <-> door_fr, body onto itself) shares the verdict
LAMP_BEZEL = 0.80                # dark bezel just inside a lens (KI5 lamp outlines L 35-46 against 80-95 inside); 0.65 x 6 mm
LAMP_BEZEL_W = 0.003             # drew the thick black ring round the headlamps (the author 2026-10-17); metres, floored at one texel
DROP_GLASS_EDGE = 0.9            # drop glass (window_*) gets a 1-texel x0.9 edge instead of a rubber seal
RUBBER_W = float(_bake_const("RUBBER_WIDTH"))   # glued glass seal, 3 cm (KI5 draws 2-3 near-black texels)
# the black frit ring round glued glass (kotris's Vitre_noir shells: the quarter windows' is 7-10 cm wide
# front and rear, 3 cm top and bottom) is drawn as the seal. Painted as clear glass it vanished, and the
# 3-10 mm slit between it and the inner pane showed the SeamBack dark block behind as a dotted dark
# line inside the glass (the author 2026-10-13, 22.png)
# ... and painted as glass again since 2026-10-13: round 2 closed the shell cracks (prep_parts
# _close_pane_cracks), so nothing shows through any more, while the all-black ring read as a black angled
# band round the quarter windows (feedback: "there's black angle around the window"). Only the RUBBER_W seal
# along the true outline stays black.
FRIT_MATS = set()
GLASS_JOIN = 0.012               # shells of one pane whose borders run this close are one pane, not outline (kotris's
                                 # windshield rings sit 3-10 mm apart; a true outline has no shell within 1-5 cm)
GLASS_FACING = 0.7               # two glass borders face each other across a slit or ring gap within 45 degrees
GAP_SCALE_NEAR = 0.0             # compose's gap-AO darkening within SEAM_W + HI_W of a drawn seam ...
GAP_SCALE_FAR = 0.5              # ... and elsewhere on painted texels (the drawn seams carry the lines)
# geometry tests
PLANE_TOL = 0.010                # a line source counts for a texel within 1 cm of the texel's tangent plane
FACING_MIN = -0.2                # ... and facing the same way (not the back of a thin panel)
SAMPLE_STEP = 0.0015             # metres between seam samples
KNN = 32                         # nearest samples examined per texel
DARK_RGB = (20, 20, 21)          # dark blocks (plan B4)
# undersides: plan A1 puts every face with n.z < -0.6 below 0.55 m into a flat DARK_RGB block, face by
# face, so a smooth surface turning under (the doors' bottom fold, bumper and sill undersides) came out
# as a zigzag of dark and paint-coloured triangles: the stair-stepped band between the doors and the
# sill (the author 2026-10-13, 23.png). Paint and plastics ramp to DARK_RGB with the smooth normal over
# UNDER_N below UNDER_Z, so the dark faces sit in a gradient that already reached their colour. The
# lower door skin proper (n.z -0.14..-0.27, see DOWN_GAIN) stays out of it
UNDER_N = (-0.30, -0.60)
UNDER_Z = (0.60, 0.50)           # full below 0.50 m, none above 0.60 m (the dark class stops at 0.55)
# overhung tops: a top under other shell geometry is in the car's shadow, not lit like the roof. The
# doors' lower-cladding ledges (z 0.44, 2.7 cm deep, under the door's bottom fold) were lifted to 47-58
# against the 29 of the sill lip in front, and showed as light dashes through the lip's uneven top
# (the author 2026-10-13, 14.png, 23.png). An island whose up-facing texels are mostly under shell geometry
# (a top-down height map) gets no up-lift: 69 islands, 15k texels (ledges 100 %, door moulding tops
# 93-100 %, grille ledges); the rear bumper top (60 %, under the spare) and the roof (<= 37 %) keep it
OVERHANG_RES = 0.004             # metres per cell of the top-down height map
OVERHANG_DZ = 0.010              # geometry this far above a texel overhangs it
OVERHANG_SHARE = 0.75            # share of an island's up-facing texels that must be overhung
# ... and overhung plastic / trim tops are darkened on top of that (2026-10-13): the game's stepped light
# lifts every up-facing face a step whatever the texel, so the doors' cladding ledges just above the
# 0.44 m sill lip (prep_parts.LIP_TOP) would still read as a light line along each door
OVERHANG_DARK = 0.60
BASE_TOL = 14.0                  # sRGB distance that still counts as a material's own colour (compose.PAINT_TOL)
STALE_MAX = 0.01                 # share of the sheet the dump covers and the bake does not (fresh dump: 0.0001)
PAINT_DIM = (0.012, 0.80)        # chromaticity distance, lowest level: a paint texel baked dimmer than the kotris paint
SNAP_TX = 1.5                   # bake texels: a bake-owned texel outside every exact raster takes a triangle this near (_snap_missed)
SNAP_K = 24                      # nearest triangle centres examined per such texel
WORKERS = int(os.environ.get("CRV_WORKERS") or max(1, (os.cpu_count() or 4) - 2))   # leave two cores free

# --- micro-detail (2026-10-13; PaintPass._details) ------------------------------------------------
# the author (in game, 2048 cap, black skin): "is it possible to have better texture, not resolution but just
# better texture with more details?" His black side (33.webp) shipped paint 44, cladding 38 and trims 36:
# one flat dark tone from roof to sill. KI5's sheets carry the small things a real car shows: keyhole and
# washer-nozzle dots, a mottled grain on the bumpers, streaky dirt on the lower body (the Trooper). (Their
# fine noise on the paint is left out: the playbook's grain trap.) Placed here by 3D position from the
# RD1 photos (blender/references/commons):
# black 2000 EX rear left / front right, 1999 LX and 1998 LX in Sebring Silver, '97-'98 Realtime 4WD.
# Every shape is >= ~1 cm (>= ~3 texels at 2.8 texels/cm; ~1 texel after the default 512 cap's 4x box)
# and no term is per-texel noise: the playbook's "grain that reads as concrete" trap.
DETAIL_SEED = 1997
# Relative tints: a tinted texel goes to luma L0 + K * its own luma, in the tint's hue, so the same dust
# LIGHTENS a black skin and DARKENS a white one, as dust and water marks do on the real cars (the black
# EX's doors and gate read grey where dirt dried; on a white car the same dirt reads beige-grey). compose's
# weather() only ever darkens (DIRT_REL), which is right for its broad grime field and why the black skin
# showed no dust at all. Black paint 44 -> 67 at full strength, white 111 -> 90, red 55 -> 71
# Use-wear master switch (2026-10-13): chose a SHOWROOM CLEAN exterior ("no wear at all,
# KI5-clean"), so dust, streaks, flap dust, hand scuffs and stone chips are all scaled by WEAR = 0.
# The layers stay so a 'used' variant is one number away. Grain, locks, nozzles and badges are not wear.
WEAR = 0.0
DUST_TINT = ((1.00, 0.94, 0.84), 52.0, 0.34)
SCUFF_TINT = ((1.00, 1.00, 1.00), 30.0, 0.62)   # polished / scratched plastic and paint where hands go: trims 36 -> 52
CHIP_TINT = ((0.97, 0.97, 1.00), 60.0, 0.50)    # primer grey in a stone chip: black hood top 84 -> 102, white 150 -> 135, red 55 -> 88
# water / dust streaks running down from the window corners, the handle cups, the rear glass, the tail lamps
# and the plate recess (black EX rear left: the gate below the glass and the recess; KI5 Trooper's lower
# body). (object, point on the LEFT side or on the object (snapped to its nearest paint texel), mirrored to
# the right-hand object / x, sub-streaks, length range m). Corners measured on the texel aux maps: front
# door belt z 1.102 at y -0.26 .. 1.076 at y 0.58, rear door 1.107 at y -0.28 .. 1.128 at y -1.04, quarter
# glass bottom z 1.163 y -1.85..-1.33, rear glass bottom z 1.172 x -0.60..0.60, handle plates (build_details)
# front y -0.164..0.070 bottom z 0.926, rear y -1.157..-0.923 bottom z 0.951, plate recess bottom z 0.80
STREAKS = [
    ("door_fl", (-0.86, -0.245, 1.090), True, 3, (0.10, 0.30)),      # front window, rear lower corner
    ("door_fl", (-0.86, 0.545, 1.066), True, 2, (0.07, 0.20)),       # ... front lower corner (mirror sail)
    ("door_rl", (-0.86, -0.305, 1.097), True, 2, (0.08, 0.24)),      # rear window, front lower corner
    ("door_rl", (-0.86, -1.045, 1.118), True, 3, (0.10, 0.30)),      # ... rear lower corner
    ("door_fl", (-0.86, -0.125, 0.918), True, 2, (0.05, 0.16)),      # front handle cup, lower corners
    ("door_fl", (-0.86, 0.040, 0.918), True, 1, (0.05, 0.14)),
    ("door_rl", (-0.86, -1.115, 0.943), True, 2, (0.05, 0.16)),      # rear handle cup
    ("door_rl", (-0.86, -0.965, 0.943), True, 1, (0.05, 0.14)),
    ("body", (-0.80, -1.820, 1.145), True, 3, (0.10, 0.28)),         # quarter glass, rear lower corner
    ("body", (-0.80, -1.360, 1.150), True, 2, (0.08, 0.22)),         # ... front lower corner
    ("body", (-0.66, -2.000, 1.150), True, 2, (0.08, 0.22)),         # under the tail lamps (rear corners)
    ("trunk", (-0.56, -2.060, 1.150), True, 3, (0.12, 0.34)),        # rear glass, lower corners, down the gate
    ("trunk", (-0.56, -2.130, 0.795), False, 2, (0.06, 0.16)),       # plate recess, lower corners
    ("trunk", (-0.14, -2.130, 0.795), False, 2, (0.06, 0.16)),
    ("body", (-0.84, -1.545, 0.888), False, 2, (0.06, 0.18)),        # fuel flap, rear lower corner (filler drips)
]
STREAK_W = (0.012, 0.024)        # width at the top (m): 3-7 texels, 1-2 after the 512 cap; tapers to 55 %
STREAK_A = (0.50, 0.90)          # strength at the top, fading to 0 at the end
STREAK_SPREAD = 0.022            # sub-streaks start within this of the corner, along the panel
STREAK_SWAY = (0.002, 0.006)     # water does not run straight: a slow sideways wander (amplitude, m) ...
STREAK_WAVE = (0.06, 0.15)       # ... over this wavelength (m)
# dust in the lower door creases: beside every drawn seam (open edges, moulding outlines) below DUST_LOW_Z
# on near-vertical paint and plastics, falling off over DUST_CREASE_W outside the seam's dark band. Not on
# up-facing ledges: lifted ledges along the sill read as light dashes (the author 2026-10-13, 14.png, 23.png)
DUST_CREASE = 0.55
DUST_CREASE_W = 0.025
DUST_LOW_Z = (0.85, 0.55)        # none above 0.85 m, full below 0.55 m
# dust round the fuel flap (build_details FLAP_C / FLAP_HALF / FLAP_R: centre y -1.472 z 0.9855, 19.4 x
# 17.5 cm, 3.5 cm corners, left rear quarter): a ring outside the flap's seam, heavier at the bottom where
# it collects, and inside along the flap's own lower edge
FLAP = ((-1.472, 0.9855), (0.097, 0.0875), 0.035)
FLAP_DUST = 0.42
FLAP_DUST_W = 0.012
# stone chips: primer-grey specks on the hood's leading 18 cm (densest at the edge), the nose paint, and
# lighter scuffs on the front bumper's top (black EX front right: chips along the hood's front edge and
# its bumper top worn grey). Diameter 0.9-1.5 cm (2.5-4 texels; KI5 draws its smallest marks 1-2 texels at
# 0.6 texels/cm), elliptic, randomly turned
CHIPS = {"hood": 30, "nose": 8, "bumper": 24}
CHIP_R = (0.0045, 0.0075)
CHIP_ASPECT = (1.0, 1.7)
CHIP_A = (0.70, 1.00)
CHIP_EDGE = (0.07, 0.18)         # hood: chip density e-folds over the first (m) behind its front edge, none past the second
# grain on the unpainted black plastics (Body_plastique: bumpers, cladding, sills, door mouldings): the
# RD1's textured grey-black plastic reads mottled in every photo. Two smooth 3D value-noise octaves, so it
# runs across island seams: soft stipple blobs of ~1.5 cm (contrast-shaped so most of the surface stays
# flat) and a ~7 cm mottle. Amplitudes x1 +- these
GRAIN_CELL = (0.016, 0.070)
GRAIN_AMP = (0.075, 0.045)
# worn where hands go (handle cups, the gate handle under the plate garnish's top bar): build_details
# HANDLE_AT / PLATE_A, PLATE_B / GRIP_LEN, GRIP_DY; the gate's bar runs z 1.00-1.075 over the recess
# (texel aux, x -0.16), its kotris pull pocket at x -0.34..-0.22
HANDLES = {"door_fl": (-0.047, 0.975, 0.165), "door_fr": (-0.047, 0.975, 0.165),
           "door_rl": (-1.040, 1.000, 0.157), "door_rr": (-1.040, 1.000, 0.157)}   # (y, z, grip length)
PLATE_HALF = (0.117, 0.049)
SCUFF_A = 0.45
GATE_PULL = ((-0.37, -0.19), (0.995, 1.022), (0.955, 0.995))   # x range, bar lip z, recess top z
# lock cylinders: front doors on build_details' lock square (16 mm, 8.9 cm behind the handle centre),
# the gate at the right-hand end of the plate garnish's top bar (black EX rear left: a 2.5 cm ring
# beside the CR-V letters; the recess ends at x -0.118 here). Chrome face, dark keyway, a ring of key
# scratches round it
DOOR_LOCK = ((-0.86, -0.136, 0.975), 0.0075)                  # left door; mirrored to door_fr
GATE_LOCK = ((-0.165, -2.125, 1.040), 0.0085, 0.0115)         # face radius, bezel radius
LOCK_RGB = (150, 152, 156)       # paint_textures.CHROME_DK; badges ship at ~190
LOCK_DARK = (30, 30, 32)
# windscreen washer nozzles: two black domes on the hood near its rear edge, both on the driver's half
# (1999 LX front left and 2000 EX front right, measured along the hood's rear edge between its corners:
# 10 % and 38 % of the width from the left corner, ~6 cm ahead of the edge, consistent in both views
# within the perspective). Not geometry: painted 2.0 x 2.8 cm, dark with a small highlight
NOZZLES = [(-0.570, 0.060), (-0.170, 0.060)]                  # (x, metres ahead of the hood's rear edge)
NOZZLE_R = (0.010, 0.014)        # half width (x), half length (y)
NOZZLE_RGB = (24, 24, 25)
# REALTIME 4WD: the post-facelift North American cars carry it in chrome on the rear glass's lower right
# (black 2000 EX rear left and 1998 LX rear left; the '97-'98 side decal is pre-facelift only). Measured
# against the H badge (6.25 cm wide here): 11.3 cm long, 0.9 cm tall, centred 2.2 cm left of the H.
# Drawn 1.2 cm tall so its letters own 3 texel rows (0.9 cm left a 1-texel dashed line). It sits on the
# glass's 3 cm black band in the photo; the seal compose draws there would cover it, so it rides just
# above (centre 3.8 cm up the glass from the outline)
BADGE_TEXT = "REALTIME 4WD"
BADGE_SIZE = (0.115, 0.012)
BADGE_AT = (-0.077, 0.038)       # x of the centre; distance of the centre up the glass from its lower outline (m)
BADGE_RGB = (176, 178, 184)
# window seal highlights: the glued panes' 3 cm seal (compose RUBBER_RGB 24) is one flat near-black band;
# a real seal's rounded lip catches the light next to the body and its edge shows a thin line against
# the glass. Multipliers of RUBBER_RGB over (from, to) metres inside the pane outline
RUBBER_LIP = (0.002, 0.009, 1.9)
RUBBER_INNER = (0.004, 1.45)     # the last this-many metres of the seal before the glass

# --- paint character (2026-10-13, the RD1's factory paints: paint_textures.PAINTS, spec/paint-colours.md) ----
# Every paint is levelled to KI5's vertical belt level (LEVEL_BASE / LEVEL_GAIN) from its median sRGB. Its
# tops then lift toward white (UP_WHITE, solid paints: Taffeta White, Milano Red) or, for a metallic or pearl,
# toward its chip photo's brighter colour taken to white's luma (the hue of the flake in the sun), by
# UP_WHITE x FINISH_LIFT: Clover Green and the two blues turn greener / bluer and brighter on the hood and
# roof, Nighthawk Black shows a blue sheen, Sebring Silver and Naples Gold brighten. Shipped medians, belt ->
# tops (2026-10-13 scratch build): Electron Blue (40, 42, 97) -> (84, 96, 179), Supermarine (25, 50, 81) ->
# (66, 106, 155), Clover (6, 61, 36) -> (44, 121, 93), Nighthawk (36, 36, 41) -> (86, 89, 104), Sebring 85 ->
# 145, Naples (92, 87, 79) -> (154, 147, 136); solid: Taffeta (106, 107, 104) -> (157, 158, 154), Milano
# (112, 21, 31) -> (163, 65, 75). Plain lift on the pearls would have given e.g. Electron (86, 87, 145)
FINISH_LIFT = {"solid": 1.0, "metallic": 1.5, "pearl": 1.25}
# Per-paint rendering levels (polish round 2, R2-EXT-1, 2026-10-17): by the one formula Taffeta White (L 236), Sebring
# Silver (167) and Naples Gold (172) shipped as nearly the same grey: door belt 115 / 93 / 96, hood top 157 / 146 / 148
# (scratch skinstat.py, the shipped 2048 sheets; the paint pass's own belt stat reads ~7 lower). KI5's silvers sit at
# 64-95 on the belt and its whites read white on the hood. The factory colours (paint_textures.PAINTS,
# spec/paint-colours.md) are unchanged; only how they are levelled: {Honda code: {"belt": vertical level replacing
# LEVEL_BASE + LEVEL_GAIN x L, "up_k": x the up-lift toward the top colour}}. White's belt 111 -> 120 and its tops
# toward ~200 (lift x2.7); silver's belt 86 -> 72 (tops ~135); gold keeps the formula and its beige
SKIN_TUNE = {"NH-578": {"belt": 120.0, "up_k": 2.7},
             "NH-552M": {"belt": 72.0}}

# --- door handles, EX trim (build_details: body-colour bezel and grip) ----------------------------------------
# A body-colour handle on a body-colour door reads by the dark finger pocket behind its grip (1998 EX in
# Supermarine Blue: a dark slot across each bezel, the lever in front of it). A rounded pocket on the bezel
# plate round the grip, darkened x(1 - POCKET_DARK), anti-aliased; the grip itself (standing 1.4 cm proud)
# keeps the paint. (half length beyond the grip's ends, half height, corner radius), metres
HANDLE_POCKET = (0.006, 0.024, 0.016)
POCKET_DARK = 0.55

# --- rear licence plate (plate_paint.py: an early-1990s Kentucky plate, KNOX county) ---------------------------
# Kentucky issues rear plates only. 12 x 6 in in the tailgate's plate recess, as on the North American cars
# (black 2000 EX rear left, silver 1998 LX, the California car): the recess outline on the shipped sheet runs
# x -0.606..-0.105, z 0.81..1.075 with the garnish bar (the gate's pull handle) across its top, z 1.00..1.06,
# the floor under it z 0.81..1.00 (shell dump, 2026-10-13). Kotris modelled the market without a plate there:
# chrome CR-V letters in the middle of the floor (x -0.405..-0.196, z 0.86..0.91) and a plain bar. With the
# plate, that floor is cleared to paint (RECESS) and the letters go on the bar where the US cars carry them
# (GARNISH_*: "CR-V" with three short bars to its left, the lock cylinder at the bar's right end, GATE_LOCK).
# Drawn as absolute overlays (their own colours on every skin), the plate with its contact shadow
PLATE = True
PLATE_AT = (-0.356, 0.903)       # x, z of the plate's centre: centred on the floor under the bar
PLATE_DEPTH = 0.020              # texels within this of the rearmost rear-facing surface at their (x, z) carry it
RECESS = ((-0.600, -0.110), (0.800, 0.995))   # x, z box of the recess floor whose baked lettering is cleared
RECESS_GAP = 0.015               # and no gap-AO outline within this of a cleared texel (the letters' 1.2 cm gap pass)
GARNISH_TEXT = "CR-V"
GARNISH_AT = (-0.285, 1.028)     # x, z of the lettering's centre on the bar (photo: the V ends ~3 cm short of the lock)
GARNISH_SIZE = (0.165, 0.024)    # width, height (m)
GARNISH_BARS = (-0.425, 0.032, 3)   # the three short bars left of the letters: x centre, length, count

# --- EX badge (OFF: the North American RD1 EX carries no trim badge) -------------------------------------------
# Honda's parts catalogue lists the 1999-2001 CR-V's emblems for every trim (EX, LX, SE): the front and rear H,
# the C / R / - / V letters on the plate garnish and the REALTIME 4WD sticker; no EX emblem (hondapartsnow.com,
# 1999 and 2001 CR-V emblem pages, 2026-10-13), and the black 2000 EX's gate (rear left photo) has none. Kept
# as an option: a chrome "EX" on the gate's upper left above the garnish bar, in the REALTIME badge's style
EX_BADGE = False
EX_AT = (-0.560, 1.108)          # x, z of the badge centre on the gate
EX_SIZE = (0.048, 0.020)         # width, height (m): ~6 x 2.5 texels rows at 2.8 texels/cm
EX_OUTLINE = 0.0015              # dark rim round the letters (m) so chrome reads on white and silver paint

# --- painted reflections (OFF: the author removed them in game 2026-10-13; 0 = off, byte-identical output) ---------------------------
# The illustrator's gloss: on the glass a soft sky gradient (lighter and bluer toward the top of each pane) with
# a horizon band (a darker strip under a crisp edge), and on the body sides a faint horizon line (lighter
# above, a thin dark line, slightly darker below). Strength 1 is the full effect below; previews at 0.5 / 1.0
# 1.0 / 1.0 chosen by the author from the previews, then OFF the same day after the in-game look: the glass
# horizon band read as an outline "of where the rear window folds" on every window ("remove it"); the
# body line is the same effect. Keep 0 unless he asks again.
REFLECT_GLASS = 0.0
REFLECT_BODY = 0.0
SKY_RGB = (150, 168, 188)        # what the glass lifts toward at its top
SKY_A = 0.30                     # lift at the very top of a pane, strength 1
SKY_FROM = 0.35                  # height fraction where the sky gradient starts
GLASS_HORIZON = {"side": 0.40, "front": 0.30, "rear": 0.44}   # height fraction of the horizon edge per pane kind
GLASS_BAND = (0.16, 0.30)        # band depth under the edge (pane fraction), darkening x(1 - this) at strength 1
GLASS_EDGE = (0.025, 0.35)       # a bright line just over the edge: width (pane fraction), lift toward SKY_RGB
BODY_HORIZON_Z = 0.86            # metres: between the rub strips' top (0.72) and the handles (0.93)
BODY_LINE = (0.012, 0.20)        # dark line: width (m, under the edge), darkening at strength 1
BODY_SKY = (0.18, 0.08)          # lighter above: fade height (m), lift at strength 1
BODY_GROUND = 0.05               # darker below the line, strength 1

# ================================================================================================
CLS_NONE, CLS_PAINT, CLS_PLASTIC, CLS_TRIM, CLS_GLASS, CLS_LAMP, CLS_CHROME = range(7)
CLS_NAMES = ("none", "paint", "plastic", "trim", "glass", "lamp", "chrome")
PAINT_MATS = {"Body"}
PLASTIC_MATS = {"Body_plastique"}
TRIM_MATS = {"Plastique_noir", "Partie_noir"}
CHROME_MATS = {"Chrome"}
NOT_PAINTED_OBJ = {"arch_liners", "bay_walls", "antenna"}
DARK_MATS = {"Dessous", "SeamBack"}
DARK_KEEP = {"Pneu", "Jante", "RimWell", "Rotor"}
SPARE_MATS = ["Pneu", "Jante"]   # bake_atlas.SPARE_MATS: on the trunk only the spare carries them
SEAM_CLS = (CLS_PAINT, CLS_PLASTIC, CLS_TRIM, CLS_CHROME)        # texels that receive seam lines
SOURCE_CLS = (CLS_PAINT, CLS_PLASTIC, CLS_TRIM, CLS_CHROME, CLS_LAMP)
SKIN_CLS = (CLS_PAINT, CLS_PLASTIC)
EPS = 1e-6


def luma(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def rasterise(x, y, prio, size, chunk=2_000_000):
    """Exact coverage: texel (r, c) belongs to a triangle when its centre (c + .5, r + .5) is inside.
    x, y: (T, 3) texel coordinates; prio: lower wins on overlap. Returns (tri (S, S) int32, -1 empty;
    bary (S, S, 3) float32)."""
    T = len(x)
    c0 = np.clip(np.ceil(x.min(1) - 0.5), 0, size).astype(np.int64)
    c1 = np.clip(np.floor(x.max(1) - 0.5), -1, size - 1).astype(np.int64)
    r0 = np.clip(np.ceil(y.min(1) - 0.5), 0, size).astype(np.int64)
    r1 = np.clip(np.floor(y.max(1) - 0.5), -1, size - 1).astype(np.int64)
    nc, nr = c1 - c0 + 1, r1 - r0 + 1
    area2 = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    n = np.where((nc > 0) & (nr > 0) & (np.abs(area2) > 1e-12), nc * nr, 0).astype(np.int64)
    cum = np.cumsum(n)
    pix, tri, bw = [], [], []
    start = 0
    while start < T:
        base = cum[start - 1] if start else 0
        end = max(start + 1, int(np.searchsorted(cum, base + chunk, side="right")))
        ids = np.arange(start, end)
        cnt = n[ids]
        tot = int(cnt.sum())
        start = end
        if not tot:
            continue
        ti = np.repeat(ids, cnt)
        k = np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        c = c0[ti] + k % nc[ti]
        r = r0[ti] + k // nc[ti]
        px, py = c + 0.5, r + 0.5
        X, Y, A = x[ti], y[ti], area2[ti]
        w0 = ((X[:, 1] - px) * (Y[:, 2] - py) - (X[:, 2] - px) * (Y[:, 1] - py)) / A
        w1 = ((X[:, 2] - px) * (Y[:, 0] - py) - (X[:, 0] - px) * (Y[:, 2] - py)) / A
        w2 = 1.0 - w0 - w1
        ok = (w0 >= -EPS) & (w1 >= -EPS) & (w2 >= -EPS)
        pix.append((r * size + c)[ok])
        tri.append(ti[ok])
        bw.append(np.stack([w0, w1, w2], 1)[ok])
    out_tri = np.full(size * size, -1, dtype=np.int32)
    out_b = np.zeros((size * size, 3), dtype=np.float32)
    if pix:
        pix, tri, bw = np.concatenate(pix), np.concatenate(tri), np.concatenate(bw)
        order = np.lexsort((tri, prio[tri], pix))
        pix, tri, bw = pix[order], tri[order], bw[order]
        first = np.ones(len(pix), dtype=bool)
        first[1:] = pix[1:] != pix[:-1]
        out_tri[pix[first]] = tri[first]
        out_b[pix[first]] = np.clip(bw[first], 0.0, 1.0)
    return out_tri.reshape(size, size), out_b.reshape(size, size, 3)


def _samples(A, B, step):
    """Points every `step` along segments A->B (both ends included); returns (points, segment index)."""
    L = np.linalg.norm(B - A, axis=1)
    k = np.maximum(1, np.ceil(L / step).astype(np.int64))
    seg = np.repeat(np.arange(len(A)), k + 1)
    t = (np.arange(len(seg)) - np.repeat(np.cumsum(k + 1) - (k + 1), k + 1)) / np.repeat(k, k + 1)
    return A[seg] + (B[seg] - A[seg]) * t[:, None], seg


def _ray_hits(q, dn, V, reach):
    """Per point q (N, 3): 1 when the line q + s dn, |s| <= reach, passes through one of the triangles
    V (M, 3, 3) (Moller-Trumbore, both directions), else 0."""
    out = np.zeros(len(q), dtype=np.int64)
    V0, E1, E2 = V[:, 0], V[:, 1] - V[:, 0], V[:, 2] - V[:, 0]
    for c0 in range(0, len(q), 2000):
        dd = dn[c0:c0 + 2000][:, None, :]
        h = np.cross(dd, E2[None])
        det = (E1[None] * h).sum(-1)
        ok = np.abs(det) > 1e-12
        inv = 1.0 / np.where(ok, det, 1.0)
        sv = q[c0:c0 + 2000][:, None, :] - V0[None]
        u = (sv * h).sum(-1) * inv
        qv = np.cross(sv, E1[None])
        v = (dd * qv).sum(-1) * inv
        s = (E2[None] * qv).sum(-1) * inv
        out[c0:c0 + 2000] = (ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (np.abs(s) <= reach)).any(1)
    return out


def _rect(r, size=None):
    """A dark block / swatch rect from the meta, in pixels with rows from the top: a list is
    [x0, y0, x1, y1] (end exclusive, the plan's A4 format), a dict {"x", "y", "w", "h"}. Nothing else
    is guessed: telling [x, y, w, h] from [x0, y0, x1, y1] by the numbers misread any cell within one
    cell size of the corner (a 16 px cell at (4, 4) shrank to 12 px)."""
    if isinstance(r, dict):
        x0, y0 = int(r["x"]), int(r["y"])
        x1, y1 = x0 + int(r["w"]), y0 + int(r["h"])
    elif isinstance(r, (list, tuple)) and len(r) == 4:
        x0, y0, x1, y1 = (int(v) for v in r)
    else:
        raise ValueError("meta rect %r: expected [x0, y0, x1, y1] or {x, y, w, h}" % (r,))
    if x1 <= x0 or y1 <= y0 or x0 < 0 or y0 < 0 or (size is not None and (x1 > size or y1 > size)):
        raise ValueError("meta rect %r: empty or off the %s px sheet ([x0, y0, x1, y1], end exclusive)" % (r, size))
    return x0, y0, x1, y1


def _hash3(ix, iy, iz, seed):
    """Integer lattice hash -> uniform -1..1 (deterministic: the same car on every build)."""
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663) ^ (iz.astype(np.int64) * 83492791) ^ (seed * 2654435761)
    h = h & 0xFFFFFFFF
    h = (((h >> 16) ^ h) * 0x45D9F3B) & 0xFFFFFFFF
    h = (((h >> 16) ^ h) * 0x45D9F3B) & 0xFFFFFFFF
    h = (h >> 16) ^ h
    return (h & 0xFFFF).astype(np.float64) / 32767.5 - 1.0


def vnoise(p, cell, seed):
    """Smooth 3D value noise (-1..1) at points p (N, 3) metres, lattice `cell` metres: evaluated in 3D
    so it runs on across island seams and panel joints (a 2D noise per island would step at every seam)."""
    q = np.asarray(p, dtype=np.float64) / cell
    i = np.floor(q)
    f = q - i
    u = f * f * (3.0 - 2.0 * f)
    i = i.astype(np.int64)
    acc = np.zeros(len(q))
    for dx in (0, 1):
        wx = u[:, 0] if dx else 1.0 - u[:, 0]
        for dy in (0, 1):
            wy = u[:, 1] if dy else 1.0 - u[:, 1]
            for dz in (0, 1):
                wz = u[:, 2] if dz else 1.0 - u[:, 2]
                acc += wx * wy * wz * _hash3(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return acc


def _text_mask(text, px=96):
    """A white-on-black coverage image (float 0..1) of `text`, tight to its ink: Pillow's bundled font
    (load_default(size) is FreeType with Pillow >= 10.1; the bitmap fallback is fine at badge size)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.load_default(size=px)
    except TypeError:
        font = ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    sw = max(1, px // 16)                # bolder strokes: the badge is ~3 texels tall, thin strokes filter away
    x0, y0, x1, y1 = probe.textbbox((0, 0), text, font=font, stroke_width=sw)
    img = Image.new("L", (x1 - x0 + 2, y1 - y0 + 2), 0)
    ImageDraw.Draw(img).text((1 - x0, 1 - y0), text, fill=255, font=font, stroke_width=sw, stroke_fill=255)
    return np.asarray(img, dtype=np.float32) / 255.0


def _rrect_sd(u, v, half, r):
    """Signed distance (m) to a rounded rectangle centred at 0 (half sizes, corner radius); < 0 inside."""
    qx = np.abs(u) - (half[0] - r)
    qy = np.abs(v) - (half[1] - r)
    return np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0)) + np.minimum(np.maximum(qx, qy), 0.0) - r


def _mirror_name(name):
    """The object on the other side of the car: door_fl <-> door_fr, window_rl <-> window_rr, ...;
    everything else (body, hood, trunk) is its own mirror image."""
    for a, b in (("_fl", "_fr"), ("_fr", "_fl"), ("_rl", "_rr"), ("_rr", "_rl")):
        if name.endswith(a):
            return name[:-len(a)] + b
    return name


class PaintPass:
    """Everything skin-independent, computed once from the dump: per-texel classes and form fields,
    line multipliers, glass and lamp levels. compose then calls ao_k(), cavity(), gap_scale(),
    base(), skin() per paint, rubber(), dark_fill() and report() / debug()."""

    def __init__(self, path, fill, colour, paint_srgb, log=print):
        """path: shell_uvmesh.npz; fill: compose's Dilate for the shell; colour: the filled bake
        colour (S, S, 3); paint_srgb: the kotris paint the bake wrote (compose.PAINT_SRGB)."""
        self.log = log
        self.paint_srgb = np.asarray(paint_srgb, dtype=np.float32)
        D = np.load(path)
        # the dump is taken at the SHEET size (its meta rects are layout pixels); the bake images are
        # SS x that (bake_atlas.SUPERSAMPLE). Everything here rasterises at the bake's size, the rects
        # scale by SS, and "a texel" in a width floor means a SHIPPED texel (self.ss bake texels)
        self.dump_size = int(D["size"])
        colour = np.asarray(colour, dtype=np.float32)
        self.size = S = int(colour.shape[0])
        if S < self.dump_size or S % self.dump_size:
            raise ValueError("shell_uvmesh.npz is %d px, the bake %d px (no whole multiple): a stale dump" % (self.dump_size, S))
        self.ss = S // self.dump_size
        self.meta = json.loads(str(D["meta"])) if "meta" in D.files else {}
        self.obj_names = [str(s) for s in D["obj_names"]]
        self.mat_names = [str(s) for s in D["mat_names"]]
        self.tri_obj = D["tri_obj"].astype(np.int64)
        self.tri_mat = D["tri_mat"].astype(np.int64)
        self.tri_gen = D["tri_gen"].astype(np.int64)
        self.tri_island = D["tri_island"].astype(np.int64)
        self.tri_wid = D["tri_wid"].astype(np.int64)
        self.tri_pos = D["tri_pos"].astype(np.float64)
        self.tri_nrm = D["tri_nrm"].astype(np.float64)
        self.tri_fnrm = _unit(D["tri_fnrm"].astype(np.float64))
        self.tri_uv = D["tri_uv"].astype(np.float64)
        self.crease = {k: D[k] for k in D.files if k.startswith("crease_")}
        self._classify()
        self._raster(fill)
        self.colour = colour
        self._lamp_covers()
        self._overhang()
        self._levels_measure()
        self._lines()
        self._glass()
        self._fields()
        self._details()
        self.stats = {}

    # -------------------------------------------------------------------------------------------
    # triangles
    def _classify(self):
        mats = np.array(self.mat_names)[self.tri_mat]
        objs = np.array(self.obj_names)[self.tri_obj]
        cls = np.full(len(mats), CLS_NONE, dtype=np.int8)
        cls[np.isin(mats, list(PAINT_MATS))] = CLS_PAINT
        cls[np.isin(mats, list(PLASTIC_MATS))] = CLS_PLASTIC
        cls[np.isin(mats, list(TRIM_MATS))] = CLS_TRIM
        cls[np.isin(mats, list(GLASS_MATS))] = CLS_GLASS
        cls[np.isin(mats, list(LAMP_MATS))] = CLS_LAMP
        cls[np.isin(mats, list(CHROME_MATS))] = CLS_CHROME
        gen = self.tri_gen
        ok = np.isin(gen, (0, 5, 7)) & ~np.char.startswith(objs.astype(str), "acc_") & ~np.isin(objs, list(NOT_PAINTED_OBJ))
        ok &= ~np.isin(self.tri_island, (-2, -3))               # dark blocks and swatches (Part A)
        # the dark class of plan A1, for layouts without islands: undersides only seen lying on the ground
        cz = self.tri_pos[:, :, 2].mean(1)
        dark = np.isin(mats, list(DARK_MATS)) | ((self.tri_fnrm[:, 2] < -0.6) & (cz < 0.55) & ~np.isin(mats, list(DARK_KEEP)))
        ok &= ~dark
        # the spare on the gate gets no paint (plan B3): its Pneu / Jante faces and every trunk face
        # inside its radius and outboard of its inner face (the hub insert is trunk Plastique_noir,
        # 2.344 m behind the axle line; the gate skin behind the tyre starts at 2.131, its inner face 2.130)
        spare = (objs == "trunk") & np.isin(mats, SPARE_MATS)
        self.tri_spare = np.zeros(len(mats), dtype=bool)
        if spare.any():
            c = self.tri_pos[spare].reshape(-1, 3).mean(0)
            d = np.hypot(self.tri_pos[spare, :, 0] - c[0], self.tri_pos[spare, :, 2] - c[2]).max()
            inner = self.tri_pos[spare, :, 1].max() - 0.005
            cen = self.tri_pos.mean(1)
            self.tri_spare = (objs == "trunk") & (np.hypot(cen[:, 0] - c[0], cen[:, 2] - c[2]) < d) & (cen[:, 1] < inner)
            ok &= ~self.tri_spare
        cls[~ok] = CLS_NONE
        self.tri_cls = cls
        # OVERRIDES: per face, the index of the rule that takes it (-1 none)
        self.tri_ovr = np.full(len(mats), -1, dtype=np.int64)
        cen3 = self.tri_pos.mean(1)
        fn = self.tri_fnrm
        for k, (_what, onames, mnames, rule, _rgb) in enumerate(OVERRIDES):
            m = np.isin(objs, list(onames)) & np.isin(mats, list(mnames)) & (self.tri_ovr < 0)
            if "nz_min" in rule:
                m &= fn[:, 2] >= rule["nz_min"]
            if "z_min" in rule:
                m &= cen3[:, 2] >= rule["z_min"]
            if "z_max" in rule:
                m &= cen3[:, 2] <= rule["z_max"]
            if "absx_min" in rule:
                m &= np.abs(cen3[:, 0]) >= rule["absx_min"]
            if "y" in rule:
                m &= (cen3[:, 1] >= rule["y"][0]) & (cen3[:, 1] <= rule["y"][1])
            if "outward" in rule:
                m &= fn[:, 0] * np.sign(cen3[:, 0]) >= rule["outward"]
            if "gen" in rule:
                m &= self.tri_gen == rule["gen"]
            if "flap" in rule:                                   # within the fuel flap's box (FLAP) + margin, left side
                (yc, zc), half, _rad = FLAP
                m &= ((cen3[:, 0] < -0.6) & (np.abs(cen3[:, 1] - yc) < half[0] + rule["flap"])
                      & (np.abs(cen3[:, 2] - zc) < half[1] + rule["flap"]))
            self.tri_ovr[m] = k
            if isinstance(_rgb, str) and _rgb == "paint":        # body-colour overrides join the paint class
                cls[m] = CLS_PAINT
        self.tri_is_drop = np.char.startswith(objs.astype(str), "window_")
        self.objs, self.mats = objs, mats
        # island layer (plan A2.4: the higher layer loses on overlap)
        layer = {int(i["id"]): int(i.get("layer", 1)) for i in self.meta.get("islands", [])}
        self.tri_prio = np.array([layer.get(int(i), 1) for i in self.tri_island], dtype=np.int64) if layer else np.ones(len(cls), np.int64)

    # -------------------------------------------------------------------------------------------
    # B2: aux maps
    def _snap_missed(self, x, y, tri, bary, miss):
        """In place: each texel of `miss` (S, S) takes the triangle whose UV footprint lies nearest its centre,
        within SNAP_TX bake texels, with the barycentrics of the nearest point of it. Returns how many."""
        R, C = np.nonzero(miss)
        if not len(R):
            return 0
        cen = np.stack([x.mean(1), y.mean(1)], 1)
        ext = np.sqrt(((np.stack([x, y], -1) - cen[:, None, :]) ** 2).sum(-1)).max(1)
        tree = cKDTree(cen)
        n = 0
        for s0 in range(0, len(R), 40_000):
            n += self._snap_chunk(x, y, tri, bary, R[s0:s0 + 40_000], C[s0:s0 + 40_000], tree, ext)
        return n

    def _snap_chunk(self, x, y, tri, bary, rr, cc, tree, ext):
        px, py = cc + 0.5, rr + 0.5
        k = min(SNAP_K, len(ext))
        _d, nb = tree.query(np.stack([px, py], 1), k=k, workers=WORKERS)
        nb = nb.reshape(len(px), -1)
        X, Y = x[nb], y[nb]                                     # (M, k, 3)
        P = np.stack([px, py], 1)[:, None, None, :]
        V = np.stack([X, Y], -1)                                # (M, k, 3, 2)
        best_d = np.full(len(px), np.inf)
        best_t = np.full(len(px), -1, dtype=np.int64)
        best_q = np.zeros((len(px), 2))
        for e in range(3):                                      # nearest point on each edge of each candidate
            a, b = V[:, :, e], V[:, :, (e + 1) % 3]
            ab = b - a
            t = np.clip(((P[:, :, 0] - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-12), 0.0, 1.0)
            q = a + ab * t[..., None]
            d = np.sqrt(((P[:, :, 0] - q) ** 2).sum(-1))
            d = np.where(ext[nb] > 1e-9, d, np.inf)
            j = d.argmin(1)
            dj = d[np.arange(len(px)), j]
            upd = dj < best_d
            best_d[upd] = dj[upd]
            best_t[upd] = nb[np.arange(len(px)), j][upd]
            best_q[upd] = q[np.arange(len(px)), j][upd]
        ok = best_d <= SNAP_TX
        rr, cc, t, q = rr[ok], cc[ok], best_t[ok], best_q[ok]
        X, Y = x[t], y[t]
        a2 = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
        a2 = np.where(np.abs(a2) > 1e-12, a2, 1e-12)
        w0 = ((X[:, 1] - q[:, 0]) * (Y[:, 2] - q[:, 1]) - (X[:, 2] - q[:, 0]) * (Y[:, 1] - q[:, 1])) / a2
        w1 = ((X[:, 2] - q[:, 0]) * (Y[:, 0] - q[:, 1]) - (X[:, 0] - q[:, 0]) * (Y[:, 2] - q[:, 1])) / a2
        w = np.clip(np.stack([w0, w1, 1.0 - w0 - w1], 1), 0.0, 1.0)
        w /= np.maximum(w.sum(1, keepdims=True), 1e-9)
        tri[rr, cc] = t
        bary[rr, cc] = w
        return int(ok.sum())

    def _raster(self, fill):
        S = self.size
        uv = self.tri_uv
        x, y = uv[..., 0] * S, (1.0 - uv[..., 1]) * S
        tri, bary = rasterise(x, y, self.tri_prio, S)
        covered = tri >= 0
        if fill is not None:
            # a dump of another unwrap at the same size passes the size check and would paint one
            # layout's fields onto another's bake: on a fresh dump 0.01 % of the sheet is covered by
            # the dump and not by the bake (2026-10-12), a stale one far more. Any coverage counts
            # (`touched`, grey edge texels included), so a bake margin of 0 cannot trip it
            stale = float((covered & ~getattr(fill, "touched", fill.cov)).mean())
            if stale > STALE_MAX:
                raise ValueError("shell_uvmesh.npz is stale: %.2f%% of the sheet is covered by its triangles but not by the "
                                 "bake (fresh: ~0.01%%); re-dump it with the bake, or delete it for the plain compose"
                                 % (100.0 * stale))
            # texels the bake owns but no triangle's exact raster covers (Cycles' own coverage test, slivers of
            # thin charts) take the triangle nearest to them in UV (SNAP_TX). Left out, their fields came from
            # the nearest covered texel of ANY chart: the hood lip's one-texel sliver took a lamp cover's class
            # 20 px away, shipped unrecoloured as raw kotris paint, and Dilate spread it over its gutter (light
            # grey dashes either side of the hood's H, polish round 1 EXT-1)
            miss = fill.cov & ~covered
            n_snap = self._snap_missed(x, y, tri, bary, miss)
            covered = tri >= 0
            self.log("paint: %d bake-owned texels outside every triangle's exact raster snapped to their nearest "
                     "triangle (of %d)" % (n_snap, int(miss.sum())))
        # texels per metre of every triangle
        uv_area = 0.5 * np.abs((x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0]))
        a3 = 0.5 * np.linalg.norm(np.cross(self.tri_pos[:, 1] - self.tri_pos[:, 0], self.tri_pos[:, 2] - self.tri_pos[:, 0]), axis=1)
        self.tri_rho = np.sqrt(uv_area / np.maximum(a3, 1e-12))
        # fill: a covered texel is its own source; any other takes the texel compose's Dilate copied its
        # colour from, or the nearest covered texel to that one
        own = ndimage.distance_transform_edt(~covered, return_distances=False, return_indices=True)
        if fill is not None:
            fr, fc = fill.idx[0], fill.idx[1]
            sr, sc = own[0][fr, fc], own[1][fr, fc]
        else:
            sr, sc = own[0], own[1]
        rr, cc = np.indices((S, S))
        sr = np.where(covered, rr, sr)
        sc = np.where(covered, cc, sc)
        cidx = np.full((S, S), -1, dtype=np.int64)
        cidx[covered] = np.arange(int(covered.sum()))
        self.src = cidx[sr, sc]                                  # (S, S) -> compact index
        t = tri[covered]
        b = bary[covered].astype(np.float64)
        self.t = t
        self.pos = (self.tri_pos[t] * b[:, :, None]).sum(1)
        self.nrm = _unit((self.tri_nrm[t] * b[:, :, None]).sum(1))
        self.fnrm = self.tri_fnrm[t]
        self.cls = self.tri_cls[t]
        self.obj = self.tri_obj[t]
        self.rho = self.tri_rho[t]
        self.cpix = np.nonzero(covered.ravel())[0]               # compact -> flat texel index
        self.log("paint: aux %d triangles, %.1f%% of texels covered; painted texels: %s"
                 % (len(self.tri_cls), 100.0 * covered.mean(),
                    ", ".join("%s %.1f%%" % (CLS_NAMES[k], 100.0 * (self.cls == k).sum() / S / S) for k in range(1, 7))))

    def _overhang(self):
        """self.sky (compact, bool): False on the texels of planar islands whose up-facing paint /
        plastic texels lie mostly under other shell geometry (OVERHANG_SHARE): they get no up-lift.
        One top-down height map (the highest shell surface over each OVERHANG_RES cell, accessories,
        liners and bay walls left out) answers it for every texel."""
        N = len(self.cls)
        self.sky = np.ones(N, dtype=bool)
        use = (~np.char.startswith(self.objs.astype(str), "acc_")) & ~np.isin(self.objs, list(NOT_PAINTED_OBJ))
        P = self.tri_pos[use]
        if not len(P):
            return
        lo = P.reshape(-1, 3).min(0) - 0.01
        X = (P[..., 0] - lo[0]) / OVERHANG_RES
        Y = (P[..., 1] - lo[1]) / OVERHANG_RES
        W = int(X.max()) + 2
        H = int(Y.max()) + 2
        c0 = np.clip(np.ceil(X.min(1) - 0.5), 0, W).astype(np.int64)
        c1 = np.clip(np.floor(X.max(1) - 0.5), -1, W - 1).astype(np.int64)
        r0 = np.clip(np.ceil(Y.min(1) - 0.5), 0, H).astype(np.int64)
        r1 = np.clip(np.floor(Y.max(1) - 0.5), -1, H - 1).astype(np.int64)
        nc, nr = c1 - c0 + 1, r1 - r0 + 1
        A = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
        n = np.where((nc > 0) & (nr > 0) & (np.abs(A) > 1e-12), nc * nr, 0).astype(np.int64)
        top = np.full(W * H, -np.inf)
        ids = np.nonzero(n)[0]
        cum = np.cumsum(n[ids])
        start = 0
        while start < len(ids):                                  # ~2M candidate cells per chunk
            base = cum[start - 1] if start else 0
            end = max(start + 1, int(np.searchsorted(cum, base + 2_000_000, side="right")))
            ii = ids[start:end]
            start = end
            cnt = n[ii]
            ti = np.repeat(ii, cnt)
            k = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
            c = c0[ti] + k % nc[ti]
            r = r0[ti] + k // nc[ti]
            px, py = c + 0.5, r + 0.5
            Xa, Ya, Aa = X[ti], Y[ti], A[ti]
            w0 = ((Xa[:, 1] - px) * (Ya[:, 2] - py) - (Xa[:, 2] - px) * (Ya[:, 1] - py)) / Aa
            w1 = ((Xa[:, 2] - px) * (Ya[:, 0] - py) - (Xa[:, 0] - px) * (Ya[:, 2] - py)) / Aa
            w2 = 1.0 - w0 - w1
            ok = (w0 >= -EPS) & (w1 >= -EPS) & (w2 >= -EPS)
            z = P[ti, 0, 2] * w0 + P[ti, 1, 2] * w1 + P[ti, 2, 2] * w2
            np.maximum.at(top, (r * W + c)[ok], z[ok])
        cx = np.clip(((self.pos[:, 0] - lo[0]) / OVERHANG_RES).astype(np.int64), 0, W - 1)
        cy = np.clip(((self.pos[:, 1] - lo[1]) / OVERHANG_RES).astype(np.int64), 0, H - 1)
        # a sloped texel's own surface rises across its cell: allow for it (nz 0.3: +1.9 cm)
        nz = np.clip(np.abs(self.fnrm[:, 2]), 0.05, 1.0)
        over = top[cy * W + cx] > self.pos[:, 2] + OVERHANG_DZ + 1.5 * OVERHANG_RES * np.sqrt(1.0 - nz * nz) / nz
        isl = self.tri_island[self.t]
        up = np.isin(self.cls, SKIN_CLS) & (self.nrm[:, 2] > 0.3) & (isl >= 0)
        if not up.any():
            return
        ui, uinv = np.unique(isl[up], return_inverse=True)
        share = np.bincount(uinv.reshape(-1), weights=over[up]) / np.bincount(uinv.reshape(-1))
        shaded = ui[share >= OVERHANG_SHARE]
        self.sky = ~np.isin(isl, shaded)
        self.log("paint: overhung tops: %d islands (%d up-facing texels) get no up-lift"
                 % (len(shaded), int((up & ~self.sky).sum())))

    def full(self, compact, fill_value=0.0):
        """Compact per-covered-texel values -> (S, S[, ...]) image through the fill mapping."""
        out = compact[np.clip(self.src, 0, None)]
        if (self.src < 0).any():
            out[self.src < 0] = fill_value
        return out

    # -------------------------------------------------------------------------------------------
    def _levels_measure(self):
        """Median baked luma per material on near-vertical covered texels (for the report), and
        which texels hold their material's own flat colour. The level scales themselves are
        measured in base(), on the shaded sheet."""
        col = self.colour.reshape(-1, 3)[self.cpix]
        L = luma(col)
        vert = np.abs(self.nrm[:, 2]) < 0.35
        self.mat_L = {}
        tm = self.tri_mat[self.t]
        for mi, name in enumerate(self.mat_names):
            sel = (tm == mi)
            if sel.sum() < 8:
                continue
            sv = sel & vert
            self.mat_L[name] = float(np.median(L[sv] if sv.sum() >= 8 else L[sel]))
        # recolour only what carries the material's own flat colour: the twins project badges and
        # emblems (the tailgate's CR-V and H, chrome on the twin) onto the low mesh's Body faces, and
        # a class-only recolour painted them over (2026-10-12), as compose's paint_mask never did
        base = {CLS_PAINT: self.paint_srgb}
        sel = (self.cls == CLS_PLASTIC) & vert
        if sel.sum() >= 8:
            base[CLS_PLASTIC] = np.median(col[sel], 0)
        self.is_base = np.ones(len(self.cls), dtype=bool)
        for k, rgb in base.items():
            m = self.cls == k
            self.is_base[m] = np.sqrt(((col[m] - np.asarray(rgb, np.float32)) ** 2).sum(1)) < BASE_TOL
        # ... and the kotris paint at a lower level (PAINT_DIM): the hood lip's sliver baked (183, 179, 170), 22 levels
        # off, so it shipped unrecoloured and Dilate spread it round the chart (polish round 1, EXT-1)
        m = (self.cls == CLS_PAINT) & ~self.is_base
        dim = self._paint_dim(col[m])
        self.is_base[np.nonzero(m)[0][dim > 0]] = True
        self.paint_dim = np.ones(len(self.cls), dtype=np.float32)
        self.paint_dim[np.nonzero(m)[0][dim > 0]] = dim[dim > 0]
        self.is_base[np.isin(self.tri_ovr[self.t], self._paint_ovr())] = True      # "paint" OVERRIDES

    @staticmethod
    def _paint_ovr():
        return [k for k, o in enumerate(OVERRIDES) if isinstance(o[4], str) and o[4] == "paint"]

    def _paint_dim(self, col):
        """Per colour (N, 3): its level against the kotris paint when it is that paint dimmed (same chromaticity
        within PAINT_DIM[0], level PAINT_DIM[1]..1.0), else 0."""
        col = np.asarray(col, dtype=np.float32)
        p = self.paint_srgb
        n = np.linalg.norm(col, axis=-1)
        cn = col / np.maximum(n, 1e-6)[..., None]
        chroma = np.linalg.norm(cn - p / np.linalg.norm(p), axis=-1)
        r = n / float(np.linalg.norm(p))
        ok = (chroma < PAINT_DIM[0]) & (r >= PAINT_DIM[1]) & (r <= 1.02)
        return np.where(ok, r, 0.0)

    # -------------------------------------------------------------------------------------------
    # seam / crease / bezel sources
    def _edges(self):
        """Welded edges, sorted by key: (triangle, corner a, corner b) per triangle side, and per
        distinct edge its first index and its count (1 open, 2 shared). Built once."""
        if hasattr(self, "_edge_table"):
            return self._edge_table
        T = len(self.tri_wid)
        w = self.tri_wid
        a_idx = np.array([0, 1, 2])
        b_idx = np.array([1, 2, 0])
        lo = np.minimum(w[:, a_idx], w[:, b_idx]).ravel()
        hi = np.maximum(w[:, a_idx], w[:, b_idx]).ravel()
        tri = np.repeat(np.arange(T), 3)
        ca = np.tile(a_idx, T)
        cb = np.tile(b_idx, T)
        good = lo != hi
        key = lo * (int(w.max()) + 1) + hi
        key, tri, ca, cb = key[good], tri[good], ca[good], cb[good]
        order = np.argsort(key, kind="stable")
        key, tri, ca, cb = key[order], tri[order], ca[order], cb[order]
        _u, first, count = np.unique(key, return_index=True, return_counts=True)
        self._edge_table = (tri, ca, cb, first, count)
        return self._edge_table

    def _lines(self):
        """Line sources (segments in metres): open edges of exterior faces (and skin edges closed by
        solidify rims), material boundaries, lamp outlines, glass shell borders."""
        cls, gen, P = self.tri_cls, self.tri_gen, self.tri_pos
        tri, ca, cb, first, count = self._edges()
        A_all = P[tri, ca]
        B_all = P[tri, cb]
        # gen 7 details (handles, mirrors, fuel flap, wipers, rails) carry their seams and recesses as
        # geometry (build_details: the flap's 7 mm seam ring, the handle recess); bands drawn from
        # their edges doubled them into rings (2026-10-12): they receive lines, never cast them
        src_ok = np.isin(cls, SOURCE_CLS) & ~np.isin(gen, (1, 2, 3, 7))
        # --- open edges of exterior faces
        one = first[count == 1]
        t1 = tri[one]
        keep = src_ok[t1]
        # gen-5 lips: only their bottom edge (the triangle lies above it)
        opp = 3 - ca[one] - cb[one]
        mid_z = (A_all[one, 2] + B_all[one, 2]) / 2.0
        lip = (gen[t1] == 5) & np.isin(cls[t1], SKIN_CLS)
        keep &= ~lip | (P[t1, opp, 2] > mid_z + 1e-4)
        W = self.tri_wid
        open_A, open_B, open_t = [A_all[one][keep]], [B_all[one][keep]], [t1[keep]]
        open_wa, open_wb = [W[tri[one], ca[one]][keep]], [W[tri[one], cb[one]][keep]]
        # --- edges shared by a gen-0/5 skin face and a solidify / closure face (the tailgate outline)
        two = first[count == 2]
        ta, tb = tri[two], tri[two + 1]
        skin_a = np.isin(gen[ta], (0, 5)) & np.isin(cls[ta], SKIN_CLS)
        skin_b = np.isin(gen[tb], (0, 5)) & np.isin(cls[tb], SKIN_CLS)
        rim_a, rim_b = np.isin(gen[ta], (1, 2, 3)), np.isin(gen[tb], (1, 2, 3))
        s = (skin_a & rim_b) | (skin_b & rim_a)
        own = np.where(skin_a, ta, tb)
        open_A.append(A_all[two][s]); open_B.append(B_all[two][s]); open_t.append(own[s])
        open_wa.append(W[tri[two], ca[two]][s]); open_wb.append(W[tri[two], cb[two]][s])
        # --- welded paint / plastic boundaries, always a gap: the door mouldings (Body_plastique on the
        # Body skin) are separate shells for most of their outline, but kotris welded the rest into the
        # skin (door_fr 0.58 m along the top edge, door_rl 0.38 m along the bottom, door_rr 0.04 m), so
        # the open-edge seam outlined them in pieces and left the twin's creases to draw the rest
        # (2026-10-13). No other object welds paint to plastic
        pb = src_ok[ta] & src_ok[tb] & np.isin(cls[ta], SKIN_CLS) & np.isin(cls[tb], SKIN_CLS) & (cls[ta] != cls[tb])
        open_A.append(A_all[two][pb]); open_B.append(B_all[two][pb]); open_t.append(np.where(cls[ta] == CLS_PAINT, ta, tb)[pb])
        open_wa.append(W[tri[two], ca[two]][pb]); open_wb.append(W[tri[two], cb[two]][pb])
        self.open_force = np.concatenate([np.zeros(sum(len(a) for a in open_A[:-1]), dtype=bool), np.ones(int(pb.sum()), dtype=bool)])
        self.open_A, self.open_B, self.open_t = np.concatenate(open_A), np.concatenate(open_B), np.concatenate(open_t)
        self.open_wa, self.open_wb = np.concatenate(open_wa), np.concatenate(open_wb)
        # --- material boundaries paint / plastic vs lamp / glass / chrome / trim (one-sided, ungated)
        other = (CLS_LAMP, CLS_GLASS, CLS_CHROME, CLS_TRIM)
        ma = np.isin(cls[ta], SKIN_CLS) & np.isin(cls[tb], other)
        mb = np.isin(cls[tb], SKIN_CLS) & np.isin(cls[ta], other)
        m = ma | mb
        self.mat_A, self.mat_B = A_all[two][m], B_all[two][m]
        self.mat_t = np.where(ma, ta, tb)[m]
        # --- lamp outlines (bezel on the lamp side): open lamp edges + lamp vs anything else
        lo1 = one[cls[t1] == CLS_LAMP]
        la = (cls[ta] == CLS_LAMP) & (cls[tb] != CLS_LAMP)
        lb = (cls[tb] == CLS_LAMP) & (cls[ta] != CLS_LAMP)
        self.lamp_A = np.concatenate([A_all[lo1], A_all[two][la | lb]])
        self.lamp_B = np.concatenate([B_all[lo1], B_all[two][la | lb]])
        self.lamp_t = np.concatenate([tri[lo1], np.where(la, ta, tb)[la | lb]])
        inner = self._lamp_inner(self.lamp_A, self.lamp_B, self.lamp_t)
        self.log("paint: lamp outlines %.1f m, %.1f m of them inside a lens (another lamp face just beyond) dropped"
                 % (np.linalg.norm(self.lamp_B - self.lamp_A, axis=1).sum(),
                    np.linalg.norm(self.lamp_B - self.lamp_A, axis=1)[inner].sum()))
        self.lamp_A, self.lamp_B, self.lamp_t = self.lamp_A[~inner], self.lamp_B[~inner], self.lamp_t[~inner]
        # --- glass edges (every border of a glass shell; _glass keeps the pane outlines among them)
        g_one = one[(cls[t1] == CLS_GLASS)]
        ga = (cls[ta] == CLS_GLASS) & (cls[tb] != CLS_GLASS)
        gb = (cls[tb] == CLS_GLASS) & (cls[ta] != CLS_GLASS)
        self.glass_A = np.concatenate([A_all[g_one], A_all[two][ga | gb]])
        self.glass_B = np.concatenate([B_all[g_one], B_all[two][ga | gb]])
        self.glass_t = np.concatenate([tri[g_one], np.where(ga, ta, tb)[ga | gb]])
        seg_len = np.linalg.norm(self.open_B - self.open_A, axis=1)
        self.log("paint: seam sources open %.1f m (welded paint / plastic %.2f m), material %.1f m, lamp outlines %.1f m; "
                 "crease samples %d"
                 % (seg_len.sum(), seg_len[self.open_force].sum(), np.linalg.norm(self.mat_B - self.mat_A, axis=1).sum(),
                    np.linalg.norm(self.lamp_B - self.lamp_A, axis=1).sum(), len(self.crease.get("crease_pos", ()))))
        self._gate()

    def _lamp_inner(self, A, B, t):
        """Lamp outline segments that lie inside a lens (LAMP_INNER): at a quarter, half and three
        quarters of each, a point stepped out of its own face (in the face's plane) meets another lamp
        face along the face normal; two of the three decide."""
        lamp_tris = np.nonzero(self.tri_cls == CLS_LAMP)[0]
        if not len(A) or not len(lamp_tris):
            return np.zeros(len(A), dtype=bool)
        n = self.tri_fnrm[t]
        d = B - A
        out = np.cross(_unit(d), n)
        cen = self.tri_pos[t].mean(1)
        out *= np.where(((cen - (A + B) / 2.0) * out).sum(1) > 0.0, -1.0, 1.0)[:, None]   # away from its own face
        V = self.tri_pos[lamp_tris]
        votes = np.zeros(len(A), dtype=np.int64)
        for f in (0.25, 0.5, 0.75):
            q = A + d * f + out * LAMP_INNER[0]
            votes += _ray_hits(q, n, V, LAMP_INNER[1])
        return votes >= 2

    def _chains(self):
        """Chain id per open segment: segments joined at welded vertices where exactly two open
        segments meet and turn by less than CHAIN_TURN (junctions and corners end a chain, so a
        lamp's outline is four runs, each with its own partner)."""
        wa, wb = self.open_wa, self.open_wb
        A, B = self.open_A, self.open_B
        nseg = len(wa)
        ends = np.concatenate([wa, wb])
        segi = np.tile(np.arange(nseg), 2)
        order = np.argsort(ends, kind="stable")
        ends, segi = ends[order], segi[order]
        _u, first, cnt = np.unique(ends, return_index=True, return_counts=True)
        f = first[cnt == 2]
        s1, s2, v = segi[f], segi[f + 1], ends[f]
        # each segment's direction pointing away from the shared vertex: straight on is a dot of -1
        u1 = np.where((wa[s1] == v)[:, None], B[s1] - A[s1], A[s1] - B[s1])
        u2 = np.where((wa[s2] == v)[:, None], B[s2] - A[s2], A[s2] - B[s2])
        link = (_unit(u1) * _unit(u2)).sum(1) < -np.cos(np.radians(CHAIN_TURN))
        _n, chain = connected_components(coo_matrix((np.ones(int(link.sum())), (s1[link], s2[link])), shape=(nseg, nseg)),
                                         directed=False)
        return chain

    def _gate(self):
        """Per open-seam sample: 0 on a flush join (highlight only, as KI5's flush joins), 1 on a gap
        (dark band). History (2026-10-12):
        - the plan gated on the 1.2 cm shell_gap AO, but paint texels within 3 mm of an open edge read
          a median gap AO of 0.97 (only 6 % under 0.6): a flat panel beside a slit sees nothing above
          it, so that gate called 91 % of the shut lines flush;
        - a 1-2 mm partner-distance ramp then left 18-42 % of the door, hood and gate joints flush and
          disagreed left against right on 12-17 % of the seams: the partner distance has no gap to
          threshold in (exact point-to-segment, same object: 0-0.5 mm 8.9 m, 0.5-1 mm 11.5 m, 1-2 mm
          15.8 m, 2-4 mm 22.8 m of seam), and sample-to-sample distances smeared it by half a step.
        So, per sample:
        - another object's open edge within JOINT_R (doors, hood, gate against the body or each
          other): a shut line, always a gap;
        - else its nearest partner, another open edge of the same object (not touching mine at a
          welded vertex), roughly parallel, facing within FLUSH_FACING, at exact point-to-segment
          distance under FLUSH_D: across a material boundary (paint / plastic against trim,
          chrome, lamp) a gap, as the welded boundary is drawn; otherwise kotris's unwelded but
          continuous pieces, flush;
        - a welded paint / plastic boundary (open_force, the door mouldings): always a gap.
        Flush is decided per chain (_chains: more than half its length flush), then made to agree
        across each coincident pair and with the mirror image (a gap on either side wins)."""
        pts, seg = _samples(self.open_A, self.open_B, SAMPLE_STEP)
        self.open_pts, self.open_seg = pts, seg
        A, B = self.open_A, self.open_B
        L = np.linalg.norm(B - A, axis=1)
        w = L[seg] / np.maximum(np.bincount(seg, minlength=len(L))[seg], 1)
        dirs = (B - A) / np.maximum(L, 1e-12)[:, None]
        t = self.open_t[seg]
        n = self.tri_fnrm[t]
        obj = self.tri_obj[t]
        joint = np.zeros(len(pts), dtype=bool)
        for oi in np.unique(obj):
            mine = np.nonzero(obj == oi)[0]
            others = np.nonzero(obj != oi)[0]
            if not len(others):
                continue
            dj, kj = cKDTree(pts[others]).query(pts[mine], k=8, distance_upper_bound=JOINT_R, workers=WORKERS)
            vj = np.isfinite(dj)
            kc = others[np.where(vj, kj, 0)]
            joint[mine] = (vj & ((n[kc] * n[mine][:, None, :]).sum(-1) > JOINT_FACING)).any(1)
        wa, wb = self.open_wa, self.open_wb
        tree = cKDTree(pts)
        d, nb = tree.query(pts, k=24, distance_upper_bound=FLUSH_D + SAMPLE_STEP, workers=WORKERS)
        valid = np.isfinite(d)
        nbc = np.where(valid, nb, 0)
        s2 = seg[nbc]
        touch = ((wa[s2] == wa[seg][:, None]) | (wa[s2] == wb[seg][:, None]) |
                 (wb[s2] == wa[seg][:, None]) | (wb[s2] == wb[seg][:, None]))
        ok = (valid & (s2 != seg[:, None]) & ~touch & ((n[nbc] * n[:, None, :]).sum(-1) > FLUSH_FACING)
              & (np.abs((dirs[s2] * dirs[seg][:, None, :]).sum(-1)) > FLUSH_PARALLEL))
        ii, kk = np.nonzero(ok)                                  # exact distance to the candidate's segment
        a = A[s2[ii, kk]]
        ab = B[s2[ii, kk]] - a
        u = np.clip(((pts[ii] - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-18), 0.0, 1.0)
        de = np.full(ok.shape, np.inf)
        de[ii, kk] = np.linalg.norm(pts[ii] - (a + ab * u[:, None]), axis=-1)
        j = de.argmin(1)
        r = np.arange(len(pts))
        dmin = de[r, j]
        partner = nbc[r, j]
        has = np.isfinite(dmin) & (dmin < FLUSH_D)
        pt = self.open_t[seg[partner]]
        c1, c2 = self.tri_cls[t], self.tri_cls[pt]
        bnd = (CLS_LAMP, CLS_GLASS, CLS_CHROME, CLS_TRIM)
        mat = has & ~joint & ((np.isin(c1, SKIN_CLS) & np.isin(c2, bnd)) | (np.isin(c2, SKIN_CLS) & np.isin(c1, bnd)))
        flush = has & ~joint & ~mat
        chain = self._chains()[seg]
        share = np.bincount(chain, weights=w * flush) / np.maximum(np.bincount(chain, weights=w), 1e-12)
        gate = np.where(share[chain] > 0.5, 0.0, 1.0)
        gate[joint | mat | self.open_force[seg]] = 1.0
        gate[has] = np.maximum(gate[has], gate[partner[has]])
        gate = np.maximum(gate, self._mirror(pts, gate, obj))
        self.open_gate = gate
        self.log("paint: seam gate: %.1f m drawn as gaps, %.1f m flush joins (highlight only); joints between objects "
                 "%.1f m, coincident (< %.1f mm) across a material boundary %.1f m, other coincident pieces %.1f m"
                 % (w[gate > 0.5].sum(), w[gate <= 0.5].sum(), w[joint].sum(), FLUSH_D * 1000, w[mat].sum(), w[flush].sum()))

    def _mirror(self, pts, val, obj):
        """val of the nearest sample to (-x, y, z) on the mirror object (door_fl <-> door_fr, ...;
        the rest mirror onto themselves) within MIRROR_TOL, 0 where none: the car is symmetric, so
        a verdict on one side holds on the other."""
        out = np.zeros(len(pts))
        names = self.obj_names
        for oi in np.unique(obj):
            mname = _mirror_name(names[oi])
            if mname not in names:
                continue
            src = np.nonzero(obj == names.index(mname))[0]
            dst = np.nonzero(obj == oi)[0]
            if not len(src):
                continue
            q = pts[dst] * np.array([-1.0, 1.0, 1.0])
            d, k = cKDTree(pts[src]).query(q, distance_upper_bound=MIRROR_TOL, workers=WORKERS)
            hit = np.isfinite(d)
            out[dst[hit]] = val[src[k[hit]]]
        return out

    def _crease_select(self):
        """Per crease sample: (strength 0..1, sign +1 convex / -1 concave), decided per chain (see
        CREASE_NEAR): a chain is drawn whole at the strength of its median fold and its majority
        convexity, or not at all. Dumps without chain ids keep the per-sample strength."""
        cr = self.crease
        cp = cr["crease_pos"].astype(np.float64)
        ang = cr["crease_ang"].astype(np.float64) if "crease_ang" in cr else np.full(len(cp), CREASE_ANG[1])
        cvx = cr["crease_cvx"].astype(np.int64)
        if "crease_chain" not in cr:
            return smoothstep(CREASE_ANG[0], CREASE_ANG[1], ang), np.sign(cvx)
        cn = cr["crease_n"].astype(np.float64)
        co = cr["crease_obj"].astype(np.int64)
        uc, inv = np.unique(cr["crease_chain"].astype(np.int64), return_inverse=True)
        inv = inv.reshape(-1)
        nch = len(uc)
        cnt = np.bincount(inv, minlength=nch).astype(np.float64)
        # along a drawn seam: open edges drawn as gaps and material boundaries
        R = SEAM_W + HI_W + CREASE_W
        drawn = [self.open_pts[self.open_gate > 0.5]]
        if len(self.mat_A):
            drawn.append(_samples(self.mat_A, self.mat_B, SAMPLE_STEP)[0])
        drawn = np.concatenate(drawn)
        near = cKDTree(drawn).query(cp, distance_upper_bound=R, workers=WORKERS)[0] < R if len(drawn) else np.zeros(len(cp), bool)
        # landed: a painted texel of the same object within CREASE_W, in the sample's plane and facing its way
        recv = np.nonzero(np.isin(self.cls, SKIN_CLS))[0]
        d, k = cKDTree(self.pos[recv]).query(cp, k=8, distance_upper_bound=CREASE_W, workers=WORKERS)
        ok = np.isfinite(d)
        kc = recv[np.where(ok, k, 0)]
        ok &= self.obj[kc] == co[:, None]
        ok &= np.abs(((cp[:, None, :] - self.pos[kc]) * self.fnrm[kc]).sum(-1)) < PLANE_TOL
        ok &= (cn[:, None, :] * self.fnrm[kc]).sum(-1) > FACING_MIN
        landed = ok.any(1)
        near_c = np.bincount(inv, weights=near, minlength=nch) / cnt
        land_c = np.bincount(inv, weights=landed, minlength=nch) / cnt
        keep = (near_c <= CREASE_NEAR) & (land_c >= CREASE_LANDED)
        # mirror pairs share the verdict: the chain most of a chain's mirrored samples fall on
        names = self.obj_names
        mir = np.full(len(cp), -1, dtype=np.int64)
        for oi in np.unique(co):
            mname = _mirror_name(names[oi])
            if mname not in names:
                continue
            src = np.nonzero(co == names.index(mname))[0]
            dst = np.nonzero(co == oi)[0]
            if not len(src):
                continue
            dm, km = cKDTree(cp[src]).query(cp[dst] * np.array([-1.0, 1.0, 1.0]), distance_upper_bound=CREASE_MIRROR_TOL,
                                            workers=WORKERS)
            hit = np.isfinite(dm)
            mir[dst[hit]] = inv[src[km[hit]]]
        has = mir >= 0
        pair = coo_matrix((np.ones(int(has.sum())), (inv[has], mir[has])), shape=(nch, nch)).tocsr()
        partner = np.asarray(pair.argmax(1)).reshape(-1)
        share = np.asarray(pair.max(1).todense()).reshape(-1) / cnt
        paired = share >= 0.5
        keep[paired] &= keep[partner[paired]]
        med = np.asarray(ndimage.median(ang, inv, index=np.arange(nch)), dtype=np.float64)
        strength = np.where(keep, smoothstep(CREASE_ANG[0], CREASE_ANG[1], med), 0.0)
        sign = np.where(np.bincount(inv, weights=cvx > 0, minlength=nch) >= 0.5 * cnt, 1, -1)
        L = cr["crease_chain_len"].astype(np.float64) if "crease_chain_len" in cr else cnt * 0.003
        first = np.unique(inv, return_index=True)[1]
        Lc = L[first]
        self.log("paint: creases %d chains %.1f m: drawn %d (%.1f m); dropped along drawn seams %d (%.1f m), in pieces on the "
                 "low mesh %d (%.1f m), with their mirror image %d"
                 % (nch, Lc.sum(), int(keep.sum()), Lc[keep].sum(), int((near_c > CREASE_NEAR).sum()),
                    Lc[near_c > CREASE_NEAR].sum(), int(((near_c <= CREASE_NEAR) & (land_c < CREASE_LANDED)).sum()),
                    Lc[(near_c <= CREASE_NEAR) & (land_c < CREASE_LANDED)].sum(),
                    int(((near_c <= CREASE_NEAR) & (land_c >= CREASE_LANDED) & ~keep).sum())))
        return strength[inv], sign[inv]

    def _nearest(self, src_pts, src_n, recv, max_r, src_key=None, recv_key=None):
        """For the compact texels `recv` (indices): distance to the nearest source sample within
        max_r that lies within PLANE_TOL of the texel's tangent plane and faces its way (and, with
        keys, carries the texel's key: same object, same pane); returns (distance (inf when none),
        sample index (-1))."""
        dist = np.full(len(recv), np.inf)
        which = np.full(len(recv), -1, dtype=np.int64)
        if not len(src_pts) or not len(recv):
            return dist, which
        tree = cKDTree(src_pts)
        for s in range(0, len(recv), 200_000):
            r = recv[s:s + 200_000]
            p, n = self.pos[r], self.fnrm[r]
            d, nb = tree.query(p, k=KNN, distance_upper_bound=max_r, workers=WORKERS)
            valid = np.isfinite(d)
            nbc = np.where(valid, nb, 0)
            q = src_pts[nbc]
            plane = np.abs(((q - p[:, None, :]) * n[:, None, :]).sum(-1)) < PLANE_TOL
            facing = (src_n[nbc] * n[:, None, :]).sum(-1) > FACING_MIN
            ok = valid & plane & facing
            if src_key is not None:
                ok &= src_key[nbc] == recv_key[s:s + 200_000][:, None]
            dd = np.where(ok, d, np.inf)
            j = dd.argmin(1)
            dist[s:s + 200_000] = dd[np.arange(len(r)), j]
            which[s:s + 200_000] = np.where(np.isfinite(dist[s:s + 200_000]), nbc[np.arange(len(r)), j], -1)
        return dist, which

    def _fields(self):
        """Per covered texel: seam darkness, highlight, crease, bezel, drop-glass edge -> one
        multiplier and one additive term (creases), plus the gap-AO scale."""
        N = len(self.cls)
        rho = np.maximum(self.rho, 1.0)
        # one texel in metres, per texel: tx of the bake (the anti-aliasing ramps), tx * ss of the
        # shipped sheet (the width floors and the one-texel edges, which are about the sheet the game loads)
        tx = self.ss / rho
        mult = np.ones(N)
        add = np.zeros(N)
        self.f_dark = np.zeros(N)
        self.f_hi = np.zeros(N)
        self.f_crease = np.zeros(N)
        # --- seams on paint, plastics, trims, chrome
        recv = np.nonzero(np.isin(self.cls, SEAM_CLS))[0]
        w_open = np.maximum(SEAM_W, 0.5 * SEAM_FLOOR_TX * tx[recv])
        w_mat = np.maximum(2.0 * SEAM_W, SEAM_FLOOR_TX * tx[recv])
        reach = 2.0 * SEAM_W + HI_W + 2.0 * float(tx[recv].max() if len(recv) else 0.01)
        on = self.tri_fnrm[self.open_t[self.open_seg]]
        d_o, s_o = self._nearest(self.open_pts, on, recv, reach)
        gate = np.where(s_o >= 0, self.open_gate[np.clip(s_o, 0, None)], 0.0)
        mpts, mseg = _samples(self.mat_A, self.mat_B, SAMPLE_STEP) if len(self.mat_A) else (np.zeros((0, 3)), np.zeros(0, np.int64))
        mn = self.tri_fnrm[self.mat_t[mseg]] if len(mseg) else np.zeros((0, 3))
        recv_m = recv[np.isin(self.cls[recv], SKIN_CLS)]
        d_m_part, _ = self._nearest(mpts, mn, recv_m, reach)
        d_m = np.full(len(recv), np.inf)
        d_m[np.isin(self.cls[recv], SKIN_CLS)] = d_m_part
        r = rho[recv]

        def band(d, w):
            core = np.clip((w - d) * r + 0.5, 0.0, 1.0)
            prof = 1.0 - SEAM_GRAD * np.clip(d / w, 0.0, 1.0)
            hi = np.clip((w + HI_W - d) * r + 0.5, 0.0, 1.0) * (1.0 - core)
            near = np.clip((w + HI_W - d) * r + 0.5, 0.0, 1.0)
            return core * prof, core, hi, near
        dk_o, core_o, hi_o, near_o = band(d_o, w_open)
        dk_m, core_m, hi_m, near_m = band(d_m, w_mat)
        dark = np.maximum(dk_o * gate, dk_m)
        # the highlight runs beside every seam, also over the dark band's place on a flush join
        hi = np.maximum(np.maximum(hi_o, hi_m), core_o * (1.0 - gate))
        hi = hi * (1.0 - np.maximum(core_o * gate, core_m))
        mult[recv] *= (1.0 - SEAM_DARK * dark) * (1.0 + (HI_K - 1.0) * hi)
        self.f_dark[recv] = dark
        self.f_hi[recv] = hi
        # distance to the nearest DRAWN seam (gaps and material boundaries), for the crease dust (_details)
        self.seam_d = np.full(N, np.inf)
        self.seam_d[recv] = np.minimum(np.where(gate > 0.5, d_o, np.inf), d_m)
        near = np.maximum(near_o, near_m)
        self.gap_scale_c = np.where(np.isin(self.cls, SOURCE_CLS + (CLS_GLASS,)), GAP_SCALE_FAR, 1.0)
        self.gap_scale_c[recv] = GAP_SCALE_FAR + (GAP_SCALE_NEAR - GAP_SCALE_FAR) * near
        # a lens's drawn outline is its bezel: the gap AO darkened 99 % of the head lens's texels x0.76
        self.gap_scale_c[self.cls == CLS_LAMP] = GAP_SCALE_NEAR
        # --- creases (twin polylines) on paint and plastics, same object, outside the dark bands
        cp = self.crease.get("crease_pos")
        if cp is not None and len(cp):
            st, sg = self._crease_select()                        # whole chains or nothing (CREASE_NEAR)
            use = st > 0.0
            recv_c = np.nonzero(np.isin(self.cls, SKIN_CLS))[0]
            wc = np.maximum(CREASE_W, 0.5 * CREASE_FLOOR_TX * tx[recv_c])
            d_c, s_c = self._nearest(cp[use].astype(np.float64), self.crease["crease_n"][use].astype(np.float64), recv_c,
                                     CREASE_W + 2.0 * float(tx[recv_c].max()),
                                     self.crease["crease_obj"][use].astype(np.int64), self.obj[recv_c])
            core = np.clip((wc - d_c) * rho[recv_c] + 0.5, 0.0, 1.0)
            core *= 1.0 - self.f_dark[recv_c]                     # never over a drawn seam
            sc = np.clip(s_c, 0, None)
            core *= np.where(s_c >= 0, st[use][sc] if use.any() else 0.0, 0.0)   # KI5 highlights steep folds, rarely shallow ones
            cvx = np.where(s_c >= 0, sg[use][sc] if use.any() else 0, 0)
            k_cvx, a_cvx = CREASE_CVX
            m_c = np.where(cvx > 0, 1.0 + (k_cvx - 1.0) * core, np.where(cvx < 0, 1.0 + (CREASE_CCV - 1.0) * core, 1.0))
            mult[recv_c] *= m_c
            add[recv_c] += np.where(cvx > 0, a_cvx * core, 0.0)
            self.f_crease[recv_c] = core * np.sign(cvx)
        # --- lamp bezels (lamp side)
        recv_l = np.nonzero(self.cls == CLS_LAMP)[0]
        if len(recv_l) and len(self.lamp_A):
            lp, ls = _samples(self.lamp_A, self.lamp_B, SAMPLE_STEP)
            wl = np.maximum(LAMP_BEZEL_W, tx[recv_l])
            d_l, _ = self._nearest(lp, self.tri_fnrm[self.lamp_t[ls]], recv_l, LAMP_BEZEL_W + 2.0 * float(tx[recv_l].max()))
            core = np.clip((wl - d_l) * rho[recv_l] + 0.5, 0.0, 1.0)
            mult[recv_l] *= 1.0 + (LAMP_BEZEL - 1.0) * core
            self.f_dark[recv_l] = core
        # --- drop glass: a one-texel edge
        recv_g = np.nonzero((self.cls == CLS_GLASS) & self.tri_is_drop[self.t])[0]
        if len(recv_g):
            core = np.clip((tx[recv_g] - self.glass_d[recv_g]) * rho[recv_g] + 0.5, 0.0, 1.0)
            mult[recv_g] *= 1.0 + (DROP_GLASS_EDGE - 1.0) * core
            self.f_dark[recv_g] = core
        self.mult_c, self.add_c = mult, add

    # -------------------------------------------------------------------------------------------
    def _glass(self):
        """Panes and their outlines. A pane is all glass of one object facing one way (side panes
        split left / right): kotris's windshield is four concentric shells that do not weld, and
        a gradient or seal per shell drew four rectangles (2026-10-12). Per pane: the level
        top * (GLASS_BOTTOM + (1 - GLASS_BOTTOM) f^2) over the pane's height, and the distance of
        every glass texel to the pane's true outline. A shell border is not outline when glass of
        the same pane lies across it within GLASS_JOIN: another shell's border (the rings), or any
        border of the pane facing it from the other side. Kotris's rear glass is one shell cut by
        T-junction slits (two across, two down from the top: 4.9 m of coincident open edges), and
        with the shell test alone the 3 cm seal ran down both sides of every slit: 49 % of the
        pane sealed against 18 % for its outline (2026-10-12)."""
        N = len(self.cls)
        self.glass_L = np.zeros(N)
        self.glass_d = np.full(N, np.inf)
        self.glass_f = np.zeros(N)                                # height fraction in the pane (REFLECT_GLASS)
        self.glass_kind = np.full(N, -1, dtype=np.int64)          # 0 side, 1 front, 2 rear
        self.glass_h = np.zeros(N)                                # the pane's z range (m)
        cls = self.tri_cls
        g = np.nonzero(cls == CLS_GLASS)[0]
        if not len(g):
            return
        tri, ca, cb, first, count = self._edges()
        T = len(cls)
        two = first[count == 2]
        ta, tb = tri[two], tri[two + 1]
        ok = (cls[ta] == CLS_GLASS) & (cls[tb] == CLS_GLASS)
        nc, comp = connected_components(coo_matrix((np.ones(int(ok.sum())), (ta[ok], tb[ok])), shape=(T, T)), directed=False)
        P = self.tri_pos
        area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
        nsum = np.zeros((nc, 3))
        np.add.at(nsum, comp[g], self.tri_fnrm[g] * area[g, None])
        xsum = np.zeros(nc)
        np.add.at(xsum, comp[g], P[g, :, 0].mean(1) * area[g])
        kind_c = np.where(np.abs(nsum[:, 0]) >= np.abs(nsum[:, 1]), 0, np.where(nsum[:, 1] > 0, 1, 2))
        side_c = np.where(kind_c == 0, np.where(xsum > 0, 1, 0), 2)
        key = self.tri_obj * 9 + kind_c[comp] * 3 + side_c[comp]
        pane = np.full(T, -1, dtype=np.int64)
        uk, inv = np.unique(key[g], return_inverse=True)
        inv = inv.reshape(-1)
        pane[g] = inv
        kind = (uk % 9) // 3
        npane = len(uk)
        zmin = np.asarray(ndimage.minimum(P[g, :, 2].min(1), inv, index=np.arange(npane)))
        zmax = np.asarray(ndimage.maximum(P[g, :, 2].max(1), inv, index=np.arange(npane)))
        top = np.array([GLASS_TOP["side"], GLASS_TOP["front"], GLASS_TOP["rear"]])[kind]
        sel = np.nonzero(self.cls == CLS_GLASS)[0]
        p = pane[self.t[sel]]
        f = np.clip((self.pos[sel, 2] - zmin[p]) / np.maximum(zmax[p] - zmin[p], 1e-3), 0.0, 1.0)
        self.glass_L[sel] = top[p] * (GLASS_BOTTOM + (1.0 - GLASS_BOTTOM) * f * f)
        self.glass_f[sel] = f
        self.glass_kind[sel] = kind[p]
        self.glass_h[sel] = (zmax - zmin)[p]
        # true outline
        pts, seg = _samples(self.glass_A, self.glass_B, SAMPLE_STEP)
        st = self.glass_t[seg]
        # in-plane direction pointing out of each sample's own triangle
        o = np.cross(_unit(self.glass_B - self.glass_A)[seg], self.tri_fnrm[st])
        o *= np.where(((pts - P[st].mean(1)) * o).sum(1) < 0.0, -1.0, 1.0)[:, None]
        tree = cKDTree(pts)
        d, nb = tree.query(pts, k=48, distance_upper_bound=GLASS_JOIN, workers=WORKERS)
        valid = np.isfinite(d)
        nbc = np.where(valid, nb, 0)
        same = valid & (pane[st][nbc] == pane[st][:, None])
        rings = same & (comp[st][nbc] != comp[st][:, None])
        # facing borders: the other's outward direction points back at mine and it lies ahead of me
        # (a slit's two sides at 0 mm, a ring gap at 3-10 mm), not behind (a narrow pane's far side)
        facing = (same & (seg[nbc] != seg[:, None]) & ((o[nbc] * o[:, None, :]).sum(-1) < -GLASS_FACING)
                  & (((pts[nbc] - pts[:, None, :]) * o[:, None, :]).sum(-1) > -0.001))
        out = ~(rings | facing).any(1)
        tx = self.ss / np.maximum(self.rho[sel], 1.0)                # a shipped texel (see _fields)
        self.glass_d[sel], _ = self._nearest(pts[out], self.tri_fnrm[st[out]], sel, RUBBER_W + 2.0 * float(tx.max()),
                                             pane[st[out]], p)
        names = ("side", "front", "rear")
        self.log("paint: glass %d panes (%s) from %d shells; outline %.1f m of %.1f m of shell borders"
                 % (npane, ", ".join("%s %d" % (names[k], int((kind == k).sum())) for k in range(3)), len(np.unique(comp[g])),
                    out.sum() * SAMPLE_STEP, len(out) * SAMPLE_STEP))

    # -------------------------------------------------------------------------------------------
    # micro-detail (constants "micro-detail"): skin-independent fields, applied by skin() last
    def _details(self):
        """Per covered texel (compact): dt_dust, dt_scuff, dt_chip (0..1 strengths of the relative tints),
        dt_grain (a multiplier on the plastics) and dt_over_a / dt_over_rgb (absolute overlays with their
        own colour: lock cylinders, washer nozzles, the REALTIME 4WD badge). Every field is a function of
        the texel's 3D position, normal, object and material, so it holds on any layout and runs on across
        island seams; random placement is seeded (DETAIL_SEED): every build paints the same car."""
        N = len(self.cls)
        self.dt_dust = np.zeros(N, dtype=np.float32)
        self.dt_scuff = np.zeros(N, dtype=np.float32)
        self.dt_chip = np.zeros(N, dtype=np.float32)
        self.dt_grain = np.ones(N, dtype=np.float32)
        self.dt_over_a = np.zeros(N, dtype=np.float32)
        self.dt_over_rgb = np.zeros((N, 3), dtype=np.float32)
        self.gen = self.tri_gen[self.t]
        self._oid = {n: i for i, n in enumerate(self.obj_names)}
        rho = np.maximum(self.rho, 1.0)
        rng = np.random.default_rng(DETAIL_SEED)
        notes = [self._streaks(rng, rho), self._crease_dust(), self._flap_dust(rho), self._chips(rng, rho),
                 self._scuffs(rho), self._grain(), self._pockets(rho), self._locks(rho), self._nozzles(rho), self._badge(rho),
                 self._recess(), self._plate(rho), self._garnish(rho), self._ex_badge(rho)]
        self.log("paint: details: " + "; ".join(n for n in notes if n))

    def _of(self, name, classes, extra=None):
        """Compact indices of object `name`'s texels of the given classes (and `extra` mask)."""
        oi = self._oid.get(name)
        if oi is None:
            return np.zeros(0, dtype=np.int64)
        m = (self.obj == oi) & np.isin(self.cls, classes)
        if extra is not None:
            m &= extra
        return np.nonzero(m)[0]

    def _snap(self, idx, pt, weights=(1.0, 1.0, 1.0), reach=0.10):
        """The texel of `idx` nearest to pt (per-axis weights let a side source ignore the panel's
        tumblehome), or None beyond `reach`."""
        if not len(idx):
            return None
        d = np.sqrt((((self.pos[idx] - np.asarray(pt, dtype=np.float64)) * np.asarray(weights)) ** 2).sum(1))
        k = int(d.argmin())
        return int(idx[k]) if d[k] < reach else None

    def _streaks(self, rng, rho):
        """Water / dust streaks (STREAKS) into dt_dust: per source corner a few sub-streaks run straight
        down the panel (along the panel's surface, measured on the horizontal across it), each a band
        STREAK_W wide tapering to 55 %, wandering sideways, fading out over its length, broken up by a
        slow noise, and stopped by a drawn seam's dark core (water runs into the gap)."""
        brk = 0.70 + 0.30 * vnoise(self.pos, 0.025, DETAIL_SEED + 11)
        free = 1.0 - np.clip(self.f_dark, 0.0, 1.0)
        n_src, n_sub = 0, 0
        for name, pt, mirror, nsub, (l0, l1) in STREAKS:
            for side in ((1.0, -1.0) if mirror else (1.0,)):
                oname = name if side > 0 else _mirror_name(name)
                p0 = np.array(pt) * np.array([side, 1.0, 1.0])
                facing = np.array([np.sign(p0[0]), 0.0, 0.0]) if abs(p0[0]) > 0.75 else np.array([0.0, -1.0, 0.0])
                cand = self._of(oname, (CLS_PAINT,), (self.fnrm @ facing > 0.5) & (np.abs(self.fnrm[:, 2]) < 0.6))
                k = self._snap(cand, p0, np.where(np.abs(facing) > 0.5, 0.25, 1.0))
                if k is None:
                    self.log("paint: details: streak source %s %s found no paint" % (oname, tuple(np.round(p0, 3))))
                    continue
                s0 = self.pos[k]
                nh = self.fnrm[k].copy()
                nh[2] = 0.0
                nh = _unit(nh)
                h = _unit(np.cross([0.0, 0.0, 1.0], nh))
                d = self.pos[cand] - s0
                dz = -d[:, 2]
                dh = d @ h
                near = ((dz > -0.01) & (dz < l1 + 0.01) & (np.abs(dh) < STREAK_SPREAD + STREAK_W[1] + STREAK_SWAY[1] + 0.01)
                        & (np.abs(d @ nh) < 0.06) & (self.fnrm[cand] @ nh > 0.5))
                ci, dz, dh = cand[near], dz[near], dh[near]
                r = rho[ci]
                a = np.zeros(len(ci))
                for _j in range(nsub):
                    off = rng.uniform(-STREAK_SPREAD, STREAK_SPREAD)
                    L = rng.uniform(l0, l1)
                    w = rng.uniform(*STREAK_W)
                    st = rng.uniform(*STREAK_A)
                    amp = rng.uniform(*STREAK_SWAY)
                    lam = rng.uniform(*STREAK_WAVE)
                    ph = rng.uniform(0.0, 2.0 * np.pi)
                    cen = off + amp * (np.sin(2.0 * np.pi * dz / lam + ph) - np.sin(ph))
                    t = np.clip(dz / L, 0.0, 1.0)
                    half = 0.5 * w * (1.0 - 0.45 * t)
                    across = np.clip((half - np.abs(dh - cen)) * r + 0.5, 0.0, 1.0)
                    along = smoothstep(-0.004, 0.012, dz) * np.clip(1.0 - dz / L, 0.0, 1.0) ** 1.3
                    a = np.maximum(a, st * across * along)
                    n_sub += 1
                a *= brk[ci] * free[ci]
                self.dt_dust[ci] = np.maximum(self.dt_dust[ci], a)
                n_src += 1
        return "streaks %d sources / %d runs (%.2f%% of texels)" % (n_src, n_sub, 100.0 * (self.dt_dust > 0.05).sum() / self.size ** 2)

    def _crease_dust(self):
        """Dust beside the drawn seams of the lower body (DUST_CREASE): near-vertical paint and plastics
        below DUST_LOW_Z, falling off over DUST_CREASE_W outside the seam's dark band (half strength on
        the core itself), broken up by a slow noise."""
        z = self.pos[:, 2]
        near = np.clip(1.0 - (self.seam_d - SEAM_W) / DUST_CREASE_W, 0.0, 1.0)
        ok = np.isin(self.cls, SKIN_CLS) & (np.abs(self.nrm[:, 2]) < 0.5) & np.isfinite(self.seam_d)
        a = DUST_CREASE * near * smoothstep(DUST_LOW_Z[0], DUST_LOW_Z[1], z) * (0.65 + 0.35 * vnoise(self.pos, 0.03, DETAIL_SEED + 12))
        a *= 1.0 - 0.5 * np.clip(self.f_dark, 0.0, 1.0)
        a = np.where(ok, a, 0.0)
        self.dt_dust = np.maximum(self.dt_dust, a.astype(np.float32))
        return "crease dust %.2f%%" % (100.0 * (a > 0.05).sum() / self.size ** 2)

    def _flap_dust(self, rho):
        """Dust round the fuel flap (FLAP): a ring outside its outline, e-folding over FLAP_DUST_W, and a
        band inside along its lower edge, both heavier at the bottom."""
        (yc, zc), half, rad = FLAP
        idx = self._of("body", (CLS_PAINT,), (self.pos[:, 0] < -0.6) & (self.fnrm[:, 0] < -0.5)
                       & (np.abs(self.pos[:, 1] - yc) < half[0] + 0.06) & (np.abs(self.pos[:, 2] - zc) < half[1] + 0.06))
        if not len(idx):
            return "fuel flap: no texels"
        y, z = self.pos[idx, 1] - yc, self.pos[idx, 2] - zc
        sd = _rrect_sd(y, z, half, rad)
        ring = np.where(sd >= 0.0, np.exp(-sd / FLAP_DUST_W) * (sd < 4.0 * FLAP_DUST_W), 0.6 * np.clip(1.0 + sd / 0.015, 0.0, 1.0))
        bottom = 0.30 + 0.70 * smoothstep(0.02, -0.08, z)
        a = FLAP_DUST * ring * bottom * (0.70 + 0.30 * vnoise(self.pos[idx], 0.02, DETAIL_SEED + 13))
        self.dt_dust[idx] = np.maximum(self.dt_dust[idx], a)
        return "fuel flap dust %d texels" % int((a > 0.05).sum())

    def _chips(self, rng, rho):
        """Stone chips (CHIPS): elliptic specks scattered by area on the hood's leading edge (density
        e-folding behind it, CHIP_EDGE), the nose paint and the front bumper's top. On paint they are
        primer (dt_chip), on the plastic bumper lighter scuffs (dt_scuff)."""
        hood = self._of("hood", (CLS_PAINT,), (self.fnrm[:, 2] > 0.15) | (self.fnrm[:, 1] > 0.4))
        groups = {}
        if len(hood):
            x = self.pos[hood, 0]
            b = np.floor(x / 0.01).astype(np.int64)
            ub, inv = np.unique(b, return_inverse=True)
            yfront = np.asarray(ndimage.maximum(self.pos[hood, 1], inv.reshape(-1), index=np.arange(len(ub))))[inv.reshape(-1)]
            dfront = yfront - self.pos[hood, 1]
            groups["hood"] = (hood, np.where(dfront < CHIP_EDGE[1], np.exp(-dfront / CHIP_EDGE[0]), 0.0))
        nose = self._of("body", (CLS_PAINT,), (self.pos[:, 1] > 1.75) & (self.fnrm[:, 1] > 0.2))
        groups["nose"] = (nose, np.ones(len(nose)))
        bump = self._of("body", (CLS_PLASTIC,), (self.pos[:, 1] > 1.85) & ((self.fnrm[:, 2] > 0.3) | ((self.fnrm[:, 1] > 0.5) & (self.pos[:, 2] > 0.6))))
        groups["bumper"] = (bump, np.ones(len(bump)))
        cen, nrm, t1, r1, r2, amp, cobj = [], [], [], [], [], [], []
        for g, (idx, w) in groups.items():
            n = CHIPS.get(g, 0)
            w = w / rho[idx] ** 2                                # per unit area
            if not n or not len(idx) or w.sum() <= 0:
                continue
            pick = idx[rng.choice(len(idx), size=n, p=w / w.sum())]
            for k in pick:
                nn = self.fnrm[k]
                a = _unit(np.cross(nn, [0.0, 0.0, 1.0] if abs(nn[2]) < 0.9 else [1.0, 0.0, 0.0]))
                b2 = np.cross(nn, a)
                th = rng.uniform(0.0, np.pi)
                r = rng.uniform(*CHIP_R)
                asp = rng.uniform(*CHIP_ASPECT)
                cen.append(self.pos[k]); nrm.append(nn); t1.append(np.cos(th) * a + np.sin(th) * b2)
                r1.append(r * np.sqrt(asp)); r2.append(r / np.sqrt(asp)); amp.append(rng.uniform(*CHIP_A))
                cobj.append(self.obj[k])
        if not cen:
            return "chips: none"
        cen, nrm, t1 = np.array(cen), np.array(nrm), np.array(t1)
        r1, r2, amp, cobj = np.array(r1), np.array(r2), np.array(amp), np.array(cobj)
        t2 = np.cross(nrm, t1)
        recv = np.concatenate([g[0] for g in groups.values()])
        reach = float(r1.max()) + 2.0 / float(rho[recv].min())
        d, nb = cKDTree(cen).query(self.pos[recv], k=4, distance_upper_bound=reach, workers=WORKERS)
        valid = np.isfinite(d)
        nb = np.where(valid, nb, 0)
        dv = self.pos[recv][:, None, :] - cen[nb]
        e = np.sqrt(((dv * t1[nb]).sum(-1) / r1[nb]) ** 2 + ((dv * t2[nb]).sum(-1) / r2[nb]) ** 2)
        cov = np.clip((1.0 - e) * r2[nb] * rho[recv][:, None] + 0.5, 0.0, 1.0) * amp[nb]
        cov *= valid & (np.abs((dv * nrm[nb]).sum(-1)) < 0.006) & (cobj[nb] == self.obj[recv][:, None])
        a = cov.max(1) * (1.0 - np.clip(self.f_dark[recv], 0.0, 1.0))
        paint = self.cls[recv] == CLS_PAINT
        self.dt_chip[recv[paint]] = np.maximum(self.dt_chip[recv[paint]], a[paint])
        self.dt_scuff[recv[~paint]] = np.maximum(self.dt_scuff[recv[~paint]], a[~paint])
        return "chips %d (%s), %d texels" % (len(cen), ", ".join("%s %d" % (g, CHIPS.get(g, 0)) for g in groups), int((a > 0.1).sum()))

    def _scuffs(self, rho):
        """Wear where hands go into dt_scuff: the handle plates below the grip and the paint just under
        each plate (HANDLES), the gate's pull under the garnish bar (GATE_PULL), and key scratches round
        every lock (DOOR_LOCK, GATE_LOCK). Mottled by a fine noise so it reads as rubbed, not painted."""
        mot = 0.55 + 0.45 * vnoise(self.pos, 0.012, DETAIL_SEED + 14)
        y, z = self.pos[:, 1], self.pos[:, 2]
        cnt = 0
        for name, (cy, cz, glen) in HANDLES.items():
            plate = self._of(name, (CLS_TRIM, CLS_PAINT), (self.gen == 7) & (np.abs(self.pos[:, 0]) > 0.8))   # black (LX) or EX
            gy = cy + 0.012                                       # build_details GRIP_DY
            zb = cz - PLATE_HALF[1]
            sel = plate[(z[plate] > zb + 0.003) & (z[plate] < cz - 0.012) & (np.abs(y[plate] - gy) < 0.5 * glen - 0.004)]
            a = SCUFF_A * mot[sel] * smoothstep(0.5 * glen - 0.004, 0.5 * glen - 0.03, np.abs(y[sel] - gy))
            self.dt_scuff[sel] = np.maximum(self.dt_scuff[sel], a)
            paint = self._of(name, (CLS_PAINT,), (z < zb) & (z > zb - 0.022) & (np.abs(y - cy) < 0.065) & (np.abs(self.fnrm[:, 0]) > 0.5)
                             & (self.gen != 7))
            a = 0.30 * mot[paint] * np.clip((z[paint] - (zb - 0.022)) / 0.022, 0.0, 1.0) * smoothstep(0.065, 0.035, np.abs(y[paint] - cy))
            self.dt_scuff[paint] = np.maximum(self.dt_scuff[paint], a)
            cnt += len(sel) + len(paint)
        (x0, x1), lip, top = GATE_PULL
        x = self.pos[:, 0]
        gate = self._of("trunk", (CLS_PAINT,), (x > x0) & (x < x1) & (self.fnrm[:, 1] < -0.3))
        mid = 0.5 * (x0 + x1)
        across = smoothstep(0.5 * (x1 - x0), 0.5 * (x1 - x0) - 0.03, np.abs(x[gate] - mid))
        a = np.where((z[gate] > lip[0]) & (z[gate] < lip[1]), 0.40, np.where((z[gate] > top[0]) & (z[gate] <= lip[0]), 0.22, 0.0))
        a = a * across * mot[gate]
        self.dt_scuff[gate] = np.maximum(self.dt_scuff[gate], a)
        cnt += int((a > 0).sum())
        # key scratches: a mottled ring round each lock
        for name, c, r0, r1, cls in self._lock_rings():
            idx = self._of(name, cls)
            d = np.linalg.norm(self.pos[idx] - c, axis=1)
            sel = idx[(d > r0) & (d < r1)]
            dd = np.linalg.norm(self.pos[sel] - c, axis=1)
            a = 0.32 * np.clip((r1 - dd) / (r1 - r0), 0.0, 1.0) * mot[sel]
            self.dt_scuff[sel] = np.maximum(self.dt_scuff[sel], a)
            cnt += len(sel)
        return "hand wear %d texels" % cnt

    def _lock_rings(self):
        """(object, centre, inner, outer radius, classes) of the key-scratch ring round each lock."""
        out = []
        for name, s in (("door_fl", 1.0), ("door_fr", -1.0)):
            c = np.array(DOOR_LOCK[0]) * np.array([s, 1.0, 1.0])
            out.append((name, c, DOOR_LOCK[1] + 0.002, DOOR_LOCK[1] + 0.013, (CLS_TRIM, CLS_PAINT)))   # black (LX) or EX bezel
        out.append(("trunk", np.array(GATE_LOCK[0]), GATE_LOCK[2] + 0.001, GATE_LOCK[2] + 0.014, (CLS_PAINT,)))
        return out

    def _grain(self):
        """Grain on the plastics (GRAIN_CELL / GRAIN_AMP): sparse soft stipple blobs (the value noise
        shaped so only its peaks and troughs show) over a broad mottle."""
        idx = np.nonzero(self.cls == CLS_PLASTIC)[0]
        if not len(idx):
            return ""
        n1 = vnoise(self.pos[idx], GRAIN_CELL[0], DETAIL_SEED + 15)
        stip = smoothstep(0.20, 0.70, n1) - smoothstep(0.20, 0.70, -n1)
        n2 = vnoise(self.pos[idx], GRAIN_CELL[1], DETAIL_SEED + 16)
        self.dt_grain[idx] = 1.0 + GRAIN_AMP[0] * stip + GRAIN_AMP[1] * n2
        return "plastic grain on %.1f%% of texels (x%.2f..%.2f)" % (100.0 * len(idx) / self.size ** 2, self.dt_grain[idx].min(), self.dt_grain[idx].max())

    def _overlay(self, idx, a, rgb):
        """Absolute overlays: a texel takes the strongest one."""
        rgb = np.broadcast_to(np.asarray(rgb, dtype=np.float64), (len(idx), 3))
        win = a > self.dt_over_a[idx]
        self.dt_over_a[idx[win]] = a[win]
        self.dt_over_rgb[idx[win]] = rgb[win]

    def _locks(self, rho):
        """Lock cylinders (DOOR_LOCK on the front doors' lock squares, GATE_LOCK on the garnish bar): a
        chrome face (the gate's in a bright bezel), a dark vertical keyway, anti-aliased."""
        made = []
        specs = []
        for name, s in (("door_fl", 1.0), ("door_fr", -1.0)):
            c = np.array(DOOR_LOCK[0]) * np.array([s, 1.0, 1.0])
            idx = self._of(name, (CLS_TRIM, CLS_PAINT), self.gen == 7)              # black (LX) or body-colour (EX) pad
            specs.append((name, c, idx, DOOR_LOCK[1], None))
        gc = np.array(GATE_LOCK[0])
        specs.append(("trunk", gc, self._of("trunk", (CLS_PAINT,), self.fnrm[:, 1] < -0.5), GATE_LOCK[1], GATE_LOCK[2]))
        for name, c, idx, rf, rb in specs:
            k = self._snap(idx, c, (0.2, 1.0, 1.0) if name.startswith("door") else (1.0, 0.2, 1.0), reach=0.05)
            if k is None:
                self.log("paint: details: lock on %s found no texel" % name)
                continue
            n = self.fnrm[k]
            cc = c.copy()
            if name.startswith("door"):
                cc[0] = self.pos[k, 0]                            # on the lock square's plane
            else:
                cc[1] = self.pos[k, 1]
            cc = cc - n * ((cc - self.pos[k]) @ n)
            R = rb or rf
            d = self.pos[idx] - cc
            near = (np.linalg.norm(d, axis=1) < R + 0.004) & (np.abs(d @ n) < 0.004) & (self.fnrm[idx] @ n > 0.7)
            sel, d = idx[near], d[near]
            h = _unit(np.cross([0.0, 0.0, 1.0], n))
            v = np.cross(n, h)
            r = np.sqrt((d @ h) ** 2 + (d @ v) ** 2)
            rr = rho[sel]
            face = np.clip((rf - r) * rr + 0.5, 0.0, 1.0)
            slot = np.clip((0.0010 - np.abs(d @ h)) * rr + 0.5, 0.0, 1.0) * np.clip((0.50 * rf - np.abs(d @ v)) * rr + 0.5, 0.0, 1.0)
            if rb is None:                                        # door: chrome face, darker rim, keyway
                rim = np.clip((r - (rf - 0.0015)) * rr + 0.5, 0.0, 1.0)
                col = np.asarray(LOCK_RGB, float) * (1.0 - 0.45 * rim)[:, None]
                a = face
            else:                                                 # gate: bright bezel round a darker face
                bez = np.clip((rb - r) * rr + 0.5, 0.0, 1.0)
                col = np.asarray(LOCK_RGB, float) * 1.12 * (1.0 - face)[:, None] + np.asarray(LOCK_RGB, float) * 0.62 * face[:, None]
                a = bez
            col = col * (1.0 - slot)[:, None] + np.asarray(LOCK_DARK, float) * slot[:, None]
            self._overlay(sel, a, col)
            made.append("%s %d" % (name, int((a > 0.5).sum())))
        return "locks " + ", ".join(made)

    def _nozzles(self, rho):
        """Washer nozzles (NOZZLES): dark elliptic domes on the hood top with a highlight towards the
        windscreen and a soft contact shadow round them."""
        top = self._of("hood", (CLS_PAINT,), self.nrm[:, 2] > 0.4)
        if not len(top):
            return "nozzles: no hood"
        made = 0
        for xn, ahead in NOZZLES:
            col = top[np.abs(self.pos[top, 0] - xn) < 0.006]
            if not len(col):
                continue
            yc = float(self.pos[col, 1].min()) + ahead
            k = self._snap(top, (xn, yc, float(self.pos[col, 2].max())), (1.0, 1.0, 0.0), reach=0.03)
            if k is None:
                continue
            c = self.pos[k]
            d = self.pos[top] - c
            near = np.linalg.norm(d[:, :2], axis=1) < 1.6 * max(NOZZLE_R) + 0.004
            sel, d = top[near], d[near]
            rr = rho[sel]
            e = np.sqrt((d[:, 0] / NOZZLE_R[0]) ** 2 + (d[:, 1] / NOZZLE_R[1]) ** 2)
            core = np.clip((1.0 - e) * NOZZLE_R[0] * rr + 0.5, 0.0, 1.0)
            # highlight: the dome's top, a 4 mm spot just behind its centre (lit from above, seen from the front)
            hs = np.hypot(d[:, 0], d[:, 1] + 0.25 * NOZZLE_R[1])
            hl = np.clip((0.004 - hs) * rr + 0.5, 0.0, 1.0) * core
            colr = np.asarray(NOZZLE_RGB, float)[None, :] * (1.0 + 2.2 * hl)[:, None]
            shadow = 0.30 * np.clip((1.5 - e) / 0.5, 0.0, 1.0) * (1.0 - core)
            a = np.maximum(core, shadow)
            self._overlay(sel, a, colr)
            made += 1
        return "washer nozzles %d" % made

    def _badge(self, rho):
        """REALTIME 4WD (BADGE_*) on the rear glass: the text rendered once, box-prefiltered to half a
        destination texel (the colour bake's lesson: a point-sampled decal comes out dashed) and mapped
        by x across and, up the glass, by the distance along its surface from the pane's lower outline
        (fitted as a line through the outline band's texels: glass_d itself stops at the seal's reach)."""
        idx = self._of("trunk_top", (CLS_GLASS,), (self.fnrm[:, 1] < -0.4) & (self.pos[:, 2] < 1.32))
        if not len(idx):
            return "badge: no rear glass"
        W, H = BADGE_SIZE
        xc, vc = BADGE_AT
        x, z = self.pos[idx, 0], self.pos[idx, 2]
        rise = np.sqrt(np.clip(1.0 - self.fnrm[idx, 2] ** 2, 0.05, 1.0))   # z gained per metre up the glass
        band = (np.abs(x - xc) < W) & (self.glass_d[idx] < 0.008)
        band &= z < z[band].min() + 0.05 if band.any() else band
        if band.sum() < 8:
            return "badge: no lower outline"
        fit = np.polyfit(x[band], z[band] - self.glass_d[idx][band] * rise[band], 1)
        u = (x - (xc - 0.5 * W)) / W
        v = ((z - np.polyval(fit, x)) / rise - (vc - 0.5 * H)) / H
        inside = (u > -0.05) & (u < 1.05) & (v > -0.3) & (v < 1.3)
        idx, u, v = idx[inside], u[inside], v[inside]
        if not len(idx):
            return "badge: off the glass"
        m = _text_mask(BADGE_TEXT)
        mh, mw = m.shape
        r = float(np.median(rho[idx]))
        fu, fv = 0.5 * mw / W / r, 0.5 * mh / H / r
        m = ndimage.uniform_filter(m, size=(max(1, int(round(fv))), max(1, int(round(fu)))), mode="constant")
        col = np.clip(u * mw - 0.5, 0, mw - 1)          # the mask's 1 px border is empty: clipping reads 0
        row = np.clip((1.0 - v) * mh - 0.5, 0, mh - 1)
        a = ndimage.map_coordinates(m, [row, col], order=1, mode="constant")
        self._overlay(idx, 0.95 * np.clip(a, 0.0, 1.0), BADGE_RGB)
        return "badge %r %d texels" % (BADGE_TEXT, int((a > 0.3).sum()))

    def _pockets(self, rho):
        """The finger pocket behind each body-colour grip (HANDLE_POCKET, the EX handles of build_details): a
        darker rounded slot on the bezel plate round the grip, folded into the line multiplier so it rides every
        skin's level. The grip, 1.1 cm proud of the plate, keeps the paint: plate texels are told from grip
        texels by their distance from the plate's plane, fitted on the plate's rim. Black (LX) handles have no
        paint texels and are left alone."""
        made = []
        for name, (cy, cz, glen) in HANDLES.items():
            idx = self._of(name, (CLS_PAINT,), (self.gen == 7) & (np.abs(self.pos[:, 0]) > 0.8) & (np.abs(self.fnrm[:, 0]) > 0.7)
                           & (np.abs(self.pos[:, 1] - cy) < 0.16) & (np.abs(self.pos[:, 2] - cz) < 0.08))
            if len(idx) < 16:
                continue
            y, z, ax = self.pos[idx, 1], self.pos[idx, 2], np.abs(self.pos[idx, 0])
            gy = cy + 0.012                                       # build_details GRIP_DY
            rim = (np.abs(y - gy) > 0.5 * glen + 0.012) | (np.abs(z - cz) > 0.025)
            if rim.sum() < 8:
                continue
            A = np.c_[y, z, np.ones(len(idx))]
            coef = np.linalg.lstsq(A[rim], ax[rim], rcond=None)[0]
            plate = ax < A @ coef + 0.006
            hl = 0.5 * glen + HANDLE_POCKET[0]
            sd = _rrect_sd(y - gy, z - cz, (hl, HANDLE_POCKET[1]), HANDLE_POCKET[2])
            cov = np.clip(-sd * rho[idx] + 0.5, 0.0, 1.0) * plate
            self.mult_c[idx] *= 1.0 - POCKET_DARK * cov
            made.append("%s %d" % (name, int((cov > 0.5).sum())))
        return ("handle pockets " + ", ".join(made)) if made else "handle pockets: no body-colour bezels"

    def _decal(self, idx, u, v, rgba, size_m):
        """Overlay an RGBA picture (float: sRGB 0..255, alpha 0..1; rows from the top) on texels idx at picture
        coordinates u, v (0..1, v up), box-prefiltered to half a destination texel first (a point-sampled decal
        comes out dashed: the colour bake's lesson). size_m: the picture's (width, height) in metres. Returns
        (the texels it landed on, their alpha)."""
        ins = (u > -0.02) & (u < 1.02) & (v > -0.02) & (v < 1.02)
        idx, u, v = idx[ins], u[ins], v[ins]
        if not len(idx):
            return idx, np.zeros(0)
        h, w = rgba.shape[:2]
        r = float(np.median(np.maximum(self.rho[idx], 1.0)))
        fu, fv = 0.5 * w / size_m[0] / r, 0.5 * h / size_m[1] / r
        pre = np.empty_like(rgba)
        a = rgba[..., 3]
        for ch in range(3):                                       # premultiplied, so a transparent fringe adds no colour
            pre[..., ch] = ndimage.uniform_filter(rgba[..., ch] * a, size=(max(1, int(round(fv))), max(1, int(round(fu)))), mode="constant")
        pre[..., 3] = ndimage.uniform_filter(a, size=(max(1, int(round(fv))), max(1, int(round(fu)))), mode="constant")
        col = np.clip(u * w - 0.5, 0, w - 1)
        row = np.clip((1.0 - v) * h - 0.5, 0, h - 1)
        out = np.stack([ndimage.map_coordinates(pre[..., ch], [row, col], order=1, mode="nearest") for ch in range(4)], 1)
        al = np.clip(out[:, 3], 0.0, 1.0)
        rgb = out[:, :3] / np.maximum(al, 1e-4)[:, None]
        self._overlay(idx, al, np.clip(rgb, 0.0, 255.0))
        return idx, al

    def _plate(self, rho):
        """The rear licence plate (PLATE, plate_paint) on the gate's recess floor: trunk texels facing rearward
        that are the rearmost surface at their (x, z) (PLATE_DEPTH), mapped by x across and z up."""
        if not PLATE:
            return "plate: off"
        import plate_paint
        rgba, (W, H) = plate_paint.plate_rgba()
        xc, zc = PLATE_AT
        x, z = self.pos[:, 0], self.pos[:, 2]
        idx = self._of("trunk", SEAM_CLS, (self.fnrm[:, 1] < -0.5) & (np.abs(x - xc) < 0.5 * W) & (np.abs(z - zc) < 0.5 * H))
        if not len(idx):
            return "plate: no recess texels"
        cell = (np.floor((x[idx] - xc) / 0.01).astype(np.int64) + 1000) * 4096 + np.floor((z[idx] - zc) / 0.01).astype(np.int64) + 1000
        uc, inv = np.unique(cell, return_inverse=True)
        ymin = np.full(len(uc), np.inf)
        np.minimum.at(ymin, inv.reshape(-1), self.pos[idx, 1])
        idx = idx[self.pos[idx, 1] < ymin[inv.reshape(-1)] + PLATE_DEPTH]
        u = (x[idx] - (xc - 0.5 * W)) / W
        v = (z[idx] - (zc - 0.5 * H)) / H
        idx, a = self._decal(idx, u, v, rgba, (W, H))
        return "plate %s %d texels (%.1f texels/cm)" % (plate_paint.SERIAL, int((a > 0.5).sum()),
                                                         float(np.median(self.rho[idx])) / 100.0 if len(idx) else 0.0)

    def _recess(self):
        """With the plate (PLATE): the recess floor's baked lettering (RECESS: kotris's CR-V, projected from the
        twin's chrome) becomes paint, and its 1.2 cm gap-AO outline goes (RECESS_GAP). base() gives the cleared
        texels the floor's own shaded paint."""
        N = len(self.cls)
        self.recess_clear = np.zeros(N, dtype=bool)
        self.recess_floor = np.zeros(N, dtype=bool)
        if not PLATE:
            return ""
        (x0, x1), (z0, z1) = RECESS
        x, z = self.pos[:, 0], self.pos[:, 2]
        box = self._of("trunk", (CLS_PAINT,), (self.fnrm[:, 1] < -0.5) & (x > x0) & (x < x1) & (z > z0) & (z < z1))
        if not len(box):
            return "recess: no floor"
        clr = box[~self.is_base[box]]
        self.recess_floor[box[self.is_base[box]]] = True
        self.recess_clear[clr] = True
        self.is_base[clr] = True
        if len(clr):
            near = cKDTree(self.pos[clr]).query(self.pos[box], distance_upper_bound=RECESS_GAP)[0] < RECESS_GAP
            self.gap_scale_c[box[near]] = 0.0
        return "recess: %d lettering texels cleared" % len(clr)

    def _garnish(self, rho):
        """The US cars' CR-V lettering on the garnish bar over the plate (GARNISH_*), chrome with a dark rim like
        the EX badge, with the three short bars to its left; only with the plate (the floor's letters are gone)."""
        if not PLATE:
            return ""
        import plate_paint
        rgba, (W, H) = plate_paint.badge_rgba(GARNISH_TEXT, GARNISH_SIZE[1], EX_OUTLINE, BADGE_RGB, LOCK_DARK, italic=True,
                                              width_m=GARNISH_SIZE[0])
        xc, zc = GARNISH_AT
        x, z = self.pos[:, 0], self.pos[:, 2]
        idx = self._of("trunk", (CLS_PAINT,), (self.fnrm[:, 1] < -0.5) & (z > 0.995) & (z < 1.07) & (x > xc - 0.6 * W - 0.15) & (x < xc + 0.6 * W))
        if not len(idx):
            return "garnish: no bar"
        # the bar is the rearmost surface there
        cell = (np.floor(x[idx] / 0.01).astype(np.int64) + 1000) * 4096 + np.floor(z[idx] / 0.01).astype(np.int64) + 1000
        uc, inv = np.unique(cell, return_inverse=True)
        ymin = np.full(len(uc), np.inf)
        np.minimum.at(ymin, inv.reshape(-1), self.pos[idx, 1])
        idx = idx[self.pos[idx, 1] < ymin[inv.reshape(-1)] + 0.01]
        made, a = self._decal(idx, (x[idx] - (xc - 0.5 * W)) / W, (z[idx] - (zc - 0.5 * H)) / H, rgba, (W, H))
        bx, bl, bn = GARNISH_BARS
        rgba2, (W2, H2) = plate_paint.bars_rgba(bl, bn, GARNISH_SIZE[1] * 0.75, EX_OUTLINE, BADGE_RGB, LOCK_DARK)
        _i2, a2 = self._decal(idx, (x[idx] - (bx - 0.5 * W2)) / W2, (z[idx] - (zc - 0.5 * H2)) / H2, rgba2, (W2, H2))
        return "garnish %r %d texels, bars %d" % (GARNISH_TEXT, int((a > 0.5).sum()), int((a2 > 0.5).sum()))

    def _ex_badge(self, rho):
        """The EX trim badge (EX_BADGE, off by default: see the constants) on the gate's upper left."""
        if not EX_BADGE:
            return "EX badge: off"
        import plate_paint
        rgba, (W, H) = plate_paint.badge_rgba("EX", EX_SIZE[1], EX_OUTLINE, BADGE_RGB, LOCK_DARK)
        W = min(W, EX_SIZE[0] + 2 * EX_OUTLINE)
        xc, zc = EX_AT
        x, z = self.pos[:, 0], self.pos[:, 2]
        idx = self._of("trunk", (CLS_PAINT,), (self.fnrm[:, 1] < -0.5) & (np.abs(x - xc) < 0.6 * W) & (np.abs(z - zc) < 0.6 * H))
        if not len(idx):
            return "EX badge: no gate paint there"
        idx, a = self._decal(idx, (x[idx] - (xc - 0.5 * W)) / W, (z[idx] - (zc - 0.5 * H)) / H, rgba, (W, H))
        return "EX badge %d texels" % int((a > 0.5).sum())

    def _detail_maps(self):
        """The detail fields as full-sheet flat (index, value) pairs, through the fill mapping so the
        padding carries them (the 512 cap's box filter reads it). Built once."""
        if hasattr(self, "_dmaps"):
            return self._dmaps
        out = {}
        for key, arr, neutral in (("grain", self.dt_grain, 1.0), ("dust", self.dt_dust, 0.0), ("scuff", self.dt_scuff, 0.0),
                                  ("chip", self.dt_chip, 0.0), ("over", self.dt_over_a, 0.0)):
            f = self.full(arr.astype(np.float32), neutral).reshape(-1)
            i = np.nonzero(np.abs(f - neutral) > 1e-4)[0]
            out[key] = (i, f[i])
        rgb = self.full(self.dt_over_rgb.astype(np.float32), 0.0).reshape(-1, 3)
        out["over_rgb"] = rgb[out["over"][0]]
        self._dmaps = out
        return out

    @staticmethod
    def _tint(c, a, tint):
        """Move colours c (n, 3) by a (n,) toward luma L0 + K * their own luma in the tint's hue."""
        hue, l0, k = tint
        hue = np.asarray(hue, dtype=np.float32)
        hue = hue / float(luma(hue))
        t = hue[None, :] * (l0 + k * luma(c))[:, None]
        return c + (t - c) * a[:, None]

    def _apply_details(self, s):
        """skin()'s last step: grain, dust, hand wear, chips, then the overlays, on the levelled skin."""
        D = self._detail_maps()
        f = s.reshape(-1, 3)
        i, m = D["grain"]
        f[i] *= m[:, None]
        for key, tint in (("dust", DUST_TINT), ("scuff", SCUFF_TINT), ("chip", CHIP_TINT)):
            if WEAR <= 0.0:
                continue                                          # showroom clean (WEAR)
            i, a = D[key]
            f[i] = self._tint(f[i], a * WEAR, tint)
        i, a = D["over"]
        f[i] = f[i] * (1.0 - a[:, None]) + D["over_rgb"] * a[:, None]
        return f.reshape(s.shape)

    # -------------------------------------------------------------------------------------------
    # what compose calls
    def ao_k(self, default):
        """Per-texel AO depth for compose.shade: AO_K_PAINT on paint and plastics."""
        k = np.where(self.cls == CLS_PAINT, AO_K_PAINT, np.where(self.cls == CLS_PLASTIC, AO_K_PLASTIC, default))
        k = np.where(self._bay(), AO_K_BAY, k)
        return self.full(k, default).astype(np.float32)

    def _bay(self):
        """Compact bool: the bay walls' texels (AO_K_BAY / CAVITY_BAY)."""
        oi = self.obj_names.index("bay_walls") if "bay_walls" in self.obj_names else -1
        return self.obj == oi

    def bay_gain(self, ao, cav):
        """(S, S) gain on the shaded shell: on the bay walls' texels the median of their shading at BAY_KEEP over its
        median at AO_K_BAY / CAVITY_BAY (so the walls' average colour stays and the deeper AO and contact cavity only
        add shadows), 1 elsewhere. ao, cav: compose's (S, S) uint8 passes as shaded."""
        bay = self.full(self._bay(), False)
        g = np.ones(bay.shape, dtype=np.float32)
        if bay.sum() < 64:
            return g
        a = np.asarray(ao, dtype=np.float32)[bay] / 255.0
        cv = np.asarray(cav, dtype=np.float32)[bay] / 255.0
        old = (1.0 - BAY_KEEP[0] + BAY_KEEP[0] * a) * (1.0 - BAY_KEEP[1] * (1.0 - cv))
        new = (1.0 - AO_K_BAY + AO_K_BAY * a) * (1.0 - CAVITY_BAY * (1.0 - cv))
        k = float(np.clip(np.median(old) / max(float(np.median(new)), 1e-3), 1.0, BAY_GAIN_MAX))
        g[bay] = k
        self.log("paint: bay walls shading x%.2f..%.2f (p10..p90, was x%.2f..%.2f), median held by a gain of %.2f"
                 % (*np.percentile(new * k, [10, 90]), *np.percentile(old, [10, 90]), k))
        return g

    def cavity(self, default):
        """Per-texel cavity depth for compose.shade: CAVITY_PAINT on paint, CAVITY_PLASTIC on plastics."""
        k = np.where(self.cls == CLS_PAINT, CAVITY_PAINT, np.where(self.cls == CLS_PLASTIC, CAVITY_PLASTIC, default))
        k = np.where(self._bay(), CAVITY_BAY, k)
        return self.full(k, default).astype(np.float32)

    def gap_scale(self):
        """Scale of compose's gap-AO darkening: 0 beside a drawn seam, 0.5 on other painted texels,
        1 (unchanged) on everything the pass does not paint."""
        return self.full(self.gap_scale_c, 1.0).astype(np.float32)

    def paint_mask(self):
        """compose's paint_mask: every texel baked in the kotris paint (gloss 0.75), except the
        projection bleed on plastic and trim faces (see base()) and the lenses (_not_paint)."""
        d = np.sqrt(((self.colour - self.paint_srgb) ** 2).sum(-1))
        bleed = np.isin(self.full(self.cls, CLS_NONE), (CLS_PLASTIC, CLS_TRIM))
        ovr = self._ovr_full()
        spare = self.full(self.tri_spare[self.t], False)
        return (((d < BASE_TOL) & ~bleed & ~self._not_paint() & (ovr < 0) & ~spare) | np.isin(ovr, self._paint_ovr())).astype(np.float32)

    def _ovr_full(self):
        """(S, S) int: the OVERRIDES rule of every texel, -1 for none."""
        if not hasattr(self, "_ovr_img"):
            self._ovr_img = self.full(self.tri_ovr[self.t], -1)
        return self._ovr_img

    def _levels(self, s):
        """The level scales, measured on the shaded, gap-darkened sheet `s` (everything compose
        does before base()), each a median over the material's texels outside the drawn line cores
        (lamp bezels, seams on trims), so that median lands on its target: plastics PLASTIC_L
        (vertical, before their form terms), lamps LAMP_L and trims TRIM_L (scale down only).
        (Measured on the raw bake they shipped low: the white lenses at 64-65 for a target of 95,
        the shading, the gap AO and the bezels all acting after the scale, 2026-10-12.)"""
        sc = np.asarray(s, dtype=np.float32).reshape(-1, 3)[self.cpix]
        L = luma(sc)
        tm = self.tri_mat[self.t]
        clear = self.f_dark < 0.25
        sel = (self.cls == CLS_PLASTIC) & self.is_base & (np.abs(self.nrm[:, 2]) < 0.35) & clear
        self.k_plastic = PLASTIC_L / max(float(np.median(L[sel])), 1.0) if sel.sum() >= 8 else 1.0
        self.k_lamp, self.lamp_sel = {}, {}
        for m, target in list(LAMP_L.items()) + list(TRIM_L.items()):
            if m not in self.mat_names:
                continue
            mat = np.isin(self.cls, (CLS_LAMP, CLS_TRIM)) & (tm == self.mat_names.index(m))
            if (mat & clear).sum() < 8:
                continue
            self.k_lamp[m] = min(1.0, target / max(float(np.median(L[mat & clear])), 1.0))
            self.lamp_sel[m] = mat
        # lamp covers (LAMP_COVER_MATS): the scale of the nearest lens (_lamp_covers)
        self.cover_k = np.ones(len(self.cls))
        for mi in np.unique(self.cover_mat[self.cover_mat >= 0]):
            k = self.k_lamp.get(self.mat_names[mi])
            if k is not None:
                self.cover_k[self.cover_mat == mi] = k
        return sc, L

    def _lamp_covers(self):
        """self.cover_mat (compact): for LAMP_COVER_MATS texels within LAMP_COVER_R of a lens texel
        (a LAMP_L material), that lens's material index; -1 elsewhere."""
        self.cover_mat = np.full(len(self.cls), -1, dtype=np.int64)
        tm = self.tri_mat[self.t]
        cov = np.nonzero(np.isin(tm, [i for i, m in enumerate(self.mat_names) if m in LAMP_COVER_MATS])
                         & ~np.isin(self.tri_island[self.t], (-2, -3)))[0]
        lens = np.nonzero((self.cls == CLS_LAMP) & np.isin(tm, [i for i, m in enumerate(self.mat_names) if m in LAMP_L]))[0]
        if len(cov) and len(lens):
            dist, near = cKDTree(self.pos[lens]).query(self.pos[cov], distance_upper_bound=LAMP_COVER_R)
            hit = np.isfinite(dist)
            self.cover_mat[cov[hit]] = tm[lens[near[hit]]]
            self.log("paint: lamp covers: %d of %d %s texels lie within %.0f cm of a lens and take its level"
                     % (int(hit.sum()), len(cov), "/".join(sorted(LAMP_COVER_MATS)), 100 * LAMP_COVER_R))

    def _not_paint(self):
        """(S, S) bool: lens texels and lamp covers, which are never paint even when their colour comes
        near the kotris paint (the reverse lens's grid lines, a white cover: recoloured as paint they
        went black on the black skin, 2026-10-13)."""
        return self.full((self.cls == CLS_LAMP) | (self.cover_mat >= 0), False)

    def base(self, shell):
        """Skin-independent levels on the shaded shell: plastics to KI5's ~36 with their form
        terms, lamp lenses and trims scaled down, glass replaced by its per-pane gradient (bake hue
        kept)."""
        s = np.asarray(shell, dtype=np.float32).copy()
        shade_k = np.clip(luma(s) / np.maximum(luma(self.colour), 1.0), 0.3, 1.1)   # the bake's shading, for OVERRIDES
        s /= self.full(self.paint_dim, 1.0)[..., None]                    # dimmed kotris paint to its full level (PAINT_DIM)
        cls = self.full(self.cls, CLS_NONE)
        self._cls_full = cls
        ovr = self._ovr_full()
        d = np.sqrt(((self.colour - self.paint_srgb) ** 2).sum(-1))
        # ... nor the spare: the cap decal's light lug-bolt faces came near the kotris paint and took the skin's
        # colour (blue dots on every lug nut, polish round 1)
        self._paintlike = (d < BASE_TOL) & ~self._not_paint() & (ovr < 0) & ~self.full(self.tri_spare[self.t], False)
        tm = self.full(self.tri_mat[self.t], -1)
        # projection bleed: the twins' paint lands on the edge texels of plastic and trim faces, 1-3
        # texels along their border with the paint (1,747 plastic and 1,256 trim texels on the
        # 2026-10-12 bake). As "plain" paint they shipped as a body-coloured line on the black parts,
        # light on the white skin: the doors' cladding ledges, window frames (2026-10-13). They take
        # their material's own median colour and are levelled with it
        self._bleed = np.isin(cls, (CLS_PLASTIC, CLS_TRIM)) & self._paintlike
        for mi in np.unique(tm[self._bleed]):
            own = (tm == mi) & np.isin(cls, (CLS_PLASTIC, CLS_TRIM)) & ~self._paintlike
            if own.sum() >= 8:
                s[self._bleed & (tm == mi)] = np.median(s[own], axis=0)
        # the plate recess's cleared lettering (_recess) takes the floor's own shaded paint
        clr = self.full(self.recess_clear, False)
        floor = self.full(self.recess_floor, False)
        if clr.any() and floor.sum() >= 8:
            s[clr] = np.median(s[floor], axis=0)
        # plastic strays (PLASTIC_STRAY): light texels of another colour the twin projected on a plastic face
        pl_all = (cls == CLS_PLASTIC) & (ovr < 0)
        own_pl = pl_all & self.full(self.is_base, False)
        n_stray = 0
        if own_pl.sum() >= 8:
            med = np.median(s[own_pl], axis=0)
            stray = pl_all & ~own_pl & ~self._bleed & (luma(s) > PLASTIC_STRAY * float(luma(med)))
            s[stray] = med
            n_stray = int(stray.sum())
        sc, L0 = self._levels(s)
        self._base_full = self.full(self.is_base, False) | (self._bleed & (cls == CLS_PLASTIC))
        nz = self.full(self.nrm[:, 2], 0.0)
        fz = self.full(self.fnrm[:, 2], 0.0)
        nz_form = np.clip(nz, fz - FORM_NZ_TOL, fz + FORM_NZ_TOL)       # FORM_NZ_TOL
        z = self.full(self.pos[:, 2], 1.0)
        # overhung tops (OVERHANG_SHARE) take the form terms of a vertical face: no up-lift, the sill ramp
        self._form = self._form_terms(np.where(self.full(self.sky, True), nz_form, np.minimum(nz_form, 0.0)), z)
        # undersides ramp to the dark blocks' colour (UNDER_N), applied after the lines in skin()
        self._under = (smoothstep(UNDER_N[0], UNDER_N[1], nz) * smoothstep(UNDER_Z[0], UNDER_Z[1], z)
                       * (np.isin(cls, SKIN_CLS) & self._base_full)).astype(np.float32)
        pl = pl_all                                               # every plastic texel takes the level (polish round 1:
        fm, fw = self._form                                       # the off-colour ones kept the bake's 77 between 36s)
        m_pl = 1.0 + PLASTIC_FORM * (fm - 1.0)
        w_pl = PLASTIC_FORM * fw
        v = s[pl] * (self.k_plastic * m_pl[pl])[:, None]
        s[pl] = v + (255.0 - v) * w_pl[pl][:, None]
        ov = (~self.full(self.sky, True)) & (nz > 0.30) & np.isin(cls, (CLS_PLASTIC, CLS_TRIM)) & self._base_full
        s[ov] *= OVERHANG_DARK                                    # overhung ledges (OVERHANG_DARK)
        for mname, k in self.k_lamp.items():
            if k >= 0.999:
                continue
            sel = np.isin(cls, (CLS_LAMP, CLS_TRIM)) & (tm == self.mat_names.index(mname))
            s[sel] *= k
        s *= self.full(self.cover_k, 1.0)[..., None].astype(np.float32)        # lamp covers: 1 everywhere else
        # the report: each material's median as it leaves the pass (scale and lines; before weathering)
        out = {m: float(np.median(L0[sel] * self.k_lamp[m] * self.mult_c[sel])) for m, sel in self.lamp_sel.items()}
        self.log("paint: levels plastic x%.2f (%d stray texels to its median); lamps and trims (baked -> out median, scale) %s"
                 % (self.k_plastic, n_stray, " ".join("%s %.0f->%.0f x%.2f" % (m, self.mat_L.get(m, 0), out[m], self.k_lamp[m]) for m in out)))
        made = []
        for k, (what, _o, _m, _r, rgb) in enumerate(OVERRIDES):         # OVERRIDES: their flat colour, the bake's shading
            sel = ovr == k
            if sel.any():
                c = self.paint_srgb if isinstance(rgb, str) else np.asarray(rgb, dtype=np.float32)
                s[sel] = c[None, :] * shade_k[sel][:, None]
            made.append("%s %d" % (what, int(sel.sum())))
        self.log("paint: overrides " + ", ".join(made))
        gl = cls == CLS_GLASS
        c = self.colour[gl]
        tint = c / np.maximum(luma(c), 1.0)[:, None]
        s[gl] = tint * self.full(self.glass_L, 40.0)[gl][:, None]
        self._mult = self.full(self.mult_c, 1.0).astype(np.float32)
        self._add = self.full(self.add_c, 0.0).astype(np.float32)
        return s

    def _form_terms(self, nz, z):
        """(multiplier, lerp-to-white weight) per texel, paint depth (plastics scale them)."""
        ramp = SILL_K + (1.0 - SILL_K) * smoothstep(RAMP_Z0, RAMP_Z1, z)
        ramp = ramp + (1.0 - ramp) * smoothstep(RAMP_UP[0], RAMP_UP[1], nz)
        up = np.clip(nz / UP_FULL, 0.0, 1.0)
        down = np.maximum(DOWN_MIN, 1.0 + DOWN_GAIN * np.minimum(nz, 0.0))
        return ramp * (1.0 + UP_GAIN * up) * down, UP_WHITE * up

    @staticmethod
    def _top(colour):
        """(top colour, lift factor) a skin's up-facing paint lifts toward (FINISH_LIFT, paint_textures.PAINTS):
        white x 1 for a solid or unknown paint; a metallic or pearl's chip-photo top colour scaled to white's
        luma (its hue in the sun; channels may pass 255, the skin is clipped at the end) x its finish's lift."""
        white = np.full(3, 255.0, dtype=np.float32)
        try:
            import paint_textures
            finish, top = paint_textures.TOPS.get(tuple(int(c) for c in colour), ("solid", None))
        except ImportError:
            return white, 1.0
        if top is None:
            return white, float(FINISH_LIFT.get(finish, 1.0))
        t = np.asarray(top, dtype=np.float32)
        return (t * (255.0 / max(float(luma(t)), 1.0))).astype(np.float32), float(FINISH_LIFT.get(finish, 1.0))

    @staticmethod
    def _tune(colour):
        """SKIN_TUNE's entry for the paint whose median sRGB is `colour` (paint_textures.PAINTS), {} for none."""
        try:
            import paint_textures
        except ImportError:
            return {}
        key = tuple(int(c) for c in colour)
        for p in paint_textures.PAINTS:
            if tuple(p[4]) == key:
                return SKIN_TUNE.get(p[1], {})
        return {}

    def _reflect(self, s):
        """Painted reflections (REFLECT_GLASS, REFLECT_BODY; preview only): on glass a sky gradient toward
        SKY_RGB over the top of each pane and a horizon band (darker under a crisp edge, a bright line on it);
        on the body sides a faint horizon at BODY_HORIZON_Z (lighter above, a thin dark line, darker below).
        Anti-aliased over a texel; applied after the lines, before the undersides and the micro-detail."""
        if not hasattr(self, "_refl"):
            r = np.maximum(self.rho, 1.0)
            g = (self.cls == CLS_GLASS) & (self.glass_kind >= 0)
            f = self.glass_f
            hz = np.array([GLASS_HORIZON["side"], GLASS_HORIZON["front"], GLASS_HORIZON["rear"]])[np.clip(self.glass_kind, 0, 2)]
            # metres along the glass per unit of f (the pane's z range over the sine of its elevation), so the
            # edges are anti-aliased over one texel whatever the pane
            rise = np.sqrt(np.clip(1.0 - self.fnrm[:, 2] ** 2, 0.05, 1.0))
            span = np.where(g, np.maximum(self.glass_h, 0.05) / rise, 1.0)
            edge = np.clip((hz - f) * span * r + 0.5, 0.0, 1.0)  # 1 under the horizon edge
            band = edge * np.clip(1.0 - (hz - f) / GLASS_BAND[0], 0.0, 1.0)
            line = np.clip((f - hz) * span * r + 0.5, 0.0, 1.0) * np.clip((hz + GLASS_EDGE[0] - f) * span * r + 0.5, 0.0, 1.0)
            sky_g = SKY_A * smoothstep(SKY_FROM, 1.0, f) + GLASS_EDGE[1] * line
            mul = np.where(g, 1.0 - REFLECT_GLASS * GLASS_BAND[1] * band, 1.0)
            sky = np.where(g, REFLECT_GLASS * sky_g, 0.0)
            # body sides: paint texels facing sideways
            b = (self.cls == CLS_PAINT) & (np.abs(self.fnrm[:, 0]) > 0.7)
            dz = self.pos[:, 2] - BODY_HORIZON_Z
            above = np.clip(dz * r + 0.5, 0.0, 1.0)
            dline = np.clip(-dz * r + 0.5, 0.0, 1.0) * np.clip((BODY_LINE[0] + dz) * r + 0.5, 0.0, 1.0)
            lift = BODY_SKY[1] * above * np.clip(1.0 - dz / BODY_SKY[0], 0.0, 1.0)
            m_b = (1.0 + REFLECT_BODY * lift) * (1.0 - REFLECT_BODY * BODY_LINE[1] * dline) * (1.0 - REFLECT_BODY * BODY_GROUND * (1.0 - above))
            mul = np.where(b, m_b, mul)
            self._refl = (self.full(mul.astype(np.float32), 1.0), self.full(sky.astype(np.float32), 0.0))
            self.log("paint: reflections (preview) glass %.2f body %.2f: %d glass texels, %d body-side texels"
                     % (REFLECT_GLASS, REFLECT_BODY, int(g.sum()), int(b.sum())))
        mul, sky = self._refl
        s = s * mul[..., None]
        return s + (np.asarray(SKY_RGB, dtype=np.float32) - s) * sky[..., None]

    def skin(self, base, colour):
        """One skin from base(): paint recoloured to its KI5 level, form terms, then every line."""
        s = np.array(base, dtype=np.float32, copy=True)
        cls = self._cls_full
        pt = (cls == CLS_PAINT) & self._base_full
        target = np.asarray(colour, dtype=np.float32)
        Lc = float(luma(target))
        tune = self._tune(colour)                                  # SKIN_TUNE
        level = float(tune.get("belt", LEVEL_BASE + LEVEL_GAIN * Lc))
        tgt = target * (level / max(Lc, 1.0))
        ratio = tgt / self.paint_srgb
        fm, fw = self._form
        v = s[pt] * ratio[None, :] * fm[pt][:, None]
        top, lift = self._top(colour)
        lift *= float(tune.get("up_k", 1.0))
        s[pt] = v + (top[None, :] - v) * np.clip(lift * fw[pt], 0.0, 1.0)[:, None]
        # the rest of what the bake painted in the kotris colour (door jambs, the hood's underside, the
        # bay walls, the gate's inner skin): the skin at its level, no form and no lines, as compose
        # recoloured it before the paint pass
        plain = self._paintlike & ~pt & ~self._bleed
        s[plain] *= ratio[None, :]
        s = s * self._mult[..., None] + self._add[..., None]
        if REFLECT_GLASS > 0.0 or REFLECT_BODY > 0.0:             # preview only (both 0 by default)
            s = self._reflect(s)
        u = self._under[..., None]
        s = s * (1.0 - u) + np.asarray(DARK_RGB, dtype=np.float32) * u
        s = self._apply_details(s)                                # micro-detail, relative to this skin's levels
        out = np.clip(s, 0, 255).astype(np.uint8)
        # stats for the report: belt paint and tops of this skin
        if not hasattr(self, "_belt"):
            nz = self.nrm[:, 2]
            belt = (self.cls == CLS_PAINT) & (np.abs(nz) < 0.1) & (self.pos[:, 2] > 0.8) & (self.pos[:, 2] < 1.15)
            tops = (self.cls == CLS_PAINT) & (nz > 0.85)
            self._belt, self._tops = self.cpix[belt], self.cpix[tops]
        L = luma(out.reshape(-1, 3))
        self.stats[tuple(int(c) for c in colour)] = (float(np.median(L[self._belt])) if len(self._belt) else 0.0,
                                                      float(np.median(L[self._tops])) if len(self._tops) else 0.0)
        return out

    def rubber(self):
        """The seal's coverage 0..1: RUBBER_W inside the true outline of glued panes (windshield, rear
        glass, fixed quarters), drawn here instead of the baked shell_rubber map, which outlines every
        shell of a pane (the windshield's rings); drop glass (window_*) has its 1-texel edge instead.
        The black frit ring of glued panes (FRIT_MATS) is seal all over."""
        glued = (self.cls == CLS_GLASS) & ~self.tri_is_drop[self.t]
        a = np.clip((RUBBER_W - self.glass_d) * np.maximum(self.rho, 1.0) + 0.5, 0.0, 1.0)   # anti-aliased over a texel
        frit = np.isin(self.tri_mat[self.t], [i for i, m in enumerate(self.mat_names) if m in FRIT_MATS])
        a = np.where(frit, 1.0, a)
        return self.full(np.where(glued, a, 0.0), 0.0).astype(np.float32)

    def rubber_rgb(self, rgb):
        """The seal's colour per texel for compose.paint_rubber (S, S, 3): `rgb` (compose RUBBER_RGB) lifted
        on the rounded lip next to the body (RUBBER_LIP) and in a thin line where the seal meets the glass
        (RUBBER_INNER), anti-aliased over a texel. Glued panes only, as rubber()."""
        r = np.maximum(self.rho, 1.0)
        d = self.glass_d
        lip = np.clip((d - RUBBER_LIP[0]) * r + 0.5, 0.0, 1.0) * np.clip((RUBBER_LIP[1] - d) * r + 0.5, 0.0, 1.0)
        inner = np.clip((d - (RUBBER_W - RUBBER_INNER[0])) * r + 0.5, 0.0, 1.0) * np.clip((RUBBER_W - d) * r + 0.5, 0.0, 1.0)
        k = 1.0 + (RUBBER_LIP[2] - 1.0) * lip + (RUBBER_INNER[1] - 1.0) * inner
        glued = (self.cls == CLS_GLASS) & ~self.tri_is_drop[self.t]
        k = np.where(glued & np.isfinite(d), k, 1.0)
        return (self.full(k.astype(np.float32), 1.0)[..., None] * np.asarray(rgb, dtype=np.float32)).astype(np.float32)

    def weather_scale(self):
        """0 on glass, 1 elsewhere: the plan's glass is a clean per-pane gradient (bake_atlas keeps the
        glass out of the grime map, GLASS_HAZE 0), but compose's gap grime from the cavity pass put pale
        patches on it (2026-10-12)."""
        return self.full(np.where(self.cls == CLS_GLASS, 0.0, 1.0), 1.0).astype(np.float32)

    def dark_cells(self):
        """[(x0, y0, x1, y1, zone)] of the dark blocks in the meta (Part A)."""
        out = []
        for b in self.meta.get("dark_blocks", []):
            x0, y0, x1, y1 = (v * self.ss for v in _rect(b["rect"], self.dump_size))   # bake texels: whole SS blocks
            out.append((x0, y0, x1, y1, b.get("zone", "body")))
        return out

    def dark_fill(self, img):
        """The dark blocks (16 x 16 cells of hidden faces, Part A) in DARK_RGB, the skin's last step."""
        a = np.asarray(img, dtype=np.uint8).copy()
        for x0, y0, x1, y1, _z in self.dark_cells():
            a[y0:y1, x0:x1, :3] = DARK_RGB
        return a

    def report(self):
        """compose's one line (plan B4); vertical paint = median belt luma per skin, min..max."""
        S2 = float(self.size * self.size)
        seams = (self.f_dark > 0.25) & np.isin(self.cls, SEAM_CLS)
        hi = self.f_hi > 0.25
        cr = np.abs(self.f_crease) > 0.25
        belts = [v[0] for v in self.stats.values()]
        tops = [v[1] for v in self.stats.values()]
        return ("paint: seams %.1f%% crease %.1f%% highlight %.1f%% of texels; vertical paint %.0f..%.0f, tops %.0f..%.0f"
                % (100.0 * seams.sum() / S2, 100.0 * cr.sum() / S2, 100.0 * hi.sum() / S2,
                   min(belts) if belts else 0, max(belts) if belts else 0, min(tops) if tops else 0, max(tops) if tops else 0))

    def debug(self, shell, path):
        """Seams red, highlights white, creases blue (convex) / cyan (concave), and the micro-detail
        fields (dust orange, wear and chips green, overlays magenta) over the shaded shell."""
        s = np.asarray(shell, dtype=np.float32).copy()
        dark = self.full(self.f_dark, 0.0)[..., None]
        hi = self.full(self.f_hi, 0.0)[..., None]
        cr = self.full(self.f_crease, 0.0)
        s = s * (1 - dark) + np.array([230, 30, 30], np.float32) * dark
        s = s * (1 - hi) + np.array([255, 255, 255], np.float32) * hi
        cv = np.clip(cr, 0, 1)[..., None]
        cc = np.clip(-cr, 0, 1)[..., None]
        s = s * (1 - cv) + np.array([40, 90, 255], np.float32) * cv
        s = s * (1 - cc) + np.array([0, 200, 220], np.float32) * cc
        # micro-detail: dust orange, hand wear / chips green, overlays magenta
        for arr, rgb in ((self.dt_dust, (255, 150, 20)), (np.maximum(self.dt_scuff, self.dt_chip), (40, 220, 60)),
                         (self.dt_over_a, (230, 40, 230))):
            k = self.full(arr.astype(np.float32), 0.0)[..., None]
            s = s * (1 - k) + np.array(rgb, np.float32) * k
        from PIL import Image
        Image.fromarray(np.clip(s, 0, 255).astype(np.uint8)).save(path)
        return path
