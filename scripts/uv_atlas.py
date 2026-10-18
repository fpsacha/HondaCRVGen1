r"""
Flat-colour UV atlas: every face is mapped to the cell of its material.

    import uv_atlas; uv_atlas.assign(obj)                    # inside Blender
    python scripts/uv_atlas.py                               # writes the PNG (needs PIL)

The model carries its colour in per-face materials. The game reads colour from one 512x512 shell
texture, so each material gets a 128x128 cell in a 4x4 grid and every face of that material is
mapped to the cell. In game the car then looks exactly like the Blender renders, and the atlas is
a real starting point for hand painting later: a cell is 128 px of paintable space, not a single
texel. KI5 uses 512x512 for everything (spec/pz-conventions.md section 7), so the size matches.
"""
import os

SIZE = 512
GRID = 4
CELL = SIZE // GRID                   # 128
INSET = 10                            # px kept clear of the cell edge, so mipmaps do not bleed

# same order as build_body.MATS, which is the material slot order on every mesh
ORDER = ["paint", "cladding", "glass", "black", "light_f", "light_r", "grille",
         "rubber", "rim", "light_a"]
COLOURS = {
    "paint":    (196, 198, 202),
    "cladding": (58, 58, 60),
    "glass":    (48, 60, 74),
    "black":    (18, 18, 18),
    "light_f":  (232, 230, 190),
    "light_r":  (176, 26, 22),
    "grille":   (26, 26, 26),
    "rubber":   (22, 22, 22),
    "rim":      (178, 180, 184),
    "light_a":  (212, 112, 16),
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEX_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1",
                       "common", "media", "textures", "Vehicles")
NAME = "Vehicles_HondaCRVGen1_Shell"


def cell_uv(index):
    """(u0, v0, u1, v1) of the paintable area of cell `index`, in UV space."""
    col, row = index % GRID, index // GRID
    x0 = col * CELL + INSET
    y0 = row * CELL + INSET
    x1 = (col + 1) * CELL - INSET
    y1 = (row + 1) * CELL - INSET
    return (x0 / SIZE, 1.0 - y1 / SIZE, x1 / SIZE, 1.0 - y0 / SIZE)


def assign(ob):
    """Map every face of `ob` onto its material's cell. Runs inside Blender."""
    me = ob.data
    uvs = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    boxes = [cell_uv(i) for i in range(GRID * GRID)]
    corners = ((0, 1), (2, 1), (2, 3), (0, 3))            # (u index, v index) per loop corner
    for poly in me.polygons:
        u0, v0, u1, v1 = boxes[min(poly.material_index, len(boxes) - 1)]
        vals = (u0, v0, u1, v1)
        n = poly.loop_total
        for i, li in enumerate(range(poly.loop_start, poly.loop_start + n)):
            ui, vi = corners[i % 4]
            uvs.data[li].uv = (vals[ui], vals[vi])
    return uvs


def write_png(path=None, mats=None):
    """Paint the atlas. Needs PIL, so it runs in the system Python, not in Blender."""
    from PIL import Image, ImageDraw
    mats = mats or ORDER
    im = Image.new("RGB", (SIZE, SIZE), (255, 0, 255))     # magenta = an unused cell
    d = ImageDraw.Draw(im)
    for i in range(GRID * GRID):
        col, row = i % GRID, i // GRID
        box = (col * CELL, row * CELL, (col + 1) * CELL - 1, (row + 1) * CELL - 1)
        name = mats[i] if i < len(mats) else None
        d.rectangle(box, fill=COLOURS.get(name, (40, 40, 40)))
    path = path or os.path.join(TEX_DIR, NAME + ".png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path)
    return path


def write_variants(colours=None):
    """One shell per paint colour, the way KI5 ships a Shell_<colour> per skin."""
    from PIL import Image
    colours = colours or {
        "": (196, 198, 202), "_white": (226, 228, 230), "_black": (34, 34, 36),
        "_red": (140, 34, 32), "_blue": (44, 66, 110), "_green": (52, 82, 58),
        "_silver": (168, 172, 178), "_gold": (188, 176, 138),
    }
    out = []
    base = write_png()
    for suffix, rgb in colours.items():
        im = Image.open(base).convert("RGB")
        px = im.load()
        u0, v0, u1, v1 = 0, 0, CELL, CELL                  # cell 0 is "paint"
        for y in range(v0, v1):
            for x in range(u0, u1):
                px[x, y] = rgb
        p = os.path.join(TEX_DIR, "%s%s.png" % (NAME, suffix))
        im.save(p)
        out.append(p)
    return out


if __name__ == "__main__":
    for p in write_variants():
        print("WROTE", p)
