r"""
Painted tyre and spare-cover decals (2026-10-12, feedback: "the tires, they need more textures", "the
back tire also need more work"). Runs inside Blender: bake_atlas calls paint() before it builds the
`tyremap` / cover layers, so the PNGs are always those of the scripts that bake them.

    import tyre_paint; tyre_paint.paint(out_dir)

Writes into out_dir (blender/bake in the build):
  tyre_tread.png  2048 x 192  the tread, unrolled: u = angle round the axle, v = across the tread
                              (t from -TREAD_HALF to +TREAD_HALF along the axle)
  tyre_side.png   2048 x 128  one sidewall, unrolled: u = angle (clockwise seen from that side, so
                              the lettering reads left to right over the top), v = radius from the
                              bead (R_BEAD) up to the shoulder (R_SHOULDER)
  spare_cover.png  512 x 512  the soft spare-tyre cover's face: CR-V lettering and a piped rim
  tail_lens.png    160 x 512  the tail lamp lens in its own frame (amber, red, reverse), a colour
                              multiplier on the lens materials (see TAIL_PNG)
Each tyre map stores a MULTIPLIER on the rubber colour (byte = m / MAP_SCALE * 255, read Non-Color
and scaled back by the bake layer), so the palette keeps the rubber's colour and the maps only shape
it. The cover decal is a colour (sRGB, read like the other decals).

What is drawn (a 205/70R15 all-season like the RD1's OEM tyre, judged at the game's 150 px/m against
KI5's tyres, whose 256 px wheel sheets carry a block tread strip and a sidewall with shoulder lugs,
a lettering ring and the rim): tread = four circumferential grooves (11 mm, two texels on the
wheel sheet), slanted slots between the intermediate blocks, straight lateral grooves through the
shoulder blocks, a sipe in every block; sidewall = bead seat, a raised rim-protector rib with a
dark line, a smooth lettering band between two thin rings holding a brand-like word (twice) and the
size / construction text, and shoulder lugs lined up with the tread pitch. The lettering is not a
real brand. Letters are Blender's own font outlines (bpy text -> mesh -> triangles rasterised with
numpy): Blender's OpenImageIO has no FreeType, and PIL is not in Blender's Python.
"""
import math
import os

import bpy
import numpy as np

TREAD_PNG = "tyre_tread.png"
SIDE_PNG = "tyre_side.png"
COVER_PNG = "spare_cover.png"
# the tyre (kotris wheel_FR_hi and the spare in trunk_hi, measured 2026-10-12): crown r 0.3356, bead
# r 0.2086, section half-width 0.1071 at r 0.27; the tread map takes over above R_SHOULDER
R_BEAD = 0.2086
R_CROWN = 0.3356
R_SHOULDER = R_CROWN - 0.012
TREAD_HALF = 0.10
PITCHES = 60                       # tread pitches round the tyre: 3.5 cm at the crown
# Resolution (2026-10-13, the anti-aliased bake): the wheel sheet went 256 -> 512 and every space bakes
# at 2x its sheet (bake_atlas.SUPERSAMPLE), so the road tyre bakes at ~9 texels/cm (1.1 mm a sample)
# where it took ~2 a texel before. The maps doubled to ~20 px/cm so they stay finer than the bake's
# samples, the prefilters dropped from about a shipped texel to about a BAKE texel (compose's 2x2 box
# then anti-aliases at the sheet), and the masks' own supersampling went 3 -> 2 at the doubled size
TREAD_W, TREAD_H = 4096, 384       # 19.4 px/cm round the crown, 19.2 across the 20 cm tread
SIDE_W, SIDE_H = 4096, 256         # 24 px/cm round the lettering band, 22 up the sidewall
COVER_SIZE = 1024                  # 17 px/cm
COVER_HALF = 0.30                  # the cover decal spans +-0.30 m about the spare's centre
SS = 2                             # supersampling for the antialiased masks
MAP_SCALE = 4.0                    # tyre maps store multiplier / MAP_SCALE (the letters reach 3.4)
# prefilters (_blur), in map pixels, about one BAKE texel: the road tyre bakes at ~9 texels/cm (2.2 px
# a sample), the spare on the shell at ~6 (3.3 px): 3 px is a bake texel between them; the cover's face
# bakes at ~4.8 texels/cm (3.5 px a sample of the 17 px/cm print). Checked 2026-10-13 (texture fix): k = 3
# is a sigma of 1.15 px (two box passes, sqrt((k^2 - 1) / 6)), about HALF a bake texel on both tyres (the
# spare now ~8.4 bake texels/cm, bake_atlas.SPARE_TYRE_WEIGHT), k = 4 on the cover 1.58 px, half of its
# 3.1 px: already where the other painters were halved to, so unchanged
BLUR_TYRE, BLUR_COVER = 3, 4
BLUR_LENS = 3                      # the tail lens map: 20 px/cm, the lens bakes at ~6 texels/cm (3.3 px a sample)
BRAND = "KESTREL"                  # brand-LIKE word: not a real tyre maker
SIZE_TEXT = "P205/70R15  95S"
SMALL_TEXT = "RADIAL TUBELESS   M+S"
FONTS = (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\ariblk.ttf")   # else Blender's built-in font

# multipliers on the rubber (Pneu 0.020 linear = sRGB 39 before shading). KI5's tread spans sRGB 18-52
# (0.3x to 1.7x of our rubber in linear), its sidewall ~28 with lettering 50-80 (up to ~4.5x). A first
# pass at letters 2.2x / blocks 1.12x was invisible at the game's 150 px/m (a plain black sidewall)
GROOVE, SLOT, SIPE, BLOCK = 0.28, 0.42, 0.85, 1.45
BEAD, PROTECTOR, PROT_LINE, RING, BAND, LETTER, UPPER, LUG_NOTCH, LUG = 0.78, 2.20, 0.65, 1.80, 1.12, 3.40, 0.95, 0.45, 1.30
BRAND_FONTS = (r"C:\Windows\Fonts\ariblk.ttf",) + FONTS     # the brand word in a heavier face


# ----------------------------------------------------------------------------------------------
# rasterising


def _font(paths=FONTS):
    for path in paths:
        if os.path.exists(path):
            try:
                return bpy.data.fonts.load(path, check_existing=True)
            except RuntimeError:
                continue
    return None


def text_tris(text, font=None):
    """Filled outline of `text` as triangles (n, 3, 2) in font units (size 1, baseline y 0), and the
    advance width. Blender evaluates a text curve to a filled mesh; nothing is left in the file."""
    cu = bpy.data.curves.new("crv_tyre_txt", 'FONT')
    cu.body = text
    if font is not None:
        cu.font = font
    cu.size = 1.0
    ob = bpy.data.objects.new("crv_tyre_txt", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    co = np.array([v.co[:2] for v in me.vertices], dtype=np.float64).reshape(-1, 2)
    idx = np.array([t.vertices[:] for t in me.loop_triangles], dtype=np.int64).reshape(-1, 3)
    pts = co[idx] if len(idx) else np.zeros((0, 3, 2))
    ev.to_mesh_clear()
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.curves.remove(cu)
    return pts


def fill_tris(img, tris, value=1.0):
    """Set every pixel whose centre lies in one of the triangles (pixel units, x right, y up = row)."""
    h, w = img.shape
    for tri in tris:
        x0, y0 = np.floor(tri.min(axis=0)).astype(int)
        x1, y1 = np.ceil(tri.max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w - 1), min(y1, h - 1)
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px, py = xs + 0.5, ys + 0.5
        (ax, ay), (bx, by), (cx, cy) = tri
        d = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(d) < 1e-12:
            continue
        s = np.sign(d)
        e0 = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) * s
        e1 = ((cx - bx) * (py - by) - (cy - by) * (px - bx)) * s
        e2 = ((ax - cx) * (py - cy) - (ay - cy) * (px - cx)) * s
        inside = (e0 >= 0) & (e1 >= 0) & (e2 >= 0)
        img[y0:y1 + 1, x0:x1 + 1][inside] = value


def place_text(img, text, cx, base_y, cap_h, font, stretch=1.0, value=1.0):
    """Draw text centred on column cx with its baseline at row base_y, capitals cap_h pixels tall
    (Arial's capitals are 0.716 of the size); stretch widens it. Wraps round in x (the maps are
    rings). Returns the drawn width in pixels."""
    tris = text_tris(text, font)
    if not len(tris):
        return 0.0
    k = cap_h / 0.716
    xs = tris[..., 0]
    width = (xs.max() - xs.min()) * k * stretch
    out = tris.copy()
    out[..., 0] = (tris[..., 0] - xs.min()) * k * stretch + cx - width / 2.0
    out[..., 1] = tris[..., 1] * k + base_y
    w = img.shape[1]
    for shift in (-w, 0, w):                         # ring maps: text crossing the seam continues
        moved = out.copy()
        moved[..., 0] += shift
        fill_tris(img, moved, value)
    return width


def _down(a, k=SS):
    h, w = a.shape
    return a.reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def _blur(a, k, wrap_x=True):
    """Two box passes of k pixels each way (about a Gaussian of sigma 0.58 k): the colour bake takes
    ONE sample per texel (narrow box pixel filter, so islands never blend), which point-samples
    these maps. Unfiltered, a 1.4 cm ring on the cover's face came out as dashes and the
    lettering as stair steps; prefiltered to about half a destination texel they come out smooth."""
    if k <= 1:
        return a
    out = a.astype(np.float64)
    for _ in range(2):
        acc = np.zeros_like(out)
        for d in range(-(k // 2), k - k // 2):
            acc += np.roll(out, d, axis=1) if wrap_x else np.take(out, np.clip(np.arange(out.shape[1]) + d, 0, out.shape[1] - 1), axis=1)
        out = acc / k
        acc = np.zeros_like(out)
        for d in range(-(k // 2), k - k // 2):
            acc += np.take(out, np.clip(np.arange(out.shape[0]) + d, 0, out.shape[0] - 1), axis=0)
        out = acc / k
    return out


def _save(arr, path, scale=1.0, srgb=False):
    """arr (rows from the BOTTOM, i.e. Blender's pixel order) -> 8-bit PNG storing arr * scale, or
    the sRGB encoding of arr (a linear colour) for a decal the bake reads as sRGB. The byte buffer's
    `pixels` are the stored values: nothing is encoded on save."""
    h, w = arr.shape[:2]
    rgb = np.clip(arr * scale, 0.0, 1.0)
    if srgb:
        rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=2)
    rgba = np.concatenate([rgb, np.ones((h, w, 1))], axis=2).astype(np.float32)
    name = "crv_" + os.path.basename(path)
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=False)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


# ----------------------------------------------------------------------------------------------
# tread


def tread_map():
    """Multiplier map of the tread (rows = t from -TREAD_HALF up, columns = angle)."""
    W, H = TREAD_W * SS, TREAD_H * SS
    circ = 2.0 * math.pi * R_CROWN
    s = (np.arange(W) + 0.5) / W * circ                          # metres round the crown
    t = (np.arange(H) + 0.5) / H * 2.0 * TREAD_HALF - TREAD_HALF  # metres across, -TREAD_HALF..+
    S, T = np.meshgrid(s, t)
    A = np.abs(T)
    p = circ / PITCHES
    ph = (S / p) % 1.0                                            # phase within a pitch
    m = np.full((H, W), BLOCK)
    # sipes first, grooves over them
    centre = A < 0.0165
    mid = (A > 0.0275) & (A < 0.0525)
    sh = A > 0.0635
    # centre rib: two slanted sipes per pitch and short notches from both grooves, staggered
    q = ((S + 0.5 * T) / (p / 2.0)) % 1.0
    m[centre & (np.abs(q - 0.5) < 0.05)] = SIPE
    qn = (S / p + np.where(T > 0, 0.0, 0.5)) % 1.0
    m[centre & (A > 0.0095) & (np.abs(qn - 0.5) < 0.09)] = SLOT
    # intermediate blocks: slots slanted ~35 deg, the two sides half a pitch apart, a sipe mid-block
    side = np.where(T > 0, 0.0, 0.5)
    qm = ((S + 0.70 * (A - 0.0275)) / p + side) % 1.0
    m[mid & (np.abs(qm - 0.5) < 0.04)] = SIPE
    m[mid & ((qm < 0.11) | (qm > 0.89))] = SLOT
    # shoulder blocks: straight lateral grooves, a sipe between, both reaching off the edge
    qs = ((S + 0.20 * (A - 0.0635)) / p + 0.25 + side) % 1.0
    m[sh & (np.abs(qs - 0.5) < 0.035)] = SIPE
    m[sh & ((qs < 0.13) | (qs > 0.87))] = SLOT
    # four circumferential grooves, 11 mm
    for c in (0.022, 0.058):
        m[np.abs(A - c) < 0.0055] = GROOVE
    # off the contact patch (the rounded shoulder) the rubber is a touch darker
    m = np.where(A > 0.086, m * 0.92, m)
    return _down(m), ph


# ----------------------------------------------------------------------------------------------
# sidewall


def side_map(font, brand_font=None):
    """Multiplier map of a sidewall (rows = r from R_BEAD up to R_SHOULDER, columns = angle,
    clockwise seen from that side)."""
    brand_font = brand_font or font
    W, H = SIDE_W * SS, SIDE_H * SS
    r = R_BEAD + (np.arange(H) + 0.5) / H * (R_SHOULDER - R_BEAD)
    m = np.ones((H, W)) * 1.0

    def band(r0, r1, val):
        rows = (r >= r0) & (r < r1)
        m[rows, :] = val
    band(R_BEAD, 0.2126, BEAD)                      # bead seat against the rim flange
    band(0.2135, 0.2190, PROTECTOR)                 # raised rim-protector rib
    band(0.2195, 0.2220, PROT_LINE)                 # its shadow line
    band(0.2310, 0.2322, 1.10)                      # two fine moulding lines
    band(0.2385, 0.2397, 1.10)
    band(0.2465, 0.2485, RING)                      # rings round the lettering band
    band(0.2485, 0.2855, BAND)
    band(0.2855, 0.2875, RING)
    band(0.2875, 0.3080, UPPER)
    # shoulder lugs, lined up with the tread pitch (column = angle; clockwise from this side)
    lug_rows = r >= 0.3100
    cols = (np.arange(W) + 0.5) / W
    ph = (cols * PITCHES) % 1.0
    notch = (ph < 0.13) | (ph > 0.87)
    m[np.ix_(lug_rows, notch)] = LUG_NOTCH
    m[np.ix_(lug_rows, ~notch)] = LUG
    # lettering, laid out at the band's mid radius
    rpx = H / (R_SHOULDER - R_BEAD)                 # rows per metre
    r_mid = 0.2670
    cpx = W / (2.0 * math.pi * r_mid)               # columns per metre at the band's middle
    letters = np.zeros((H, W))
    big = 0.028                                     # brand capitals, metres (4 px at the game's zoom)
    small = 0.0135
    base_big = (0.2670 - big / 2.0 - R_BEAD) * rpx
    base_small = (0.2670 - small / 2.0 - R_BEAD) * rpx
    for u in (0.0, 0.5):
        place_text(letters, BRAND, u * W + 0.25 * W, base_big, big * rpx, brand_font, stretch=1.25 * cpx / rpx)
    place_text(letters, SIZE_TEXT, 0.50 * W, base_small, small * rpx, font, stretch=1.1 * cpx / rpx)
    place_text(letters, SMALL_TEXT, 0.0 * W, base_small, small * rpx, font, stretch=1.1 * cpx / rpx)
    m = np.where(letters > 0, LETTER, m)
    return _down(m)


# ----------------------------------------------------------------------------------------------
# spare cover


COVER_BG, COVER_INK = 0.030, 0.42      # linear: black vinyl, silver-grey print


# Polish round 2 (R2-WA-3): the two rings (1.4 and 0.8 cm, 1.2 cm apart) beat against the texel grid at the
# default 512 cap (~0.6 texels/cm on the cover) into a dotted zipper, and Arial Bold's 1.5 cm strokes with ~1 cm
# between letters smeared "CR-V" into one blob. One ring 2.4 cm wide, and the letters in Arial Black (strokes
# ~2.5 cm) set one by one with COVER_TRACK between their ink: every stroke and gap >= the playbook's 1.2 cm.
# A 1.6 cm ring still beaded a little at the cap (under one 512 texel); 2.4 cm is ~1.5 of them
COVER_RING = (0.241, 0.265)            # the printed ring's inner and outer radius, metres
COVER_CAP = 0.125                      # letter height, metres
COVER_TRACK = 0.020                    # gap between the letters' ink, metres
COVER_TEXT_W = 0.40                    # the word's widest (it sits inside the ring)


def cover_map(font, heavy=None):
    """The cover's face as seen from behind the car (u = +x = the viewer's right, v = up), linear
    colour: black vinyl, CR-V lettering and one printed ring 3.5 cm inside the face's edge."""
    n = COVER_SIZE * SS
    px_m = n / (2.0 * COVER_HALF)
    ink = np.zeros((n, n))
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(xx + 0.5 - n / 2.0, yy + 0.5 - n / 2.0) / px_m
    ink[(rr > COVER_RING[0]) & (rr < COVER_RING[1])] = 1.0
    # the letters one by one: ink extents in font units (cap 0.716 of the size), laid out with COVER_TRACK between
    k = COVER_CAP / 0.716                            # metres per font unit
    glyphs = [text_tris(ch, heavy or font) for ch in "CR-V"]
    widths = [(g[..., 0].max() - g[..., 0].min()) * k if len(g) else 0.0 for g in glyphs]
    total = sum(widths) + COVER_TRACK * (len(glyphs) - 1)
    squeeze = min(1.0, COVER_TEXT_W / total)         # keep the word inside the ring
    x = -total * squeeze / 2.0
    base = -COVER_CAP / 2.0
    for g, w in zip(glyphs, widths):
        if len(g):
            t = g.copy()
            t[..., 0] = ((g[..., 0] - g[..., 0].min()) * k * squeeze + x) * px_m + n / 2.0
            t[..., 1] = (g[..., 1] * k + base) * px_m + n / 2.0
            fill_tris(ink, t, 1.0)
        x += (w + COVER_TRACK) * squeeze
    ink = _down(ink)
    col = COVER_BG + (COVER_INK - COVER_BG) * ink
    return col


# ----------------------------------------------------------------------------------------------
# tail lamp lens (2026-10-13, screenshot 17.png "the rear lights are weird")
#
# The old tail_ribs.png (paint_engine_decals) mapped u by y on every lens face: kotris's lens is one
# strip leaning 28 degrees (the D-pillar's rake and tumblehome) and wrapping from rear- to side-facing,
# so its "vertical" ribs ran 16-32 degrees across the lens and the bars at constant z crossed them: a
# hatched grille. Its y range also missed most of the reverse lens, whose faces then sampled the
# decal's dark border (half the lamp black). This map lies in the lens's own frame instead: u across
# the lamp, v along it (bake_atlas TEXTURED maps both by a direction with |x|, so one entry serves both
# lamps), and it draws the RD1 lens as the photos show it (commons: the 2000 EX and 1998 LX rear
# lefts, high-passed): amber on top with a plain bright frame along its top and outer side round a
# gridded inner block, a red lens with a faint pillow grid inside a plain margin, a moulded divider
# between them, and the clear reverse lens at the bottom, framed in the red, with a grid of upright
# cells. It is a MULTIPLIER (sRGB-encoded, read as colour) on each lens material's PALETTE colour;
# paint_pass's LAMP_L then sets each lens's level, and the outline is paint_pass's lamp bezel.
TAIL_PNG = "tail_lens.png"
TAIL_U_AXIS = (0.658, 0.743, -0.118)   # across the lens (outboard and forward), |x|: kotris body_hi's tail
TAIL_V_AXIS = (-0.276, 0.384, 0.881)   # lens: its plane's long axis (PCA) and the in-plane perpendicular
TAIL_U = (-1.2005, -1.0405)            # the map's extent in metres along each axis: the lens (u -1.1945 ..
TAIL_V = (0.085, 0.597)                # -1.0454, v 0.0975 .. 0.5799) plus ~6 mm. bake_atlas.TEXTURED repeats these
TAIL_PX_M = 2000.0                     # 20 px/cm: the lens bakes at ~6 texels/cm (2.8 on the sheet x SUPERSAMPLE)
# the outline in the lens frame (u, v), from kotris body_hi's open edges and material boundaries
_TAIL_OUT = ((0.1163, -1.0454), (0.1784, -1.0502), (0.2405, -1.0551), (0.3484, -1.0637), (0.4126, -1.0672),
             (0.4625, -1.0715), (0.5212, -1.0772), (0.5799, -1.0831))      # outboard edge u(v)
_TAIL_IN = -1.1945                                                         # inboard edge
_TAIL_TOP = ((-1.1945, 0.5661), (-1.1597, 0.5669), (-1.1444, 0.5679), (-1.1285, 0.5698), (-1.1123, 0.5729),
             (-1.0966, 0.5776), (-1.0831, 0.5799))                         # top edge v(u)
_TAIL_BOT = ((-1.1945, 0.0985), (-1.1094, 0.0993), (-1.0878, 0.1024), (-1.0670, 0.1082), (-1.0454, 0.1163))
_TAIL_AMBER = ((-1.1945, 0.4011), (-1.1410, 0.4010), (-1.1217, 0.4022), (-1.1017, 0.4045), (-1.0834, 0.4082),
               (-1.0454, 0.4170))                                          # amber above, red below
_REV_U = (-1.1805, -1.0641)
_REV_BOT = ((-1.1805, 0.1095), (-1.1748, 0.1054), (-1.1517, 0.1040), (-1.1311, 0.1045), (-1.1099, 0.1063),
            (-1.0882, 0.1094), (-1.0725, 0.1129), (-1.0641, 0.1221))
_REV_TOP = ((-1.1805, 0.1470), (-1.1728, 0.1552), (-1.1529, 0.1556), (-1.1330, 0.1561), (-1.1119, 0.1576),
            (-1.0897, 0.1609), (-1.0743, 0.1639), (-1.0641, 0.1562))
# multipliers (linear) on the lens colours; KI5 draws its lenses' pattern at roughly +-15 % of the lens
AMBER_FRAME = (1.0, 1.0, 1.0)          # the bright yellow-orange frame (PALETTE Feux_orange as is)
AMBER_INNER = (0.82, 0.68, 0.45)       # the inner block, deeper orange (photos: frame lighter and yellower)
AMBER_FRAME_W = (0.018, 0.018, 0.005)  # frame width along the top, the outer side, the inner side (metres)
CELL = 0.014                           # grid pitch in the amber block and the red lens (metres): 4 texels, 4.6 px at
                                       # 326 px/m (1.1 cm, 3 texels, aliased into an uneven, barely visible mesh)
GRID_LINE = 0.0035                     # grid line width: one texel (the bake point-samples; thinner lines beaded)
GRID_AMBER, GRID_RED_V, GRID_RED_U = 0.76, 0.74, 0.88    # line multipliers (rows across the lamp, columns along)
ROW_SLOPE = 0.11                       # dv/du of the lens's cross lines (divider 0.10, bottom edge 0.12)
RED_MARGIN = 0.012                     # plain margin inside the red lens's outline
RED_DEPTH = 0.15                       # the red lens reads deeper towards its sides (the reflector bowl behind)
DIVIDER_W, DIVIDER_K = 0.0035, 0.55    # moulded wall between amber and red (each side), and round the reverse lens
REV_COLS, REV_LINE, REV_K = 7, 0.0035, 0.72              # reverse lens: upright cells, line width, line multiplier


def _band(x, w):
    """1 inside a band of half-width w around 0, 0 outside, anti-aliased over a pixel width of the map."""
    px = 1.0 / TAIL_PX_M / SS
    return np.clip((w - np.abs(x)) / px + 0.5, 0.0, 1.0)


def _grid(c, pitch, width):
    """1 on the lines of a grid of `pitch` along coordinate c (lines `width` wide), 0 between."""
    return _band(((c / pitch + 0.5) % 1.0 - 0.5) * pitch, width / 2.0)


def tail_lens_map():
    """(H, W, 3) linear multiplier, rows from v TAIL_V[0] up, columns from u TAIL_U[0] (inboard)."""
    W = int(round((TAIL_U[1] - TAIL_U[0]) * TAIL_PX_M)) * SS
    H = int(round((TAIL_V[1] - TAIL_V[0]) * TAIL_PX_M)) * SS
    u = TAIL_U[0] + (np.arange(W) + 0.5) / W * (TAIL_U[1] - TAIL_U[0])
    v = TAIL_V[0] + (np.arange(H) + 0.5) / H * (TAIL_V[1] - TAIL_V[0])
    U, V = np.meshgrid(u, v)

    def interp_u(pts):                       # v of a boundary at each column
        p = np.array(pts)
        return np.interp(U, p[:, 0], p[:, 1])
    u_out = np.interp(V, *np.array(_TAIL_OUT).T)
    v_top, v_bot, v_amb = interp_u(_TAIL_TOP), interp_u(_TAIL_BOT), interp_u(_TAIL_AMBER)
    v_rb, v_rt = interp_u(_REV_BOT), interp_u(_REV_TOP)
    amber = V >= v_amb
    rev = (U >= _REV_U[0]) & (U <= _REV_U[1]) & (V >= v_rb) & (V <= v_rt)
    d_in, d_out = U - _TAIL_IN, u_out - U                      # distances to the outline (metres)
    d_top, d_bot, d_amb = v_top - V, V - v_bot, np.abs(V - v_amb)
    m = np.ones((H, W, 3))
    # amber: plain frame along the top and both sides round a deeper, gridded block
    frame = (d_top < AMBER_FRAME_W[0]) | (d_out < AMBER_FRAME_W[1]) | (d_in < AMBER_FRAME_W[2])
    inner = amber & ~frame
    row = V - ROW_SLOPE * (U - _TAIL_IN)                       # rows parallel to the divider and the bottom edge
    gl = np.maximum(_grid(U - _TAIL_IN - AMBER_FRAME_W[2], CELL, GRID_LINE), _grid(row - _TAIL_AMBER[0][1], CELL, GRID_LINE))
    m[inner] = np.array(AMBER_INNER) * (1.0 + (GRID_AMBER - 1.0) * gl[inner])[:, None]
    m[amber & frame] = AMBER_FRAME
    # red: a plain margin, then a faint pillow grid; a little deeper towards the sides
    d_red = np.minimum.reduce([d_in, d_out, d_bot, d_amb])
    across = np.clip((U - _TAIL_IN) / np.maximum(u_out - _TAIL_IN, 1e-6), 0.0, 1.0)
    depth = 1.0 - RED_DEPTH * (2.0 * across - 1.0) ** 2
    red = ~amber & ~rev
    gr = np.where(d_red > RED_MARGIN, 1.0 + (GRID_RED_V - 1.0) * _grid(row - _TAIL_BOT[0][1], CELL, GRID_LINE), 1.0)
    gr = gr * np.where(d_red > RED_MARGIN, 1.0 + (GRID_RED_U - 1.0) * _grid(U - _TAIL_IN, CELL, GRID_LINE * 0.8), 1.0)
    m[red] = (depth * gr)[red][:, None]
    # the reverse lens: upright cells, lighter across their middles
    ru = (U - _REV_U[0]) / (_REV_U[1] - _REV_U[0])
    rv = np.clip((V - v_rb) / np.maximum(v_rt - v_rb, 1e-6), 0.0, 1.0)
    pitch = (_REV_U[1] - _REV_U[0]) / REV_COLS
    lines = np.maximum(_grid(U - _REV_U[0], pitch, REV_LINE), _band((rv - 0.5) * (v_rt - v_rb), REV_LINE / 2.0))
    cellv = (rv * 2.0) % 1.0
    m[rev] = ((1.0 + (REV_K - 1.0) * lines) * (0.92 + 0.08 * np.sin(np.pi * cellv)))[rev][:, None]
    # moulded walls: amber / red divider, the ring round the reverse lens (both sides of its outline)
    wall = _band(V - v_amb, DIVIDER_W)
    d_rev = np.minimum.reduce([np.abs(U - _REV_U[0]), np.abs(U - _REV_U[1]), np.abs(V - v_rb), np.abs(V - v_rt)])
    near_rev = (U > _REV_U[0] - 0.004) & (U < _REV_U[1] + 0.004) & (V > v_rb - 0.004) & (V < v_rt + 0.004)
    wall = np.maximum(wall, np.where(near_rev, _band(d_rev, DIVIDER_W), 0.0))
    m *= (1.0 + (DIVIDER_K - 1.0) * wall)[..., None]
    out = np.stack([_down(m[..., c]) for c in range(3)], axis=2)
    return out


# ----------------------------------------------------------------------------------------------
# headlamp (2026-10-13, screenshot 25.png: the unlit headlamp "looks black")
#
# What the clear lens shows, as the RD1's (commons: the 2000 EX front right): the big inboard cell's
# reflector bowl round its bulb, the outboard lower cell's smaller bowl with the amber turn-signal
# bulb behind clear glass, the outboard upper strip's vertical flutes (the side lamp), grey housing
# walls between the cells. The old headlight.png (paint_engine_decals) drew two equal bowls and 0.7 mm
# flutes the bake point-samples at ~3.6 mm a texel: dotted moire on the lens. Every feature here is at
# least a texel wide and the map is prefiltered (BLUR_HEAD). It is a COLOUR (sRGB, replace) on the
# low Phare / Phare_vitre, mapped like headlight.png (|x| 0.442..0.784, z 0.738..0.894) so compose's
# lights_lit reads the same picture for the lit lamp; paint_pass's LAMP_L sets the unlit level.
HEAD_PNG = "headlamp_lens.png"
HEAD_X = (0.442, 0.784)                # |x| and z extent (metres), = bake_atlas.TEXTURED Phare / Phare_vitre
HEAD_Z = (0.738, 0.894)
HEAD_PX_M = 2000.0                     # 20 px/cm (the lens bakes at ~5.6 texels/cm: 2.8 on the sheet x SUPERSAMPLE)
# kotris body_hi's lens pieces (|x|, z boxes) and the two bulbs (closed Phare / Phare_orange shapes)
HEAD_CELLS = {"main": (0.442, 0.689, 0.741, 0.890), "turn": (0.699, 0.784, 0.742, 0.837),
              "side": (0.691, 0.772, 0.845, 0.894)}
HEAD_BULB = (0.547, 0.793)             # the main cell's bulb (|x|, z)
HEAD_TURN_BULB = (0.725, 0.787)        # the amber turn-signal bulb behind the outboard lower cell
# 2026-10-17 lighting pass (feedback: "really upgrade ... the headlights"; Project Viewpoint shows the lamp up close):
# the 2000 EX photo's lamp is bright chrome behind clear glass, silver cell walls, horizontal lens flutes in
# the two outboard cells and across the main lens, no dark walls. paint_pass.LAMP_L sets the median (170).
HEAD_SRGB = {"housing": 0.80, "wall": 0.70, "bowl": 0.95, "bowl_rim": 0.76, "cap": 0.99, "socket": 0.58,
             "shield": 0.90, "turn_bulb": (0.90, 0.60, 0.20), "flute_hi": 0.92, "flute_lo": 0.70}
# Polish round 2 (R2-EXT-3, 2026-10-17): with every term between 0.70 and 0.95 the lens shipped flat 166-195 and
# read as frosted grey plastic. A chrome reflector shows its surroundings: in the photos (commons 2000 EX front right,
# the 1999 LX in Sebring Silver) the bowl is bright above the bulb (sky), a dark band runs through it a little under
# the bulb (the horizon / the road's shadow), the lower bowl is mid-dark, each of its concentric facet rings is light
# at its inner edge and darker at its outer one, and there are hard white highlights on the upper rim. The terms
# below are sRGB (0..1) and the median stays ~0.70, so paint_pass.LAMP_L (170) keeps the lamp as bright as before
# (scale ~0.95) and the lit lamp (compose.lights_lit, LIGHT_DETAIL) keeps the same structure. Every feature that
# must survive the 512 cap (the bowl's light top and dark band, the highlights) is >= 1.5 cm.
CHROME = {"sky": 0.97, "horizon": 0.32, "ground": 0.58, "ring_k": 0.16, "facet_k": 0.05, "spec": 1.0,
          "wall": 0.62, "wall_hi": 0.90, "deep": 0.40, "flute_hi": 0.93, "flute_lo": 0.56}
HEAD_FLUTE = 0.008                     # the side lamp's flute pitch: 2.2 texels on the 2048 sheet (5 mm aliased)
HEAD_RINGS = 3                         # concentric facet rings across the main bowl (R 0.11 m: ~3.7 cm a ring)
HEAD_HORIZON = (-0.014, 0.012)         # the dark band: centre (m from the bulb's z) and half width (>= 1.5 cm wide
                                       # at its core after the x1.6 ramp)
BLUR_HEAD = 3


def _chrome_bowl(X, Z, cx, cz, R, rings, wall_d):
    """sRGB 0..1 of a faceted chrome reflector round a bulb at (cx, cz), radius R: environment by height (sky above,
    a dark horizon band just under the bulb, darker ground below), concentric facet rings (light inner edge, darker
    outer), twelve faint radial facets, the cell's walls deepening its edge (wall_d 0 at the wall .. 1 inside)."""
    c = CHROME
    dz = Z - cz
    r = np.hypot(X - cx, dz)
    e = dz / R                                                # -1 .. 1 down to up across the bowl
    env = np.where(e > 0, c["sky"] - 0.18 * np.clip(1.0 - e, 0, 1) ** 3, c["ground"] + 0.10 * np.clip(-e - 0.5, 0, 1))
    band = np.clip(1.0 - np.abs(dz - HEAD_HORIZON[0] * R / 0.11) / (HEAD_HORIZON[1] * R / 0.11), 0.0, 1.0)
    env = env + (c["horizon"] - env) * np.clip(band * 1.6, 0.0, 1.0) * np.clip(r / (0.30 * R), 0.0, 1.0)
    t = np.clip(r / R, 0.0, 1.0) * rings
    ring = 1.0 + c["ring_k"] * (0.5 - (t % 1.0))              # light at each ring's inner edge, darker outward
    ring = np.where(r < R, ring, 1.0)
    facet = 1.0 + c["facet_k"] * np.cos(12.0 * np.arctan2(dz, X - cx))
    v = env * ring * facet
    return c["deep"] + (v - c["deep"]) * (0.45 + 0.55 * wall_d)


def headlamp_map():
    """(H, W, 3) linear colour, rows from z HEAD_Z[0] up, columns from |x| HEAD_X[0] (inboard)."""
    W = int(round((HEAD_X[1] - HEAD_X[0]) * HEAD_PX_M)) * SS
    H = int(round((HEAD_Z[1] - HEAD_Z[0]) * HEAD_PX_M)) * SS
    X, Z = np.meshgrid(HEAD_X[0] + (np.arange(W) + 0.5) / W * (HEAD_X[1] - HEAD_X[0]),
                       HEAD_Z[0] + (np.arange(H) + 0.5) / H * (HEAD_Z[1] - HEAD_Z[0]))
    c = HEAD_SRGB
    ch = CHROME
    # the walls between the cells: silver, lit along their top edges (chrome facing the sky), darker below
    img = ch["wall"] + (ch["wall_hi"] - ch["wall"]) * np.clip((Z - HEAD_Z[0]) / (HEAD_Z[1] - HEAD_Z[0]), 0.0, 1.0) ** 2

    def inside(box, margin=0.0):
        x0, x1, z0, z1 = box
        return (X > x0 + margin) & (X < x1 - margin) & (Z > z0 + margin) & (Z < z1 - margin)

    def edge_depth(box):                       # 0 at a cell wall, 1 from 1.2 cm in: the cell's edge is deeper
        x0, x1, z0, z1 = box
        d = np.minimum.reduce([X - x0, x1 - X, Z - z0, z1 - Z])
        return np.clip(d / 0.012, 0.0, 1.0)

    def lip_shadow(box):                       # the housing's top lip shades the cell's top 1.5 cm a little
        return 1.0 - 0.10 * np.clip(1.0 - (box[3] - Z) / 0.015, 0.0, 1.0)
    # main cell: the faceted chrome bowl round its bulb, the bulb's round shield cap (a chrome dome with its own
    # highlight) in front of it, highlights on the bowl's upper rim, faint horizontal lens flutes (8 mm)
    box = HEAD_CELLS["main"]
    m = inside(box)
    dx, dz = X - HEAD_BULB[0], Z - HEAD_BULB[1]
    r = np.hypot(dx, dz)
    R = 0.11
    bowl = _chrome_bowl(X, Z, HEAD_BULB[0], HEAD_BULB[1], R, HEAD_RINGS, edge_depth(box))
    for hx, hz, hr in ((-0.040, 0.050, 0.014), (0.055, 0.040, 0.010), (-0.085, 0.010, 0.008)):   # hard highlights
        bowl = np.maximum(bowl, ch["spec"] * np.clip(1.4 - np.hypot(dx - hx, (dz - hz) * 1.6) / hr, 0.0, 1.0))
    bowl += 0.015 * np.cos(2.0 * math.pi * Z / 0.008)
    bowl *= lip_shadow(box)
    dome = 0.62 + 0.36 * np.clip((dz + 0.6 * dx) / 0.020 + 0.3, 0.0, 1.0)                # lit from above
    dome = np.maximum(dome, np.clip(1.5 - np.hypot(dx + 0.006, dz - 0.007) / 0.005, 0.0, 1.0))
    bowl = np.where(r < 0.023, 0.36, bowl)                     # the socket's shadow round the cap
    bowl = np.where(r < 0.019, dome, bowl)
    img = np.where(m, bowl, img)
    # outboard lower cell: a small chrome reflector round the amber turn bulb (warm halo), horizontal flutes
    box = HEAD_CELLS["turn"]
    m = inside(box)
    r2 = np.hypot(X - HEAD_TURN_BULB[0], Z - HEAD_TURN_BULB[1])
    turn = _chrome_bowl(X, Z, HEAD_TURN_BULB[0], HEAD_TURN_BULB[1], 0.055, 2, edge_depth(box))
    turn += 0.04 * np.cos(2.0 * math.pi * Z / 0.006)
    turn *= lip_shadow(box)
    img = np.where(m, turn, img)
    # outboard upper strip: the side lamp's horizontal flutes (5 mm), chrome: bright crests, dark troughs, the
    # strip darker toward its bottom (its reflector faces down at the road)
    box = HEAD_CELLS["side"]
    m = inside(box)
    flute = ch["flute_lo"] + (ch["flute_hi"] - ch["flute_lo"]) * (0.5 + 0.5 * np.cos(2.0 * math.pi * Z / HEAD_FLUTE))
    flute *= 0.80 + 0.20 * np.clip((Z - box[2]) / (box[3] - box[2]), 0.0, 1.0)
    flute = ch["deep"] + (flute - ch["deep"]) * (0.6 + 0.4 * edge_depth(box))
    img = np.where(m, flute, img)
    rgb = np.repeat(np.clip(img, 0.0, 1.0)[..., None], 3, axis=2)
    halo = inside(HEAD_CELLS["turn"]) & (r2 < 0.022)
    k = np.clip((0.022 - r2[halo]) / 0.009, 0.0, 1.0)[:, None]
    rgb[halo] = rgb[halo] * (1.0 - 0.35 * k) + np.array(c["turn_bulb"]) * 0.35 * k
    amber = (r2 < 0.013) & inside(HEAD_CELLS["turn"])
    rgb[amber] = c["turn_bulb"]
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return np.stack([_down(lin[..., k]) for k in range(3)], axis=2)


def paint(out_dir):
    """Write the five PNGs into out_dir; returns their paths."""
    os.makedirs(out_dir, exist_ok=True)
    font = _font()
    tread, _ph = tread_map()
    tread = _blur(tread, BLUR_TYRE)
    side = _blur(side_map(font, _font(BRAND_FONTS)), BLUR_TYRE)
    cover = _blur(cover_map(font, _font(BRAND_FONTS)), BLUR_COVER, wrap_x=False)
    tail = tail_lens_map()
    tail = np.stack([_blur(tail[..., c], BLUR_LENS, wrap_x=False) for c in range(3)], axis=2)
    head = headlamp_map()
    head = np.stack([_blur(head[..., c], BLUR_HEAD, wrap_x=False) for c in range(3)], axis=2)
    paths = [os.path.join(out_dir, TREAD_PNG), os.path.join(out_dir, SIDE_PNG), os.path.join(out_dir, COVER_PNG),
             os.path.join(out_dir, TAIL_PNG), os.path.join(out_dir, HEAD_PNG)]
    _save(tread, paths[0], scale=1.0 / MAP_SCALE)
    _save(side, paths[1], scale=1.0 / MAP_SCALE)
    _save(cover, paths[2], srgb=True)
    _save(tail, paths[3], srgb=True)
    _save(head, paths[4], srgb=True)
    print("tyre_paint: tread %dx%d (groove %.2f, block %.2f), side %dx%d (letters %.2f), cover %dx%d, tail lens %dx%d,"
          " headlamp %dx%d, font %s -> %s" % (TREAD_W, TREAD_H, GROOVE, BLOCK, SIDE_W, SIDE_H, LETTER, COVER_SIZE,
                                             COVER_SIZE, tail.shape[1], tail.shape[0], head.shape[1], head.shape[0],
                                             font.name if font else "built-in", out_dir))
    return paths
