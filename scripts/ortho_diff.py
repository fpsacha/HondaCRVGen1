r"""
Score a set of calibrated ortho renders against the blueprint crops.

    python scripts/ortho_diff.py export/ortho_cmp v8_

For each of side / front / top: model silhouette = bright pixels of the white-on-black render;
blueprint silhouette = non-white pixels of bp_<view>.png (the drawing is coloured on white; the
light watermark is excluded by the threshold). Writes an overlay per view — blueprint in grey,
model-only in red, blueprint-only in blue, agreement in green — and prints IoU and the
model-only / blueprint-only fractions. IoU is the number to drive up; the overlay says where.
"""
import os
import sys

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BP = os.path.join(ROOT, "blender", "references", "blueprints")


def masks(render_path, bp_path):
    r = Image.open(render_path).convert("L")
    b = Image.open(bp_path).convert("RGB")
    if b.size != r.size:
        b = b.resize(r.size, Image.LANCZOS)
    model = r.point(lambda v: 255 if v > 40 else 0)
    # blueprint: same segmentation as the tracer (holes filled so windows count as body,
    # dimension lines removed) so the score measures shape, not drawing style
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from trace_blueprint import car_mask
    bp = Image.fromarray((car_mask(b) * 255).astype(np.uint8))
    return model, bp, b


def score(model, bp):
    inter = ImageChops.multiply(model, bp)
    union = ImageChops.lighter(model, bp)
    n_i = sum(1 for v in inter.getdata() if v)
    n_u = sum(1 for v in union.getdata() if v)
    n_m = sum(1 for v in model.getdata() if v)
    n_b = sum(1 for v in bp.getdata() if v)
    return (n_i / n_u if n_u else 0.0), (n_m - n_i) / max(n_b, 1), (n_b - n_i) / max(n_b, 1)


def overlay(model, bp, b_rgb):
    base = b_rgb.convert("L").point(lambda v: 120 + v // 2).convert("RGB")
    red = Image.new("RGB", base.size, (230, 40, 40))
    blue = Image.new("RGB", base.size, (40, 90, 230))
    green = Image.new("RGB", base.size, (40, 170, 70))
    m_only = ImageChops.subtract(model, bp)
    b_only = ImageChops.subtract(bp, model)
    both = ImageChops.multiply(model, bp)
    out = Image.composite(green, base, both.point(lambda v: 110 if v else 0))
    out = Image.composite(red, out, m_only.point(lambda v: 170 if v else 0))
    out = Image.composite(blue, out, b_only.point(lambda v: 170 if v else 0))
    return out


def main(out_dir, prefix):
    for view in ("side", "front", "top"):
        rp = os.path.join(out_dir, "%s%s.png" % (prefix, view))
        bpth = os.path.join(BP, "bp_%s.png" % view)
        if not (os.path.exists(rp) and os.path.exists(bpth)):
            print(view, "missing", rp if not os.path.exists(rp) else bpth)
            continue
        model, bp, b_rgb = masks(rp, bpth)
        iou, extra, missing = score(model, bp)
        ov = overlay(model, bp, b_rgb)
        op = os.path.join(out_dir, "%s%s_overlay.png" % (prefix, view))
        ov.save(op)
        print("%-6s IoU %.3f   model-only %.3f   blueprint-only %.3f   -> %s" % (view, iou, extra, missing, op))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "export", "ortho_cmp")
    main(out, sys.argv[2] if len(sys.argv) > 2 else "")
