r"""
A small 2D painter for moulded interior trims (door cards, the tailgate card, the cargo trims), in
numpy only so it runs inside Blender (prep_parts, bake_atlas) and in system Python alike.

Why it exists (2026-10-13, feedback: "is it possible to have better texture, not resolution but just
better texture with more details?"; screenshot 34.png showed the open tailgate's card as a flat light-grey
slab). The cards were flat fills with hard edges: a grey board with dark rectangles on it. KI5's
painted trims (Touran, Trooper, XJ, W460 sheets) read as moulded plastic because the LIGHT is in the
texture: every raised panel has a lit top edge and a dark bottom edge, every recess the reverse, every
panel line is a dark line with a lighter line beside it, and raised parts drop a soft shadow on the
card under them. The game lights the whole card with one 3-step value, so nothing else draws that
relief. This module draws exactly those terms from signed distance fields:

  * shapes are signed distances in METRES (negative inside), so a 1.2 cm line is 1.2 cm on every card
    whatever its texture size, and the bevels follow the true outline (gradient of the distance);
  * the light comes from above (+v, the card's up); u is mirrored between the left and right doors
    (the decal maps by model y), so a horizontal light component would flip between the sides;
  * sizes follow the playbook's density rules: the cards bake at ~2.8 texels/cm (shell sheet, door
    card weight 2) and ~0.7 after the default 512 cap; the cargo trims at ~0.7 (interior sheet) and
    ~0.35 capped. Lines are >= 0.8 cm with their highlight (>= 1.2 cm together), shapes >= ~1 cm, no
    texel-scale grain (it read as speckle / static at the game's zoom, 2026-10-11 / 10-12);
  * the bake POINT-samples the painted map (one sample per texel, playbook "the colour bake takes one
    sample per texel"), so `prefilter` blurs the finished canvas to about half a destination texel.

Canvas rows run bottom-up (row 0 = v 0), Blender's pixel order; `to_rgba` returns floats 0..1.
"""
import numpy as np

LIGHT = (0.0, 1.0)                       # canvas-space light direction: straight down from above


def srgb(c):
    return np.asarray(c, dtype=np.float32)


class Canvas:
    """w x h metres at px_per_m; colours are sRGB 0..255 floats; X, Y are metres from the bottom-left."""

    def __init__(self, w, h, px_per_m=1000.0, base=(128, 128, 128)):
        self.w, self.h, self.k = float(w), float(h), float(px_per_m)
        self.W = max(16, int(round(self.w * self.k)))
        self.H = max(16, int(round(self.h * self.k)))
        self.px = self.w / self.W                # metres per pixel (x); y uses the same within 1 %
        xs = (np.arange(self.W, dtype=np.float32) + 0.5) * (self.w / self.W)
        ys = (np.arange(self.H, dtype=np.float32) + 0.5) * (self.h / self.H)
        self.X, self.Y = np.meshgrid(xs, ys)
        self.img = np.empty((self.H, self.W, 3), np.float32)
        self.img[:] = srgb(base)

    # ------------------------------------------------------------------ shapes (signed metres)
    def rrect(self, x0, y0, x1, y1, r=0.0, X=None, Y=None):
        X = self.X if X is None else X
        Y = self.Y if Y is None else Y
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        hx, hy = abs(x1 - x0) / 2.0, abs(y1 - y0) / 2.0
        r = max(0.0, min(r, hx, hy))
        qx = np.abs(X - cx) - (hx - r)
        qy = np.abs(Y - cy) - (hy - r)
        out = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
        return out + np.minimum(np.maximum(qx, qy), 0.0) - r

    def circle(self, cx, cy, r, X=None, Y=None):
        X = self.X if X is None else X
        Y = self.Y if Y is None else Y
        return np.hypot(X - cx, Y - cy) - r

    def seg_dist(self, pts, X=None, Y=None, with_t=False):
        """Unsigned distance to a polyline; with_t also returns the arc length of the nearest point."""
        X = self.X if X is None else X
        Y = self.Y if Y is None else Y
        best = np.full(X.shape, np.inf, np.float32)
        tbest = np.zeros(X.shape, np.float32)
        run = 0.0
        for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            L = L2 ** 0.5
            t = np.clip(((X - ax) * dx + (Y - ay) * dy) / max(L2, 1e-12), 0.0, 1.0)
            d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
            closer = d < best
            best = np.where(closer, d, best)
            if with_t:
                tbest = np.where(closer, run + t * L, tbest)
            run += L
        return (best, tbest) if with_t else best

    def band(self, pts, half_w, X=None, Y=None):
        """A thick polyline (round ends and joins)."""
        return self.seg_dist(pts, X, Y) - half_w

    def polygon(self, pts, X=None, Y=None):
        """Signed distance to a closed polygon (even-odd inside test)."""
        X = self.X if X is None else X
        Y = self.Y if Y is None else Y
        P = list(pts) + [pts[0]]
        d = self.seg_dist(P, X, Y)
        inside = np.zeros(X.shape, bool)
        for (ax, ay), (bx, by) in zip(P[:-1], P[1:]):
            cross = ((ay > Y) != (by > Y))
            xint = ax + (Y - ay) * (bx - ax) / ((by - ay) if by != ay else 1e-12)
            inside ^= cross & (X < xint)
        return np.where(inside, -d, d)

    def outline(self, tris, segs):
        """Signed distance to a card's true outline: tris (N,3,2) and boundary segments (M,2,2), metres
        in canvas space. Inside = covered by a triangle (texel centre test)."""
        inside = np.zeros(self.X.shape, bool)
        for a, b, c in tris:
            x0, x1 = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
            y0, y1 = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
            i0, i1 = max(0, int(x0 / self.px) - 1), min(self.W, int(x1 / self.px) + 2)
            j0, j1 = max(0, int(y0 / self.px) - 1), min(self.H, int(y1 / self.px) + 2)
            if i1 <= i0 or j1 <= j0:
                continue
            X, Y = self.X[j0:j1, i0:i1], self.Y[j0:j1, i0:i1]
            den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(den) < 1e-14:
                continue
            l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / den
            l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / den
            inside[j0:j1, i0:i1] |= (l1 >= -1e-6) & (l2 >= -1e-6) & (l1 + l2 <= 1 + 1e-6)
        d = np.full(self.X.shape, np.inf, np.float32)
        for (ax, ay), (bx, by) in segs:
            d = np.minimum(d, self.seg_dist([(ax, ay), (bx, by)]))
        return np.where(inside, -d, d)

    @staticmethod
    def union(*ds):
        return np.minimum.reduce(ds)

    @staticmethod
    def cut(a, b):
        """a minus b."""
        return np.maximum(a, -b)

    # ------------------------------------------------------------------ coverage and fields
    def cov(self, d, feather=None):
        f = self.px if feather is None else max(feather, self.px)
        return np.clip(0.5 - d / f, 0.0, 1.0)

    def normal(self, d):
        """Unit outward normal (gradient of the distance), canvas axes."""
        gy, gx = np.gradient(d, self.px)
        n = np.hypot(gx, gy) + 1e-9
        return gx / n, gy / n

    def facing(self, d):
        nx, ny = self.normal(d)
        return nx * LIGHT[0] + ny * LIGHT[1]

    # ------------------------------------------------------------------ paint operations
    def fill(self, d, colour, a=1.0, feather=None):
        c = (self.cov(d, feather) * a)[..., None]
        self.img = self.img * (1.0 - c) + srgb(colour) * c

    def scale(self, d, k, feather=None):
        """Multiply inside the shape by k (scalar or per-pixel)."""
        c = self.cov(d, feather)
        self.img *= (1.0 + c * (np.asarray(k, np.float32) - 1.0))[..., None]

    def gradient_v(self, d, k_top, k_bottom, y0, y1):
        """Inside the shape, multiply by a vertical ramp k_bottom (y0) .. k_top (y1)."""
        t = np.clip((self.Y - y0) / max(y1 - y0, 1e-6), 0.0, 1.0)
        self.scale(d, k_bottom + (k_top - k_bottom) * t)

    def bevel(self, d, w, hi=1.16, lo=0.74, raised=True, edge=0.96):
        """A moulded edge `w` wide just inside the outline: raised parts catch the light on their top
        edge and fall dark on the bottom one (recessed: the reverse); `edge` darkens every side a
        little so vertical edges still read."""
        s = self.facing(d)
        if not raised:
            s = -s
        e = np.clip(1.0 + d / max(w, 1e-6), 0.0, 1.0) * self.cov(d)
        e = e * e * (3.0 - 2.0 * e)                       # smooth falloff into the panel
        k = np.where(s > 0, 1.0 + (hi - 1.0) * s, 1.0 + (1.0 - lo) * s) * edge
        self.img *= (1.0 + e * (k - 1.0))[..., None]

    def groove(self, d, w=0.008, k=0.62, hi=1.12, hw=0.006):
        """A moulded panel line centred on the outline: a dark core `w` wide (KI5's 1-texel line at our
        density) and a lighter line `hw` wide on its lower side, where the groove's far wall faces up.
        The core stays dark net of the highlight, so the line survives the 512 cap's 4x box."""
        s = self.facing(d)
        core = self.cov(np.abs(d) - w / 2.0)
        self.img *= (1.0 - (1.0 - k) * core)[..., None]
        below = np.sign(d) * s < 0                        # the side of the line away from the light
        band = self.cov(np.abs(d) - (w / 2.0 + hw)) * (1.0 - core) * below * np.abs(s)
        self.img *= (1.0 + (hi - 1.0) * band)[..., None]

    def shadow(self, shape, off=0.012, soft=0.012, k=0.70):
        """Soft shadow a raised shape drops on the card under it (outside the shape only). `shape` is a
        function (X, Y) -> signed distance; the shadow is the shape moved down by `off`, feathered."""
        d0 = shape(self.X, self.Y)
        ds = shape(self.X, self.Y + off)
        s = self.cov(ds, soft) * (1.0 - self.cov(d0))
        self.img *= (1.0 - (1.0 - k) * s)[..., None]

    def dots(self, d, pitch, r, k, offset=(0.0, 0.0)):
        """A grid of round dimples (speaker grilles) inside the shape, each multiplied by k."""
        gx = np.mod(self.X - offset[0], pitch) - pitch / 2.0
        gy = np.mod(self.Y - offset[1], pitch) - pitch / 2.0
        dd = np.hypot(gx, gy) - r
        self.img *= (1.0 - (1.0 - k) * self.cov(dd) * self.cov(d))[..., None]

    def dashes(self, pts, offset=0.0, length=0.010, gap=0.006, w=0.0035, k=0.80):
        """Stitching: dashes along a polyline (at `offset` from it, + = the polyline's left side)."""
        dist, t = self.seg_dist(pts, with_t=True)
        if offset:
            # side of the polyline: sign of the cross product with the nearest segment's direction
            side = np.zeros(self.X.shape, np.float32)
            best = np.full(self.X.shape, np.inf, np.float32)
            for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
                dd = self.seg_dist([(ax, ay), (bx, by)])
                cr = (bx - ax) * (self.Y - ay) - (by - ay) * (self.X - ax)
                closer = dd < best
                best = np.where(closer, dd, best)
                side = np.where(closer, np.sign(cr), side)
            dist = np.abs(dist * side - offset)
        on = np.mod(t, length + gap) < length
        m = self.cov(dist - w / 2.0) * on
        self.img *= (1.0 - (1.0 - k) * m)[..., None]

    def grain(self, cell, amount, seed=1, d=None):
        """Smooth value noise with features ~`cell` metres (>= 1 cm: finer grain reads as speckle at the
        game's zoom), multiplied in at +-amount, optionally only inside a shape."""
        rng = np.random.default_rng(seed)
        gw, gh = int(self.w / cell) + 3, int(self.h / cell) + 3
        g = rng.standard_normal((gh, gw)).astype(np.float32)
        fx, fy = self.X / cell + 1.0, self.Y / cell + 1.0
        ix, iy = np.floor(fx).astype(int), np.floor(fy).astype(int)
        tx, ty = fx - ix, fy - iy
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        v = (g[iy, ix] * (1 - tx) * (1 - ty) + g[iy, ix + 1] * tx * (1 - ty)
             + g[iy + 1, ix] * (1 - tx) * ty + g[iy + 1, ix + 1] * tx * ty)
        k = 1.0 + amount * np.clip(v, -2.0, 2.0) / 2.0
        if d is not None:
            k = 1.0 + (k - 1.0) * self.cov(d)
        self.img *= k[..., None]

    # ------------------------------------------------------------------ output
    def prefilter(self, sigma_m):
        """Gaussian blur of sigma metres (separable, a sampled kernel): the bake point-samples the map.
        2026-10-13 texture fix: was three box passes of an odd width b (sigma sqrt((b^2 - 1) / 4)), which
        can only be 0, 1.41, 2.45 ... px: the door cards' 0.8 mm (half a bake texel since the 2x
        supersampled bake) would have stayed 1.41 px. The kernel takes any sigma."""
        s = sigma_m / self.px
        if s < 0.3:
            return
        r = int(np.ceil(3.0 * s))
        k = np.exp(-0.5 * (np.arange(-r, r + 1) / s) ** 2)
        k /= k.sum()
        for axis in (0, 1):
            n = self.img.shape[axis]
            pad = [(r, r) if a == axis else (0, 0) for a in range(self.img.ndim)]
            p = np.pad(self.img, pad, mode="edge")
            out = np.zeros_like(self.img)
            for i, w in enumerate(k):
                out += np.float32(w) * np.take(p, np.arange(i, i + n), axis=axis)
            self.img = out

    def to_rgba(self):
        rgb = np.clip(self.img / 255.0, 0.0, 1.0)
        return np.concatenate([rgb, np.ones(rgb.shape[:2] + (1,), np.float32)], axis=2)


def _box(a, b, axis):
    """Box filter of odd width b along axis, edges clamped."""
    h = b // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (h + 1, h)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(b, b + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / b).astype(np.float32)


def lin_to_srgb(x):
    x = np.clip(np.asarray(x, np.float32), 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
