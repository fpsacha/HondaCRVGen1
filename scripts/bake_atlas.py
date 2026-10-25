r"""
Unwrap the kotris parts and bake their flat material colours into texture atlases.

    blender -b blender\import\parts_kotris.blend --python scripts\bake_atlas.py -- [--out blender\bake] [--save blender\crv_kotris.blend]
            [--spaces shell,wheel] [--decals DIR]

Four UV spaces, one per texture the game script references:
    shell    body + every opening panel + glass + spare (2048)   -> Vehicles_..._Shell / Mask / Lights
    interior interior + cabin (build_cabin.py)            (1024) -> Vehicles_..._Interior
    wheel    wheel_FR                                      (512)  -> Vehicles_..._Wheel
    engine   engine_block                                  (512)  -> Vehicles_..._Engine
Each space is laid out at that size and baked at SUPERSAMPLE x it (the anti-aliased bake, 2026-10-13);
compose reduces the shipped sheets to it.

Sheet sizes (2026-10-12, read from the game's bytecode): model textures are never mipmapped
(ModelManager never sets TextureFlags.MIPMAPS, TextureID then samples GL_LINEAR min and mag) and
are capped at load by the player's texture-size option (Vehicle Texture Size for shaders named
vehicle*, engine default 512; Texture Size otherwise, default 256). KI5 authors every sheet at
512 with ~0.6 texels/cm: every texel is magnified, nothing is thrown away. The 1024 step of
2026-10-12 aimed at ~1 texel/cm for a 150 px/m camera; the in-game screenshots then measured
~326 px/m (playbook), where that sheet was magnified ~2.7x.

The shell is the planar "blueprint" layout (spec/planar-texture-plan.md, scripts/planar_uv.py):
every kotris panel one island projected along its own mean normal at ~3 texels/cm on a 2048
sheet, generated faces, details, the spare, cards and accessories as xatlas charts at ~1.5
texels/cm x their weight, the underbody and seam backing in 16x16 dark cells, tube steel in
swatch cells, all packed by xatlas in one call. It writes shell_layout.png (islands tinted by
axis), the face attribute uv_island and, through uvmesh_dump (Part B) when its file is there,
shell_uvmesh.npz for compose's 2D paint pass. Its report line and its layout check line
(planar_uv.check_layout: overlap, range, gap, starved charts) are gated by build.py. The shell
bakes with margin 0 (SPACE_MARGIN); compose's Dilate fills the padding.

Interior, wheel and engine: xatlas charts across all the space's objects, one packing. Then per
space Cycles bakes
    <space>_color.png   diffuse colour only (no lighting)
    <space>_ao.png      ambient occlusion, linear
    <space>_cavity.png  4 cm ambient occlusion (creases, recesses)
    shell_gap.png       1.2 cm ambient occlusion: only the real shut lines occlude; compose
                        thresholds it into the crisp dark seam lines KI5 draws
    shell_rubber.png    window seals: a band RUBBER_WIDTH wide inside every pane outline
    shell_zone.png      the game's part-zone colours (vehicle.frag colZone table), exact, linear
    shell_lights.png    emissive lamps: headlamps white, tails red, indicators amber
compose_textures.py (system Python + Pillow) turns those into the final PNG set.

The vehicle shader samples rust, damage and blood through a SECOND UV set (texCoords1); every
mesh gets "UVMap1" as a copy of the atlas UVs. Meshes get a custom property uv_baked=1 so
export_fbx keeps these UVs instead of projecting its own.

Feature plugins (scripts/features): their OBJECTS join the sheet they name (features.spaces), their
SPACES are sheets of their own (xatlas, like the interior), their zones / texel weights / materials
(BAKE_TEXTURED, BAKE_MAT_WEIGHTS) join the tables here and BAKE_PAINT writes their maps before the
first space bakes. Every acc_* object is invisible to the car's rays, so name feature meshes acc_<key>_*.
"""
import json
import math
import os
import sys

import bmesh
import bpy

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
# the xatlas job is this file's sibling, not ROOT's: a worktree copy under test must run its own
# (run_rebuild's exec'd scripts have no __file__, this one is always run by path)
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.path.join(ROOT, "scripts")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import tyre_paint  # noqa: E402  (painted tyre maps and the spare cover's face, written before the bake)
import door_cards  # noqa: E402  (the door / gate cards, repainted along each card's outline before the bake)
import cargo_bay_paint  # noqa: E402  (the cargo bay's deck and side trim maps, written before the bake)
import features  # noqa: E402  (scripts/features: the plugins' objects, sheets, materials and painted maps)

SPACES = {
    "shell": (["body", "hood", "door_fl", "door_fr", "door_rl", "door_rr",
               "window_fl", "window_fr", "window_rl", "window_rr", "trunk", "trunk_top",
               "arch_liners", "antenna", "bay_walls",
               # accessories (build_accessories.py): on this sheet, invisible to the car's rays
               "acc_bullbar", "acc_roofrack", "acc_guard_ws", "acc_guard_rear",
               "acc_guard_fl", "acc_guard_fr", "acc_guard_rl", "acc_guard_rr", "acc_table",
               "acc_rack_load1", "acc_rack_load2", "acc_rack_load3",                 # rack cargo states
               "acc_spare_cover"], 2048),                                            # soft cover on the spare
    # sizes: see the docstring. The shell is 2048 since the planar layout (spec/planar-texture-plan.md:
    # ~3 texels/cm on the panels, ~1:1 at the measured 326 px/m); the others are unchanged
    # (texel-per-screen-pixel at 150 px/m; the 512 load cap most players run). The interior's
    # "mottled grey at 1024" (2026-10-11) was full-contrast grain, since damped by the flat factors
    # in TEXTURED, not a lack of texels.
    "interior": (["interior", "cabin"], 1024),
    # wheel 256 -> 512 (2026-10-13, approved): the vehiclewheel shader's name starts with "vehicle",
    # so the default Vehicle Texture Size (512) loads it unhalved; at 256 the tyre's lettering and the
    # rim's windows were ~2 texels/cm, a soft blur at 326 px/m
    "wheel": (["wheel_FR"], 512),
    "engine": (["engine_block"], 512),       # its own sheet: the shared atlas starved the cover lettering
}
# the feature plugins' meshes join their sheet's list and their own sheets follow (features.spaces; the
# literal above stays the first SPACES assignment: build.py and paint_pass read it with ast and merge alike)
SPACES = features.spaces(SPACES)
# Anti-aliased bake (2026-10-13, approved). Cycles bakes ONE sample position per texel (the 0.01
# box pixel filter in main(): a wider filter blends islands into each other), so every baked edge,
# lettering, badges, lamp grids, handle recesses, trim and decal edges, was a staircase of whole
# texels. Every space now bakes at SUPERSAMPLE x its sheet size and compose works at that size (Dilate,
# shading, the paint pass, lights, mask) and reduces each shipped sheet at the very end: a 2 x 2 box
# for colour, lights and gloss (4 samples a texel, the edges anti-aliased), the majority of the 2 x 2
# for the Mask's zones (exact legal colours). The layout does not change: UVs are size-free, the
# layout gate stays at the sheet size, the padding doubles in bake texels, the dark / swatch cells
# land on whole 2 x 2 blocks. The 2x2 box also averages four independent AO estimates per texel.
SUPERSAMPLE = 2
# material -> emission colour (linear) of the LIT lens; compose_textures.lights_lit takes it as the lit
# median in sRGB and puts the lens's own pattern on it. Only what a lamp zone really lights: the game
# lights lights_*h / lights_*t with the headlights and stop_* when braking (vehicle_common.frag: no
# reverse or indicator zone), so the amber turn signals and side markers (Feux_orange, Phare_orange,
# Reflect_orange), the reverse lamp (Feux_blanc) and the bumper's red reflex reflectors (Reflect_red)
# stay dark; until 2026-10-13 the amber ones glowed with the tail lamps. Levels after KI5's Lights
# (Touran, XJ, Trooper, W460): tail lenses lit (123-197, 16-31, 16-31), head lenses neutral, median
# 128-195, p90 208-239. The old (1.0, 0.08, 0.04) tail shipped as a flat orange-red (237, 74, 52).
# One emission colour = one lens: the headlamp's lens and reflector share theirs (no outline between).
LIGHT_MATS = {
    "Phare_vitre": (0.72, 0.69, 0.58), "Phare": (0.72, 0.69, 0.58),     # sRGB (221, 216, 200), warm white
    "Feux_rouge": (0.515, 0.0091, 0.0060),                              # sRGB (190, 24, 18), tail
    "Feux_stop": (0.68, 0.0116, 0.0070),                                # sRGB (215, 28, 20), the high stop lamp
    "AccLens": (0.72, 0.69, 0.58),    # the bull bar's driving lamps come on with the headlights
}
# Kotris authored flat linear colours that read washed out once converted to sRGB: the tyre at
# 0.169 linear is mid grey, not black, and the rim bakes near white. These overrides are applied
# for the colour bake only, then restored. Lamp lenses keep their own colours.
PALETTE = {
    "Pneu": (0.020, 0.020, 0.020),          # tyre rubber (KI5 tyres: lum p50 32 with a lighter sidewall ring)
    "Jante": (0.335, 0.335, 0.345),         # alloy rim: sRGB ~156 before the wheel sheet's AO (0.26 read flat grey once
                                            # the windows were real). Polish round 2 (R2-WA-5, values from the details
                                            # team): spokes ship ~150-155 under a brighter centre cap (~195-205, the
                                            # hubcap.png decal's own level); 0.32 shipped ~151 at the spoke centres
    "Plastique_noir": (0.030, 0.030, 0.033),
    "WellTub": (0.012, 0.012, 0.013),          # the cargo tub under the picnic table (build_table.WELL_MAT): black plastic
    "Partie_noir": (0.015, 0.015, 0.015),
    "Body_plastique": (0.075, 0.075, 0.080),  # charcoal bumper and cladding
    "Dessous": (0.030, 0.030, 0.030),
    # badges: the 1.2 cm gap pass now draws a dark outline round every badge, so they can be as
    # light as KI5's (sRGB ~207). The 0.30 of v6 was "0.55 vanished on silver paint", which
    # happened without an outline.
    "Chrome": (0.62, 0.63, 0.66),
    # lamp lenses: kotris's reds measured (129, 62, 61) on the shipped sheet, saturation 67 against
    # KI5's (77, 18, 16) / (62, 18, 18); amber (141, 119, 75). Deep lens colours, the lens map
    # (tyre_paint.tail_lens_map) multiplies over them and paint_pass.LAMP_L sets their level. The tail
    # lamp's amber is the yellow-orange of its frame (the photos' lighter band along the top and the
    # outer side); the map deepens the block inside it
    "Feux_rouge": (0.32, 0.012, 0.010), "Feux_stop": (0.32, 0.012, 0.010), "Reflect_red": (0.20, 0.010, 0.010),
    "Feux_orange": (0.80, 0.34, 0.03), "Phare_orange": (0.80, 0.30, 0.02), "Reflect_orange": (0.60, 0.22, 0.02),
    "Feux_blanc": (0.70, 0.70, 0.68),
    "Vitre": (0.030, 0.040, 0.040),
    "Vitre_noir": (0.026, 0.034, 0.034),    # rear quarter glass: 0.012 read as a black hole beside the other windows (2026-10-12)
    # cabin (2026-10-12): the cabin baked at sRGB 119-156 against KI5's interior sheet mean of 29; the
    # tints in TEXTURED land these albedos (linear) at the sRGB in the comments
    "Interieur": (0.060, 0.060, 0.062),           # shell, headliner, pillar trims: sRGB 70
    "Interieur_sol": (0.030, 0.030, 0.031),       # carpet: sRGB 48
    "CabDark": (0.026, 0.026, 0.028),             # dash top, binnacle, wheel, column, tray: sRGB 46 (was 52)
    "CabDash": (0.040, 0.040, 0.042),             # dash face and stack (cabin_dash.png): sRGB 56 (was 64)
    # seats (polish round 2, R2-OC-3): the RD1's grey cloth reads sRGB 116-130 in the cabin photos, front, rear and
    # bolsters alike (one fabric); at 85 / 57 the interior sheet's AO (compose AO_K_SPACE 0.50) shipped them at 67-71 /
    # 41-46, black plastic beside a 31-38 dash. Raised so the shipped median lands ~115 after the AO.
    # Feature round 2026-10-19 (the owner's photos of the car: DARK grey cloth, grey on grey; ours read as light-grey
    # boxes, shipped 106-151): target shipped sRGB ~55-75 on the bolsters, ~45-65 on the striped insert (darker than
    # the bolsters); x ~0.28 / ~0.22 linear from the 2026-10-18 levels
    "SeatCloth": (0.057, 0.058, 0.062),           # striped seat insert: sRGB ~68 before the AO
    "SeatBolster": (0.073, 0.074, 0.078),         # bolsters, the same cloth plain: sRGB ~77 before the AO
    "Siege": (0.115, 0.115, 0.118),
    "Siege_2": (0.145, 0.145, 0.150),
    "Miroir": (0.100, 0.100, 0.105),
    "Metal": (0.230, 0.230, 0.240),
    "Feux_chrome": (0.300, 0.300, 0.310),
    "Phare": (0.050, 0.050, 0.052),
    "TrimDark": (0.17, 0.17, 0.175),        # (v4 cards; unused since v5)
    # the windowed alloy (prep_parts._rim_face, 2026-10-12): the pockets' walls (darkened with depth by
    # the rim_shade attribute) and the disc behind them, dark so the windows read as holes at 150 px/m
    "RimWell": (0.035, 0.035, 0.037),       # window walls and barrel, x rim_shade (1 at the face, 0.22 at the
                                            # disc): the 30-degree camera sees mostly the lower walls; at 0.20
                                            # and 0.06 the windows read as grey on grey spokes at 150 px/m
    "Rotor": (0.10, 0.085, 0.07),           # brake rotor / hub face behind the windows (was 0.30: a
                                            # backing disc on the twin only the projection rays saw); 0.025 -> warm
                                            # cast-iron grey (sRGB ~89, 82, 74) in polish round 2 (R2-WA-5): a rotor in
                                            # the windows, not pure black; the hub centre stays dark (ROTOR_HUB)
    "AccLens": (0.50, 0.53, 0.56),          # driving lamps on the bull bar
    "SeamBack": (0.010, 0.010, 0.011),      # prep's backing plates / gutter strips behind seams: what a crack shows
}
DECAL_BOOST = 3.0                    # UV scale for "Decal*" materials before packing
# PolyHaven CC0 surfaces (blender/references/polyhaven, CREDITS.md there) box-mapped by object
# position for the colour bake only: material -> (diffuse jpg, tile size in metres, tint multiplier)
POLYHAVEN = os.path.join(ROOT, "blender", "references", "polyhaven")
TEXTURED = {
    # material -> layer list, applied in order during the colour bake only. Layers:
    #   ("box", jpg, tile_m, tint)                        PolyHaven grain, greyscale x tint (replaces)
    #   ("noise", scale_per_m, amount)                     multiplies by 1 +- amount noise
    #   ("decal", png, (axis, a0, a1[, "abs"]), (axis, b0, b1), mode[, gate])
    #                                                      mode replace|multiply; gate ("normal", axis, "<"|">", v);
    #                                                      axis "x" | "y" | "z", or a direction (dx, dy, dz) whose
    #                                                      dot product with the position maps (|x| with "abs"):
    #                                                      a decal along a slanted surface's own axes
    #   ("tyremap",)                                       the painted tyre (tyre_paint: tread blocks, sipes,
    #                                                      sidewall lettering, rim protector, shoulder lugs)
    #                                                      wrapped round the tyre the material sits on
    #   ("stripes", pitch_m, amount)                       diagonal weave (x + y + z), x (1 +amount / 1 -0.6 amount)
    #   ("attr", name)                                     multiplies by a float corner attribute (rack cargo AO)
    #   ("tint", rgb, gates)                               a flat linear colour where every gate passes (the
    #                                                      decal's gates: ("normal", ...), ("range", ...))
    # flat factors (5th value) damp the grain: at the game's zoom full-contrast grain reads as
    # static / mottled concrete (feedback, first in-game look 2026-10-11: the interior looked poor).
    # Raised again with the 1024 interior sheet (2026-10-12): at ~1 texel/cm the grain period is
    # 1-2 texels and anything left of its contrast is pixel speckle under GL_LINEAR with no mips.
    "Siege":         [("box", "poly_wool_herringbone_diffuse_1k.jpg", 0.30, (0.60, 0.60, 0.62), 0.60)],
    "Siege_2":       [("box", "poly_wool_herringbone_diffuse_1k.jpg", 0.30, (0.42, 0.42, 0.44), 0.60)],
    # cabin (2026-10-12): tints from albedo = tint x (flat + (1 - flat) x g), g the jpg's measured linear
    # grey mean (herringbone 0.183, leather 0.113, carpet 0.033), so each lands on its PALETTE albedo.
    # The old cluster layer on "Interieur" is gone: it painted a 40 x 18 cm black box on the binnacle AND
    # the dash behind it; the cluster now rides the cabin's binnacle face (CabDark).
    "Interieur_sol": [("box", "dirty_carpet_diffuse_1k.jpg",          0.45, (0.062, 0.064, 0.066), 0.45)],
    # the headliner, the sun visors and the pillar trims above the belt line are LIGHT grey on the RD1 (photos
    # DSC_7904 / 7909 / 7952: ~sRGB 180-200 against the charcoal lower trims); one "Interieur" covers both, so the
    # upper part mixes to a flat light grey over z 1.10-1.18 (object space; polish round 1, 2026-10-17: the
    # headliner shipped at sRGB 32-60)
    "Interieur":     [("box", "fabric_leather_01_diffuse_1k.jpg",     0.18, (0.106, 0.108, 0.112), 0.50),
                      ("zmix", 1.10, 1.18, (0.36, 0.36, 0.35), 0.03)],
    # cabin_cluster.png on the binnacle's driver-facing face only: the y gate keeps it off the wheel
    # (rim and hub surfaces facing the driver lie at y <= 0.468) and off the dash face (y >= 0.59)
    # feature round 2026-10-19: tints for the darker PALETTE (CabDark 0.026, CabDash 0.040); cabin_dash_top.png
    # multiplies the passenger airbag door's seam onto the dash top (up-facing faces only, x 0.10..0.74)
    "CabDark":       [("box", "fabric_leather_01_diffuse_1k.jpg",     0.12, (0.043, 0.043, 0.047), 0.55),
                      ("decal", "cabin_cluster.png", ("x", -0.575, -0.225), ("z", 1.035, 1.165), "replace",
                       [("normal", "y", "<", -0.6), ("range", "y", 0.475, 0.53)]),
                      ("decal", "cabin_dash_top.png", ("x", 0.10, 0.74), ("y", 0.56, 0.88), "multiply",
                       [("normal", "z", ">", 0.5), ("range", "z", 1.0, 1.3)]),
                      # the steering wheel face-on (2026-10-20, build_cabin.paint_wheel: badge, horn pads, SRS badge, the
                      # rim's perforated grips), mapped in the wheel's own plane: u along its in-plane right, v its up
                      # (build_cabin.wheel_decal_frame(), printed by the cabin build), on the faces turned to the driver
                      # in front of the binnacle (y < 0.47: not the cluster pod or the stalks)
                      ("decal", "cabin_wheel.png", ((0.9998, 0.01909, -0.00577), -0.60265, -0.17265),
                       ((0.0, 0.28918, 0.95728), 0.89534, 1.32534), "replace",
                       [("normal", "y", "<", -0.5), ("range", "y", 0.30, 0.47)])],
    # cabin_dash.png (vents, radio, HVAC, glovebox, switch bank) on the faces turned to the cabin
    "CabDash":       [("box", "fabric_leather_01_diffuse_1k.jpg",     0.15, (0.072, 0.072, 0.075), 0.50),
                      ("decal", "cabin_dash.png", ("x", -0.72, 0.72), ("z", 0.48, 1.21), "replace",
                       [("normal", "y", "<", -0.3), ("range", "y", 0.44, 0.80)])],
    # the RD1 insert's diagonal stripes: feature round 2026-10-19 (the owner's photos: "a darker diagonal-stripe
    # weave, broad diagonal stripes on the backrest and cushion"): one broad 7 cm stripe at +-38 % (dark / light
    # 1.8 : 1, ~8 texels a period at 1.2 texels/cm) over a faint 3.1 cm one for the weave; the polish-round-2
    # pair (6.5 / 4.1 cm at 14 / 8 %) read as a fine light hatch. Tints for PALETTE SeatCloth / SeatBolster
    "SeatCloth":     [("box", "poly_wool_herringbone_diffuse_1k.jpg", 0.30, (0.112, 0.114, 0.122), 0.40),
                      ("stripes", 0.070, 0.38), ("stripes", 0.031, 0.06)],
    "SeatBolster":   [("box", "poly_wool_herringbone_diffuse_1k.jpg", 0.30, (0.116, 0.117, 0.123), 0.55)],
    "Plastique_noir": [("box", "fabric_leather_01_diffuse_1k.jpg",    0.12, (0.22, 0.22, 0.23), 0.60)],
    # noise amplitudes (2026-10-12): 12-25 % per texel at 40-160 /m was pixel-level speckle at 1.2-2.7
    # texels per screen pixel (GL_LINEAR, no mips); KI5's tyres and cladding are flat with drawn
    # detail. 4-8 % keeps a hint of grain without the shimmer.
    "Pneu":           [("noise", 90.0, 0.06)],
    "Jante":          [("noise", 160.0, 0.04)],
    "RimWell":        [("noise", 160.0, 0.04), ("attr", "rim_shade")],   # every RimWell face carries it
    "Body_plastique": [("noise", 25.0, 0.05)],
    "Dessous":        [("noise", 40.0, 0.08)],
    "Partie_noir":    [("noise", 120.0, 0.04)],
    "EngPlastic":     [("noise", 140.0, 0.10)],
    "EngIron":        [("noise", 90.0, 0.08)],
    "EngAlu":         [("noise", 120.0, 0.08)],
    "EngGrey":        [("noise", 60.0, 0.08)],
    "TrimDark":       [("box", "fabric_leather_01_diffuse_1k.jpg",    0.12, (0.22, 0.22, 0.23), 0.6)],   # soft-grained dark plastic: full grain read as a black speckled board, flat noise as a bare sheet
    # the headlamp as its clear lens shows it (tyre_paint.headlamp_map: the main bowl and bulb, the amber
    # turn bulb, the side lamp's flutes); it reaches the low lens now that lenses bake opaque, and
    # compose's lights_lit lights the same picture. Named axes only: lights_lit maps it too
    "Phare":          [("decal", "headlamp_lens.png", ("x", 0.442, 0.784, "abs"), ("z", 0.738, 0.894), "replace")],
    "Phare_vitre":    [("decal", "headlamp_lens.png", ("x", 0.442, 0.784, "abs"), ("z", 0.738, 0.894), "replace")],
    # the tail lamp lens (tyre_paint.tail_lens_map, its TAIL_* constants): one map over the whole lens in
    # the lens's own frame, u across it and v along its 28-degree lean, |x| so it serves both lamps. The
    # old tail_ribs.png mapped u by y: diagonal ribs crossing horizontal bars (screenshot 17.png, "the rear
    # lights are weird"), and a y range that missed most of the reverse lens (half of it black)
    "Feux_rouge":     [("decal", "tail_lens.png", ((0.658, 0.743, -0.118), -1.2005, -1.0405, "abs"),
                        ((-0.276, 0.384, 0.881), 0.085, 0.597, "abs"), "multiply")],
    "Feux_orange":    [("decal", "tail_lens.png", ((0.658, 0.743, -0.118), -1.2005, -1.0405, "abs"),
                        ((-0.276, 0.384, 0.881), 0.085, 0.597, "abs"), "multiply")],
    "Feux_blanc":     [("decal", "tail_lens.png", ((0.658, 0.743, -0.118), -1.2005, -1.0405, "abs"),
                        ((-0.276, 0.384, 0.881), 0.085, 0.597, "abs"), "multiply")],
}
# tyres (2026-10-12, feedback: "the tires, they need more textures", "the back tire also need more
# work"): KI5's wheels (Trooper, Touran, LC80, 256-512 px) draw a block tread strip and a sidewall
# with shoulder lugs, lettering and the rim protector; the procedural stripes this replaced read as
# a plain black ring. The painted maps (tyre_paint) wrap round whichever tyre the layer finds: the
# road wheel on its own sheet, and the spare on the gate, which rides the shell sheet and had no
# tyre layer at all
TYRE_LAYERS = [("noise", 90.0, 0.04), ("tyremap",)]
INBOARD_RGB = (0.040, 0.040, 0.042)  # linear: the wheel's inboard face (brake backing plate / rotor), sRGB ~56
ROTOR_HUB = (1.323, 0.342, 0.055)    # wheel_FR's axle (object y, z) and the half size of the dark hub centre (m)
TEXTURED_BY_SPACE = {                # extra layers that only make sense for one sheet
    "wheel": {"Pneu": TYRE_LAYERS,
              "HubCap": [("hubdecal", "hubcap.png", 0.105)],         # the disc covers the lug circle (r 0.105)
              # the hub centre behind the cap (a box round the axle, object y / z) keeps the old dark 0.025
              "Rotor": [("noise", 220.0, 0.10),
                        ("tint", (0.025, 0.025, 0.027), [("range", "y", ROTOR_HUB[0] - ROTOR_HUB[2], ROTOR_HUB[0] + ROTOR_HUB[2]),
                                                         ("range", "z", ROTOR_HUB[1] - ROTOR_HUB[2], ROTOR_HUB[1] + ROTOR_HUB[2])])],
              # the rim's inboard face (the twin's Jante facing -x behind the disc, projected onto the low wheel's
              # inboard RimWell disc) read as a pale plate from under the car (Wheel.png 137, polish round 2
              # R2-WA-6): the brake's backing plate and rotor are what shows there, dark steel
              "Jante": TEXTURED["Jante"] + [("tint", INBOARD_RGB, [("normal", "x", "<", -0.6), ("range", "x", 0.55, 0.70)])]},
    "shell": {"Pneu": TYRE_LAYERS,                                   # the spare on the tailgate
              # exterior trims (window frames, B-pillars, rubbers) are smooth black plastic: the
              # cabin's leather layer baked them at sRGB ~103 (paint pass review, 2026-10-12); an
              # empty stack bakes the PALETTE colour. The spare's centre cap (SPARE_HUB_LAYER) on every
              # material its hub can show
              "Plastique_noir": [("sparehub", "hubcap.png", 0.105)],
              # showroom clean (2026-10-13, the author): no baked noise on the shell's exterior plastics.
              # The bumpers' and cladding's grain is paint_pass's (GRAIN_*, smooth 3D noise sized for
              # the game's zoom); this 4 cm +-5 % noise under it read as mottling. Partie_noir's
              # 8 mm +-4 % was 2-3 texel speckle on the black trims
              "Body_plastique": [], "Partie_noir": [("sparehub", "hubcap.png", 0.105)],
              "Jante": TEXTURED["Jante"] + [("sparehub", "hubcap.png", 0.105)],
              "Chrome": [("sparehub", "hubcap.png", 0.105)],
              "Body": [("sparehub", "hubcap.png", 0.105)]},       # the twin's lug-nut tips are paint
    # the cargo bay seen with the gate open (2026-10-13, screenshot 34.png: plain dark carpet and plain
    # trim): cargo_bay_paint's maps, interior sheet only (the shell's projection twins carry Interieur /
    # Interieur_sol faces too). They REPLACE the colour at the PALETTE's own levels (a multiply map
    # could only darken a sRGB-48 carpet, and its detail never showed). The deck: the floor board's
    # gap, the tie-down anchors, the sill's scuff plate, the well's edge, gated to the deck's height
    # (the table well's floor stays plain). The side trims: speaker, storage recess, vent, the
    # wheelhouse line, a hook, one map for both walls (|x| symmetric), each wall gated by its facing.
    "interior": {
        "Interieur_sol": TEXTURED["Interieur_sol"] + [
            ("decal", cargo_bay_paint.FLOOR_PNG, ("x",) + cargo_bay_paint.FLOOR_X, ("y",) + cargo_bay_paint.FLOOR_Y, "replace",
             [("normal", "z", ">", 0.9), ("range", "z") + cargo_bay_paint.FLOOR_Z])],
        "Interieur": TEXTURED["Interieur"] + [
            ("decal", cargo_bay_paint.SIDE_PNG, ("y",) + cargo_bay_paint.SIDE_Y, ("z",) + cargo_bay_paint.SIDE_Z, "replace",
             [("normal", "x", ">", 0.6), ("range", "x", -cargo_bay_paint.SIDE_X[1], -cargo_bay_paint.SIDE_X[0])]),
            ("decal", cargo_bay_paint.SIDE_PNG, ("y",) + cargo_bay_paint.SIDE_Y, ("z",) + cargo_bay_paint.SIDE_Z, "replace",
             [("normal", "x", "<", -0.6), ("range", "x") + cargo_bay_paint.SIDE_X])],
    },
}
# UV scale per material before packing: decal lettering and the hub cap get more texels (the cap's H
# was ~10 px in v4 and read as a smudge in game); the painted inner sides of the panels get fewer
# (rarely seen, and they would otherwise double the shell's UV area).
UV_SCALE = {"HubCap": 4.0, "BodyInner": 0.5}
BAKE_PNG = os.path.join(ROOT, "blender", "bake")
_AXIS = {"x": "X", "y": "Y", "z": "Z"}


def _tyre_frame(objs, mat_name="Pneu"):
    """(centre, axle axis pointing out of the car, radial units u and v, bead radius, shoulder
    radius) of the tyre among objs: the object (or its full-detail twin, preferred: the rays shade
    the twin) with the most vertices on faces of mat_name; the axle is the direction of least
    spread, as prep_parts._wheel_frame takes it. Object space: every part sits at the identity, so
    it is also the space of the 'Object' texture coordinate on the low part and on its twin."""
    import numpy as np
    from mathutils import Vector
    best = None
    for ob in objs:
        for o in (bpy.data.objects.get(ob.name + "_hi"), ob):
            if o is None or o.type != 'MESH':
                continue
            ids = {i for i, m in enumerate(o.data.materials) if m and m.name == mat_name}
            if not ids:
                continue
            vids = {vi for p in o.data.polygons if p.material_index in ids for vi in p.vertices}
            if vids and (best is None or len(vids) > len(best[1])):
                best = (o, vids)
            break                                   # the twin if it has the tyre, else the low part
    if best is None:
        return None
    o, vids = best
    pts = np.array([tuple(o.data.vertices[i].co) for i in vids])
    c = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    _w, V = np.linalg.eigh(np.cov((pts - c).T))
    ax = Vector(V[:, 0]).normalized()
    if ax.dot(Vector(c) - Vector((0.0, 0.0, 0.8))) < 0:
        ax = -ax
    u = ax.orthogonal().normalized()
    v = ax.cross(u).normalized()
    d = pts - c
    t = d @ np.array(ax)
    r = np.linalg.norm(d - np.outer(t, np.array(ax)), axis=1)
    r_bead, r_crown = float(r.min()), float(r.max())
    r_sh = r_crown - (tyre_paint.R_CROWN - tyre_paint.R_SHOULDER)
    print("bake: tyre map on %s: centre (%.3f, %.3f, %.3f), axle (%.2f, %.2f, %.2f), bead r %.4f, shoulder r %.4f, crown r %.4f"
          % (o.name, c[0], c[1], c[2], ax.x, ax.y, ax.z, r_bead, r_sh, r_crown))
    return Vector(c), ax, u, v, r_bead, r_sh


class _Textured:
    """Temporarily drive Base Color of the TEXTURED materials through their layer stack (colour bake
    only); undone on exit. Node names carry the CRV_TX_ prefix."""

    def __init__(self, mats, objs=(), space=""):
        table = dict(TEXTURED)
        table.update(TEXTURED_BY_SPACE.get(space, {}))
        self.table = table
        self.mats = [m for m in mats if m.name in table]
        self.objs = list(objs)
        self.saved = {}

    def _new(self, nt, kind, name):
        n = nt.nodes.new(kind)
        n.name = "CRV_TX_" + name
        return n

    def _math(self, nt, op, a, b=None, c=None, name="m"):
        m = self._new(nt, 'ShaderNodeMath', name)
        m.operation = op
        for i, val in enumerate((a, b, c)):
            if val is None:
                continue
            if hasattr(val, "is_output"):
                nt.links.new(val, m.inputs[i])
            else:
                m.inputs[i].default_value = val
        return m.outputs[0]

    def _vmath(self, nt, op, a, b, name="vm"):
        """Vector math node on a socket and a socket or constant vector."""
        n = self._new(nt, 'ShaderNodeVectorMath', name)
        n.operation = op
        for i, val in enumerate((a, b)):
            if hasattr(val, "is_output"):
                nt.links.new(val, n.inputs[i])
            else:
                n.inputs[i].default_value = val
        return n

    def _mix(self, nt, a, b, fac=1.0, blend='MULTIPLY', name="mix"):
        mix = self._new(nt, 'ShaderNodeMix', name)
        mix.data_type = 'RGBA'; mix.blend_type = blend
        if hasattr(fac, "is_output"):
            nt.links.new(fac, mix.inputs['Factor'])
        else:
            mix.inputs['Factor'].default_value = fac
        for sock, val in ((6, a), (7, b)):
            if hasattr(val, "is_output"):
                nt.links.new(val, mix.inputs[sock])
            else:
                mix.inputs[sock].default_value = val
        return mix.outputs[2]

    def _gate(self, nt, gates, u_out, v_out, coord):
        """1 where the decal applies: inside its u/v range and through every gate:
        ("normal", axis, "<"|">", v) on the surface normal, ("range", axis, a, b) on object position."""
        mask = self._math(nt, 'MULTIPLY',
                          self._math(nt, 'MULTIPLY', self._math(nt, 'GREATER_THAN', u_out, 0.0), self._math(nt, 'LESS_THAN', u_out, 1.0)),
                          self._math(nt, 'MULTIPLY', self._math(nt, 'GREATER_THAN', v_out, 0.0), self._math(nt, 'LESS_THAN', v_out, 1.0)))
        if not gates:
            return mask
        if isinstance(gates[0], str):
            gates = [gates]
        for gate in gates:
            if gate[0] == "normal":
                _k, axis, op, value = gate
                geo = self._new(nt, 'ShaderNodeNewGeometry', "geo")
                sep = self._new(nt, 'ShaderNodeSeparateXYZ', "nsep")
                nt.links.new(geo.outputs['Normal'], sep.inputs['Vector'])
                term = self._math(nt, 'LESS_THAN' if op == "<" else 'GREATER_THAN', sep.outputs[_AXIS[axis]], value)
            else:
                _k, axis, a, b = gate
                sep = self._new(nt, 'ShaderNodeSeparateXYZ', "psep")
                nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
                term = self._math(nt, 'MULTIPLY', self._math(nt, 'GREATER_THAN', sep.outputs[_AXIS[axis]], a),
                                  self._math(nt, 'LESS_THAN', sep.outputs[_AXIS[axis]], b))
            mask = self._math(nt, 'MULTIPLY', mask, term)
        return mask

    def _apply(self, nt, coord, spec, prev, base, mat_name):
        kind = spec[0]
        if kind == "box":
            _k, jpg, tile, tint = spec[:4]
            flat = spec[4] if len(spec) > 4 else 0.0      # 0 = full grain contrast, 1 = flat tint
            path = os.path.join(POLYHAVEN, jpg)
            if not os.path.exists(path):
                print("bake: missing texture", path); return prev
            mapn = self._new(nt, 'ShaderNodeMapping', "map")
            mapn.inputs['Scale'].default_value = (1.0 / tile, 1.0 / tile, 1.0 / tile)
            tex = self._new(nt, 'ShaderNodeTexImage', "img")
            tex.image = bpy.data.images.load(path, check_existing=True)
            tex.projection = 'BOX'; tex.projection_blend = 0.3
            bw = self._new(nt, 'ShaderNodeRGBToBW', "bw")
            nt.links.new(coord.outputs['Object'], mapn.inputs['Vector'])
            nt.links.new(mapn.outputs['Vector'], tex.inputs['Vector'])
            nt.links.new(tex.outputs['Color'], bw.inputs['Color'])
            grain = bw.outputs['Val']
            if flat > 0.0:
                rng = self._new(nt, 'ShaderNodeMapRange', "flat")
                rng.inputs['To Min'].default_value = flat
                rng.inputs['To Max'].default_value = 1.0
                nt.links.new(bw.outputs['Val'], rng.inputs['Value'])
                grain = rng.outputs['Result']
            return self._mix(nt, grain, tuple(tint) + (1.0,))
        if kind == "noise":
            _k, scale, amount = spec
            noise = self._new(nt, 'ShaderNodeTexNoise', "noise")
            noise.inputs['Scale'].default_value = scale
            noise.inputs['Detail'].default_value = 4.0
            nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
            rng = self._new(nt, 'ShaderNodeMapRange', "range")
            rng.inputs['To Min'].default_value = 1.0 - amount
            rng.inputs['To Max'].default_value = 1.0 + amount
            nt.links.new(noise.outputs['Fac'], rng.inputs['Value'])
            return self._mix(nt, prev, rng.outputs['Result'])
        if kind == "tyremap":
            # the painted tyre (tyre_paint) wrapped round the tyre this material sits on in this
            # space: d = P - c in the tyre's frame, t along the axle (outward +), r from it, the angle
            # round it. Above the shoulder radius the tread map (u = angle, v = t), below it the
            # sidewall map (u = angle clockwise seen from that side, so the lettering reads over the
            # top on both faces; v = radius from the bead)
            frame = _tyre_frame(self.objs, mat_name)
            if frame is None:
                return prev
            c, ax, u, v, r_bead, r_sh = frame
            imgs = {}
            for key, png in (("tread", tyre_paint.TREAD_PNG), ("side", tyre_paint.SIDE_PNG)):
                path = os.path.join(BAKE_PNG, png)
                if not os.path.exists(path):
                    print("bake: missing tyre map", path); return prev
                tex = self._new(nt, 'ShaderNodeTexImage', "img")
                tex.image = bpy.data.images.load(path, check_existing=True)
                tex.image.colorspace_settings.name = 'Non-Color'
                tex.interpolation = 'Linear'
                tex.extension = 'REPEAT'
                imgs[key] = tex
            d = self._vmath(nt, 'SUBTRACT', coord.outputs['Object'], tuple(c)).outputs[0]
            t = self._vmath(nt, 'DOT_PRODUCT', d, tuple(ax)).outputs['Value']
            x = self._vmath(nt, 'DOT_PRODUCT', d, tuple(u)).outputs['Value']
            y = self._vmath(nt, 'DOT_PRODUCT', d, tuple(v)).outputs['Value']
            r = self._math(nt, 'SQRT', self._math(nt, 'ADD', self._math(nt, 'MULTIPLY', x, x), self._math(nt, 'MULTIPLY', y, y)))
            turn = self._math(nt, 'MULTIPLY', self._math(nt, 'ARCTAN2', y, x), 1.0 / (2.0 * math.pi))   # -0.5..0.5
            sgn = self._math(nt, 'MULTIPLY_ADD', self._math(nt, 'GREATER_THAN', t, 0.0), 2.0, -1.0)   # +1 outer face
            u_side = self._math(nt, 'SUBTRACT', 0.5, self._math(nt, 'MULTIPLY', turn, sgn))
            v_side = self._math(nt, 'MULTIPLY_ADD', r, 1.0 / (r_sh - r_bead), -r_bead / (r_sh - r_bead))
            v_side = self._math(nt, 'MINIMUM', self._math(nt, 'MAXIMUM', v_side, 0.004), 0.996)
            u_tread = self._math(nt, 'ADD', turn, 0.5)
            v_tread = self._math(nt, 'MULTIPLY_ADD', t, 0.5 / tyre_paint.TREAD_HALF, 0.5)
            v_tread = self._math(nt, 'MINIMUM', self._math(nt, 'MAXIMUM', v_tread, 0.003), 0.997)
            for key, uu, vv in (("tread", u_tread, v_tread), ("side", u_side, v_side)):
                comb = self._new(nt, 'ShaderNodeCombineXYZ', "comb")
                nt.links.new(uu, comb.inputs['X'])
                nt.links.new(vv, comb.inputs['Y'])
                nt.links.new(comb.outputs['Vector'], imgs[key].inputs['Vector'])
            on_tread = self._math(nt, 'GREATER_THAN', r, r_sh)
            side_m = imgs["side"].outputs['Color']
            f = self._math(nt, 'MULTIPLY_ADD', self._math(nt, 'SUBTRACT', imgs["tread"].outputs['Color'], side_m), on_tread, side_m)
            f = self._math(nt, 'MULTIPLY', f, tyre_paint.MAP_SCALE)
            return self._mix(nt, prev, f)
        if kind == "zmix":                                       # above a height (object z), mix to a flat colour
            _k, z0, z1, tint = spec[:4]                          # over z0..z1, x 1 +- amount noise (2 cm)
            amount = spec[4] if len(spec) > 4 else 0.0
            sep = self._new(nt, 'ShaderNodeSeparateXYZ', "zsep")
            nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
            rng = self._new(nt, 'ShaderNodeMapRange', "zrange")
            rng.clamp = True
            rng.inputs['From Min'].default_value = z0
            rng.inputs['From Max'].default_value = z1
            nt.links.new(sep.outputs['Z'], rng.inputs['Value'])
            col = tuple(tint) + (1.0,)
            if amount > 0.0:
                noise = self._new(nt, 'ShaderNodeTexNoise', "znoise")
                noise.inputs['Scale'].default_value = 50.0
                noise.inputs['Detail'].default_value = 2.0
                nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
                nr = self._new(nt, 'ShaderNodeMapRange', "znr")
                nr.inputs['To Min'].default_value = 1.0 - amount
                nr.inputs['To Max'].default_value = 1.0 + amount
                nt.links.new(noise.outputs['Fac'], nr.inputs['Value'])
                col = self._mix(nt, col, nr.outputs['Result'])
            return self._mix(nt, prev, col, fac=rng.outputs['Result'], blend='MIX')
        if kind == "sparehub":
            # the road wheels' centre cap (hubcap.png, mapped as "hubdecal" maps it on the wheel sheet) on the spare
            # on the gate (polish round 1, 2026-10-17: the projection put kotris's twin hub there, an H turned 90
            # degrees, dark, with two of five lug holes open). The spare's axle runs along y: u = +x (the viewer's
            # right from behind), v = +z, centred on the spare's rim, inside the road cap's own disc radius, on
            # every material a projection ray can meet there (SPARE_HUB_MATS)
            _k, png, r = spec[:3]
            hub = _spare_hub()
            path = os.path.join(BAKE_PNG, png)
            if hub is None or not os.path.exists(path):
                return prev
            cx, cz, y_out, r_disc = hub
            sep = self._new(nt, 'ShaderNodeSeparateXYZ', "hsep")
            nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
            comb = self._new(nt, 'ShaderNodeCombineXYZ', "hcomb")
            uu = self._math(nt, 'MULTIPLY_ADD', sep.outputs['X'], 1.0 / (2 * r), 0.5 - cx / (2 * r))
            vv = self._math(nt, 'MULTIPLY_ADD', sep.outputs['Z'], 1.0 / (2 * r), 0.5 - cz / (2 * r))
            nt.links.new(uu, comb.inputs['X'])
            nt.links.new(vv, comb.inputs['Y'])
            tex = self._new(nt, 'ShaderNodeTexImage', "img")
            tex.image = bpy.data.images.load(path, check_existing=True)
            tex.extension = 'EXTEND'
            nt.links.new(comb.outputs['Vector'], tex.inputs['Vector'])
            dx = self._math(nt, 'SUBTRACT', sep.outputs['X'], cx)
            dz = self._math(nt, 'SUBTRACT', sep.outputs['Z'], cz)
            rr = self._math(nt, 'SQRT', self._math(nt, 'ADD', self._math(nt, 'MULTIPLY', dx, dx), self._math(nt, 'MULTIPLY', dz, dz)))
            gate = self._math(nt, 'MULTIPLY', self._math(nt, 'LESS_THAN', rr, r_disc),
                              self._math(nt, 'LESS_THAN', sep.outputs['Y'], y_out + SPARE_HUB_DEPTH))
            return self._mix(nt, prev, tex.outputs['Color'], fac=gate, blend='MIX')
        if kind == "tint":                                       # a flat colour where the gates pass
            _k, rgb, gates = spec[:3]
            return self._mix(nt, prev, tuple(rgb) + (1.0,), fac=self._gate(nt, gates, 0.5, 0.5, coord), blend='MIX')
        if kind == "attr":                                       # x a float corner attribute (the rack cargo's
            _k, name = spec[:2]                                  # acc_shade): ONLY on materials whose every face
            node = self._new(nt, 'ShaderNodeAttribute', "attr")  # carries it (a missing attribute reads 0, black)
            node.attribute_type = 'GEOMETRY'
            node.attribute_name = name
            return self._mix(nt, prev, node.outputs['Fac'])
        if kind == "stripes":                                    # s = x + y + z: a diagonal on every seat plane
            _k, pitch, amount = spec
            sep = self._new(nt, 'ShaderNodeSeparateXYZ', "sep")
            nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
            s = self._math(nt, 'ADD', self._math(nt, 'ADD', sep.outputs['X'], sep.outputs['Y']), sep.outputs['Z'])
            on = self._math(nt, 'GREATER_THAN', self._math(nt, 'SINE', self._math(nt, 'MULTIPLY', s, 2.0 * math.pi / pitch)), 0.3)
            f = self._math(nt, 'MULTIPLY_ADD', on, 1.6 * amount, 1.0 - 0.6 * amount)      # 1 + amount / 1 - 0.6 amount
            return self._mix(nt, prev, f)
        if kind == "hubdecal":                                   # square decal centred on the object's hub
            _k, png, r = spec
            ob = next((o for o in self.objs if any(m and m.name == mat_name for m in o.data.materials)), None)
            path = os.path.join(BAKE_PNG, png)
            if ob is None or not os.path.exists(path):
                return prev
            ys = [v.co.y for v in ob.data.vertices]; zs = [v.co.z for v in ob.data.vertices]
            yc, zc = (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
            sep = self._new(nt, 'ShaderNodeSeparateXYZ', "sep")
            nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
            comb = self._new(nt, 'ShaderNodeCombineXYZ', "comb")
            nt.links.new(self._math(nt, 'MULTIPLY_ADD', sep.outputs['Y'], 1.0 / (2 * r), 0.5 - yc / (2 * r)), comb.inputs['X'])
            nt.links.new(self._math(nt, 'MULTIPLY_ADD', sep.outputs['Z'], 1.0 / (2 * r), 0.5 - zc / (2 * r)), comb.inputs['Y'])
            tex = self._new(nt, 'ShaderNodeTexImage', "img")
            tex.image = bpy.data.images.load(path, check_existing=True)
            tex.extension = 'EXTEND'
            nt.links.new(comb.outputs['Vector'], tex.inputs['Vector'])
            return tex.outputs['Color']
        if kind == "decal":
            png, u, v, mode = spec[1], spec[2], spec[3], spec[4]
            gate = spec[5] if len(spec) > 5 else None
            path = os.path.join(BAKE_PNG, png)
            if not os.path.exists(path):
                print("bake: missing decal", path); return prev
            sep = self._new(nt, 'ShaderNodeSeparateXYZ', "sep")
            nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
            comb = self._new(nt, 'ShaderNodeCombineXYZ', "comb")
            outs = {}
            for slot, ax in (("X", u), ("Y", v)):
                axis, a0, a1 = ax[0], ax[1], ax[2]
                mirror = len(ax) > 3 and ax[3] == "abs"
                if isinstance(axis, str):
                    src = sep.outputs[_AXIS[axis]]
                    if mirror:
                        src = self._math(nt, 'ABSOLUTE', src)
                else:                                        # a direction (dx, dy, dz): src = d . (x, y, z), with
                    xs = sep.outputs['X']                    # |x| when "abs" (one entry serves both sides)
                    if mirror:
                        xs = self._math(nt, 'ABSOLUTE', xs)
                    src = self._math(nt, 'MULTIPLY', xs, float(axis[0]))
                    src = self._math(nt, 'MULTIPLY_ADD', sep.outputs['Y'], float(axis[1]), src)
                    src = self._math(nt, 'MULTIPLY_ADD', sep.outputs['Z'], float(axis[2]), src)
                outs[slot] = self._math(nt, 'MULTIPLY_ADD', src, 1.0 / (a1 - a0), -a0 / (a1 - a0))
                nt.links.new(outs[slot], comb.inputs[slot])
            tex = self._new(nt, 'ShaderNodeTexImage', "img")
            tex.image = bpy.data.images.load(path, check_existing=True)
            tex.extension = 'EXTEND'
            nt.links.new(comb.outputs['Vector'], tex.inputs['Vector'])
            if mode == "over":                           # the map's colour over prev by its alpha (armour rust: lighter
                tex.image.alpha_mode = 'CHANNEL_PACKED'  # than dark steel); colour and alpha read independently
                layer = self._mix(nt, prev, tex.outputs['Color'], fac=tex.outputs['Alpha'], blend='MIX')
            else:
                layer = tex.outputs['Color'] if mode == "replace" else self._mix(nt, prev, tex.outputs['Color'])
            if gate is None:
                return layer
            return self._mix(nt, prev, layer, fac=self._gate(nt, gate, outs["X"], outs["Y"], coord), blend='MIX')
        return prev

    def __enter__(self):
        for m in self.mats:
            b = _bsdf(m)
            if b is None:
                continue
            nt = m.node_tree
            link = b.inputs['Base Color'].links[0].from_socket if b.inputs['Base Color'].links else None
            base = tuple(b.inputs['Base Color'].default_value)
            self.saved[m.name] = (link, base)
            coord = self._new(nt, 'ShaderNodeTexCoord', "coord")
            rgb = self._new(nt, 'ShaderNodeRGB', "rgb")
            rgb.outputs[0].default_value = base
            prev = rgb.outputs[0]
            for spec in self.table[m.name]:
                prev = self._apply(nt, coord, spec, prev, base, m.name)
            nt.links.new(prev, b.inputs['Base Color'])
        return self

    def __exit__(self, *exc):
        for m in self.mats:
            if m.name not in self.saved:
                continue
            b = _bsdf(m)
            nt = m.node_tree
            for node in [n for n in nt.nodes if n.name.startswith("CRV_TX_")]:
                nt.nodes.remove(node)
            link, default = self.saved[m.name]
            if link is not None:
                nt.links.new(link, b.inputs['Base Color'])
            b.inputs['Base Color'].default_value = default
        return False


CAVITY_DISTANCE = 0.04               # metres: reach of the cavity AO pass
# gap pass (2026-10-12): KI5's panel gaps are a 1-texel dark line with a lighter texel beside it;
# ours came only from the 4 cm cavity AO, a soft 2-3 cm gradient that compose's declutter then
# erased below 1.6 cm, so the car had no lines at all at the game's zoom. At 1.2 cm reach only the
# real shut lines, lamp recess edges and badge outlines occlude; compose thresholds it.
GAP_DISTANCE = 0.012
GAP_SAMPLES = 64                     # 32 -> 64 (2026-10-13): compose thresholds this pass into lines, noise beads them
# window seal (2026-10-12): KI5 draws 2-3 near-black texels (3-5 cm) round every pane. Ours is
# written straight into shell_rubber.png from the low pane outlines after the unwrap (see
# _rubber_map); compose paints that band RUBBER_RGB and matte.
RUBBER_WIDTH = 0.03                  # metres, inside the pane outline
AO_DISTANCE = 0.6
AO_SAMPLES = 128                     # v6: 48 left grain in the large flat charts xatlas makes; 96 -> 128 with the
                                     # anti-aliased bake (2026-10-13): with its 2x2 box, 512 rays a shipped texel
CAVITY_SAMPLES = 48                  # the 4 cm pass: 24 -> 48 (192 a shipped texel)
# CRV_FAST_BAKE=1 (scratch test builds only, never a shipped build): an eighth of the AO rays, for
# checking a layout, geometry or a feature's parts in minutes; the textures come out grainy
if os.environ.get("CRV_FAST_BAKE") == "1":
    GAP_SAMPLES, AO_SAMPLES, CAVITY_SAMPLES = 8, 16, 6
KEY =(1.0, 0.0, 1.0)                # background of every bake image = "no island here"
BAKE_NODE = "CRV_BAKE"
ZONE_ATTR = "zone"

# media/shaders/vehicle.frag colZone table (linear RGB). White = plain body.
ZONE = {
    "body": (1.0, 1.0, 1.0),
    "head": (1.0, 0.0, 0.0), "tail": (0.0, 1.0, 0.0),
    "door_fr": (0.0, 1.0, 1.0), "door_rr": (1.0, 1.0, 0.0), "door_fl": (1.0, 0.0, 1.0), "door_rl": (0.0, 0.0, 1.0),
    "window_fr": (0.0, 0.5, 0.5), "window_rr": (0.5, 0.5, 0.0), "window_fl": (0.5, 0.0, 0.5), "window_rl": (0.0, 0.0, 0.5),
    "window_t": (0.5, 0.0, 0.0), "window_h": (0.0, 0.5, 0.0),
    "guard_fr": (0.75, 0.0, 0.75), "guard_rr": (0.0, 0.0, 0.75), "guard_fl": (0.0, 0.75, 0.75), "guard_rl": (0.75, 0.75, 0.0),
    "roof": (0.0, 0.0, 0.0),
    "lights_rh": (0.25, 0.0, 0.0), "lights_lh": (0.75, 0.0, 0.0), "lights_rt": (0.0, 0.75, 0.0), "lights_lt": (0.0, 0.25, 0.0),
    "stop_r": (0.5, 0.25, 0.0), "stop_l": (0.5, 0.75, 0.0),
    "hood": (1.0, 0.0, 0.5), "boot": (0.0, 1.0, 0.5),
    # the combined stop / tail lens's stop part (bug wave 3, H-VP-1): its side's stop zone with blue 2/255, 0.0078
    # from the stop colour, so the game and Project Viewpoint (both match a zone within 0.01) light it as a stop
    # lamp, and the mod's shader (gen_shaders LAMP_RULE) tells it from the high stop lamp (plain stop_l). Never
    # baked (snap_zones would round it away): compose_textures.mark_combined_stop writes it on the shipped Mask
    "stop_rc": (0.5, 0.25, 0.0078431), "stop_lc": (0.5, 0.75, 0.0078431),
}
LAMP_MATS = {"Phare", "Phare_vitre", "Phare_orange", "Reflect_orange", "Feux_rouge", "Feux_orange", "Feux_stop",
             "Feux_blanc", "Reflect_red", "AccLens"}
TRIM_MATS = {"Interieur", "Interieur_sol", "Siege", "Siege_2", "TrimDark", "BodyInner"}   # trim baked on the shell sheet (cards sit behind the skin: AO ~0)
# the painted door / gate cards (door_cards, one material per card since v5, so the exact names above
# never matched them): their relief and shadows are painted, and the shut-pose AO printed the seats,
# a black pocket box and contact marks on them (x0.5-0.6 of the painted card; measured 2026-10-13)
TRIM_PREFIXES = ("DoorCard_",)
HEAD_LAMP_MATS = {"Phare", "Phare_vitre", "Phare_orange", "Reflect_orange"}
TAIL_LAMP_MATS = {"Feux_rouge", "Feux_orange", "Feux_blanc", "Reflect_red", "Feux_chrome"}
STOP_LAMP_MATS = {"Feux_stop"}
GLASS_MATS = {"Vitre", "Vitre_noir"}
ACC_PREFIX = "acc_"
# accessories (build_accessories.py): scuffed powder coat on the tube, bare plate elsewhere, the
# skid plate's slot decal (written by the builder into blender/bake)
TEXTURED["AccSteel"] = [("box", "metal_plate_02_diffuse_1k.jpg", 0.40, (0.085, 0.086, 0.090), 0.45), ("noise", 90.0, 0.10)]
TEXTURED["AccPlate"] = [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, (0.19, 0.19, 0.20), 0.35)]
TEXTURED["AccTable"] = [("box", "fabric_leather_01_diffuse_1k.jpg", 0.10, (0.22, 0.22, 0.225), 0.55)]   # grained grey plastic
# the table's top as it rides in the cargo floor (most of the floor the open-gate camera sees): the
# moulded lip, corner caps, hinge rivets and the CR-V plate (cargo_bay_paint.render_table), gated to the
# top face in the car
TEXTURED["AccTable"] = TEXTURED["AccTable"] + [
    ("decal", cargo_bay_paint.TABLE_PNG, ("x",) + cargo_bay_paint.TABLE_X, ("y",) + cargo_bay_paint.TABLE_Y, "multiply",
     [("normal", "z", ">", 0.9), ("range", "z") + cargo_bay_paint.TABLE_Z])]
TEXTURED["AccChrome"] = [("box", "metal_plate_02_diffuse_1k.jpg", 0.25, (0.50, 0.50, 0.53), 0.6)]        # the table legs
TEXTURED["AccSkid"] = [("box", "metal_plate_02_diffuse_1k.jpg", 0.30, (0.19, 0.19, 0.20), 0.35),
                       ("decal", "skidplate.png", ("x", -0.32, 0.32), ("z", 0.42, 0.60), "multiply")]
# roof rack cargo (build_accessories.build_rack_loads): olive canvas duffel, blue foam bedroll,
# charcoal tote and kit bag, mustard tote lid, black and orange webbing. Painted detail since
# 2026-10-13 (feedback: "better texture ... with more details"; the PolyHaven grain at a flat factor read
# as flat colour blocks in game): scripts/cargo_paint.py draws each material's top, side and front
# views in model metres (seams, zips, pockets, folds, ribs, label, handles, stacking pads, the roll's
# spiral, webbing edges, stitching, load labels) and gives these stacks: the views as replace decals
# gated by the face normal, at the levels the old tints landed (olive (86, 88, 54), blue (39, 63, 103),
# charcoal 82, mustard (188, 148, 42), orange (196, 92, 28)). Accessories are invisible to the bake's
# rays, so each stack ends in the cargo's own AO, the corner attribute build_accessories._shade writes
# (every face of these materials carries it).
import cargo_paint  # noqa: E402  (the floor height comes from the load objects, so after the .blend is loaded)
TEXTURED.update(cargo_paint.layers())       # AccCanvas, AccTarp, AccTote, AccLid, AccStrap
# the soft spare-tyre cover (build_accessories.build_spare_cover): black grained vinyl; its face
# carries tyre_paint's CR-V print, mapped by _cover_layers from the box the builder stores
TEXTURED["AccVinyl"] = [("box", "fabric_leather_01_diffuse_1k.jpg", 0.14, (0.050, 0.050, 0.052), 0.55), ("noise", 60.0, 0.05)]


# The high-mount stop lamp is one lamp on the centre line. Each of its faces took stop_r or stop_l by
# its own x, and the shader's zone test (bilinear Mask, matched within 0.01) fails along the boundary,
# so an unlit line ran down its middle while braking (round-1 lights, open issue 1). The whole lamp,
# the Feux_chrome cover kotris puts in front of the low one included (inside STOP_BOX, which no tail
# lamp reaches), takes one zone. BaseVehicle lights stop_l and stop_r together (textureLightsEnables2
# 5 and 9, from stoplightsOn and the battery alone), so either serves.
STOP_ZONE = "stop_l"
# The tail lamps' red lens is tail AND brake on the RD1 (one dual-filament bulb): its upper half takes the
# side's stop zone, its lower half the tail zone, so braking lights the cluster, not only the high stop lamp
# (until 2026-10-17 stop_r had no texel and the main lamps never lit on the brake), and with the lights on
# and braking the whole lens glows. Feux_rouge spans z 1.174..1.392 on each side (crv_kotris.blend).
# Bug wave 3 (H-VP-1, 2026-10-24): wave 1's lamp guard made the whole lens a tail zone (a tail / stop edge inside
# one UV island is no zone at every cap), so Project Viewpoint, which lights each zone from the game's own
# switches, lit only the high stop lamp on the brake in daylight. Now the two parts are their own islands, packed
# as one rigid group per side with the stop block planar_uv.GROUP_GAP away from the tail block (shell_tris:
# LENS_GROUPS), so no capped texel mixes them; the game lights the tail part with the lights and the stop part on
# the brake, and the mod's shader still glows the whole lens softly with the lights (compose marks the stop part
# stop_rc / stop_lc, gen_shaders LAMP_RULE).
TAIL_STOP_Z = 1.283
LENS_OBJECT = "body"                 # the D-pillar clusters (kotris's Feux_* faces) are body faces ...
LENS_Y = -1.0                        # ... behind this
LENS_GROUPS = {"lights_rt": (0, 1), "stop_r": (0, 2), "lights_lt": (1, 1), "stop_l": (1, 2)}   # zone -> (group, split)
STOP_BOX = (0.15, 1.45, -1.80)       # |x| below, z above, y below: kotris's lamp is |x| < 0.09, z 1.53-1.58, y -1.85..-1.89
FEATURE_ZONES = features.zones()     # feature meshes (acc_<feature>_*): the zone each dents and greys with


def _stop_lamp(mat_name, c):
    return mat_name in STOP_LAMP_MATS or (mat_name == "Feux_chrome" and abs(c.x) < STOP_BOX[0]
                                          and c.z > STOP_BOX[1] and c.y < STOP_BOX[2])


def zone_of(obj_name, mat_name, c):
    """Part zone for one face: object first, then lamp materials, then body regions by position."""
    side = "r" if c.x > 0 else "l"
    if obj_name in ("door_fl", "door_fr", "door_rl", "door_rr"):
        return obj_name
    if obj_name in ("window_fl", "window_fr", "window_rl", "window_rr"):
        return obj_name
    if obj_name == "hood":
        return "hood"
    if obj_name == "trunk":
        return "boot"
    if obj_name == "trunk_top":
        # the lift glass: only the pane is the rear window. Its painted header strip, rubber, wiper and backing
        # plates take the gate's zone (they dent and grey with TrunkDoor, BaseVehicle's "boot" part): as window_t
        # Project Viewpoint drew ~19k painted texels as 40 % glass (polish round 2, R2-VP-1)
        if _stop_lamp(mat_name, c):
            return STOP_ZONE
        return "window_t" if mat_name in GLASS_MATS else "boot"
    if obj_name in ("engine_block", "arch_liners", "antenna", "bay_walls"):
        return "body"
    if obj_name.startswith("acc_"):                          # accessories: dent with what they guard
        if mat_name == "AccLens":                            # lamp lenses light with the headlamp of their side
            return "lights_" + side + "h"
        z = {"acc_bullbar": "head", "acc_roofrack": "roof", "acc_guard_fl": "door_fl", "acc_guard_fr": "door_fr",
             "acc_guard_rl": "door_rl", "acc_guard_rr": "door_rr",
             "acc_rack_load1": "roof", "acc_rack_load2": "roof", "acc_rack_load3": "roof",
             "acc_spare_cover": "boot"}.get(obj_name, FEATURE_ZONES.get(obj_name, "body"))
        if z == "panel":                                     # a feature mesh lying on the body's paint (the decals):
            return zone_of("body", "Body", c)                # the zone of the body panel under each face
        return z
    # body
    if _stop_lamp(mat_name, c):
        return STOP_ZONE
    if mat_name in HEAD_LAMP_MATS and c.y > 1.0:
        return "lights_" + side + "h"
    # ... and kotris's Feux_chrome covers over the upper lens with it: in the tail zone their lit cover texels (compose
    # LIGHT_COVER_MATS) glowed as tail specks at z 1.44 above the braking half (polish round 2, R2-VP-8)
    if mat_name in ("Feux_rouge", "Feux_chrome") and c.y < -1.0 and c.z > TAIL_STOP_Z:
        return "stop_" + side
    if mat_name in TAIL_LAMP_MATS and c.y < -1.0:
        return "lights_" + side + "t"
    if mat_name in GLASS_MATS:
        # the fixed rear quarter windows are no game part: in the body zone Project Viewpoint drew them as solid
        # black panels beside see-through windows (R2-VP-2). They take the rear glass's zone (decided by the
        # integrator, 2026-10-17): they also vanish with the rear glass if it is removed or broken
        return "window_h" if c.y > 0.0 else "window_t"
    if c.z > 1.58:
        return "roof"
    if c.y > 1.60:
        return "head"                                        # bumper, grille, valance
    if c.y < -1.70:
        return "tail"
    if abs(c.x) > 0.55 and 0.40 < c.z < 1.20:
        if c.y > 0.79:
            return "guard_f" + side                          # front fenders
        if c.y < -1.22:
            return "guard_r" + side                          # rear quarters
    return "body"


def _args():
    """--out DIR (bake images), --save FILE (the unwrapped .blend), --spaces a,b (default: all four),
    --decals DIR (where the hand/procedurally painted decal PNGs are read from; default --out, which
    in the normal build is blender/bake where prep_parts and paint_engine_decals write them)."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = os.path.join(ROOT, "blender", "bake")
    save = os.path.join(ROOT, "blender", "crv_kotris.blend")
    spaces = list(SPACES)
    decals = None
    for i, a in enumerate(argv):
        if a == "--out":
            out = argv[i + 1]
        if a == "--save":
            save = argv[i + 1]
        if a == "--spaces":
            spaces = [s for s in argv[i + 1].split(",") if s in SPACES]
        if a == "--decals":
            decals = argv[i + 1]
    return out, save, spaces, decals or out


def _objects(names):
    return [bpy.data.objects[n] for n in names if n in bpy.data.objects]


def _select(objs):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs:
        ob.hide_set(False)
        ob.hide_viewport = False
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


# v6 atlas: xatlas charts (tools/pylib, pip-installed for Blender's Python) with a texel-density
# weight per face, so the sheet goes where the game camera looks. Smart UV Project spent ~1/6 of the
# shell sheet on the underbody and scattered thousands of slivers; about half the sheet was empty.
PYLIB = os.path.join(ROOT, "tools", "pylib")
if not os.path.isdir(PYLIB):                 # a scratch CRV_ROOT without tools/: the main checkout's (read only)
    PYLIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_")))), "tools", "pylib")
# padding 8 / margin 4 on the 2048 sheet left 75-79 % of it to padding and margin round ~9.5k
# charts (face coverage 21-24 %); at 1024 the same texel counts are 4 / 2 (2026-10-12)
ATLAS_PADDING = 4                    # px between charts; the bake margin stays under half of it
# per sheet (polish round 1, 2026-10-17): the 512 engine sheet was 40 % faces under 970 charts with 4 px each, a
# padding tuned for the 2048 shell. It is one object baked in one pass (its margin fills only texels no face
# owns) and composed with the nearest-texel fill, and it loads unhalved at the default 512 cap: 1 px (+ xatlas's
# bilinear texel round every chart)
ATLAS_PADDING_SPACE = {"engine": 1}
BAKE_MARGIN = 2
# planar shell (spec/planar-texture-plan.md A6): margin 0. Islands of different objects sit a
# padding apart, and a later object's margin overwrites an earlier one's edge texels (Blender 4.5:
# EXTEND overwrites, ADJACENT_FACES blends 50/50), which turned ~430 Mask texels into foreign zones
# in the v1 model, some into window zones the shader discards when that window is down. compose's
# Dilate fills every uncovered texel from its nearest covered one instead.
SPACE_MARGIN = {"shell": 0, "engine": 1}
_margin = [BAKE_MARGIN]              # the margin of the space being baked (bake_space sets it)
TEXEL_WEIGHT_MAT = {                 # texel density relative to the paint
    "SeamBack": 0.15,                # backing plates and gutter strips behind seams: a crack's width of them ever shows
    "Dessous": 0.15, "BodyInner": 0.35, "Rotor": 0.6, "HubCap": 4.0, "ArchLiner": 0.25,
    "Vitre": 0.5, "Vitre_noir": 0.5, "Plastique_noir": 0.8, "Partie_noir": 0.8, "Body_plastique": 0.9,
    "Phare": 2.0, "Phare_vitre": 2.0, "Phare_orange": 2.0, "Reflect_orange": 2.0, "Feux_rouge": 2.0,
    "Feux_orange": 2.0, "Feux_stop": 2.0, "Feux_blanc": 2.0, "Reflect_red": 2.0, "Feux_chrome": 1.2,
    "Chrome": 2.0, "Interieur": 0.7, "Interieur_sol": 0.5, "Siege": 0.8, "Siege_2": 0.8,
    "AccSteel": 0.5, "AccPlate": 0.6, "AccSkid": 0.9, "AccLens": 1.2, "AccTable": 0.8, "AccChrome": 0.6,
    "AccCanvas": 0.5, "AccTarp": 0.5, "AccStrap": 0.5,   # rack cargo: soft shapes and webbing, seen at roof distance;
    "AccTote": 1.0, "AccLid": 1.0,                       # the tote's lip, rim and latches want paint density
    "AccVinyl": 1.0,                           # spare cover: the CR-V print's strokes are >= 1.2 cm
    # build_cabin. The interior sheet measured 1.2 texels/cm at weight 1 on 1024 (34 m2): the dash face's
    # painted vents, glovebox line and switches are >= 1 cm, so CabDash gets 2.0 (2.4 texels/cm)
    "CabDark": 1.0, "CabDash": 2.0, "SeatCloth": 1.0, "SeatBolster": 0.8,
}
TEXEL_WEIGHT_GEN = {1: 0.35, 2: 0.2, 3: 0.25, 4: 0.6, 5: 0.6, 6: 4.0,   # generated faces (prep_parts)
                    7: 1.0}          # exterior details (build_details): the 2.6 cm grip, 7 mm flap seam and mirror rim at paint density
RIM_GEN = 8                          # the windowed alloy (prep_parts._rim_face): weight by material, x2 on the spare
RIM_WEIGHT = {"Jante": 1.0, "RimWell": 0.5, "Rotor": 0.25}   # walls 5 cm deep: ~5 texels for their shade ramp
TEXEL_WEIGHT_OBJ = {"arch_liners": 0.25, "bay_walls": 0.35, "antenna": 0.4}
TEXEL_WEIGHT_OBJ.update(features.texel_weights())     # feature meshes on a sheet other than the shell
TEXEL_WEIGHT_MAT.update(features.bake_mat_weights())  # feature materials
DECAL_WEIGHT = 3.0
# decals mostly out of sight (engine bay v2, 2026-10-17): the radiator's fin faces sit behind the black top
# tank and the header and took ~1/6 of the engine sheet at 3x; the tie bar and the air box's front band
# are thin strips seen edge-on
DECAL_WEIGHT_MAT = {"DecalRadFins": 0.5, "DecalTieBar": 1.5, "DecalIntakeAirboxFront": 1.5}
# exact decal weights, not snapped to WEIGHT_LEVELS (their own chart group): the cam cover's front band carries
# "HONDA MOTOR CO." in ~1.5 cm letters, ~4 texels tall at the snapped 4 (polish round 1, 2026-10-17)
DECAL_WEIGHT_EXACT = {"DecalCoverFront": 6.0}
# the instrument cluster's face (build_cabin.paint_cluster), exact, its own chart group: 7.2 texels/cm, the speedometer's
# 7.5 mm numerals ~5.4 texels tall (2026-10-20, the owner: "the speedo legend should stay readable"); ~3 % of the sheet
CLUSTER_WEIGHT = 6.0
# every weight is snapped to one of these (nearest in log2) before the xatlas pass: each distinct
# weight is its own mesh group for xatlas, and 17 groups per object fragmented the sheet into
# ~9.5k charts whose padding ate three quarters of it (2026-10-12)
WEIGHT_LEVELS = (0.25, 0.5, 1.0, 2.0, 4.0)
DOOR_CARD_WEIGHT = 2.0               # painted door cards: seen up close with the door open
SPARE_MATS = ("Pneu", "Jante")       # the spare tyre and its rim on the trunk (prep_parts.LATHE_SUB)
SPARE_WEIGHT = 2.0
# the spare's TYRE faces that look out (2026-10-13 texture fix): at weight 2 they shipped at 2.81 texels/cm
# against the road tyres' ~3.8-4.25 on their 512 wheel sheet, so the painted tread and sidewall
# lettering read coarser on the gate than on the road wheels. 3.0 puts them at ~4.2 (fallback 1.385 x 3)
# for +52k texels (+1.2 % of the 2048 sheet); the rim (Jante 2.75, the road rim's 2.73) and the hidden
# side stay. Exact, not snapped to WEIGHT_LEVELS (3 would snap to 4: +125k texels, the panels toward 2.6)
SPARE_TYRE_WEIGHT = 3.0
# the spare's centre cap (the "sparehub" layer, polish round 1): the road wheels' hubcap.png on the spare's hub
# disc (radius of the road wheel's HubCap disc), faces within SPARE_HUB_DEPTH of the rim's outer face.
# SPARE_HUB_WEIGHT (0: the faces keep their spare weights) gives the hub's low faces of SPARE_HUB_WEIGHT_MATS their
# own texel weight. The rim's Jante faces stay at the spare's 2 (at 4 for the whole disc the planar pack shifted
# and one panel island starved, layout gate 2026-10-17); the 7 cm centre insert (Plastique_noir) carries the cap's
# H and was ~8 texels across at its weight 1: at the road cap's 4.0
SPARE_HUB_DEPTH = 0.08
SPARE_HUB_WEIGHT = 4.0
SPARE_HUB_WEIGHT_MATS = ("Plastique_noir",)
_SPARE_HUB = []


def _spare_hub():
    """(centre x, centre z, the rim's outermost y, cap disc radius) of the spare on the trunk, object space (the trunk
    sits at the identity); the disc radius is the road wheel's HubCap disc (wheel_FR, 0.07 without it). None
    without a spare."""
    if _SPARE_HUB:
        return _SPARE_HUB[0]
    hub = None
    ob = bpy.data.objects.get("trunk")
    if ob is not None and ob.type == 'MESH':
        names = [m.name if m else "?" for m in ob.data.materials]
        vs = [ob.data.vertices[v].co for p in ob.data.polygons if names and names[p.material_index] == "Jante" for v in p.vertices]
        if vs:
            xs, ys, zs = [v.x for v in vs], [v.y for v in vs], [v.z for v in vs]
            r_disc = 0.07
            wh = bpy.data.objects.get("wheel_FR")
            if wh is not None and wh.type == 'MESH':
                wn = [m.name if m else "?" for m in wh.data.materials]
                cv = [wh.data.vertices[v].co for p in wh.data.polygons if wn and wn[p.material_index] == "HubCap" for v in p.vertices]
                if cv:
                    yc = (min(v.y for v in cv) + max(v.y for v in cv)) / 2
                    zc = (min(v.z for v in cv) + max(v.z for v in cv)) / 2
                    r_disc = max(((v.y - yc) ** 2 + (v.z - zc) ** 2) ** 0.5 for v in cv)
            hub = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2, min(ys), r_disc)
            print("bake: spare hub cap at x %.4f z %.4f, rim face y %.4f, disc r %.4f" % hub)
    _SPARE_HUB.append(hub)
    return hub
# planar shell (spec/planar-texture-plan.md A3.5): only the fallback charts use weights now, at
# planar_uv.FALLBACK_TPC (1.5 texels/cm) against the panels' 3.0
SHELL_DETAIL_WEIGHT = 2.0            # gen 7 handles, mirrors, flap, wipers sit on panels at planar density
SHELL_MAT_WEIGHT = {"DecalHoodPad": 1.0}   # was 4 (DECAL_WEIGHT): 281 kpx for the hood's underside pad
SHELL_OBJ_WEIGHT = {"acc_table": 2.0,      # its dropped world item samples this sheet under the 256 Texture Size default
                    "bay_walls": 0.25, "arch_liners": 0.25}
SHELL_OBJ_WEIGHT.update(features.shell_weights())     # feature meshes on the shell (OBJECTS weight)
SHELL_RACK_LOAD_WEIGHT = 0.5         # acc_rack_load1-3 built before 2026-10-13 (no per-face weights)
# acc_rack_load1-3 since 2026-10-13: per face, the FLOAT face attribute build_accessories._texel_weights
# writes from what the game camera can see of it (cargo_paint.TEXEL_W_SEEN = 1 where seen: the painted
# cargo detail at ~1.4 texels/cm; 0.5 seen edge-on; 0.25 never seen. Weight 2 measured: the pack
# fell from scale 0.94 to 0.83, every panel 2.83 -> 2.51 texels/cm)
RACK_LOAD_WEIGHT_ATTR = "texel_w"
TEXEL_ATTR_OBJECTS = features.texel_attr_objects()   # feature meshes whose builder wrote texel_w per face (OBJECTS texel_w)


def _door_card_layers():
    """The door cards' painted textures (door_cards.paint), mapped by object y / z over each card's
    bounding box (custom property card_bbox, written by prep_parts)."""
    for ob in bpy.data.objects:
        bb = ob.get("card_bbox") if ob.type == 'MESH' else None
        if bb is None:
            continue
        a0, a1, z0, z1 = list(bb)
        axis = ob.get("card_axis", "y")          # doors: panel in the y/z plane; tailgate: x/z
        TEXTURED["DoorCard_" + ob.name] = [("decal", "doorcard_%s.png" % ob.name, (axis, a0, a1), ("z", z0, z1), "replace"),
                                           ("noise", 150.0, 0.04)]


def _cover_layers():
    """The spare cover's face print (tyre_paint.cover_map), mapped by object x / z over the box the
    builder stored (custom property decal_box on acc_spare_cover: x0, x1, z0, z1), on the faces that
    look back from the car; grain and noise as AccVinyl's."""
    ob = bpy.data.objects.get("acc_spare_cover")
    bb = ob.get("decal_box") if ob is not None else None
    if bb is None:
        return
    x0, x1, z0, z1 = list(bb)
    base = [layer for layer in TEXTURED["AccVinyl"] if layer[0] != "decal"]
    TEXTURED["AccVinyl"] = base[:1] + [("decal", tyre_paint.COVER_PNG, ("x", x0, x1), ("z", z0, z1), "replace",
                                        [("normal", "y", "<", -0.75)])] + base[1:]


def _quantise_weight(w):
    """Nearest WEIGHT_LEVELS entry in log2 (0.35 -> 0.25, 0.7 -> 0.5, 1.3 -> 1.0, 1.6 -> 2.0, 3.0 -> 4.0)."""
    k = int(round(math.log2(max(w, 1e-6))))
    k = max(-2, min(2, k))
    return 2.0 ** k


def _face_weights(ob, space):
    me = ob.data
    names = [m.name if m else "?" for m in me.materials]
    gen = [0] * len(me.polygons)
    attr = me.attributes.get("gen")
    if attr is not None:
        attr.data.foreach_get("value", gen)
    out = []
    hub = _spare_hub() if space == "shell" and ob.name == "trunk" else None
    shell_obj = SHELL_OBJ_WEIGHT.get(ob.name) if space == "shell" else None
    rack_w = None
    if (space == "shell" and ob.name.startswith("acc_rack_load")) or ob.name in TEXEL_ATTR_OBJECTS:
        tw = me.attributes.get(RACK_LOAD_WEIGHT_ATTR)
        if tw is not None and tw.domain == 'FACE' and tw.data_type == 'FLOAT':
            rack_w = [0.0] * len(me.polygons)
            tw.data.foreach_get("value", rack_w)
        elif ob.name in TEXEL_ATTR_OBJECTS:
            raise RuntimeError("bake: %s declares texel_w (scripts/features) but carries no FLOAT face attribute %s"
                               % (ob.name, RACK_LOAD_WEIGHT_ATTR))
        else:
            shell_obj = SHELL_RACK_LOAD_WEIGHT
    for p in me.polygons:
        mat = names[p.material_index] if names else "?"
        if rack_w is not None:
            w = rack_w[p.index]
            if space == "shell" and w <= 0:
                out.append(0.0)                          # texel_w 0: a swatch cell, no chart (planar_uv.classify)
                continue
        elif shell_obj is not None:
            w = shell_obj
        elif space == "shell" and mat in SHELL_MAT_WEIGHT:
            w = SHELL_MAT_WEIGHT[mat]
        elif space == "shell" and gen[p.index] == 7:
            w = SHELL_DETAIL_WEIGHT
        elif mat.startswith("DoorCard_"):
            w = DOOR_CARD_WEIGHT                         # painted door card (gen 5, but seen up close)
        elif gen[p.index] == RIM_GEN:
            w = RIM_WEIGHT.get(mat, 0.5) * (SPARE_WEIGHT if space == "shell" else 1.0)
        elif gen[p.index]:
            w = TEXEL_WEIGHT_GEN.get(gen[p.index], 0.3)
        elif ob.name in TEXEL_WEIGHT_OBJ:
            w = TEXEL_WEIGHT_OBJ[ob.name]
        elif mat in DECAL_WEIGHT_EXACT:
            out.append(DECAL_WEIGHT_EXACT[mat])
            continue
        elif mat in DECAL_WEIGHT_MAT:
            w = DECAL_WEIGHT_MAT[mat]
        elif mat.startswith("Decal"):
            w = DECAL_WEIGHT
        elif (ob.name == "cabin" and p.normal.y < -0.5 and -0.59 < p.center.x < -0.21 and 1.02 < p.center.z < 1.18
              and p.center.y > 0.47):
            out.append(CLUSTER_WEIGHT)   # exact: the cluster face (2026-10-20: its numerals were ~5 texels tall at 4)
            continue
        elif ob.name == "cabin" and p.normal.y < -0.5 and (
                (-0.14 < p.center.x < 0.14 and 0.72 < p.center.z < 1.20 and p.center.y < 0.58)
                or (-0.61 < p.center.x < -0.17 and 0.82 < p.center.z < 1.24 and 0.30 < p.center.y < 0.47)):
            w = 3.0          # the centre stack (y < 0.58: not the dash face hidden behind it) and the steering wheel's
                             # driver-facing faces (cabin_wheel.png: badge, horn pads, grips; y 0.30-0.47: not the seat
                             # backs, not the cluster) carry painted detail; at 1x the H lost its crossbar (1.2
                             # texels/cm at 1024). 2026-10-20: the whole wheel, not only the pad (one density for the decal)
        elif ob.name == "acc_spare_cover" and p.normal.y < -0.75:
            w = SPARE_WEIGHT                             # the cover's face carries the CR-V print
        elif (SPARE_HUB_WEIGHT and space == "shell" and ob.name == "trunk" and hub is not None and mat in SPARE_HUB_WEIGHT_MATS
              and p.normal.y < -0.5
              and p.center.y < hub[2] + SPARE_HUB_DEPTH and ((p.center.x - hub[0]) ** 2 + (p.center.z - hub[1]) ** 2) ** 0.5 < hub[3] + 0.01):
            out.append(SPARE_HUB_WEIGHT)                 # the spare's centre cap (sparehub layer)
            continue
        elif space == "shell" and ob.name == "trunk" and mat in SPARE_MATS:
            # the spare on the gate at the road wheel's density (wheel sheet ~2.2 texels/cm): at the
            # shell's 1.2 its 11 mm tread grooves were one texel. Its face against the gate: hidden
            if mat == "Pneu" and p.normal.y < 0.5:
                out.append(SPARE_TYRE_WEIGHT)            # exact (see SPARE_TYRE_WEIGHT): its own chart group
                continue
            w = SPARE_WEIGHT if p.normal.y < 0.5 else 0.5
        else:
            w = TEXEL_WEIGHT_MAT.get(mat, 1.0)
            if p.normal.z < -0.6 and p.center.z < 0.55 and space in ("shell", "interior"):
                w = min(w, 0.2)                          # undersides: only seen lying on the ground
            if space == "wheel" and p.normal.x * (1 if p.center.x > 0 else -1) < -0.5:
                w = min(w, 0.4)                          # the wheel's back face, towards the car
        out.append(_quantise_weight(w))
    return out


def _triangulate(objs):
    for ob in objs:
        if all(len(p.vertices) == 3 for p in ob.data.polygons):
            continue
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3], quad_method='BEAUTY', ngon_method='BEAUTY')
        bm.to_mesh(ob.data)
        bm.free()


def _python_exe():
    """Blender's bundled interpreter (same ABI as tools/pylib), run as a separate process."""
    cand = [sys.executable,
            os.path.join(os.path.dirname(bpy.app.binary_path), "%d.%d" % bpy.app.version[:2], "python", "bin", "python.exe")]
    for c in cand:
        if c and os.path.basename(c).lower().startswith("python") and os.path.exists(c):
            return c
    raise ImportError("no python executable found for the xatlas job")


def _xatlas_job(payload):
    """scripts/xatlas_job.py in its own process (inside blender.exe xatlas crashes on Blender's older
    MSVCP140): payload dict in, dict of arrays out."""
    import planar_uv
    return planar_uv.run_xatlas_job(payload, _python_exe(), os.path.join(HERE, "xatlas_job.py"), PYLIB)


def _xatlas_pass(objs, size, space, weights):
    """One xatlas layout (xatlas_job's atlas mode). weights(ob) -> per-face texel weight list.
    Returns {object name: [(u, v) per loop]}."""
    import numpy as np
    groups = []
    for ob in objs:
        me = ob.data
        ws = weights(ob)
        by_w = {}
        for p in me.polygons:
            by_w.setdefault(ws[p.index], []).append(p.index)
        for w, fids in sorted(by_w.items()):
            vids = sorted({v for f in fids for v in me.polygons[f].vertices})
            local = {v: i for i, v in enumerate(vids)}
            pos = np.array([tuple(me.vertices[v].co * w) for v in vids], dtype=np.float32)
            ind = np.array([[local[v] for v in me.polygons[f].vertices] for f in fids], dtype=np.uint32)
            groups.append((ob, fids, ind, pos))
    payload = {"size": size, "padding": ATLAS_PADDING_SPACE.get(space.split(" ")[0], ATLAS_PADDING), "n": len(groups)}
    for k, g in enumerate(groups):
        payload["pos%d" % k] = g[3]
        payload["ind%d" % k] = g[2]
    res = _xatlas_job(payload)
    # "faces" is the true share of the sheet under triangles; xatlas's utilization also counts the
    # padding and bilinear margin round every chart (76 % utilization was 21 % faces on v6's shell)
    print("bake: %s xatlas %d charts, %d page(s), utilization %.0f%%, faces %.0f%% of sheet, %.2f texels/cm at weight 1"
          % (space, int(res["charts"]), int(res["pages"]), 100.0 * float(res["util"]),
             100.0 * float(res["faces"]) if "faces" in res else 0.0, float(res["tpu"]) / 100.0))
    if int(res["pages"]) != 1:
        raise RuntimeError("xatlas could not fit %s on one page" % space)
    out_uv = {ob.name: [None] * len(ob.data.loops) for ob in objs}
    bad = 0
    for k, (ob, fids, ind, _pos) in enumerate(groups):
        vmap, out, uvs = res["vmap%d" % k], res["ind%d" % k], res["uv%d" % k]
        me = ob.data
        dst_uv = out_uv[ob.name]
        for j, f in enumerate(fids):
            poly = me.polygons[f]
            srcv = list(ind[j])
            for c, li in enumerate(poly.loop_indices):
                cc = c
                if vmap[out[j][c]] != srcv[c]:                # xatlas may rotate a triangle's corners
                    cc = next((x for x in range(3) if vmap[out[j][x]] == srcv[c]), c)
                    bad += cc == c
                u, v = uvs[out[j][cc]]
                dst_uv[li] = (float(u), float(v))
    if bad:
        print("bake: warning %d corners could not be matched to xatlas output" % bad)
    return out_uv


def _check_xatlas():
    if not os.path.exists(os.path.join(PYLIB, "xatlas") + ".cp311-win_amd64.pyd") and not any(
            f.startswith("xatlas") and f.endswith(".pyd") for f in (os.listdir(PYLIB) if os.path.isdir(PYLIB) else [])):
        raise ImportError("xatlas is not installed in " + PYLIB)


def _write_uvs(ob, flat0, flat1):
    """UVMap (layer 0, the bake) and UVMap1 (texCoords1), flat [u, v, u, v, ...] per loop."""
    me = ob.data
    while len(me.uv_layers) > 1:                      # keep layer 0: removing every layer left the
        me.uv_layers.remove(me.uv_layers[-1])         # render-UV pointer dangling (bake crashed in
    if not me.uv_layers:                              # the tangent pass)
        me.uv_layers.new(name="UVMap")
    me.uv_layers[0].name = "UVMap"
    me.uv_layers.new(name="UVMap1")                   # texCoords1: rust / damage / blood
    # look both up AFTER the second exists: adding a layer reallocates them, and writing through a
    # wrapper taken before that corrupted memory (Cycles crashed syncing the mesh)
    uv0, uv1 = me.uv_layers["UVMap"], me.uv_layers["UVMap1"]
    uv0.data.foreach_set("uv", flat0)
    uv1.data.foreach_set("uv", flat1)
    me.uv_layers.active = me.uv_layers["UVMap"]
    me.uv_layers["UVMap"].active_render = True
    me["uv_baked"] = 1


def _flat(per_loop):
    return [c for uv in per_loop for c in (uv if uv is not None else (0.0, 0.0))]


def unwrap_xatlas(objs, size, space):
    """UVMap: xatlas charts with texel density weighted per face (the bake). UVMap1 (texCoords1:
    rust, damage, blood): a second, EVEN layout; copying the weighted one made rust and dents 6x
    coarser on the underbody than on the doors."""
    _check_xatlas()
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    _triangulate(objs)                    # one UV per corner needs whole triangles in one chart
    main_uv = _xatlas_pass(objs, size, space, lambda ob: _face_weights(ob, space))
    even_uv = _xatlas_pass(objs, size, space + " (even, texCoords1)", lambda ob: [1.0] * len(ob.data.polygons))
    for ob in objs:
        _write_uvs(ob, _flat(main_uv[ob.name]), _flat(even_uv[ob.name]))


# The planar shell (spec/planar-texture-plan.md, Part A; scripts/planar_uv.py): every kotris panel
# one island projected along its own mean normal, the rest xatlas charts, all packed by xatlas in
# one call. UVMap1 stays the EVEN xatlas layout at the sheet size it had (the Rust map is 1024).
PLANAR_SPACES = ("shell",)
EVEN_SIZE = {"shell": 1024}
ISLAND_ATTR = "uv_island"             # INT face attribute: island id; -1 fallback, -2 dark, -3 swatch


def shell_tris(objs, space="shell"):
    """Every triangle of the (triangulated) parts as planar_uv.unwrap wants it, plus the loop index
    of each corner ((T, 3), per object) for writing the UVs back."""
    import numpy as np
    from mathutils import Vector
    zone_names = list(ZONE)
    mat_names = []
    cols = {k: [] for k in ("pos", "obj", "mat", "gen", "zone", "w", "group", "split", "loops")}
    for oi, ob in enumerate(objs):
        me = ob.data
        nv, npoly = len(me.vertices), len(me.polygons)
        co = np.empty(nv * 3, dtype=np.float32)              # foreach_get buffers in the properties' own types
        me.vertices.foreach_get("co", co)
        m = np.array(ob.matrix_world)
        co = co.reshape(-1, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
        total = np.empty(npoly, dtype=np.int32)
        me.polygons.foreach_get("loop_total", total)
        if npoly and total.max() != 3:
            raise RuntimeError("%s is not triangulated" % ob.name)
        start = np.empty(npoly, dtype=np.int32)
        me.polygons.foreach_get("loop_start", start)
        vidx = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", vidx)
        loops = start.astype(np.int64)[:, None] + np.arange(3)[None, :]
        mi = np.empty(npoly, dtype=np.int32)
        me.polygons.foreach_get("material_index", mi)
        names = [mt.name if mt else "?" for mt in me.materials] or ["?"]
        for nm in names:
            if nm not in mat_names:
                mat_names.append(nm)
        lut = np.array([mat_names.index(nm) for nm in names])
        gen = np.zeros(npoly, dtype=np.int64)
        attr = me.attributes.get("gen")
        if attr is not None:
            g = [0] * npoly
            attr.data.foreach_get("value", g)
            gen = np.array(g, dtype=np.int64)
        pos = co[vidx[loops]]
        cen = pos.mean(axis=1)
        zone = [zone_names.index(zone_of(ob.name, names[mi[i]], Vector(cen[i]))) for i in range(npoly)]
        # the D-pillar lamp clusters as rigid groups (planar_uv GROUP_GAP): tail and stop parts never share an
        # island and lie GROUP_GAP apart on the sheet (LENS_GROUPS)
        grp = np.full(npoly, -1, dtype=np.int64)
        spl = np.zeros(npoly, dtype=np.int64)
        if ob.name == LENS_OBJECT:
            for i in range(npoly):
                g = LENS_GROUPS.get(zone_names[zone[i]])
                if g is not None and cen[i][1] < LENS_Y and not _stop_lamp(names[mi[i]], Vector(cen[i])):
                    grp[i], spl[i] = g
        cols["pos"].append(pos)
        cols["obj"].append(np.full(npoly, oi))
        cols["mat"].append(lut[np.minimum(mi, len(names) - 1)])
        cols["gen"].append(gen)
        cols["zone"].append(np.array(zone, dtype=np.int64))
        cols["w"].append(np.array(_face_weights(ob, space), dtype=np.float64))
        cols["group"].append(grp)
        cols["split"].append(spl)
        cols["loops"].append(loops)
    tris = {k: np.concatenate(v) for k, v in cols.items() if k != "loops"}
    tris.update(obj_names=[ob.name for ob in objs], mat_names=mat_names, zone_names=zone_names)
    return tris, cols["loops"]


def _uv2_from_host(ob, host, host_uv):
    """UVMap1 (texCoords1: rust, dents, blood) of a mesh lying on another, `host` (custom property uv2_host,
    the decals feature): each corner takes the host's even UV at the nearest point of the host, so the
    rust and blood run on across the decal instead of sampling a chart of its own. Flat [u, v, ...]."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    hm, hw = host.data, host.matrix_world
    hv = [hw @ v.co for v in hm.vertices]
    tree = BVHTree.FromPolygons(hv, [list(p.vertices) for p in hm.polygons])
    me, mw = ob.data, ob.matrix_world
    out = []
    for lp in me.loops:
        p = mw @ me.vertices[lp.vertex_index].co
        loc, _n, fi, _d = tree.find_nearest(p)
        if fi is None:
            out += [0.0, 0.0]
            continue
        poly = hm.polygons[fi]
        a, b, c = (hv[v] for v in poly.vertices[:3])
        v0, v1, v2 = b - a, c - a, loc - a
        d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
        den = d00 * d11 - d01 * d01
        wb = (d11 * d20 - d01 * d21) / den if abs(den) > 1e-20 else 0.0
        wc = (d00 * d21 - d01 * d20) / den if abs(den) > 1e-20 else 0.0
        wa = 1.0 - wb - wc
        li = list(poly.loop_indices)[:3]
        uvs = [Vector(host_uv[i] if host_uv[i] is not None else (0.0, 0.0)) for i in li]
        uv = uvs[0] * wa + uvs[1] * wb + uvs[2] * wc
        out += [uv.x, uv.y]
    return out


def unwrap_planar(objs, size, space, out_dir):
    """The shell's planar layout (planar_uv.unwrap) into UVMap, the even xatlas layout into UVMap1,
    the island ids into the uv_island face attribute; prints the report, writes shell_layout.png.
    Returns planar_uv's result (its meta goes to uvmesh_dump)."""
    import numpy as np
    import planar_uv
    _check_xatlas()
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    _triangulate(objs)
    tris, loops = shell_tris(objs, space)
    res = planar_uv.unwrap(tris, _xatlas_job, size=size)
    even_uv = _xatlas_pass(objs, EVEN_SIZE.get(space, size), space + " (even, texCoords1)",
                           lambda ob: [1.0] * len(ob.data.polygons))
    first = 0
    for ob, lp in zip(objs, loops):
        me = ob.data
        n = len(lp)
        flat0 = np.zeros((len(me.loops), 2))
        flat0[lp.reshape(-1)] = res["uv"][first:first + n].reshape(-1, 2)
        host = bpy.data.objects.get(ob.get("uv2_host", "")) if ob.get("uv2_host") else None
        if host is not None and host.name in even_uv:        # a decal: the panel's own rust / blood UVs
            flat1 = _uv2_from_host(ob, host, even_uv[host.name])
        else:
            flat1 = _flat(even_uv[ob.name])
        _write_uvs(ob, flat0.reshape(-1).tolist(), flat1)
        attr = me.attributes.get(ISLAND_ATTR)
        if attr is not None:
            me.attributes.remove(attr)
        attr = me.attributes.new(ISLAND_ATTR, 'INT', 'FACE')
        attr.data.foreach_set("value", res["island"][first:first + n].astype(int).tolist())
        first += n
    print(res["line"])
    for line in res["lines"]:
        print(line)
    # the layout's safety numbers on every build, not only in a harness: a mesh change could bring
    # back overlapping or starved charts and still pass the density gate (build.py gates this line)
    print(planar_uv.check_line(planar_uv.check_layout(res)))
    path = os.path.join(out_dir, "%s_layout.png" % space)
    planar_uv.write_png(path, planar_uv.layout_image(res))
    # the meta (island axes and directions, cell rects) lives nowhere else: kept beside the bake so
    # the triangle dump can be retaken from the saved .blend without unwrapping again
    with open(os.path.join(out_dir, "%s_layout_meta.json" % space), "w", encoding="utf-8") as f:
        json.dump(res["meta"], f)
    print("bake: %s layout preview -> %s" % (space, path))
    return res


def unwrap(objs, margin=0.002):
    _select(objs)
    for ob in objs:
        me = ob.data
        while len(me.uv_layers) > 1:
            me.uv_layers.remove(me.uv_layers[-1])
        if not me.uv_layers:
            me.uv_layers.new(name="UVMap")
        me.uv_layers[0].name = "UVMap"
        me.uv_layers.active_index = 0
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(72.0), island_margin=0.001,
                             area_weight=0.0, correct_aspect=False, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    # Decal faces (cast lettering, labels) get DECAL_BOOST x the texel density: a uniform scale
    # about the UV origin keeps every island intact, and the pack below re-fits everything.
    for ob in objs:
        me = ob.data
        uv = me.uv_layers[0].data
        for poly in me.polygons:
            m = me.materials[poly.material_index] if me.materials else None
            if m is None:
                continue
            k = DECAL_BOOST if m.name.startswith("Decal") else UV_SCALE.get(m.name)
            if k:
                for li in poly.loop_indices:
                    uv[li].uv = uv[li].uv * k
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(rotate=True, margin_method='FRACTION', margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')
    for ob in objs:
        me = ob.data
        uv1 = me.uv_layers.new(name="UVMap1")             # texCoords1: rust / damage / blood
        for i, d in enumerate(me.uv_layers[0].data):
            uv1.data[i].uv = d.uv
        me.uv_layers.active_index = 0
        me["uv_baked"] = 1


def _materials(objs):
    mats = []
    for ob in objs:
        for m in ob.data.materials:
            if m and m not in mats:
                mats.append(m)
    return mats


def _bsdf(mat):
    mat.use_nodes = True
    return next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def _point(mats, image):
    for m in mats:
        m.use_nodes = True
        nodes = m.node_tree.nodes
        node = nodes.get(BAKE_NODE)
        if node is None:
            node = nodes.new('ShaderNodeTexImage')
            node.name = BAKE_NODE
            node.location = (-600, 400)
        node.image = image
        nodes.active = node


def _image(name, size, linear):
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, size, size, alpha=False, float_buffer=linear)
    img.colorspace_settings.name = 'Non-Color' if linear else 'sRGB'
    img.generated_color = KEY + (1.0,)                 # unbaked texels keep the key; compose dilates over them
    return img


def _save(img, path):
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()


def _gpu():
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.get_devices()
            found = False
            for d in prefs.devices:
                if d.type != 'CPU':
                    d.use = True
                    found = True
            if found:
                bpy.context.scene.cycles.device = 'GPU'
                return kind
    except Exception as exc:                   # noqa: BLE001
        print("bake: GPU setup failed (%s), using CPU" % exc)
    return "CPU"


class _Joined:
    """The direct bakes on ONE joined copy per ray-visibility class instead of every part (2026-10-13).
    Blender bakes several selected objects one by one, each a full pass over the whole image (pixel
    arrays, the render buffer, the write-back): 28 shell parts took 27 s a pass at 2048 and 97 s at
    4096 whatever the samples (scratch prof_bake), against 3-4 s for one object. The copies are joined
    (materials, UVs, attributes such as zone / rim_shade / acc_shade, custom normals carry over) and
    the originals leave the render meanwhile, so rays meet the same geometry: the car as one object,
    the ray-invisible accessories as another. Parts not at the identity keep their own bake (the
    'Object' texture coordinate of the TEXTURED layers is object space). The margin of a joined bake
    only fills texels no part owns: per part it overwrote the edge texels of the parts baked before."""

    def __init__(self, objs):
        self.objs = list(objs)
        self.made, self.hidden, self.bake = [], [], []

    def __enter__(self):
        from mathutils import Matrix
        groups = {}
        for ob in self.objs:
            if ob.matrix_world != Matrix.Identity(4) or ob.type != 'MESH':
                self.bake.append(ob)
                continue
            groups.setdefault(tuple(getattr(ob, a) for a in RAY_FLAGS), []).append(ob)
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        col = bpy.context.scene.collection
        for flags, obs in groups.items():
            if len(obs) == 1:
                self.bake.append(obs[0])
                continue
            copies = []
            for ob in obs:
                c = ob.copy()
                c.data = ob.data.copy()
                c.name = "CRV_JOIN_" + ob.name
                c.hide_render = False
                col.objects.link(c)
                copies.append(c)
            spent = [c.data for c in copies[1:]]
            with bpy.context.temp_override(active_object=copies[0], selected_editable_objects=copies,
                                           selected_objects=copies, object=copies[0]):
                bpy.ops.object.join()
            for me in spent:                     # the joined-in copies' meshes are orphans now
                if me.users == 0:
                    bpy.data.meshes.remove(me)
            j = copies[0]
            me = j.data
            if "UVMap" in me.uv_layers:
                me.uv_layers.active = me.uv_layers["UVMap"]
                me.uv_layers["UVMap"].active_render = True
            for a, v in zip(RAY_FLAGS, flags):
                setattr(j, a, v)
            self.made.append(j)
            self.bake.append(j)
            for ob in obs:
                self.hidden.append((ob, ob.hide_render))
                ob.hide_render = True
        return self.bake

    def __exit__(self, *exc):
        for ob, flag in self.hidden:
            ob.hide_render = flag
        for j in self.made:
            me = j.data
            bpy.data.objects.remove(j, do_unlink=True)
            if me.users == 0:
                bpy.data.meshes.remove(me)
        return False


def _bake(objs, kind, samples, **kw):
    scene = bpy.context.scene
    scene.cycles.samples = samples
    scene.render.bake.use_clear = False
    scene.render.bake.margin = _margin[0]
    scene.render.bake.use_selected_to_active = False
    with _Joined(objs) as baked:
        _select(baked)
        bpy.ops.object.bake(type=kind, **kw)


# v6: every low part has a full-detail twin '<name>_hi' (prep_parts). Each pass bakes the low parts
# directly first (the fallback wherever a projection ray misses, and the only source for generated
# faces, which have no twin), then projects the twin onto the low part (selected-to-active): rays
# start CAGE outside the low surface and travel up to RAY. During projection every low part and
# its generated faces are invisible to rays, so only the full-detail car shades and occludes.
HILO_CAGE = {"engine_block": (0.03, 0.10),          # (cage extrusion, max ray distance), metres; the coarse engine sits on its source
             "wheel_FR": (0.04, 0.22), "trunk": (0.04, 0.22),   # lathe tyres and rim lips (the spoke face is gen 8, flat)
             # build_cabin: coarse and full share centre lines (coarse vertices p95 11.5 / max 15 mm off the twin,
             # the cup wells 5 cm deep); a tight cage keeps rim rays off the hub pad
             "cabin": (0.02, 0.08),
             # the rear bench out of the cabin (function feature), upright and folded: the cabin's cage
             "acc_function_seats_up": (0.02, 0.08), "acc_function_seats_fold": (0.02, 0.08),
             "acc_function_bedding": (0.02, 0.08)}          # the bed on the folded bench (its own model, 2026-10-22)
HILO_DEFAULT = (0.04, 0.12)
RAY_FLAGS = ("visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow")
GEN_SUFFIX = "__gen"


def _twin(ob):
    return bpy.data.objects.get(ob.name + "_hi")


def _base_name(name):
    name = name.split(GEN_SUFFIX)[0]
    return name[:-3] if name.endswith("_hi") else name


def _split_gen(objs):
    """Move the generated faces (face attribute gen > 0) of every part that has a twin into
    '<name>__gen' (UVs kept): they have nothing to project from and are baked directly only."""
    gens = []
    for ob in objs:
        if _twin(ob) is None:
            continue
        attr = ob.data.attributes.get("gen")
        if attr is None:
            continue
        vals = [0] * len(ob.data.polygons)
        attr.data.foreach_get("value", vals)
        ids = [i for i, v in enumerate(vals) if v > 0]
        if not ids:
            continue
        keep = set(ids)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        cp = bm.copy()
        cp.faces.ensure_lookup_table()
        cp.faces.index_update()
        bmesh.ops.delete(cp, geom=[f for f in cp.faces if f.index not in keep], context='FACES')
        me = bpy.data.meshes.new(ob.name + GEN_SUFFIX)
        for m in ob.data.materials:
            me.materials.append(m)
        cp.to_mesh(me)
        cp.free()
        bmesh.ops.delete(bm, geom=[bm.faces[i] for i in ids], context='FACES')
        bm.to_mesh(ob.data)
        bm.free()
        me["uv_baked"] = 1
        g = bpy.data.objects.new(ob.name + GEN_SUFFIX, me)
        ob.users_collection[0].objects.link(g)
        g.matrix_world = ob.matrix_world
        gens.append(g)
    return gens


def _join_gen(gens):
    for g in gens:
        dst = bpy.data.objects.get(_base_name(g.name))
        if dst is None:
            continue
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        dst.hide_set(False)
        g.hide_set(False)
        dst.select_set(True)
        g.select_set(True)
        bpy.context.view_layer.objects.active = dst
        with bpy.context.temp_override(active_object=dst, selected_editable_objects=[dst, g], selected_objects=[dst, g]):
            bpy.ops.object.join()


def _flatten(objs):
    """Strip custom normals and shade flat (AO crease lesson, see bake_space); returns what to restore."""
    saved = {}
    for ob in objs:
        me = ob.data
        custom = None
        if "custom_normal" in me.attributes:
            src = me.corner_normals if hasattr(me, "corner_normals") else me.loops
            custom = [(v.vector if hasattr(v, "vector") else v.normal).copy() for v in src]
            with bpy.context.temp_override(object=ob, active_object=ob):
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
        saved[ob.name] = ([poly.use_smooth for poly in me.polygons], custom)
        for poly in me.polygons:
            poly.use_smooth = False
    return saved


def _unflatten(objs, saved):
    for ob in objs:
        if ob.name not in saved:
            continue
        me = ob.data
        flags, custom = saved[ob.name]
        for poly, flag in zip(me.polygons, flags):
            poly.use_smooth = flag
        if custom is not None:
            me.normals_split_custom_set(custom)


def _bake_hilo(pairs, kind, samples, **kw):
    """Project each twin onto its low part (see HILO_CAGE)."""
    if not pairs:
        return
    scene = bpy.context.scene
    scene.cycles.samples = samples
    rb = scene.render.bake
    his = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.endswith("_hi")]
    quiet = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.endswith("_hi")
             and (_twin(o) is not None or GEN_SUFFIX in o.name)]
    saved = {o.name: tuple(getattr(o, a) for a in RAY_FLAGS) for o in quiet}
    for o in quiet:
        for a in RAY_FLAGS:
            setattr(o, a, False)
    for h in his:
        h.hide_render = False
        h.hide_viewport = False
        h.hide_set(False)
    # variant meshes (function feature, 2026-10-14: the rear bench upright and folded, which overlap): twins
    # with the same crv_variant never shade each other. Each bakes with the car and itself; any other part
    # sees only the set's crv_variant_default twin (the upright bench shades the car as it always did). A twin's
    # crv_variant_with names the set's twins (comma-separated) that are always drawn with it and so shade it (the
    # bedding lies on the folded bench, 2026-10-22)
    variants = [h for h in his if h.get("crv_variant")]
    vflags = {h.name: tuple(getattr(h, a) for a in RAY_FLAGS) for h in variants}
    try:
        for low, hi in pairs:
            vset = hi.get("crv_variant")
            with_ = set(filter(None, str(hi.get("crv_variant_with", "")).split(",")))
            for h in variants:
                if h.get("crv_variant") == vset:
                    on = h is hi or h.name in with_
                else:
                    on = bool(h.get("crv_variant_default"))
                h.hide_render = not on
                for a in RAY_FLAGS:                      # acc_ twins may have left the rays: back for their turn
                    setattr(h, a, True if on else vflags[h.name][RAY_FLAGS.index(a)])
            cage, ray = HILO_CAGE.get(low.name, HILO_DEFAULT)
            if bpy.context.object and bpy.context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            low.hide_set(False)
            hi.select_set(True)
            low.select_set(True)
            bpy.context.view_layer.objects.active = low
            rb.use_clear = False
            rb.margin = _margin[0]
            rb.use_selected_to_active = True
            rb.use_cage = False
            rb.cage_extrusion = cage
            rb.max_ray_distance = ray
            bpy.ops.object.bake(type=kind, use_selected_to_active=True, cage_extrusion=cage,
                                max_ray_distance=ray, margin=_margin[0], use_clear=False, **kw)
    finally:
        for o in quiet:
            for a, v in zip(RAY_FLAGS, saved[o.name]):
                setattr(o, a, v)
        for h in variants:
            for a, v in zip(RAY_FLAGS, vflags[h.name]):
                setattr(h, a, v)
        for h in his:
            h.hide_render = True
            h.hide_set(True)
        rb.use_selected_to_active = False


def _bake2(direct, pairs, kind, samples, **kw):
    """Direct bake of the low parts (fallback + generated faces), then the projection on top."""
    _bake(direct, kind, samples, **kw)
    _bake_hilo(pairs, kind, samples, **kw)


def _paint_zones(objs):
    """Face-corner colour attribute holding each face's zone colour (twins and generated-face
    objects take their part's zone)."""
    for ob in objs:
        me = ob.data
        attr = me.color_attributes.get(ZONE_ATTR)
        if attr is None:
            attr = me.color_attributes.new(ZONE_ATTR, 'FLOAT_COLOR', 'CORNER')
        names = [m.name if m else "?" for m in me.materials]
        part = _base_name(ob.name)
        low = _lens_low_zones(part) if part == LENS_OBJECT and part != ob.name else None
        mw = ob.matrix_world
        for poly in me.polygons:
            z = zone_of(part, names[poly.material_index], poly.center)
            if low is not None and z in LENS_GROUPS:
                z = low(mw @ poly.center) or z
            col = ZONE[z]
            for li in poly.loop_indices:
                attr.data[li].color = (col[0], col[1], col[2], 1.0)


def _lens_low_zones(part):
    """For the full-detail twin of LENS_OBJECT: point (world) -> the D-pillar lamp zone of the nearest LOW face
    (zone_of at its centre), None off the lens. The zone bake projects the twin onto the low faces, and the
    twin's lens faces split at TAIL_STOP_Z by their own centres: along the split a low stop triangle (in the stop
    block of its rigid group, LENS_GROUPS) took tail texels from the twin, which no guard can make pure (bug wave
    3, scratch build: 0.7-3.7 % of the lens's lit fragments unlit at 1024-256). With the low face's zone the
    projected zones follow the low triangles, the ones planar_uv grouped."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    ob = bpy.data.objects.get(part)
    if ob is None:
        return None
    me, mw = ob.data, ob.matrix_world
    names = [m.name if m else "?" for m in me.materials]
    verts = [mw @ v.co for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons]
    zones = []
    for p in me.polygons:
        c = sum((verts[i] for i in p.vertices), Vector()) / len(p.vertices)
        zones.append(zone_of(part, names[p.material_index], c))
    tree = BVHTree.FromPolygons(verts, polys)

    def look(pt):
        _loc, _n, fi, dist = tree.find_nearest(pt, 0.02)
        if fi is None:
            return None
        z = zones[fi]
        return z if z in LENS_GROUPS else None
    return look


# Weathering: a dirt field over the whole car, baked as its own map (shell_grime etc.) and mixed
# in by compose AFTER the paint recolour, so every skin gets the same wear and the paint mask stays
# clean. Dirt rises from the sills and the wheel arches, sits faintly on roof and hood, is uneven
# (noise) and streaked; glass carries a dust haze except inside the wiper sweeps. Per material
# (or material prefix) a strength; 0 leaves the material clean.
GRIME_STRENGTH = {
    # lamps 0.5 -> 0.2 (2026-10-12): at the game's zoom a lens is 6-10 px and dirt on it only
    # greyed it; KI5's lamps are clean and saturated
    "shell": {"*": 1.0, "Vitre": 0.0, "Vitre_noir": 0.0, "Phare": 0.2, "Phare_vitre": 0.2, "Feux_rouge": 0.2,
              "Feux_stop": 0.2, "Feux_orange": 0.2, "Feux_blanc": 0.2, "Reflect_red": 0.2, "Reflect_orange": 0.2,
              "Phare_orange": 0.2, "Feux_chrome": 0.2, "DoorCard_": 0.25, "BodyInner": 0.6, "Interieur": 0.3,
              "AccLens": 0.2},
    "interior": {"*": 0.0, "Interieur_sol": 1.0, "Interieur": 0.35, "Plastique_noir": 0.3},
    "engine": {"*": 0.6, "Decal": 0.3},
    "wheel": {"*": 0.0, "Pneu": 0.6, "Jante": 0.5},
}
WHEELS_XY = ((0.72, 1.31), (-0.72, 1.31), (0.72, -1.31), (-0.72, -1.31))
# wiper sweeps: (pivot x, pivot z, radius, angle from, angle to) in the glass's x/z plane, degrees
# counter-clockwise from +x; glass object -> (x range, z range, y range gate, sweeps)
WIPERS = {
    "windscreen": (("x", -0.76, 0.76), ("z", 1.04, 1.62), ("y", 0.20, 1.10),
                   [(-0.30, 1.04, 0.56, 8.0, 118.0), (0.36, 1.04, 0.50, 58.0, 168.0)]),
    "rear": (("x", -0.70, 0.70), ("z", 1.12, 1.64), ("y", -2.20, -1.60),
             [(0.0, 1.16, 0.40, 28.0, 152.0)]),
}
GLASS_HAZE = 0.0                     # dust on the glass outside the wiper sweeps. 0.45 read in game as a pale
                                     # smear with two arcs on every windscreen (feedback, 2026-10-11): off


def _grime_strength(space, mat_name):
    table = GRIME_STRENGTH.get(space, {"*": 0.0})
    for key, val in table.items():
        if key != "*" and mat_name.startswith(key):
            return val
    return table.get("*", 0.0)


class _GrimeOverride:
    """Temporarily route every material's output through Emission(dirt field)."""

    def __init__(self, mats, space):
        self.mats = mats
        self.space = space
        self.saved = {}

    @staticmethod
    def _m(nt, op, a, b=None, c=None):
        n = nt.nodes.new('ShaderNodeMath')
        n.name = "CRV_GRIME_m"
        n.operation = op
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if hasattr(v, "is_output"):
                nt.links.new(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    def _field(self, nt, strength, glass):
        def m(op, a, b=None, c=None):
            return self._m(nt, op, a, b, c)
        coord = nt.nodes.new('ShaderNodeTexCoord'); coord.name = "CRV_GRIME_c"
        sep = nt.nodes.new('ShaderNodeSeparateXYZ'); sep.name = "CRV_GRIME_s"
        nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
        x, y, z = sep.outputs['X'], sep.outputs['Y'], sep.outputs['Z']
        geo = nt.nodes.new('ShaderNodeNewGeometry'); geo.name = "CRV_GRIME_g"
        nsep = nt.nodes.new('ShaderNodeSeparateXYZ'); nsep.name = "CRV_GRIME_ns"
        nt.links.new(geo.outputs['Normal'], nsep.inputs['Vector'])
        nz = nsep.outputs['Z']
        noise = nt.nodes.new('ShaderNodeTexNoise'); noise.name = "CRV_GRIME_n"
        noise.inputs['Scale'].default_value = 7.0
        noise.inputs['Detail'].default_value = 5.0
        noise.inputs['Roughness'].default_value = 0.6
        nt.links.new(coord.outputs['Object'], noise.inputs['Vector'])
        streak = nt.nodes.new('ShaderNodeTexNoise'); streak.name = "CRV_GRIME_st"
        streak.inputs['Scale'].default_value = 1.0
        streak.inputs['Detail'].default_value = 3.0
        mapn = nt.nodes.new('ShaderNodeMapping'); mapn.name = "CRV_GRIME_map"
        mapn.inputs['Scale'].default_value = (28.0, 28.0, 2.5)          # long vertical streaks
        nt.links.new(coord.outputs['Object'], mapn.inputs['Vector'])
        nt.links.new(mapn.outputs['Vector'], streak.inputs['Vector'])
        if glass:
            # haze everywhere on the pane, cleaned inside the wiper sweeps
            clean = None
            for _name, (xr, zr, yr, sweeps) in WIPERS.items():
                gate = m('MULTIPLY', m('GREATER_THAN', y, yr[1]), m('LESS_THAN', y, yr[2]))
                for px, pz, r, a0, a1 in sweeps:
                    dx, dz = m('SUBTRACT', x, px), m('SUBTRACT', z, pz)
                    rr = m('SQRT', m('ADD', m('MULTIPLY', dx, dx), m('MULTIPLY', dz, dz)))
                    ang = m('DEGREES', m('ARCTAN2', dz, dx))
                    inside = m('MULTIPLY', m('MULTIPLY', m('LESS_THAN', rr, r), m('GREATER_THAN', rr, 0.07)),
                               m('MULTIPLY', m('GREATER_THAN', ang, a0), m('LESS_THAN', ang, a1)))
                    inside = m('MULTIPLY', inside, gate)
                    clean = inside if clean is None else m('MAXIMUM', clean, inside)
            haze = m('MULTIPLY', m('ADD', 0.75, m('MULTIPLY', noise.outputs['Fac'], 0.5)), GLASS_HAZE)
            return m('MULTIPLY', haze, m('SUBTRACT', 1.0, clean))
        # low: 1 at the sills (z 0.40), fading out by z 0.90 (mid door); arches: within ~0.45 m of a
        # wheel centre. Tuned twice: full to z 0.7 read as a mud bath, none above 0.80 at 0.75 was
        # invisible in the shipped sheet (p99 of the darkening 18 levels).
        low = m('MINIMUM', 1.0, m('MAXIMUM', 0.0, m('MULTIPLY', m('SUBTRACT', 0.90, z), 1.0 / 0.50)))   # full below z 0.40, none above 0.90
        arch = None
        for wx, wy in WHEELS_XY:
            d2 = m('ADD', m('POWER', m('SUBTRACT', x, wx), 2.0), m('POWER', m('SUBTRACT', y, wy), 2.0))
            a = m('MULTIPLY', m('EXPONENT', m('MULTIPLY', d2, -1.0 / 0.18)), m('LESS_THAN', z, 0.78))   # splash stays below the fender tops
            arch = a if arch is None else m('MAXIMUM', arch, a)
        up = m('MULTIPLY', m('GREATER_THAN', nz, 0.6), 0.0)                      # roof / hood dust: off, it read as blotches in game
        base = m('MINIMUM', 1.0, m('ADD', m('ADD', m('MULTIPLY', low, 0.70), m('MULTIPLY', arch, 0.60)), up))
        uneven = m('MULTIPLY', m('ADD', 0.35, m('MULTIPLY', noise.outputs['Fac'], 0.9)),
                   m('ADD', 0.70, m('MULTIPLY', streak.outputs['Fac'], 0.45)))
        return m('MULTIPLY', m('MULTIPLY', base, uneven), strength)

    def __enter__(self):
        for mat in self.mats:
            nt = mat.node_tree
            out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
            if out is None:
                continue
            link = out.inputs['Surface'].links[0] if out.inputs['Surface'].links else None
            self.saved[mat.name] = (out, link.from_socket if link else None)
            emit = nt.nodes.new('ShaderNodeEmission')
            emit.name = "CRV_GRIME_EMIT"
            strength = _grime_strength(self.space, mat.name)
            glass = mat.name in GLASS_MATS and self.space == "shell"
            if strength <= 0.0 and not glass:
                emit.inputs['Color'].default_value = (0.0, 0.0, 0.0, 1.0)
            else:
                val = self._field(nt, strength, glass)
                nt.links.new(val, emit.inputs['Color'])
            nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
        return self

    def __exit__(self, *exc):
        for mat in self.mats:
            if mat.name not in self.saved:
                continue
            nt = mat.node_tree
            out, src = self.saved[mat.name]
            for n in [n for n in nt.nodes if n.name.startswith("CRV_GRIME")]:
                nt.nodes.remove(n)
            if src is not None:
                nt.links.new(src, out.inputs['Surface'])
        return False


class _EmitOverride:
    """Temporarily route every material's output through Emission(colour attribute, or a flat colour)."""

    def __init__(self, mats, flat=None, pointiness=False, edge=False):
        self.mats = mats
        self.flat = flat
        self.pointiness = pointiness
        self.edge = edge
        self.saved = {}

    def __enter__(self):
        for m in self.mats:
            nt = m.node_tree
            out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
            if out is None:
                continue
            link = out.inputs['Surface'].links[0] if out.inputs['Surface'].links else None
            self.saved[m.name] = (out, link.from_socket if link else None)
            emit = nt.nodes.new('ShaderNodeEmission')
            emit.name = "CRV_ZONE_EMIT"
            if self.edge:                         # EDGE_*: (1 - Bevel normal . true normal) x gain, clamped
                bev = nt.nodes.new('ShaderNodeBevel'); bev.name = "CRV_EDGE_bev"
                bev.samples = 16
                bev.inputs['Radius'].default_value = EDGE_RADIUS
                geo = nt.nodes.new('ShaderNodeNewGeometry'); geo.name = "CRV_EDGE_geo"
                dot = nt.nodes.new('ShaderNodeVectorMath'); dot.name = "CRV_EDGE_dot"
                dot.operation = 'DOT_PRODUCT'
                nt.links.new(bev.outputs['Normal'], dot.inputs[0])
                nt.links.new(geo.outputs['True Normal'], dot.inputs[1])
                val = nt.nodes.new('ShaderNodeMath'); val.name = "CRV_EDGE_val"
                val.operation = 'MULTIPLY_ADD'
                val.use_clamp = True
                nt.links.new(dot.outputs['Value'], val.inputs[0])
                val.inputs[1].default_value = -EDGE_GAIN
                val.inputs[2].default_value = EDGE_GAIN
                nt.links.new(val.outputs[0], emit.inputs['Color'])
            elif self.pointiness:
                geo = nt.nodes.new('ShaderNodeNewGeometry'); geo.name = "CRV_ZONE_GEO"
                attr = nt.nodes.new('ShaderNodeMapRange'); attr.name = "CRV_ZONE_ATTR"
                attr.inputs['From Min'].default_value = CAVITY_RANGE[0]
                attr.inputs['From Max'].default_value = CAVITY_RANGE[1]
                nt.links.new(geo.outputs['Pointiness'], attr.inputs['Value'])
                nt.links.new(attr.outputs['Result'], emit.inputs['Color'])
            elif self.flat is None:
                attr = nt.nodes.new('ShaderNodeVertexColor')
                attr.name = "CRV_ZONE_ATTR"
                attr.layer_name = ZONE_ATTR
                nt.links.new(attr.outputs['Color'], emit.inputs['Color'])
            else:
                attr = nt.nodes.new('ShaderNodeRGB')
                attr.name = "CRV_ZONE_ATTR"
                col = self.flat.get(m.name, (0.0, 0.0, 0.0)) if isinstance(self.flat, dict) else self.flat
                attr.outputs[0].default_value = tuple(col) + (1.0,)
                nt.links.new(attr.outputs[0], emit.inputs['Color'])
            nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])
        return self

    def __exit__(self, *exc):
        for m in self.mats:
            nt = m.node_tree
            if m.name not in self.saved:
                continue
            out, from_socket = self.saved[m.name]
            for n in ("CRV_ZONE_EMIT", "CRV_ZONE_ATTR", "CRV_ZONE_GEO"):
                node = nt.nodes.get(n)
                if node:
                    nt.nodes.remove(node)
            for node in [x for x in nt.nodes if x.name.startswith("CRV_EDGE_")]:
                nt.nodes.remove(node)
            if from_socket is not None:
                nt.links.new(from_socket, out.inputs['Surface'])
        return False


def _fill_convex(img, pts):
    """Paint a convex polygon (pixel coordinates, any winding) white into a 2-D uint8 array."""
    import numpy as np
    pts = np.asarray(pts, dtype=np.float64)
    h, w = img.shape
    x0, y0 = int(max(0, np.floor(pts[:, 0].min()))), int(max(0, np.floor(pts[:, 1].min())))
    x1, y1 = int(min(w - 1, np.ceil(pts[:, 0].max()))), int(min(h - 1, np.ceil(pts[:, 1].max())))
    if x1 < x0 or y1 < y0:
        return
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    px, py = xs + 0.5, ys + 0.5
    inside = np.ones(px.shape, dtype=bool)
    sign = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        cross = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
        if sign == 0.0:
            area2 = 0.0
            for k in range(len(pts)):
                c, d = pts[k], pts[(k + 1) % len(pts)]
                area2 += c[0] * d[1] - d[0] * c[1]
            sign = 1.0 if area2 >= 0 else -1.0
        inside &= cross * sign >= -1e-9
    img[y0:y1 + 1, x0:x1 + 1][inside] = 255


def _rubber_map(objs, size, path):
    """shell_rubber.png: white in a band RUBBER_WIDTH wide just inside every pane outline, written
    straight from the low meshes after the unwrap (no bake pass). A pane outline is every edge of a
    glass face (GLASS_MATS) that no other glass face shares, vertices matched by position so
    kotris's unwelded duplicates open no false edges. Each outline edge's band is laid inside its
    own triangle in that triangle's UV frame, so it follows the real pane edge and never a chart
    seam xatlas cut through the pane (an outline of the window zone taken in UV space would, and
    the packer puts a stranger next to every chart). Vertex distances would not do either: on a
    decimated pane nearly every vertex is on the outline, so a whole pane would read as edge."""
    import numpy as np
    img = np.zeros((size, size), dtype=np.uint8)
    n_edges = 0
    for ob in objs:
        me = ob.data
        if not me.uv_layers or not me.materials:
            continue
        names = [m.name if m else "?" for m in me.materials]
        glass = [p for p in me.polygons if names[p.material_index] in GLASS_MATS]
        if not glass:
            continue

        def key(vi):
            co = me.vertices[vi].co
            return (round(co.x, 4), round(co.y, 4), round(co.z, 4))
        count = {}
        for p in glass:
            vs = list(p.vertices)
            for i in range(len(vs)):
                e = tuple(sorted((key(vs[i]), key(vs[(i + 1) % len(vs)]))))
                count[e] = count.get(e, 0) + 1
        uv = me.uv_layers[0].data
        for p in glass:
            vs = list(p.vertices)
            uvs = [np.array(uv[li].uv, dtype=np.float64) for li in p.loop_indices]
            uv_area = 0.0
            for i in range(len(uvs)):
                a, b = uvs[i], uvs[(i + 1) % len(uvs)]
                uv_area += a[0] * b[1] - b[0] * a[1]
            uv_area = abs(uv_area) / 2.0
            if p.area <= 1e-12 or uv_area <= 1e-14:
                continue
            w = RUBBER_WIDTH * (uv_area / p.area) ** 0.5 * size      # band width in pixels, this face's density
            centre = sum(uvs) / len(uvs) * size
            for i in range(len(vs)):
                j = (i + 1) % len(vs)
                if count.get(tuple(sorted((key(vs[i]), key(vs[j])))), 0) != 1:
                    continue
                a, b = uvs[i] * size, uvs[j] * size
                d = b - a
                length = float(np.hypot(d[0], d[1]))
                if length < 1e-6:
                    continue
                t = d / length
                nrm = np.array((-t[1], t[0]))
                if float(np.dot(nrm, centre - (a + b) / 2.0)) < 0.0:
                    nrm = -nrm                                      # into the pane
                a2, b2 = a - t * w * 0.5, b + t * w * 0.5           # past the corners: no notch where two bands meet
                _fill_convex(img, [a2, b2, b2 + nrm * w, a2 + nrm * w])
                n_edges += 1
    out = bpy.data.images.get("shell_rubber")
    if out:
        bpy.data.images.remove(out)
    out = bpy.data.images.new("shell_rubber", size, size, alpha=False, float_buffer=False)
    out.colorspace_settings.name = 'Non-Color'
    rgba = np.empty((size, size, 4), dtype=np.float32)
    rgba[..., :3] = (img.astype(np.float32) / 255.0)[..., None]
    rgba[..., 3] = 1.0
    out.pixels.foreach_set(rgba.ravel())
    _save(out, path)
    print("bake: shell rubber map: %d pane outline edges, %.2f%% of the sheet" % (n_edges, 100.0 * (img > 0).mean()))


def _density(objs, size, space):
    """Texels per centimetre, overall and for the decal faces."""
    def uv_area(me, poly):
        uv = me.uv_layers[0].data
        pts = [uv[li].uv for li in poly.loop_indices]
        a = 0.0
        for i in range(len(pts)):
            x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % len(pts)]
            a += x0 * y1 - x1 * y0
        return abs(a) / 2.0
    tot_w = tot_uv = dec_w = dec_uv = 0.0
    for ob in objs:
        me = ob.data
        for poly in me.polygons:
            w, u = poly.area, uv_area(me, poly)
            tot_w += w; tot_uv += u
            m = me.materials[poly.material_index] if me.materials else None
            if m is not None and m.name.startswith("Decal"):
                dec_w += w; dec_uv += u
    def tpc(uv_a, w_a):
        return (uv_a * size * size / w_a) ** 0.5 / 100.0 if w_a > 0 else 0.0
    print("bake: %s  %.1f m2 on %d^2, coverage %.0f%%, %.1f texels/cm; decals %.2f m2 at %.1f texels/cm"
          % (space, tot_w, size, tot_uv * 100.0, tpc(tot_uv, tot_w), dec_w, tpc(dec_uv, dec_w)))


class _Clock:
    """Wall time per bake pass, printed as 'bake: <space> <pass> <s> s' (build.py echoes bake: lines)."""

    def __init__(self, space):
        import time
        self.time = time.time
        self.space = space
        self.t0 = self.last = time.time()

    def lap(self, what):
        now = self.time()
        print("bake: %s %s %.0f s" % (self.space, what, now - self.last), flush=True)
        self.last = now

    def total(self, size, bake_size):
        print("bake: %s total %.0f s (%d px sheet baked at %d px, supersample %dx)"
              % (self.space, self.time() - self.t0, size, bake_size, bake_size // size), flush=True)


def quiet_removables(names):
    """Every removable mesh leaves the rays before a space bakes, whichever sheet it bakes on.
    acc_* (accessories, the table, every feature's body-file meshes) for good: the bare car must not
    carry their shadows, and each keeps its own AO in the acc_shade attribute. Until 2026-10-13 only
    the acc_ meshes of the space being baked were quieted, so the shell (baked first) printed the
    off-road ladder's four bracket plates on the right rear quarter and the snorkel's flange on the
    right front fender of every bare car, in all 8 paints (they bake later, on the offroad sheet).
    Feature meshes that are not acc_ (the wheel-file wheel_<feature>_*) leave the rays while ANOTHER
    space bakes and keep them for their own: returns [(object, saved flags)] for restore_rays."""
    keep = set(names)
    feature = set(features.objects())
    saved = []
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        if o.name.startswith(ACC_PREFIX):
            for a in RAY_FLAGS:
                setattr(o, a, False)
        elif o.name in feature and o.name not in keep:
            saved.append((o, tuple(getattr(o, a) for a in RAY_FLAGS)))
            for a in RAY_FLAGS:
                setattr(o, a, False)
    return saved


def restore_rays(saved):
    for o, flags in saved:
        for a, v in zip(RAY_FLAGS, flags):
            setattr(o, a, v)


# Spaces baked as the player sees them, with these meshes out of the rays: the engine bay is only ever
# seen with the hood up (engine bay v2, 2026-10-17), and baked under the shut hood its AO was ~0
# everywhere (compose's old DESPECKLE note), so the bay got no shading of its own.
OPEN_FOR = {"engine": ("hood", "hood_hi")}
# Parts of a sheet that are only ever seen in another pose, re-baked after the space's AO, cavity and gap passes
# with the meshes of the pose they hide out of the rays: (parts re-baked, meshes out; each name covers its _hi twin
# and __gen faces). The direct and projection bakes write only the re-baked parts' texels (use_clear off, the
# shell's margin 0). Polish round 1, 2026-10-17: the bay walls (firewall, aprons, shelves, strut towers, support,
# header) baked under the shut hood at AO 0 and cavity 5-122, so a white car's bay shipped charcoal (firewall
# (62, 62, 60) against the fender's (139, 140, 136)); the hood's underside (the insulator pad, its grey inner
# skin) baked against the shut bay, AO 0-19 in a plenum-shaped blob, a black hole in game. It is only seen
# lifted off the bay. The bay walls also bake without the arch liners and the body: the liners' inner walls stand
# 1.5 cm inboard of the aprons and kotris's body puts Dessous plates 4 cm inboard of them, both facing the wheels,
# so the game culls them from the bay, but to the rays they closed the aprons in (AO 0 with the hood away too)
REBAKE_OPEN = {"shell": ((("bay_walls",), ("hood", "arch_liners", "body")),
                         (("hood",), ("engine_block", "bay_walls")))}
# soft edge wear on the engine sheet (polish round 1, BAY-11): an EMIT bake of how far a Bevel normal (EDGE_RADIUS)
# turns from the true normal (x EDGE_GAIN, clamped) on the flat-shaded parts: ~1 within a few mm of every sharp
# edge, 0 on open faces. compose keeps the convex ones (the 4 cm cavity open) and lightens them a little
EDGE_SPACES = ("engine",)
EDGE_RADIUS = 0.006
EDGE_GAIN = 3.0
EDGE_SAMPLES = 8


def _rebake_open(space, direct, pairs, kind, samples):
    """The REBAKE_OPEN passes of one AO-type pass (the world's AO distance already set)."""
    for names, off in REBAKE_OPEN.get(space, ()):
        sub = [o for o in direct if _base_name(o.name) in names]
        sub_pairs = [(lo, hi) for lo, hi in pairs if lo.name in names]
        if not sub:
            continue
        hide = [o for o in bpy.data.objects if o.type == 'MESH' and _base_name(o.name) in off]
        saved = [(o, tuple(getattr(o, a) for a in RAY_FLAGS)) for o in hide]
        for o in hide:
            for a in RAY_FLAGS:
                setattr(o, a, False)
        try:
            flat = _flatten(sub)
            _bake(sub, kind, samples)
            _unflatten(sub, flat)
            _bake_hilo(sub_pairs, kind, samples)
        finally:
            restore_rays(saved)
        print("bake: %s %s re-baked %s with %s out of the rays" % (space, kind, "+".join(o.name for o in sub), "+".join(o.name for o in hide)))


def bake_space(space, names, size, out_dir):
    """Unwrap the space at its sheet size (the layout, its gate and the triangle dump), then bake every
    pass at size x SUPERSAMPLE (the images compose reduces to `size`). No removable mesh is visible
    to the rays meanwhile (quiet_removables), nor the space's OPEN_FOR meshes."""
    saved = quiet_removables(names)
    for name in OPEN_FOR.get(space, ()):
        o = bpy.data.objects.get(name)
        if o is not None and o.type == 'MESH':
            saved.append((o, tuple(getattr(o, a) for a in RAY_FLAGS)))
            for a in RAY_FLAGS:
                setattr(o, a, False)
    try:
        _bake_space(space, names, size, out_dir)
    finally:
        restore_rays(saved)


def _bake_space(space, names, size, out_dir):
    objs = _objects(names)
    if not objs:
        return
    clock = _Clock(space)
    bake_size = size * SUPERSAMPLE
    _margin[0] = SPACE_MARGIN.get(space, BAKE_MARGIN) * SUPERSAMPLE     # in bake texels: the same width on the sheet
    planar = None
    try:
        if space in PLANAR_SPACES:
            planar = unwrap_planar(objs, size, space, out_dir)
        else:
            unwrap_xatlas(objs, size, space)
    except ImportError as exc:                  # tools/pylib missing: the v5 Smart UV Project path
        print("bake: warning xatlas unavailable (%s), Smart UV Project instead" % exc)
        unwrap(objs)
    if planar is None:
        _density(objs, size, space)     # the planar report line replaces it (cells would count every face again)
    clock.lap("unwrap")
    if space == "shell":
        _rubber_map(objs, bake_size, os.path.join(out_dir, "shell_rubber.png"))
    if planar is not None:
        # the triangle dump of the final layout for compose's 2D paint pass (Part B), taken before
        # the generated faces move to their own objects. Only an absent module is tolerated (Part A
        # without Part B); once the file is there any error in it, an ImportError of its own
        # dependencies included, stops the bake instead of shipping without the paint pass
        if os.path.exists(os.path.join(HERE, "uvmesh_dump.py")):
            import uvmesh_dump
            dump_path = os.path.join(out_dir, "%s_uvmesh.npz" % space)
            # at the SHEET size: the meta's cell rects are layout pixels; paint_pass rasterises at the
            # bake images' size and scales the rects by their ratio (a whole SUPERSAMPLE)
            uvmesh_dump.dump(objs, dump_path, size, planar["meta"])
            print("bake: %s uvmesh dump -> %s" % (space, dump_path))
        else:
            print("bake: warning scripts/uvmesh_dump.py absent: no %s_uvmesh.npz, compose paints as before" % space)
    gens = _split_gen(objs)
    pairs = [(o, _twin(o)) for o in objs if _twin(o) is not None]
    direct = objs + gens
    his = [h for _o, h in pairs]
    mats = _materials(direct + his)
    print("bake: %s  %d parts (%d with a full-detail twin), %d generated-face objects" % (space, len(objs), len(pairs), len(gens)))
    scene = bpy.context.scene
    # colour, with the palette overrides in place
    saved_palette = {}
    for m in mats:
        if m.name not in PALETTE:
            continue
        b = _bsdf(m)
        if b is None:
            continue
        saved_palette[m.name] = tuple(b.inputs['Base Color'].default_value)
        b.inputs['Base Color'].default_value = PALETTE[m.name] + (1.0,)
    # lamp lenses bake opaque (2026-10-13): kotris gives every lens an Alpha (Phare_vitre 0.36, the tail
    # lenses 0.72-0.89) and Cycles' DIFFUSE COLOR of a part-transparent surface is a fraction of its
    # colour. The head lens baked at luma 36 under a decal of 159 (x0.05 in linear: the projection rays
    # meet the twin's see-through lens), "the headlamp looks black" (screenshot 25.png), and the tail lenses
    # lost 20-30 %, which LAMP_L could not give back (it only scales down): brown amber. The game draws
    # the shell opaque; paint_pass's LAMP_L sets each lens's level from its full colour.
    saved_alpha = {}
    for m in mats:
        b = _bsdf(m) if m.name in LAMP_MATS else None
        if b is None or 'Alpha' not in b.inputs or b.inputs['Alpha'].links:
            continue
        saved_alpha[m.name] = b.inputs['Alpha'].default_value
        b.inputs['Alpha'].default_value = 1.0
    img = _image("%s_color" % space, bake_size, linear=False)
    _point(mats, img)
    with _Textured(mats, objs, space):
        _bake2(direct, pairs, 'DIFFUSE', 1, pass_filter={'COLOR'})
    _save(img, os.path.join(out_dir, "%s_color.png" % space))
    clock.lap('color')
    # coverage: white where a face (or the bake margin) owns the texel, black elsewhere; edge texels
    # the pixel filter only partly covers come out grey and compose treats them as empty
    img = _image("%s_cov" % space, bake_size, linear=True)
    img.generated_color = (0.0, 0.0, 0.0, 1.0)
    _point(mats, img)
    with _EmitOverride(mats, flat=(1.0, 1.0, 1.0)):
        _bake(direct, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "%s_cov.png" % space))
    clock.lap('cov')
    for m in mats:
        if m.name in saved_palette:
            b = _bsdf(m)
            if b is not None:
                b.inputs['Base Color'].default_value = saved_palette[m.name]
        if m.name in saved_alpha:
            _bsdf(m).inputs['Alpha'].default_value = saved_alpha[m.name]
    # ambient occlusion, with FLAT normals: smooth normals across a shallow crease (the hood's two
    # character lines) tilt part of the hemisphere under the neighbouring face, and those rays hit
    # it at zero distance -> dashed dark streaks baked along the crease. Restored afterwards.
    img = _image("%s_ao" % space, bake_size, linear=True)
    _point(mats, img)
    scene.world.light_settings.distance = AO_DISTANCE
    all_his = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.endswith("_hi")]
    _flatten([h for h in all_his if not h.get("crv_flat")])      # the projected AO is taken on the twins:
    for h in all_his:                                             # flat there, once (they never ship)
        h["crv_flat"] = 1
    saved = _flatten(direct)
    _bake(direct, 'AO', AO_SAMPLES)
    _unflatten(direct, saved)                 # the low parts keep their normals for the projection cage
    _bake_hilo(pairs, 'AO', AO_SAMPLES)
    _rebake_open(space, direct, pairs, 'AO', AO_SAMPLES)
    _save(img, os.path.join(out_dir, "%s_ao.png" % space))
    clock.lap('ao')
    # cavity: a second AO pass with a 4 cm reach darkens panel gaps, seams and cast creases crisply
    # (pointiness blotched on the coarse kotris panels). Same flat-normal treatment as the AO above.
    img = _image("%s_cavity" % space, bake_size, linear=True)
    _point(mats, img)
    scene.world.light_settings.distance = CAVITY_DISTANCE
    saved = _flatten(direct)
    _bake(direct, 'AO', CAVITY_SAMPLES)
    _unflatten(direct, saved)
    _bake_hilo(pairs, 'AO', CAVITY_SAMPLES)
    _rebake_open(space, direct, pairs, 'AO', CAVITY_SAMPLES)
    _save(img, os.path.join(out_dir, "%s_cavity.png" % space))
    clock.lap('cavity')
    if space == "shell":
        # gap: a third AO pass with a 1.2 cm reach (GAP_DISTANCE). Open paint, even in a shallow
        # crease, sees nothing that close; only the shut lines, lamp recess edges and badge
        # outlines go dark, and compose thresholds the result into KI5-style seam lines.
        img = _image("shell_gap", bake_size, linear=True)
        _point(mats, img)
        scene.world.light_settings.distance = GAP_DISTANCE
        saved = _flatten(direct)
        _bake(direct, 'AO', GAP_SAMPLES)
        _unflatten(direct, saved)
        _bake_hilo(pairs, 'AO', GAP_SAMPLES)
        _rebake_open(space, direct, pairs, 'AO', GAP_SAMPLES)
        _save(img, os.path.join(out_dir, "shell_gap.png"))
        clock.lap('gap')
    # weathering: the dirt field (see _GrimeOverride), direct + projected like the colour
    img = _image("%s_grime" % space, bake_size, linear=True)
    img.generated_color = (0.0, 0.0, 0.0, 1.0)
    _point(mats, img)
    with _GrimeOverride(mats, space):
        _bake2(direct, pairs, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "%s_grime.png" % space))
    clock.lap('grime')
    if space in EDGE_SPACES:
        img = _image("%s_edge" % space, bake_size, linear=True)
        img.generated_color = (0.0, 0.0, 0.0, 1.0)
        _point(mats, img)
        saved = _flatten(direct)
        with _EmitOverride(mats, edge=True):
            _bake(direct, 'EMIT', EDGE_SAMPLES)
        _unflatten(direct, saved)
        _save(img, os.path.join(out_dir, "%s_edge.png" % space))
        clock.lap('edge')
    if space != "shell":
        _join_gen(gens)
        clock.total(size, bake_size)
        return
    # zones: exact colours through an emission shader fed by the per-face attribute
    _paint_zones(direct + his)
    img = _image("shell_zone", bake_size, linear=True)
    _point(mats, img)
    with _EmitOverride(mats):
        _bake2(direct, pairs, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "shell_zone.png"))
    clock.lap('zone')
    # lights: lamp materials emit, everything else black
    saved = {}
    for m in mats:
        b = _bsdf(m)
        if b is None:
            continue
        saved[m.name] = (tuple(b.inputs['Base Color'].default_value), tuple(b.inputs['Emission Color'].default_value),
                         b.inputs['Emission Strength'].default_value)
        b.inputs['Base Color'].default_value = (0, 0, 0, 1)
        col = LIGHT_MATS.get(m.name)
        b.inputs['Emission Color'].default_value = (col + (1.0,)) if col else (0, 0, 0, 1)
        b.inputs['Emission Strength'].default_value = 1.0 if col else 0.0
    img = _image("shell_lights", bake_size, linear=False)
    _point(mats, img)
    _bake2(direct, pairs, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "shell_lights.png"))
    clock.lap('lights')
    # lamp mask: lenses and reflectors sit in recesses the AO and cavity passes would blacken;
    # compose keeps them bright where this is white
    img = _image("shell_lampmask", bake_size, linear=True)
    img.generated_color = (0.0, 0.0, 0.0, 1.0)
    _point(mats, img)
    with _EmitOverride(mats, flat={n: (1.0, 1.0, 1.0) for n in LAMP_MATS}):
        _bake2(direct, pairs, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "shell_lampmask.png"))
    clock.lap('lampmask')
    # trim mask: interior trim that rides the shell sheet (tailgate card, door cards) sits in slots
    # a few centimetres deep where the AO pass reads black; compose lifts it
    img = _image("shell_trimmask", bake_size, linear=True)
    img.generated_color = (0.0, 0.0, 0.0, 1.0)
    _point(mats, img)
    with _EmitOverride(mats, flat={m.name: (1.0, 1.0, 1.0) for m in mats
                                   if m.name in TRIM_MATS or m.name.startswith(TRIM_PREFIXES)}):
        _bake2(direct, pairs, 'EMIT', 1)
    _save(img, os.path.join(out_dir, "shell_trimmask.png"))
    clock.lap('trimmask')
    for m in mats:
        b = _bsdf(m)
        if b is None or m.name not in saved:
            continue
        base, em, strength = saved[m.name]
        b.inputs['Base Color'].default_value = base
        b.inputs['Emission Color'].default_value = em
        b.inputs['Emission Strength'].default_value = strength
    _join_gen(gens)
    clock.total(size, bake_size)


def main():
    global BAKE_PNG
    out_dir, save, spaces, BAKE_PNG = _args()
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    try:
        scene.cycles.pixel_filter_type = 'BOX'   # no pixel-filter blending at island edges
        scene.cycles.filter_width = 0.01
    except Exception as exc:                     # noqa: BLE001
        print("bake: pixel filter not narrowed (%s)" % exc)
    # one render tile per bake image: at the default 2048 tile a 4096 bake went through four tiles and
    # their merge, 97 s against 74 s for the same pass (scratch prof_bake, 2026-10-13)
    scene.cycles.tile_size = max(SUPERSAMPLE * size for _names, size in SPACES.values())
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    print("bake: device", _gpu())
    tyre_paint.paint(BAKE_PNG)                   # tyre maps and the cover print, from this checkout's painter
    door_cards.paint_all(BAKE_PNG)               # cards along their true outlines (prep_parts' copy uses the box)
    cargo_bay_paint.paint(BAKE_PNG)                  # cargo deck, side trim and table-top maps (TEXTURED_BY_SPACE
                                                 # interior, TEXTURED AccTable)
    _door_card_layers()
    _cover_layers()
    for feat, _r in features.call("BAKE_PAINT", BAKE_PNG):   # the plugins' painted maps, then their material stacks
        print("bake: feature %s painted its maps" % feat)
    extra = features.bake_textured()
    clash = sorted(set(extra) & set(TEXTURED))
    if clash:
        raise RuntimeError("bake: feature BAKE_TEXTURED redefines materials %s" % ", ".join(clash))
    TEXTURED.update(extra)
    for space in spaces:
        names, size = SPACES[space]
        bake_space(space, names, size, out_dir)
        print("bake: %s done" % space)
    bpy.ops.wm.save_as_mainfile(filepath=save)
    print("BAKE DONE ->", out_dir, "saved", save)


# Blender's --python runs this file as __main__; a harness imports it (spec/planar-texture-plan.md A5)
if __name__ == "__main__":
    main()
