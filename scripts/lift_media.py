r"""
The lift feature's hand-made media (scripts/features/lift.py MEDIA): the "4x4 Off-Road" magazine's
inventory icon, drawn at 4x and reduced to the 32 x 32 RGBA the game's magazine icons use. Our own
drawing: a glossy cover leaning slightly, a red masthead with 4x4, a dusk sky over a mountain ridge and
a lifted SUV's silhouette on big tyres.

    python scripts\lift_media.py        (system Python + Pillow; writes into this checkout's mod folder)
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures",
                   "Item_CRVGen1_LiftMagazine.png")
K = 4
S = 32 * K


def _font(size):
    for p in (r"C:\Windows\Fonts\ariblk.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def draw():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 5 * K, 2 * K, 27 * K, 30 * K               # the cover (22 x 28 px)
    d.rectangle((x0 + K, y0 + K, x1 + K, y1 + K), fill=(0, 0, 0, 110))   # drop shadow
    d.rectangle((x0, y0, x1, y1), fill=(232, 226, 210, 255), outline=(40, 34, 28, 255), width=K)
    # picture: dusk sky, ridge, ground
    px0, py0, px1, py1 = x0 + 2 * K, y0 + 9 * K, x1 - 2 * K, y1 - 2 * K
    for i in range(py1 - py0):
        t = i / float(py1 - py0)
        d.line((px0, py0 + i, px1, py0 + i), fill=(int(236 - 90 * t), int(150 - 60 * t), int(70 + 40 * t), 255))
    ridge = [(px0, py0 + 9 * K), (px0 + 5 * K, py0 + 4 * K), (px0 + 8 * K, py0 + 7 * K), (px0 + 12 * K, py0 + 2 * K),
             (px1, py0 + 8 * K), (px1, py1), (px0, py1)]
    d.polygon(ridge, fill=(70, 60, 74, 255))
    d.rectangle((px0, py1 - 5 * K, px1, py1), fill=(96, 70, 44, 255))
    # the lifted SUV: boxy body high on two big wheels
    bx0, by0 = px0 + 3 * K, py1 - 11 * K
    d.polygon([(bx0, by0 + 3 * K), (bx0 + 3 * K, by0), (bx0 + 10 * K, by0), (bx0 + 12 * K, by0 + 3 * K),
               (bx0 + 13 * K, by0 + 3 * K), (bx0 + 13 * K, by0 + 6 * K), (bx0, by0 + 6 * K)], fill=(22, 22, 26, 255))
    for wx in (bx0 + 3 * K, bx0 + 10 * K):
        d.ellipse((wx - 2 * K - K // 2, by0 + 5 * K, wx + 2 * K + K // 2, by0 + 10 * K), fill=(14, 14, 16, 255))
        d.ellipse((wx - K, by0 + 6 * K + K // 2, wx + K, by0 + 8 * K + K // 2), fill=(150, 150, 150, 255))
    # masthead
    d.rectangle((x0 + K, y0 + K, x1 - K, y0 + 8 * K), fill=(196, 34, 30, 255))
    f = _font(8 * K)
    text = "4x4"
    w = d.textlength(text, font=f)
    d.text(((x0 + x1) / 2.0 - w / 2.0, y0 + 0.2 * K), text, font=f, fill=(255, 246, 220, 255))
    return im.resize((32, 32), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    draw().save(OUT)
    print("WROTE %s" % OUT)


if __name__ == "__main__":
    main()
