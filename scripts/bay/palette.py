"""The engine bay v2 palette (no bpy: kit.py and the Pillow paint modules both read it).

Flat colours, LINEAR rgb + roughness. Values are held down on purpose: the game lights the open bay
brightly and the vehiclewheel shader has no paint tint (so nothing here is body colour: the towers,
support and firewall are bay_walls on the painted shell sheet). Read against the photos in
blender/references/engine_bay: a dark bay, the cast plenum and the heat shield the two bright areas,
the caps the only colour. A decal painted in Pillow is sRGB: srgb(name) gives a palette colour's
8-bit sRGB value so a decal's ground matches the flat parts around it exactly.
"""
PALETTE = {
    "CoverBlack":  ((0.016, 0.016, 0.017), 0.90),   # cam cover crinkle black
    # 2026-10-17 (review BAY-6): baked, the shield came out 80-83 against the plenum's 98, the alternator / head
    # 73-82 and the bottles 103-124. In lhd_03 / lhd_06 the shield is the bright silver with the plenum, the dull
    # castings sit well under both and the bottles under the plenum: shield up, dull alu and reservoir down.
    "AluCast":     ((0.175, 0.172, 0.165), 0.55),   # upper intake plenum, throttle body: the brightest metal
    "AluDull":     ((0.070, 0.069, 0.066), 0.70),   # head, transmission case, alternator, brackets: weathered
    "ShieldSteel": ((0.210, 0.204, 0.190), 0.60),   # exhaust heat shield, pressed steel
    "Iron":        ((0.045, 0.043, 0.042), 0.85),   # block, exhaust manifold
    "BlackPaint":  ((0.028, 0.028, 0.030), 0.70),   # booster, hold-downs, brackets, rails
    "Plastic":     ((0.022, 0.022, 0.024), 0.80),   # airbox, fuse box, covers, shrouds, tanks
    "PlasticGrey": ((0.055, 0.055, 0.058), 0.80),   # connectors, aged plastic, the distributor cap
    "Rubber":      ((0.012, 0.012, 0.012), 0.95),   # hoses, belts, wires, the harness loom
    "Reservoir":   ((0.200, 0.192, 0.162), 0.50),   # translucent aged white plastic
    "WireGrey":    ((0.150, 0.150, 0.152), 0.75),   # the light-grey plug wires of the LHD cars (lhd_03 / lhd_06)
    "CapYellow":   ((0.700, 0.500, 0.040), 0.50),   # dipstick loop, oil / power steering caps
    "CapBlue":     ((0.150, 0.380, 0.550), 0.50),   # washer filler (light blue in the photos)
    "CapRed":      ((0.420, 0.030, 0.025), 0.55),   # battery + cover
    "Copper":      ((0.380, 0.150, 0.065), 0.50),   # the copper line across the front (photos)
    "Steel":       ((0.220, 0.220, 0.230), 0.40),   # clamps, bolts, the radiator cap, the prop rod
    "RadCore":     ((0.040, 0.040, 0.042), 0.80),   # radiator / condenser fins
    "Grey":        ((0.080, 0.080, 0.082), 0.85),   # subframe, undertray bits: not paint
}


def to_srgb8(c):
    c = max(0.0, min(1.0, c))
    s = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return int(round(s * 255))


def srgb(name):
    """8-bit sRGB of a palette colour, for Pillow."""
    return tuple(to_srgb8(c) for c in PALETTE[name][0])
