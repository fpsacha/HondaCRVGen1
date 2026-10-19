r"""
The shut bay's stand-in (performance pass, 2026-10-19): "engine_low", a few dark boxes drawn instead of the
engine bay (engine_block, ~3,600 triangles) while the hood is shut. Part CRVEngineBay shows one of the two
(gen_scripts.engine_bay_part, 42/media/lua/shared/HondaCRVGen1_EngineBay.lua).

What a shut bay shows was measured, not guessed (2026-10-19, the shipped FBX of f3d6753, pzview with the bay
hidden against the same views with it): the grille slots and the bumper opening show the radiator's front,
the hood-to-fender seams and the cowl gap a sliver of the engine's top, all under 100 px of a 1,000 px view;
the undertray (envelope.Z_TRAY), the aprons, the firewall and the radiator support close the rest, and no leak
count changed. So two boxes inside the bay's envelope:
  * the radiator: the tanks' outline (front.TANK_X, front.RAD_Y0..RAD_Y1, front.BOT_Z0..TOP_Z1);
  * the engine's mass: between the aprons and the firewall and the fan shroud, its top under the hood's
    insulator pad (envelope.hood_limit less TOP_DROP), sloping down toward the nose.
Their bottoms are never seen (the undertray) and are left out; every other face looks out of its box.

Built at EXPORT (export_fbx.export_all, before prepare), never in the parts or bake blends: the stand-in must
not shade the bay's own bake (it sits inside the bay) and needs no backfill, holecheck or chart of its own.
It takes its colours from the engine sheet: each face gets ONE uv, the texel at the centre of the nearest
engine_block face that looks the same way and whose 7 x 7 texel neighbourhood is uniform (so the colour
survives a box-halved sheet at a lower Vehicle Texture Size), i.e. the radiator core's colour on the radiator,
the engine top's on the mass. Flat colour per face; the game's light shades the faces.
"""
import os

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from bay import envelope, front

NAME = "engine_low"
SOURCE = "engine_block"
# engine mass box: x half width (inside the aprons at 0.575), y from the firewall (0.99) to just behind the
# radiator support's side panels (y 1.70), z from the undertray (0.555) to TOP_DROP under the pad
MASS_X = 0.53
MASS_Y0, MASS_Y1 = 1.00, 1.69
MASS_Z0 = 0.56
TOP_DROP = 0.07                          # metres under the pad zone (envelope.hood_limit: the hood skin less PAD_ZONE)
UNIFORM_R = 3                            # texels each side: a 7 x 7 neighbourhood
UNIFORM_TOL = 10                         # max channel deviation (0..255) inside it
SEARCH_R = 0.30                          # metres: engine faces considered round a stand-in face's centre


def _top(y):
    """The mass box's top at y: TOP_DROP under the lowest hood limit across its width (the real hood when
    the blend has one, ray cast as envelope.audit does)."""
    return min(envelope.hood_limit(x, y) for x in (-MASS_X, -MASS_X / 2, 0.0, MASS_X / 2, MASS_X)) - TOP_DROP


def boxes():
    """[(corner list of 8 (x, y, z), faces kept)]: corners in the order
    0 (x0,y0,z0) 1 (x1,y0,z0) 2 (x1,y1,z0) 3 (x0,y1,z0) 4..7 the same at the top; faces by name."""
    r = (-front.TANK_X, front.TANK_X, front.RAD_Y0, front.RAD_Y1, front.BOT_Z0, front.TOP_Z1)
    rad = [(r[0], r[2], r[4]), (r[1], r[2], r[4]), (r[1], r[3], r[4]), (r[0], r[3], r[4]),
           (r[0], r[2], r[5]), (r[1], r[2], r[5]), (r[1], r[3], r[5]), (r[0], r[3], r[5])]
    t0, t1 = _top(MASS_Y0), _top(MASS_Y1)
    mass = [(-MASS_X, MASS_Y0, MASS_Z0), (MASS_X, MASS_Y0, MASS_Z0), (MASS_X, MASS_Y1, MASS_Z0), (-MASS_X, MASS_Y1, MASS_Z0),
            (-MASS_X, MASS_Y0, t0), (MASS_X, MASS_Y0, t0), (MASS_X, MASS_Y1, t1), (-MASS_X, MASS_Y1, t1)]
    sides = ("top", "front", "back", "left", "right")
    return [(rad, sides), (mass, sides)]


# corner indices per face, counter-clockwise seen from outside
FACES = {"top": (4, 5, 6, 7), "bottom": (0, 3, 2, 1), "front": (2, 3, 7, 6), "back": (0, 1, 5, 4),
         "left": (0, 4, 7, 3), "right": (1, 2, 6, 5)}


def build(collection=None):
    """The stand-in object in model metres (identity transform), every face no_backfill. Returns it."""
    old = bpy.data.objects.get(NAME)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    bm = bmesh.new()
    for corners, keep in boxes():
        vs = [bm.verts.new(c) for c in corners]
        for k in keep:
            bm.faces.new([vs[i] for i in FACES[k]])
    bm.normal_update()
    me = bpy.data.meshes.new(NAME)
    bm.to_mesh(me)
    bm.free()
    a = me.attributes.new("no_backfill", 'INT', 'FACE')
    a.data.foreach_set("value", [1] * len(me.polygons))
    ob = bpy.data.objects.new(NAME, me)
    (collection or bpy.context.scene.collection).objects.link(ob)
    return ob


def _sheet(path):
    """The engine sheet as rows of RGB bytes (row 0 = the image top), with its size; None if missing."""
    if not path or not os.path.exists(path):
        return None
    img = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    w, h = img.size
    px = list(img.pixels)                # 8-bit PNG: the stored bytes / 255 (playbook), bottom row first
    bpy.data.images.remove(img)
    ch = len(px) // (w * h)
    rows = []
    for yy in range(h):
        src = h - 1 - yy
        base = src * w * ch
        rows.append([(int(px[base + x * ch] * 255 + 0.5), int(px[base + x * ch + 1] * 255 + 0.5),
                      int(px[base + x * ch + 2] * 255 + 0.5)) for x in range(w)])
    return rows, w, h


def _uniform(sheet, u, v):
    rows, w, h = sheet
    x, y = int(u * w), int((1.0 - v) * h)
    if x - UNIFORM_R < 0 or y - UNIFORM_R < 0 or x + UNIFORM_R >= w or y + UNIFORM_R >= h:
        return None
    c = rows[y][x]
    for yy in range(y - UNIFORM_R, y + UNIFORM_R + 1):
        for xx in range(x - UNIFORM_R, x + UNIFORM_R + 1):
            p = rows[yy][xx]
            if max(abs(p[0] - c[0]), abs(p[1] - c[1]), abs(p[2] - c[2])) > UNIFORM_TOL:
                return None
    return ((x + 0.5) / w, 1.0 - (y + 0.5) / h), c


def assign_uv(ob, src, sheet_path, report=print):
    """One uv per stand-in face from the engine sheet (see the module docstring). src: engine_block (its first
    uv layer is the baked engine sheet). Marks ob's mesh uv_baked so export_fbx keeps the layout."""
    sme = src.data
    M = src.matrix_world
    R = M.to_3x3()
    sv = [M @ v.co for v in sme.vertices]
    tree = BVHTree.FromPolygons(sv, [tuple(p.vertices) for p in sme.polygons])
    suv = sme.uv_layers[0].data
    cand = []
    for p in sme.polygons:
        uvs = [suv[i].uv for i in p.loop_indices]
        cand.append(((R @ p.normal).normalized(), Vector((sum(x.x for x in uvs) / len(uvs), sum(x.y for x in uvs) / len(uvs)))))
    sheet = _sheet(sheet_path)
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers[0].data
    picked = []
    for p in me.polygons:
        c = ob.matrix_world @ p.center
        n = (ob.matrix_world.to_3x3() @ p.normal).normalized()
        near = tree.find_nearest_range(c, SEARCH_R) or [tree.find_nearest(c)]
        best = None
        for _co, _no, idx, dist in sorted(near, key=lambda h: h[3]):
            fn, uv = cand[idx]
            score = dist + 0.15 * (1.0 - fn.dot(n))          # a face looking the same way, near
            if best is not None and score >= best[0]:
                continue
            if sheet is not None:
                got = _uniform(sheet, uv.x, uv.y)
                if got is None:
                    continue
                best = (score, Vector(got[0]), got[1], idx)
            else:
                best = (score, uv.copy(), None, idx)
        if best is None:                                         # nothing uniform within reach: the nearest face
            _co, _no, idx, _d = tree.find_nearest(c)
            best = (0.0, cand[idx][1].copy(), None, idx)
        for li in p.loop_indices:
            uvl[li].uv = best[1]
        picked.append(best[2])
    me["uv_baked"] = True
    report("engine_low: %d faces, %d tris; colours %s" % (len(me.polygons), sum(len(p.vertices) - 2 for p in me.polygons),
                                                         ", ".join("#%02x%02x%02x" % c if c else "?" for c in picked)))
    return picked


def add(sheet_path, report=print):
    """export_fbx's hook: build the stand-in next to engine_block and colour it from the engine sheet."""
    src = bpy.data.objects.get(SOURCE)
    if src is None:
        report("engine_low warning: no %s in this blend, stand-in not built" % SOURCE)
        return None
    col = src.users_collection[0] if src.users_collection else None
    ob = build(col)
    for name, what in envelope.audit([ob], quiet=True):          # a CLEARANCE line per problem, as build_bay's
        report("CLEARANCE %-20s %s" % (name, what))
    assign_uv(ob, src, sheet_path, report)
    return ob
