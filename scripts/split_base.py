r"""
Split the imported kotris666 CR-V base mesh ("base") into the Project Zomboid part objects.

The asset is already built as separate mesh islands per panel (hood, doors, tailgate, fenders,
bumpers, cladding, trims, wheels, seats...). So instead of box-cutting a fused shell we classify
every island and only bisect the few trims that run across a shut line (side cladding, door frame
trim, rear cladding). Runs inside Blender (live via MCP, or -b):

    exec(compile(open(r"scripts\split_base.py").read(), "split_base", "exec"))

Output objects (same frame as the loft pipeline: +Y nose, +Z up, +X right, ground z=0):
    body, hood, door_fl, door_fr, door_rl, door_rr, window_fl, window_fr, window_rl, window_rr,
    trunk (side-hinged tailgate), trunk_top (flip-up glass), interior, spare,
    wheel_FR, wheel_FL, wheel_RR, wheel_RL
"""
import bpy
import bmesh
from collections import defaultdict
from mathutils import Vector

SRC = "base"
PARTS = ["body", "hood", "door_fl", "door_fr", "door_rl", "door_rr",
         "window_fl", "window_fr", "window_rl", "window_rr", "trunk", "trunk_top",
         "interior", "wheel_FR", "wheel_FL", "wheel_RR", "wheel_RL"]

# shut planes measured on the model's own panel islands (face-centre extents)
Y_FENDER_DOOR = 0.795
Y_DOOR_DOOR = -0.265
Y_DOOR_QUARTER = -1.215
CUT_MIN_SPAN = 0.08          # only bisect an island that reaches >= 8 cm past a plane on both sides
TOL = 0.035                  # bbox containment tolerance

WHEEL_MATS = {"Jante", "Pneu"}
INTERIOR_MATS = {"Siege", "Siege_2", "Interieur", "Interieur_sol"}
GLASS_MATS = {"Vitre"}

# part -> ((x0,x1),(y0,y1),(z0,z1)); an island whose bbox fits inside (with TOL) is that part
BOXES = {
    "hood":      ((-0.78, 0.78), (0.85, 2.02), (0.89, 1.17)),
    "trunk":     ((-0.72, 0.72), (-2.22, -1.94), (0.66, 1.19)),
    "trunk_top": ((-0.64, 0.64), (-2.12, -1.84), (1.17, 1.64)),
    "door_fr":   ((0.52, 1.04), (-0.31, 0.84), (0.44, 1.64)),     # z0 0.44: the rocker garnish (z 0.37-0.44) stays on the body
    "door_fl":   ((-1.04, -0.52), (-0.31, 0.84), (0.44, 1.64)),
    "door_rr":   ((0.52, 1.04), (-1.25, -0.21), (0.44, 1.64)),
    "door_rl":   ((-1.04, -0.52), (-1.25, -0.21), (0.44, 1.64)),
}
# The windscreen's lower corners, |x| 0.68-0.74 at y 0.78-0.83, z 1.10-1.17: kotris's small A-pillar-base
# / cowl junction trims (1-5 faces each) and the passenger wiper's tip fit the front doors' boxes (y up
# to 0.875 with TOL) but lie inboard of the door skin, at the glass. On the doors they would swing away
# with them, and the doors' 70-tri rubber budget (prep_parts.SUB_BUDGET, no shape guard) collapsed them:
# a see-through notch at each pillar base and a spike over the passenger wiper (2026-10-13). Any island
# whose face centres all lie in this box (|x|, y, z) is body.
WS_CORNER = ((0.66, 0.745), (0.74, 0.86), (1.08, 1.20))
# The roof-edge strip above the rear glass (the painted spoiler lip, its high-mount stop lamp, the lamp's chrome
# housing and the badge between them: y -1.89..-1.70, z 1.53..1.68). On the RD1 it is part of the hatch and
# lifts with the glass, hinged at the strip's front edge (2026-10-16, reference photos; it was body, and the
# stop lamp was held on the roof on 2026-10-12, which left the strip standing on the roof while the glass rose).
LIP_BOX = ((-0.56, 0.56), (-1.92, -1.66), (1.50, 1.72))
LIP_MATS = {"Body", "Feux_stop", "Feux_chrome", "Plastique_noir"}


def _islands(bm):
    seen = [False] * len(bm.faces)
    out = []
    for f in bm.faces:
        if seen[f.index]:
            continue
        stack, grp = [f], []
        seen[f.index] = True
        while stack:
            g = stack.pop()
            grp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if not seen[h.index]:
                        seen[h.index] = True
                        stack.append(h)
        out.append(grp)
    return out


def _bbox(faces):
    cs = [f.calc_center_median() for f in faces]
    lo = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
    hi = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
    return lo, hi


def _inside(lo, hi, box):
    (x0, x1), (y0, y1), (z0, z1) = box
    return (lo.x >= x0 - TOL and hi.x <= x1 + TOL and lo.y >= y0 - TOL and hi.y <= y1 + TOL
            and lo.z >= z0 - TOL and hi.z <= z1 + TOL)


def _side(x):
    return "r" if x > 0 else "l"


def _door_by_y(y, x):
    if Y_DOOR_DOOR <= y <= Y_FENDER_DOOR:
        return "door_f" + _side(x)
    if Y_DOOR_QUARTER <= y < Y_DOOR_DOOR:
        return "door_r" + _side(x)
    return "body"


# kotris wheel hubs (centre of the Jante/Pneu islands) and the wheels' x span. Every island that lies
# wholly inside a wheel's cylinder belongs to that wheel whatever its material: the centre cap
# (Plastique_noir), the chrome lug nuts, their dark seats and the dark inserts between the spokes
# are not Jante/Pneu, and v1-v4 left them on the BODY. In Blender they sat on the kotris wheels and
# looked right; in game the wheel model sits at the script's x 0.72 (4 cm inboard) and turns, while
# those pieces stayed put in front of it: the "double H", the black patches "not attached to the
# wheel" and the black marks the user kept reporting.
HUBS = {"wheel_FR": (0.759, 1.323, 0.342), "wheel_FL": (-0.759, 1.323, 0.342),
        "wheel_RR": (0.759, -1.297, 0.336), "wheel_RL": (-0.759, -1.297, 0.336)}
HUB_RADIUS = 0.335                 # tyre radius: nothing of the body lies inside it
HUB_X = (0.640, 0.880)             # |x| span of the wheels, with a little room


def _in_wheel(lo, hi):
    for name, (hx, hy, hz) in HUBS.items():
        if (hx > 0) != (lo.x + hi.x > 0):
            continue
        if not (HUB_X[0] <= min(abs(lo.x), abs(hi.x)) and max(abs(lo.x), abs(hi.x)) <= HUB_X[1]):
            continue
        far = max(((y - hy) ** 2 + (z - hz) ** 2) ** 0.5 for y in (lo.y, hi.y) for z in (lo.z, hi.z))
        if far <= HUB_RADIUS:
            return name
    return None


def classify(mat, lo, hi, c):
    """Whole-island rule. Returns a part name, or None when the island must be cut."""
    wheel = _in_wheel(lo, hi)
    if wheel is not None:
        return wheel
    if mat == "Dessous" and min(abs(lo.x), abs(hi.x)) < 0.75:
        return "body"                             # underbody strips reaching inboard of the doors: never
                                                  # cut at the shut lines (a fan of them rode the rear doors
                                                  # and swung out as a 37 cm spike)
    if mat in WHEEL_MATS:
        if c.y < -2.0 and c.z > 0.55:
            return "trunk"                        # the spare is bolted to the tailgate and swings with it
        return "wheel_%s%s" % ("F" if c.y > 0 else "R", "R" if c.x > 0 else "L")
    if mat in INTERIOR_MATS:
        return "interior"
    if c.y < -2.25 and c.z > 0.7:
        return "trunk"                            # spare-wheel face, its cap and emblem ride the gate
    if mat in GLASS_MATS:
        if c.y > 0.9:
            return "body"                         # windscreen
        if c.y < -1.85 and abs(c.x) < 0.65:
            return "trunk_top"                    # flip-up tailgate glass
        if abs(c.x) > 0.55:
            part = _door_by_y(c.y, c.x)
            return part.replace("door_", "window_") if part != "body" else "body"   # quarter glass stays
        return "body"
    if mat in LIP_MATS and _inside(lo, hi, LIP_BOX):
        return "trunk_top"                        # the roof-edge strip with the stop lamp rides the glass
    if lo.z > 1.55 and abs(c.x) < 0.62:
        return "body"                             # roof fittings (antenna base, rails) sit inside the door boxes' z range
    (ax0, ax1), (ay0, ay1), (az0, az1) = WS_CORNER
    if (lo.x * hi.x > 0 and ax0 <= min(abs(lo.x), abs(hi.x)) and max(abs(lo.x), abs(hi.x)) <= ax1
            and ay0 <= lo.y and hi.y <= ay1 and az0 <= lo.z and hi.z <= az1):
        return "body"                             # trims at the windscreen's lower corners, not the doors'
    for part, box in BOXES.items():
        if _inside(lo, hi, box):
            if part == "hood" and mat != "Body" and hi.y < 1.05:
                return "body"                     # wiper arms and cowl vents lie over the hood's rear edge
            if part == "trunk" and (mat.startswith("Feux") or mat.startswith("Reflect")):
                return "body"                     # the tail lamps' lower sections reach into the gate's box
            if part == "trunk_top" and (mat.startswith("Feux") or mat.startswith("Reflect")):
                return "body"                     # the high-mount stop lamp (Feux_stop + chrome housing, y -1.85..-1.89,
                                                  # z 1.53-1.58) is fixed to the roof inside the glass on the RD1: it rode
                                                  # the flip-up glass once the glass lifted (feedback, 2026-10-12)
            if part == "trunk" and mat == "Body_plastique" and hi.z < 0.80:
                return "body"                     # bumper-top slivers under the gate's lower edge
            if part == "trunk" and lo.z > 1.15:
                return "trunk_top"                # the glass hatch's catches above the gate's top edge
            return part
    # side-band trims running across the shut lines get cut; everything else is body
    on_side = (lo.x > 0.5 or hi.x < -0.5) and lo.z > 0.1 and hi.z < 1.66
    if on_side:
        for plane in (Y_FENDER_DOOR, Y_DOOR_DOOR, Y_DOOR_QUARTER):
            if lo.y <= plane - CUT_MIN_SPAN and hi.y >= plane + CUT_MIN_SPAN:
                return None
    return "body"


def split(src_name=SRC, report=print):
    src = bpy.data.objects[src_name]
    me = src.data
    names = [m.name if m else "?" for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    isl_layer = bm.faces.layers.int.new("isl")
    part_layer = bm.faces.layers.int.new("part")
    islands = _islands(bm)
    plan = {}                                     # island id -> part name or None (cut)
    log = defaultdict(int)
    for i, grp in enumerate(islands):
        mats = defaultdict(int)
        for f in grp:
            mats[names[f.material_index]] += 1
            f[isl_layer] = i
        mat = max(mats.items(), key=lambda kv: kv[1])[0]
        lo, hi = _bbox(grp)
        c = (lo + hi) / 2
        part = classify(mat, lo, hi, c)
        plan[i] = part
        if part is None:
            report("  CUT  %5d f  %-14s x %5.2f..%5.2f y %5.2f..%5.2f z %4.2f..%4.2f"
                   % (len(grp), mat, lo.x, hi.x, lo.y, hi.y, lo.z, hi.z))
        elif len(grp) >= 100:
            report("  %-10s %5d f  %-14s y %5.2f..%5.2f z %4.2f..%4.2f"
                   % (part, len(grp), mat, lo.y, hi.y, lo.z, hi.z))
    # bisect the straddlers on the three shut planes
    cut_ids = [i for i, p in plan.items() if p is None]
    for i in cut_ids:
        for plane in (Y_FENDER_DOOR, Y_DOOR_DOOR, Y_DOOR_QUARTER):
            faces = [f for f in bm.faces if f[isl_layer] == i]
            lo, hi = _bbox(faces)
            if not (lo.y <= plane - CUT_MIN_SPAN and hi.y >= plane + CUT_MIN_SPAN):
                continue
            verts = {v for f in faces for v in f.verts}
            edges = {e for f in faces for e in f.edges}
            bmesh.ops.bisect_plane(bm, geom=list(verts) + list(edges) + faces,
                                   plane_co=(0.0, plane, 0.0), plane_no=(0.0, 1.0, 0.0), dist=1e-5)
    # per-face part assignment
    idx = {p: k for k, p in enumerate(PARTS)}
    for f in bm.faces:
        part = plan[f[isl_layer]]
        if part is None:
            c = f.calc_center_median()
            part = _door_by_y(c.y, c.x)
        f[part_layer] = idx[part]
        log[part] += 1
    # write one object per part
    for part in PARTS:
        old = bpy.data.objects.get(part)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        k = idx[part]
        pb = bm.copy()
        pl = pb.faces.layers.int.get("part")
        pb.faces.ensure_lookup_table()
        bmesh.ops.delete(pb, geom=[f for f in pb.faces if f[pl] != k], context='FACES')
        if not len(pb.faces):
            pb.free()
            continue
        newme = bpy.data.meshes.new(part)
        for m in me.materials:
            newme.materials.append(m)
        pb.to_mesh(newme)
        pb.free()
        newme.validate()
        ob = bpy.data.objects.new(part, newme)
        src.users_collection[0].objects.link(ob)
        for p in newme.polygons:
            p.use_smooth = True
    bm.free()
    src.hide_set(True)
    src.hide_render = True
    report("PARTS " + ", ".join("%s:%d" % (p, log[p]) for p in PARTS if log[p]))
    return log


split()
