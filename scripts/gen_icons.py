r"""
Inventory icons for the accessory items: each part rendered alone with its own composed sheet, then
reduced to the 32 x 32 RGBA icon the base game and KI5 use.

    blender -b blender\crv_kotris.blend --python scripts\gen_icons.py

Writes common/media/textures/Item_<item>.png (the item scripts' `Icon = <item>`) and the 256 px renders
to blender/icons_raw. Run after compose (it needs the sheets); the build runs it in its overlays step.

Vanilla's vehicle-part icons (UI2.pack: CarDoorFront, CarMuffler, CarSuspension, SheetMetal...) are the
style: a 3/4 view lit from the upper left, the object's own colours, HARD alpha (no soft edge), a 1 px
dark outline (luminance 0.07-0.21), the inside mid to light (p90 0.49-0.84), 170-660 opaque pixels. The
first icons here were grey renders with soft alpha and a light one-pixel rim: guards and meshes read as
wireframes, the bare steel as pale blanks, the black off-road parts as sticks. So every icon now goes
through the same steps, whatever the part:
  1. rendered at 256 px in Workbench (studio light from the upper left, specular, cavity), its longer
     side fitted to FIT of the 32 px (the outline takes the last pixel each side);
  2. silhouettes thickened by THICKEN render px (thin tubes and mesh strands stay a whole icon pixel
     after the 8 x reduction instead of breaking into dashes or a grey haze), colour from the part;
  3. box-reduced, alpha cut hard at ALPHA_CUT;
  4. levels: a pale low-contrast part is spread to MIN_SPREAD around its median; the exposure is
     EXPOSURE, raised (up to GAIN_MAX) until the brightest tenth reaches MIN_HI, so black powder coat
     stays dark but shows its highlights, and held under MAX_HI; then a light unsharp mask;
  5. a dark 1 px outline round the silhouette.
An ICONS entry is (object, azimuth, elevation): object is a mesh name, or a callable(ic) that builds
the icon's own little scene and returns its objects (ic = this module: flat_material, coil, cylinder,
copy, box): the lift kit is springs and a shock in front of its tyre, the picnic table stands on its
legs. azimuth 0 looks from the car's right, 90 from the front (geocheck / pzview convention).
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
if HERE and HERE not in sys.path:
    sys.path.insert(0, HERE)
import features  # noqa: E402  (scripts/features: the plugins' ICONS, and the sheet each of their meshes bakes on)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(globals().get("__file__") or os.path.join("scripts", "_"))))
TEX = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures")
SHELL = os.path.join(TEX, "Vehicles", "Vehicles_HondaCRVGen1_Shell.png")
SHEET_TEX = {"shell": "Shell", "interior": "Interior", "wheel": "Wheel", "engine": "Engine"}
RAW = os.path.join(ROOT, "blender", "icons_raw")
SIZE, ICON = 256, 32
K = SIZE // ICON
FIT = 30.0                     # icon px the object's longer side spans
THICKEN = 3                    # render px every silhouette grows by before the reduction
ALPHA_CUT = 0.42               # coverage that makes an icon pixel opaque
OUTLINE = (0.075, 0.07, 0.065)
MIN_SPREAD = 0.42              # p5..p95 luminance spread a part is stretched to at least
EXPOSURE = 1.15                # base gain on the Workbench render
MIN_HI, MAX_HI = 0.58, 0.86    # p90 luminance kept between these (vanilla 0.49 tyre .. 0.84 sheet metal)
GAIN_MAX = 4.0                 # a black part stays dark but shows its highlights
SHARPEN = 0.45                 # unsharp amount on the 32 px colours
STUDIO = "Default"             # Workbench studio light (camera space): key from the upper left
STUDIO_ROT = 0.0


def _table(ic):
    """The picnic table standing on its legs (build_table, the sprite's bold tube sizes), its top the
    placed table's grey moulded top, the legs black."""
    import bmesh
    import build_table
    bm = bmesh.new()
    build_table.standing_table(bm, 0.022, 0.030, 0.016)
    me = bpy.data.meshes.new("icon_table")
    bm.to_mesh(me)
    bm.free()
    import build_accessories as A
    cols = {build_table.TOP_MAT: (0.36, 0.36, 0.37), build_table.CHROME_MAT: (0.08, 0.08, 0.085)}
    for name in A.MATS:
        me.materials.append(ic.flat_material("icon_" + name, cols.get(name, (0.20, 0.20, 0.21))))
    ob = bpy.data.objects.new("icon_table", me)
    bpy.context.scene.collection.objects.link(ob)
    return [ob]


# item -> (object or callable, camera azimuth, elevation) in degrees
ICONS = {
    "CRVGen1_Bullbar": ("acc_bullbar", 62.0, 22.0),
    "CRVGen1_RoofRack": ("acc_roofrack", 30.0, 38.0),
    "CRVGen1_GuardWindshield": ("acc_guard_ws", 70.0, 30.0),
    "CRVGen1_GuardRearGlass": ("acc_guard_rear", 250.0, 26.0),
    "CRVGen1_GuardWindowFront": ("acc_guard_fl", 205.0, 18.0),
    "CRVGen1_GuardWindowRear": ("acc_guard_rl", 200.0, 18.0),
    "CRVGen1_SpareCover": ("acc_spare_cover", 250.0, 20.0),
    "CRVGen1_PicnicTable": (_table, 215.0, 30.0),
}
ICONS.update(features.icons())


def _sheet(obj_name):
    """The composed texture an object's icon is drawn with: its sheet (feature meshes may bake off the shell)."""
    spec = features.objects().get(obj_name)
    if spec is None or spec["space"] == "shell":
        return SHELL
    tex = SHEET_TEX.get(spec["space"]) or features.new_spaces()[spec["space"]]["texture"]
    return os.path.join(TEX, "Vehicles", "Vehicles_HondaCRVGen1_%s.png" % tex)


# --------------------------------------------------------------------------- scene helpers (ic.*)
_MATS = {}


def _material(png=SHELL):
    if png in _MATS:
        return _MATS[png]
    mat = bpy.data.materials.new("icon_" + os.path.basename(png))
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(png, check_existing=True)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.active = tex
    _MATS[png] = mat
    return mat


def flat_material(name, rgb):
    """A material Workbench's texture colour mode draws as one colour (a 4 x 4 image of it)."""
    key = (name, tuple(rgb))
    if key in _MATS:
        return _MATS[key]
    img = bpy.data.images.new(name, 4, 4, alpha=False)
    img.pixels[:] = [c for _ in range(16) for c in (rgb[0], rgb[1], rgb[2], 1.0)]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.active = tex
    _MATS[key] = mat
    return mat


def _object(name, verts, faces, rgb, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.uv_layers.new(name="UVMap")
    me.materials.append(flat_material("icon_" + name, rgb))
    for p in me.polygons:
        p.use_smooth = smooth
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def coil(name, rgb, radius, wire, turns, height, loc=(0.0, 0.0, 0.0), seg=14, ring=8):
    """A coil spring standing on loc (z up): a tube of radius `wire` swept along a helix, ends ground flat."""
    n = int(turns * seg)
    verts, faces = [], []
    for i in range(n + 1):
        t = i / float(n)
        a = 2 * math.pi * turns * t
        c = Vector((radius * math.cos(a), radius * math.sin(a), wire + (height - 2 * wire) * t))
        tan = Vector((-math.sin(a) * radius * 2 * math.pi * turns, math.cos(a) * radius * 2 * math.pi * turns, height)).normalized()
        u = Vector((math.cos(a), math.sin(a), 0.0))
        v = tan.cross(u).normalized()
        for j in range(ring):
            b = 2 * math.pi * j / ring
            p = c + (u * math.cos(b) + v * math.sin(b)) * wire
            verts.append(tuple(p + Vector(loc)))
    for i in range(n):
        for j in range(ring):
            a0, a1 = i * ring + j, i * ring + (j + 1) % ring
            faces.append((a0, a1, a1 + ring, a0 + ring))
    faces.append(tuple(range(ring - 1, -1, -1)))
    faces.append(tuple(n * ring + j for j in range(ring)))
    return _object(name, verts, faces, rgb)


def cylinder(name, rgb, radius, z0, z1, loc=(0.0, 0.0, 0.0), seg=20):
    """A closed upright cylinder from z0 to z1 at loc."""
    verts = []
    for z in (z0, z1):
        for j in range(seg):
            a = 2 * math.pi * j / seg
            verts.append((loc[0] + radius * math.cos(a), loc[1] + radius * math.sin(a), loc[2] + z))
    faces = [(j, (j + 1) % seg, seg + (j + 1) % seg, seg + j) for j in range(seg)]
    faces += [tuple(range(seg - 1, -1, -1)), tuple(range(seg, 2 * seg))]
    ob = _object(name, verts, faces, rgb)
    for p in ob.data.polygons:
        p.use_smooth = len(p.vertices) == 4
    return ob


def copy(name, at=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=1.0, squash=1.0):
    """A copy of a scene mesh with its own sheet, moved (its centre to `at`, Euler degrees). squash < 1
    shortens it along its longest axis only (an icon-only stylisation: a long thin part keeps its tube
    and head sizes and so reads thicker once its length is fitted to the icon)."""
    src = bpy.data.objects[name]
    ob = bpy.data.objects.new("icon_" + name, src.data.copy())
    pts = [src.matrix_world @ v.co for v in src.data.vertices]
    c = sum(pts, Vector()) / len(pts)
    sq = Matrix.Identity(4)
    if squash != 1.0:
        P = np.array([tuple(p - c) for p in pts])
        ax = np.linalg.eigh(P.T @ P)[1][:, 2]
        m3 = np.eye(3) + (squash - 1.0) * np.outer(ax, ax)
        sq = Matrix([list(m3[0]) + [0.0], list(m3[1]) + [0.0], list(m3[2]) + [0.0], [0.0, 0.0, 0.0, 1.0]])
    # into the vertices, not the object: a squash along a slanted axis is a shear an object's
    # location / rotation / scale cannot hold (the render would not match the framing)
    ob.data.transform(Matrix.Translation(Vector(at)) @ Euler([math.radians(a) for a in rot]).to_matrix().to_4x4()
                      @ Matrix.Diagonal((scale, scale, scale, 1.0)) @ sq
                      @ Matrix.Translation(-c) @ src.matrix_world)
    ob.matrix_world = Matrix.Identity(4)
    ob.data.materials.clear()
    ob.data.materials.append(_material(_sheet(name)))
    if ob.data.uv_layers.get("UVMap"):
        ob.data.uv_layers["UVMap"].active_render = True
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mean_colour(name):
    """The area-weighted mean sheet colour under a mesh's faces (UVMap, stored sRGB): a stand-in's colour,
    so it follows the part's real texture."""
    src = bpy.data.objects[name]
    img = bpy.data.images.load(_sheet(name), check_existing=True)
    w, h = img.size
    px = np.array(img.pixels[:], np.float32).reshape(h, w, img.channels)
    uv = src.data.uv_layers["UVMap"].data
    acc, tot = np.zeros(3), 0.0
    for p in src.data.polygons:
        u = sum(uv[li].uv[0] for li in p.loop_indices) / p.loop_total
        v = sum(uv[li].uv[1] for li in p.loop_indices) / p.loop_total
        acc += px[min(h - 1, max(0, int(v * h))), min(w - 1, max(0, int(u * w))), :3] * p.area
        tot += p.area
    return tuple(float(c) for c in acc / max(tot, 1e-9))


def _hull(q):
    """Convex hull of 2D points, counter-clockwise (monotone chain)."""
    pts = sorted(set((round(float(x), 5), round(float(y), 5)) for x, y in q))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def lattice_panel(name, cells=4.5, frame=0.045, strand=0.030, slope=0.62):
    """Icon-only stand-in for an expanded-metal panel. Its real diamonds (~14 cm) come out ~2 icon px and
    fill in, so the panel read as a plate: the stand-in keeps the panel's outline (its convex hull in its
    own plane) as a frame and puts ~`cells` big diamonds across it, strands about an icon pixel wide, in
    the panel's mean sheet colour."""
    src = bpy.data.objects[name]
    pts = [src.matrix_world @ v.co for v in src.data.vertices]
    c = sum(pts, Vector()) / len(pts)
    P = np.array([tuple(p - c) for p in pts])
    _w, V = np.linalg.eigh(P.T @ P)
    nrm, ax_u, ax_v = V[:, 0], V[:, 2], V[:, 1]
    hull = _hull(np.stack([P @ ax_u, P @ ax_v], axis=1))
    edges = []
    for i in range(len(hull)):
        a, b = np.array(hull[i]), np.array(hull[(i + 1) % len(hull)])
        d = b - a
        if np.hypot(*d) > 1e-6:
            edges.append((a, b, np.array([-d[1], d[0]]) / np.hypot(*d)))      # inward normal (CCW: left)
    segs = [(a, b, n * frame) for a, b, n in edges]                           # the frame: one band per hull edge
    span = max(p[0] for p in hull) - min(p[0] for p in hull)
    pitch = span / cells
    for sgn in (1.0, -1.0):                                                   # two strand families
        d = np.array([1.0, sgn * slope]) / math.hypot(1.0, slope)
        nd = np.array([-d[1], d[0]])
        offs = [float(np.dot(np.array(p), nd)) for p in hull]
        k = math.floor(min(offs) / pitch)
        while k * pitch < max(offs):
            p0 = nd * (k * pitch + pitch * 0.5 * (sgn < 0))
            t0, t1 = -10.0, 10.0
            for a, _b, n in edges:                                            # clip to the hull (Cyrus-Beck)
                num, den = float(np.dot(n, p0 - a)), float(np.dot(n, d))
                if abs(den) < 1e-12:
                    if num < 0:
                        t0, t1 = 1.0, 0.0
                elif den > 0:
                    t0 = max(t0, -num / den)
                else:
                    t1 = min(t1, -num / den)
            if t1 - t0 > strand:
                a, b = p0 + d * t0, p0 + d * t1
                segs.append((a - nd * strand / 2, b - nd * strand / 2, nd * strand))
            k += 1
    verts, faces = [], []
    for i, (a, b, w) in enumerate(segs):                                      # each band a thin box
        z = 0.0015 + 0.001 * (i % 2)
        quad = [a, b, b + w, a + w]
        base = len(verts)
        for zz in (-z, z):
            for p in quad:
                verts.append(tuple(c + Vector(tuple(ax_u * p[0] + ax_v * p[1] + nrm * zz))))
        faces += [(base, base + 1, base + 2, base + 3)[::-1], (base + 4, base + 5, base + 6, base + 7)]
        faces += [(base + j, base + (j + 1) % 4, base + 4 + (j + 1) % 4, base + 4 + j) for j in range(4)]
    ob = _object("icon_lattice_" + name, verts, faces, mean_colour(name), smooth=False)
    me = ob.data
    me.validate()
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return [ob]


# ------------------------------------------------------------------------------------------ render
def _setup():
    scene = bpy.context.scene
    try:
        scene.render.engine = 'BLENDER_WORKBENCH'
    except TypeError:
        pass
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.display.render_aa = '16'
    sh = scene.display.shading
    sh.light = 'STUDIO'
    try:
        sh.studio_light = STUDIO
    except TypeError:
        pass
    sh.use_world_space_lighting = False
    sh.studiolight_rotate_z = math.radians(STUDIO_ROT)
    sh.show_specular_highlight = True
    sh.color_type = 'TEXTURE'
    sh.show_backface_culling = True
    sh.show_cavity = True
    sh.cavity_type = 'BOTH'
    sh.cavity_ridge_factor = 1.0
    sh.cavity_valley_factor = 1.0
    sh.show_shadows = False
    sh.show_object_outline = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    cam = bpy.data.objects.new("icon_cam", bpy.data.cameras.new("icon_cam"))
    cam.data.type = 'ORTHO'
    cam.data.clip_end = 100
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def _aim(cam, obs, az, el):
    """Ortho camera from (az, el) on the objects' centre, their longer projected side at FIT of ICON px."""
    a, e = math.radians(az), math.radians(el)
    d = Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))
    pts = [ob.matrix_world @ v.co for ob in obs for v in ob.data.vertices]
    centre = sum(pts, Vector()) / len(pts)
    cam.location = centre + d * 20.0
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    inv = cam.matrix_world.inverted()
    loc = [inv @ p for p in pts]
    w = max(p.x for p in loc) - min(p.x for p in loc)
    h = max(p.y for p in loc) - min(p.y for p in loc)
    cx = (max(p.x for p in loc) + min(p.x for p in loc)) / 2
    cy = (max(p.y for p in loc) + min(p.y for p in loc)) / 2
    cam.location = cam.matrix_world @ Vector((cx, cy, 0.0))
    cam.data.ortho_scale = max(w, h) * (ICON + 2 * THICKEN / float(K)) / FIT


def _thicken(pre, alpha, r):
    """Grey dilation of the coverage by a disc of r px, each grown pixel taking its neighbour's colour."""
    best_a, best_p = alpha.copy(), pre.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if (dx or dy) and dx * dx + dy * dy <= r * r + r:
                a = np.roll(np.roll(alpha, dy, axis=0), dx, axis=1)
                p = np.roll(np.roll(pre, dy, axis=0), dx, axis=1)
                win = a > best_a
                best_a = np.where(win, a, best_a)
                best_p = np.where(win[..., None], p, best_p)
    return best_p, best_a


def _lum(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def reduce_icon(a):
    """256 x 256 RGBA (sRGB values, straight alpha, rows top-down) -> 32 x 32 icon in the vanilla manner."""
    alpha = a[..., 3]
    pre = a[..., :3] * alpha[..., None]
    pre, alpha = _thicken(pre, alpha, THICKEN)
    pre = pre.reshape(ICON, K, ICON, K, 3).mean(axis=(1, 3))
    alpha = alpha.reshape(ICON, K, ICON, K).mean(axis=(1, 3))
    solid = alpha >= ALPHA_CUT
    rgb = np.where(alpha[..., None] > 1e-4, pre / np.maximum(alpha[..., None], 1e-4), 0.0)
    if solid.any():
        lum = _lum(rgb)[solid]
        lo, med, hi = np.percentile(lum, [5, 50, 95])
        k = min(2.0, max(1.0, MIN_SPREAD / max(hi - lo, 1e-3)))
        rgb = np.clip(med + (rgb - med) * k, 0.0, 1.0)
        p90 = max(float(np.percentile(_lum(rgb)[solid], 90)), 1e-3)
        g = max(EXPOSURE, MIN_HI / p90)              # a dark part lifted until its highlights show
        g = min(g, GAIN_MAX, MAX_HI / p90)           # never blown out
        rgb = np.clip(rgb * g, 0.0, 1.0)
        # unsharp mask inside the silhouette (the blur only averages solid neighbours)
        m = solid.astype(np.float32)
        acc = np.zeros_like(rgb)
        cnt = np.zeros_like(m)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acc += np.roll(np.roll(rgb * m[..., None], dy, axis=0), dx, axis=1)
                cnt += np.roll(np.roll(m, dy, axis=0), dx, axis=1)
        blur = acc / np.maximum(cnt[..., None], 1.0)
        rgb = np.clip(rgb + SHARPEN * (rgb - blur), 0.0, 1.0)
    grown = solid.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            grown |= np.roll(np.roll(solid, dy, axis=0), dx, axis=1)
    ring = grown & ~solid
    out = np.zeros((ICON, ICON, 4), np.float32)
    out[solid, :3] = rgb[solid]
    out[solid, 3] = 1.0
    out[ring, :3] = OUTLINE
    out[ring, 3] = 1.0
    return out


def _reduce(src, dst):
    img = bpy.data.images.load(src, check_existing=False)
    a = np.array(img.pixels[:], dtype=np.float32).reshape(SIZE, SIZE, 4)[::-1]     # Blender rows run bottom-up
    bpy.data.images.remove(img)
    out = reduce_icon(a)
    icon = bpy.data.images.new(os.path.basename(dst), ICON, ICON, alpha=True)
    icon.pixels[:] = out[::-1].ravel().tolist()
    icon.filepath_raw = dst
    icon.file_format = 'PNG'
    icon.save()
    bpy.data.images.remove(icon)
    return out


def check_icon(out):
    """The style every rendered icon must keep (vanilla's): hard alpha, a dark outline all round, at least
    200 opaque px, its longer side across the icon, the inside neither dark nor blown (p90 luminance)."""
    a = out[..., 3]
    errors = []
    if ((a > 0) & (a < 1)).any():
        errors.append("soft alpha")
    solid = a >= 1
    if solid.sum() < 200:
        errors.append("%d opaque px" % solid.sum())
    if not solid.any():
        return errors
    inner = solid.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            inner &= np.roll(np.roll(np.pad(solid, 1), dy, axis=0), dx, axis=1)[1:-1, 1:-1]
    rim = solid & ~inner
    if np.abs(out[rim, :3] - np.array(OUTLINE)).max() > 1.5 / 255:       # (an 8-bit PNG read back rounds it)
        errors.append("no dark outline")
    ys, xs = np.where(solid)
    if max(xs.max() - xs.min(), ys.max() - ys.min()) + 1 < ICON - 2:
        errors.append("spans %d px" % (max(xs.max() - xs.min(), ys.max() - ys.min()) + 1))
    body = solid & ~rim
    if body.any():
        p90 = np.percentile(_lum(out[body, :3]), 90)
        if not 0.45 <= p90 <= 0.9:
            errors.append("p90 luminance %.2f" % p90)
    return errors


def render(items=None, tex=TEX, raw=RAW):
    """Render ICONS (or the named items) into tex/Item_<item>.png; returns {item: 32 x 32 RGBA}."""
    os.makedirs(raw, exist_ok=True)
    cam = _setup()
    ic = sys.modules[__name__]
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    out = {}
    for item, (what, az, el) in ICONS.items():
        if items and item not in items:
            continue
        temps = []
        if callable(what):
            obs = temps = what(ic)
            name = getattr(what, "__name__", "scene")
        else:
            ob = bpy.data.objects.get(what)
            if ob is None:
                print("ICON warning: %s has no object %s" % (item, what))
                continue
            ob = copy(what)
            obs = temps = [ob]
            name = what
        for o in meshes:
            o.hide_render = True
        _aim(cam, obs, az, el)
        path = os.path.join(raw, item + ".png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        dst = os.path.join(tex, "Item_%s.png" % item)
        out[item] = _reduce(path, dst)
        n = int((out[item][..., 3] > 0).sum())
        print("ICON %s <- %s (%d px)" % (os.path.basename(dst), name, n))
        for o in temps:
            bpy.data.objects.remove(o, do_unlink=True)
    bad = ["%s: %s" % (item, ", ".join(e)) for item, e in ((i, check_icon(o)) for i, o in out.items()) if e]
    if bad:
        raise SystemExit("ICON CHECK FAILED: " + "; ".join(bad))
    if out:
        print("ICON CHECK ok: %d icons, hard alpha, outlined, %d-%d opaque px" % (
            len(out), min(int(o[..., 3].sum()) for o in out.values()), max(int(o[..., 3].sum()) for o in out.values())))
    print("ICONS DONE")
    return out


if __name__ == "__main__":
    render()
