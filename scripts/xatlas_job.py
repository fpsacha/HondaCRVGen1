r"""
xatlas charts + packing in a separate process (bake_atlas.unwrap_xatlas, planar_uv.unwrap).

    <python 3.11> scripts\xatlas_job.py in.npz out.npz [pylib_dir]

xatlas (tools/pylib, built with a newer MSVC runtime) crashes inside blender.exe, which loads its
own older MSVCP140.dll first (std::mutex access violation on every worker thread). Blender's
bundled python.exe on its own is fine, so the caller writes its meshes to in.npz, runs this with
that interpreter, and reads the UVs back from out.npz. bake_atlas passes its PYLIB as the third
argument (a worktree copy of the scripts has no tools/pylib of its own).

Modes (in.npz "mode"; absent = "atlas"):
  atlas  charts + packing of 3D mesh groups on one page of `size` (the interior, wheel and engine
         sheets and the shell's even texCoords1 layout; bake_atlas._xatlas_pass)
         in:  size, padding, n, pos<k> (float32 Vx3), ind<k> (uint32 Fx3)
         out: vmap<k>, ind<k>, uv<k> per group, plus charts, pages, util, tpu, faces
  chart  charting and parametrisation only (planar_uv: the shell's fallback faces): resolution 0 at
         a fixed texels_per_unit, so every chart comes out at that density; nothing is packed for
         real (padding 0, no brute force)
         in:  tpu, n, pos<k>, ind<k>
         out: vmap<k>, ind<k>, uv<k> per group with uv in TEXELS, plus charts, width, height
  pack   packing only of ready-made UV islands (planar_uv: panel islands, fallback charts, cells),
         one add_uv_mesh, coordinates in texels at texels_per_unit 1 so xatlas keeps every scale.
         xatlas makes a chart of faces that share a vertex index OR a vertex POSITION (measured
         2026-10-12: two triangles touching at one corner with distinct indices came out as one
         chart), so islands that overlap in their own coordinates (a fold's second layer, two
         fallback charts packed edge to edge) would be packed welded together: every face carries
         its chart id as its material, and faces of different materials are never one chart.
         90-degree turns allowed (xatlas turns a chart by transposing it), never
         rotate_charts_to_axis (panel islands stay axis-aligned).
         The page: with resolution = size xatlas left the right ~20 % of the shell page empty and
         spilled small charts onto a second page (2026-10-12: extents 1646 x 2048 at scale 0.857,
         six charts of <= 17 px spilled), since its brute-force search only looks a step past the
         extents it has. So the atlas is resizable (resolution 0) and starts with an L-shaped
         dummy chart along two edges of a size x size page: from the first chart on, every place
         inside the page costs the same in xatlas's metric (extents^2 + area) and its tie-break
         (closest to the origin) makes it a bottom-left fill. A layout fits when every real chart
         lies inside the page (FRAME_MARGIN from the far edges). If it does not, every non-fixed
         input shrinks by `step` until it fits, the last step landing on `min_scale` itself (if
         that misses too, pages = 2 and the caller fails loudly); then REFINE bisections between
         the last miss and the fit take the largest scale that fits.
         in:  uv (float32 Vx2 texels), ind (uint32 Fx3), mat (uint32 F: chart id), fixed (bool V:
              cells keep their size), size, padding, step, min_scale
         out: vmap, ind (the real faces), uv (normalised by size), pages, charts, util, width,
              height, scale
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(HERE), "tools", "pylib"))

import numpy as np  # noqa: E402
import xatlas  # noqa: E402


def face_coverage(atlas, n):
    """Share of the page under triangles (uv is normalised 0..1 here). xatlas's own utilization
    counts padding and the bilinear margin as used: on v6's shell 76 % utilization was 21 % faces."""
    total = 0.0
    for k in range(n):
        _vmap, ind, uv = atlas[k]
        p = uv[ind]                                            # (F, 3, 2)
        a, b, c = p[:, 0], p[:, 1], p[:, 2]
        total += float(np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])).sum()) / 2.0
    return total


def _util(atlas):
    util = atlas.utilization
    return float(util[0]) if hasattr(util, "__len__") else float(util)


def atlas_mode(d):
    size, padding, n = int(d["size"]), int(d["padding"]), int(d["n"])
    tpu = 0.0
    for _attempt in range(10):
        atlas = xatlas.Atlas()
        for k in range(n):
            atlas.add_mesh(d["pos%d" % k], d["ind%d" % k])
        co = xatlas.ChartOptions()
        co.max_iterations = 2
        po = xatlas.PackOptions()
        po.resolution = size
        po.padding = padding
        po.bilinear = True
        po.rotate_charts = True
        po.bruteForce = True            # 76 % -> 90 % utilization on the shell set for ~30 s a pass (2026-10-12)
        po.texels_per_unit = tpu
        atlas.generate(co, po)
        if atlas.atlas_count == 1:
            break
        tpu = atlas.texels_per_unit * 0.93          # spilled onto a second page: a little less density
    faces = face_coverage(atlas, n) if atlas.atlas_count == 1 else 0.0
    out = {"charts": atlas.chart_count, "pages": atlas.atlas_count, "util": _util(atlas),
           "tpu": float(atlas.texels_per_unit), "faces": faces}
    for k in range(n):
        vmap, ind, uv = atlas[k]
        out["vmap%d" % k] = vmap
        out["ind%d" % k] = ind
        out["uv%d" % k] = uv
    print("XATLAS %d charts, %d page(s), utilization %.0f%%, faces %.0f%% of sheet"
          % (atlas.chart_count, atlas.atlas_count, 100 * out["util"], 100 * faces))
    return out


def chart_mode(d):
    n, tpu = int(d["n"]), float(d["tpu"])
    atlas = xatlas.Atlas()
    for k in range(n):
        atlas.add_mesh(d["pos%d" % k], d["ind%d" % k])
    co = xatlas.ChartOptions()
    co.max_iterations = 2
    po = xatlas.PackOptions()
    po.resolution = 0                   # one page as big as it needs: the charts keep tpu exactly
    po.padding = 0
    po.bilinear = False
    po.rotate_charts = True             # each chart turned to its smallest box (rotate_charts_to_axis default)
    po.bruteForce = False
    po.texels_per_unit = tpu
    atlas.generate(co, po)
    w, h = atlas.width, atlas.height
    out = {"charts": atlas.chart_count, "pages": atlas.atlas_count, "width": w, "height": h}
    for k in range(n):
        vmap, ind, uv = atlas[k]
        out["vmap%d" % k] = vmap
        out["ind%d" % k] = ind
        out["uv%d" % k] = (uv.astype(np.float64) * np.array([w, h])).astype(np.float32)
    print("XATLAS chart %d charts at %.1f texels/m, %d x %d" % (atlas.chart_count, tpu, w, h))
    return out


FRAME_MARGIN = 1                      # texels a real chart keeps from the page's far edges
REFINE = 4                            # bisections after the first fit (scale to ~0.3 % of a step)


def _pack_once(uv, ind, mat, fixed, size, padding, scale):
    """One resizable xatlas pack behind the L frame; (fits, result dict)."""
    n, nf = len(uv), len(ind)
    u = uv.copy()
    u[~fixed] *= scale
    arm = float(size - 2 * (padding + 1) - 2)        # its footprint (padding, bilinear texel) stays on the page
    frame = np.array([(0, 0), (arm, 0), (arm, 1), (1, 1), (1, arm), (0, arm)], dtype=np.float32)
    fi = np.array([(0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 5)], dtype=np.uint32) + n
    atlas = xatlas.Atlas()
    atlas.add_uv_mesh(np.concatenate([u, frame]), np.concatenate([ind, fi]),
                      np.concatenate([mat, np.full((4, 1), mat.max() + 1, dtype=np.uint32)]))
    po = xatlas.PackOptions()
    po.resolution = 0
    po.padding = padding
    po.bilinear = True
    po.rotate_charts = True
    po.rotate_charts_to_axis = False
    po.bruteForce = True
    po.texels_per_unit = 1.0
    atlas.generate(xatlas.ChartOptions(), po)
    vmap, oind, ouv = atlas[0]
    q = ouv.astype(np.float64) * np.array([atlas.width, atlas.height])
    real = q[vmap < n]
    fits = atlas.atlas_count == 1 and real.min() >= 0.0 and real.max() <= size - FRAME_MARGIN
    print("XATLAS pack scale %.4f: %d charts, extents %.0f x %.0f of %d, utilization %.0f%% -> %s"
          % (scale, atlas.chart_count - 1, real[:, 0].max(), real[:, 1].max(), size, 100 * _util(atlas),
             "fits" if fits else "no"), flush=True)
    return fits, {"vmap": vmap, "ind": oind[:nf], "uv": (q / size).astype(np.float32), "pages": 1 if fits else 2,
                  "charts": atlas.chart_count - 1, "util": _util(atlas) * atlas.width * atlas.height / size ** 2,
                  "width": size, "height": size, "scale": scale}


def pack_mode(d):
    uv, ind = d["uv"].astype(np.float32), d["ind"].astype(np.uint32)
    mat = d["mat"].astype(np.uint32).reshape(-1, 1)
    fixed = d["fixed"].astype(bool)
    size, padding = int(d["size"]), int(d["padding"])
    step, min_scale = float(d["step"]), float(d["min_scale"])
    scale, miss = 1.0, None
    while True:
        fits, best = _pack_once(uv, ind, mat, fixed, size, padding, scale)
        if fits:
            break
        miss = scale
        if scale <= min_scale + 1e-9:
            break                       # not even the floor fits: pages 2, the caller fails loudly
        # the last step lands on the floor itself (from 1.0 by 0.95 the steps skip 0.80-0.81)
        scale = max(scale * step, min_scale)
    if fits and miss is not None:
        lo, hi = scale, miss
        for _k in range(REFINE):
            mid = 0.5 * (lo + hi)
            ok, res = _pack_once(uv, ind, mat, fixed, size, padding, mid)
            if ok:
                lo, best = mid, res
            else:
                hi = mid
    return best


def main():
    src, dst = sys.argv[1], sys.argv[2]
    d = np.load(src)
    mode = str(d["mode"]) if "mode" in d.files else "atlas"
    out = {"atlas": atlas_mode, "chart": chart_mode, "pack": pack_mode}[mode](d)
    np.savez(dst, **out)


if __name__ == "__main__":
    main()
