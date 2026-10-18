r"""
Triangle dump of one UV space for compose's 2D paint pass (spec/planar-texture-plan.md, B1).

    blender -b <scratch copy of an unwrapped .blend> --python scripts\uvmesh_dump.py -- --out <file.npz> [--size N] [--space shell]

Why it exists: the paint pass (paint_pass.py) draws KI5's lines and gradients in texture space but
measures everything in metres on the car: a seam is 8 mm wide in 3D whatever the texel density, a
gradient runs with the height above the ground, a highlight follows the surface normal. It runs in
compose (system Python, numpy / scipy) so the paint can be tuned in seconds without a rebake; what
it needs from Blender is written here once: every triangle's UVs, world positions, corner normals
as rendered, material, gen and island, and the crease polylines of the full-detail twins.

Why the creases come from the twins: the decimated low mesh cannot tell a design line from a
decimation facet. The design review (2026-10-12) found 132 of its 151 m of 12-55 degree paint
edges were facets whose corner normals run smooth across them. The twins (`<name>_hi`, the kotris
mesh before lowpoly.py) only fold where the car folds.

Welding: kotris leaves unwelded duplicate vertices (65.9 m of shell edges are "open" by vertex id
but shared by position), so every id that means "the same point" is a position rounded to 0.1 mm,
per object (as bake_atlas._rubber_map does): `tri_wid` here, and the crease graph below.

bake_atlas calls dump(objs, path, size, meta) after the unwrap and before _split_gen. The command
line is for tests on a saved .blend: it never saves, but open a scratch copy anyway.
"""
import ast
import json
import math
import os
import sys

import bpy
import numpy as np

WELD = 1e-4                     # metres: vertices closer than this (rounded) are one point (plan, "Weld by position")
# twin creases (plan B1). 20 degrees: KI5 draws its crease highlights on 20-60 degree folds (ki5_measure
# out_creases.txt: convex 20-35 highlighted on 86 % of the XJ's samples, 8-20 on 6-44 %); below that a
# fold is a curvature change the normal-elevation term already shades.
CREASE_MATS = ("Body", "Body_plastique")
CREASE_MIN_DEG = 20.0
CREASE_MAX_DEG = 120.0          # beyond this the two faces are a flipped pair or a lip folded back, not a crease
CREASE_MIN_CHAIN = 0.10         # metres: shorter chains are bolt bosses, badge steps, facet noise
CREASE_STEP = 0.003             # metres between samples along a chain (paint_pass queries them in a cKDTree)
CREASE_TURN = math.cos(math.radians(35.0))   # a chain runs on through a junction along the straightest edge


def _space_objects(space):
    """The object names of bake_atlas.SPACES[space], read from its source (importing bake_atlas
    would run its bake)."""
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bake_atlas.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SPACES" for t in node.targets):
            return ast.literal_eval(node.value)[space]
    raise KeyError("no SPACES in " + src)


def _world(ob, co):
    mw = np.array(ob.matrix_world, dtype=np.float64)
    return co @ mw[:3, :3].T + mw[:3, 3], np.linalg.inv(mw[:3, :3]).T


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-15)


def _weld_ids(pos):
    q = np.round(pos / WELD).astype(np.int64)
    _u, inv = np.unique(q, axis=0, return_inverse=True)
    return inv.reshape(-1).astype(np.int64)


def _face_attr(me, name, default):
    out = np.full(len(me.polygons), default, dtype=np.int64)
    a = me.attributes.get(name)
    if a is not None and a.domain == 'FACE' and len(me.polygons):
        vals = [0] * len(me.polygons)
        a.data.foreach_get("value", vals)
        out[:] = vals
    return out


def _corner_normals(me):
    n = np.empty(len(me.loops) * 3, dtype=np.float32)
    src = me.corner_normals if hasattr(me, "corner_normals") else me.loops
    src.foreach_get("vector" if hasattr(me, "corner_normals") else "normal", n)
    return n.reshape(-1, 3).astype(np.float64)


def _triangles(ob, mat_index):
    """Per loop triangle of one object: material (global index), gen, island, vertex ids, welded
    ids, world positions, corner normals, face normal, layer-0 UVs."""
    me = ob.data
    me.calc_loop_triangles()
    T = len(me.loop_triangles)
    nv, nl = len(me.vertices), len(me.loops)
    co = np.empty(nv * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    pos, nrm_m = _world(ob, co.reshape(-1, 3))
    tv = np.empty(T * 3, dtype=np.int32)
    tl = np.empty(T * 3, dtype=np.int32)
    tp = np.empty(T, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", tv)
    me.loop_triangles.foreach_get("loops", tl)
    me.loop_triangles.foreach_get("polygon_index", tp)
    tv, tl = tv.reshape(-1, 3), tl.reshape(-1, 3)
    pm = np.zeros(len(me.polygons), dtype=np.int32)
    if len(me.polygons):
        me.polygons.foreach_get("material_index", pm)
    names = [m.name if m else "?" for m in me.materials] or ["?"]
    local = np.array([mat_index(n) for n in names], dtype=np.int16)
    gen = _face_attr(me, "gen", 0)
    isl = _face_attr(me, "uv_island", -1)
    cn = _corner_normals(me) @ nrm_m.T
    cn = _unit(cn)
    uv = np.zeros(nl * 2, dtype=np.float32)
    if me.uv_layers:
        me.uv_layers[0].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    P = pos[tv]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    ln = np.linalg.norm(fn, axis=1)
    poly_n = np.empty(len(me.polygons) * 3, dtype=np.float64)
    if len(me.polygons):
        me.polygons.foreach_get("normal", poly_n)
    poly_n = _unit(poly_n.reshape(-1, 3) @ nrm_m.T)
    fn = np.where(ln[:, None] > 1e-14, fn / np.maximum(ln, 1e-30)[:, None], poly_n[tp])
    return {
        "mat": local[np.clip(pm[tp], 0, len(local) - 1)],
        "gen": gen[tp].astype(np.int8),
        "island": isl[tp].astype(np.int32),
        "vid": tv.astype(np.int64),
        "wid": _weld_ids(pos)[tv],
        "pos": P.astype(np.float32),
        "nrm": cn[tl].astype(np.float32),
        "fnrm": fn.astype(np.float32),
        "uv": uv[tl].astype(np.float32),
        "nv": nv,
    }


def _crease_edges(ob):
    """Crease edges of one twin: welded edges shared by exactly two faces of the same material in
    CREASE_MATS, folded CREASE_MIN_DEG..CREASE_MAX_DEG. Returns (A, B, wa, wb, n1, n2, convex,
    angle) arrays. (Whether the corner normals split across an edge says nothing here: the bake
    flattens the twins and crv_kotris.blend keeps them flat.)"""
    me = ob.data
    nv, nl, npoly = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(nv * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    pos, nrm_m = _world(ob, co.reshape(-1, 3))
    wid = _weld_ids(pos)
    lv = np.empty(nl, dtype=np.int32)
    me.loops.foreach_get("vertex_index", lv)
    start = np.empty(npoly, dtype=np.int32)
    total = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    pm = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get("material_index", pm)
    pn = np.empty(npoly * 3, dtype=np.float64)
    me.polygons.foreach_get("normal", pn)
    pn = _unit(pn.reshape(-1, 3) @ nrm_m.T)
    pc = np.empty(npoly * 3, dtype=np.float64)
    me.polygons.foreach_get("center", pc)
    pc, _ = _world(ob, pc.reshape(-1, 3))
    names = [m.name if m else "?" for m in me.materials] or ["?"]
    ok_mat = np.array([n in CREASE_MATS for n in names])
    poly_of = np.repeat(np.arange(npoly), total)
    nxt = np.arange(nl) + 1
    ends = start + total - 1
    nxt[ends] = start
    wa, wb = wid[lv], wid[lv[nxt]]
    lo, hi = np.minimum(wa, wb), np.maximum(wa, wb)
    keep = (lo != hi) & ok_mat[pm[poly_of]]
    loops = np.nonzero(keep)[0]
    key = lo[loops] * (int(wid.max()) + 1) + hi[loops]
    order = np.argsort(key, kind="stable")
    loops, key = loops[order], key[order]
    uk, first, count = np.unique(key, return_index=True, return_counts=True)
    two = first[count == 2]
    l1, l2 = loops[two], loops[two + 1]
    p1, p2 = poly_of[l1], poly_of[l2]
    same = (p1 != p2) & (pm[p1] == pm[p2])
    l1, l2, p1, p2 = l1[same], l2[same], p1[same], p2[same]
    n1, n2 = pn[p1], pn[p2]
    ang = np.degrees(np.arccos(np.clip((n1 * n2).sum(1), -1.0, 1.0)))
    sel = (ang >= CREASE_MIN_DEG) & (ang <= CREASE_MAX_DEG)
    l1, l2, p1, p2, n1, n2, ang = l1[sel], l2[sel], p1[sel], p2[sel], n1[sel], n2[sel], ang[sel]
    A, B = pos[lv[l1]], pos[lv[nxt[l1]]]
    mid = (A + B) / 2.0
    s = ((n1 * (pc[p2] - mid)).sum(1) + (n2 * (pc[p1] - mid)).sum(1))
    convex = np.where(s < 0.0, 1, -1).astype(np.int8)
    return A, B, wid[lv[l1]], wid[lv[nxt[l1]]], n1, n2, convex, ang


def _chains(wa, wb, A, B):
    """Chain edges through shared welded vertices; at a junction a chain runs on along the
    straightest unused edge (within 35 degrees). Returns a chain id per edge and each chain's length."""
    E = len(wa)
    adj = {}
    for e in range(E):
        adj.setdefault(int(wa[e]), []).append(e)
        adj.setdefault(int(wb[e]), []).append(e)
    used = np.zeros(E, dtype=bool)
    chain = np.full(E, -1, dtype=np.int64)
    lens = []
    d = B - A
    ln = np.linalg.norm(d, axis=1)
    u = d / np.maximum(ln, 1e-15)[:, None]

    def other(e, v):
        return int(wb[e]) if int(wa[e]) == v else int(wa[e])

    def walk(e, v, cid):
        """from edge e, leaving through vertex v"""
        total = 0.0
        while True:
            dir_e = u[e] if int(wb[e]) == v else -u[e]
            best, best_c = None, CREASE_TURN
            for f in adj.get(v, ()):
                if used[f]:
                    continue
                dir_f = u[f] if int(wa[f]) == v else -u[f]
                c = float(np.dot(dir_e, dir_f))
                if c > best_c:
                    best, best_c = f, c
            if best is None:
                return total
            used[best] = True
            chain[best] = cid
            total += ln[best]
            e, v = best, other(best, v)

    # start at chain ends (vertices that are not simple pass-throughs) so a chain is walked whole
    deg = {v: len(es) for v, es in adj.items()}
    seeds = [e for e in range(E) if deg[int(wa[e])] != 2 or deg[int(wb[e])] != 2] + list(range(E))
    for e in seeds:
        if used[e]:
            continue
        cid = len(lens)
        used[e] = True
        chain[e] = cid
        total = ln[e] + walk(e, int(wb[e]), cid) + walk(e, int(wa[e]), cid)
        lens.append(total)
    return chain, np.array(lens, dtype=np.float64)


def creases(twins):
    """twins: [(obj index in the dump, twin object)]. Samples every CREASE_STEP along every crease
    chain at least CREASE_MIN_CHAIN long."""
    out = {k: [] for k in ("pos", "n", "cvx", "obj", "ang", "chain", "chain_len")}
    stats = []
    cid0 = 0
    for oi, tw in twins:
        A, B, wa, wb, n1, n2, cvx, ang = _crease_edges(tw)
        if not len(A):
            continue
        chain, lens = _chains(wa, wb, A, B)
        ok = lens[chain] >= CREASE_MIN_CHAIN
        stats.append((tw.name, float(np.linalg.norm(B - A, axis=1).sum()), float(np.linalg.norm(B - A, axis=1)[ok].sum()),
                      int((lens >= CREASE_MIN_CHAIN).sum())))
        nm = _unit(n1 + n2)
        for e in np.nonzero(ok)[0]:
            L = float(np.linalg.norm(B[e] - A[e]))
            k = max(1, int(math.ceil(L / CREASE_STEP)))
            t = (np.arange(k + 1) / k)[:, None]
            out["pos"].append(A[e] + (B[e] - A[e]) * t)
            m = k + 1
            out["n"].append(np.repeat(nm[e][None], m, 0))
            out["cvx"].append(np.full(m, cvx[e], np.int8))
            out["obj"].append(np.full(m, oi, np.int16))
            out["ang"].append(np.full(m, ang[e], np.float32))
            out["chain"].append(np.full(m, cid0 + chain[e], np.int32))
            out["chain_len"].append(np.full(m, lens[chain[e]], np.float32))
        cid0 += len(lens)
    if not out["pos"]:
        return {"crease_pos": np.zeros((0, 3), np.float32), "crease_n": np.zeros((0, 3), np.float32),
                "crease_cvx": np.zeros(0, np.int8), "crease_obj": np.zeros(0, np.int16),
                "crease_ang": np.zeros(0, np.float32),
                "crease_chain": np.zeros(0, np.int32), "crease_chain_len": np.zeros(0, np.float32)}, stats
    cat = {k: np.concatenate(v) for k, v in out.items()}
    return {"crease_pos": cat["pos"].astype(np.float32), "crease_n": cat["n"].astype(np.float32),
            "crease_cvx": cat["cvx"], "crease_obj": cat["obj"], "crease_ang": cat["ang"],
            "crease_chain": cat["chain"], "crease_chain_len": cat["chain_len"]}, stats


def dump(objs, path, size, meta=None):
    """Write `path` (np.savez_compressed). Arrays: size, obj_names, mat_names, meta (JSON string);
    per triangle tri_obj int16, tri_mat int16, tri_gen int8, tri_island int32 (face attribute
    uv_island, -1 when absent), tri_vid int32 (T,3) (per-object offsets), tri_wid int32 (T,3) (welded
    by position, per object), tri_pos float32 (T,3,3) world, tri_nrm float32 (T,3,3) corner normals
    as rendered, tri_fnrm float32 (T,3), tri_uv float32 (T,3,2) layer-0 UVs (v up: texel column =
    u * size, row = (1 - v) * size); crease_* from the `<name>_hi` twins (see creases()): crease_pos
    (N,3), crease_n (N,3) the mean of the two face normals, crease_cvx int8 (+1 convex, -1 concave),
    crease_obj int16, and for tuning crease_ang (fold, degrees), crease_chain, crease_chain_len."""
    mats = []

    def mat_index(n):
        if n not in mats:
            mats.append(n)
        return mats.index(n)
    parts = []
    voff = woff = 0
    twins = []
    for oi, ob in enumerate(objs):
        t = _triangles(ob, mat_index)
        T = len(t["mat"])
        t["obj"] = np.full(T, oi, np.int16)
        t["vid"] = t["vid"] + voff
        t["wid"] = t["wid"] + woff
        voff += t["nv"]
        if T:
            woff = int(t["wid"].max()) + 1
        parts.append(t)
        tw = bpy.data.objects.get(ob.name + "_hi")
        if tw is not None and tw.type == 'MESH':
            twins.append((oi, tw))
    cat = {k: np.concatenate([p[k] for p in parts]) for k in ("obj", "mat", "gen", "island", "vid", "wid", "pos", "nrm", "fnrm", "uv")}
    cr, stats = creases(twins)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    np.savez_compressed(
        path, size=np.int32(size), obj_names=np.array([o.name for o in objs]), mat_names=np.array(mats),
        meta=np.array(json.dumps(meta or {})),
        tri_obj=cat["obj"].astype(np.int16), tri_mat=cat["mat"].astype(np.int16), tri_gen=cat["gen"].astype(np.int8),
        tri_island=cat["island"].astype(np.int32), tri_vid=cat["vid"].astype(np.int32), tri_wid=cat["wid"].astype(np.int32),
        tri_pos=cat["pos"], tri_nrm=cat["nrm"], tri_fnrm=cat["fnrm"], tri_uv=cat["uv"], **cr)
    for name, total, kept, n in stats:
        print("uvmesh: %-14s crease edges %.1f m, %.1f m in %d chains >= %.0f cm" % (name, total, kept, n, CREASE_MIN_CHAIN * 100))
    print("uvmesh: %d triangles of %d objects, %d crease samples (%d twins) -> %s"
          % (len(cat["obj"]), len(objs), len(cr["crease_pos"]), len(twins), path))
    return path


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

    def arg(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default
    space = arg("--space", "shell")
    names, size = _space_objects(space)
    size = int(arg("--size", size))
    out = arg("--out", None)
    if out is None:
        raise SystemExit("uvmesh_dump: --out <file.npz> is required (never writes into the repo by default)")
    objs = [bpy.data.objects[n] for n in names if n in bpy.data.objects and bpy.data.objects[n].type == 'MESH']
    dump(objs, out, size, {"source": os.path.basename(bpy.data.filepath), "space": space})
    print("UVMESH DONE")


if __name__ == "__main__":
    main()
