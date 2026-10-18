r"""
Draw the owner's manual's inventory icon (function feature): Item_CRVGen1_OwnersManual.png, 32 x 32 RGBA
like the mod's other item icons. Our own drawing: a dark vinyl booklet seen slightly from the side, its
pages showing at the edge, a light outline of a boxy small SUV and two title lines on the cover. No logo.

    python scripts\function_icon.py [--out PATH] [--preview PATH]

Drawn at 8x and reduced with a box filter so the edges stay soft at 32 px.
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "mod", "Contents", "mods", "HondaCRVGen1", "common", "media", "textures",
                   "Item_CRVGen1_OwnersManual.png")
K = 8                                   # supersampling
N = 32


def P(x, y):
    return (round(x * K), round(y * K))


def draw():
    im = Image.new("RGBA", (N * K, N * K), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # shadow
    d.polygon([P(7.5, 29.5), P(28.5, 27.5), P(29.5, 29.0), P(9.0, 31.0)], fill=(0, 0, 0, 70))
    # page block (right and bottom edges), then the cover over it
    d.polygon([P(8, 4), P(27, 3), P(28.5, 27.2), P(9.2, 29.4)], fill=(222, 216, 198, 255))
    for i in range(4):                     # page lines on the fore-edge
        y0 = 6 + i * 5.5
        d.line([P(27.4, y0), P(28.1, y0 + 4)], fill=(170, 164, 148, 255), width=K // 2)
    d.polygon([P(6, 3.5), P(26, 2.5), P(27, 26.5), P(7, 28.6)], fill=(44, 52, 66, 255))
    # spine band
    d.polygon([P(6, 3.5), P(9, 3.35), P(10, 28.3), P(7, 28.6)], fill=(30, 36, 47, 255))
    # cover edge highlight
    d.line([P(9, 3.35), P(26, 2.5)], fill=(92, 104, 124, 255), width=K // 2)
    # title lines
    d.line([P(12, 7.6), P(23.4, 7.1)], fill=(214, 214, 206, 255), width=int(K * 1.4))
    d.line([P(13.4, 10.6), P(22, 10.2)], fill=(150, 158, 170, 255), width=int(K * 0.9))
    # the car: a boxy 90s small SUV in profile (long roof, upright tailgate, spare on the back)
    body = [P(11.6, 20.6), P(11.8, 17.7), P(14.2, 17.1), P(15.4, 14.2), P(23.6, 13.9), P(24.2, 17.0),
            P(24.4, 20.2)]
    d.line(body + [body[0]], fill=(200, 206, 214, 255), width=int(K * 0.9), joint="curve")
    d.line([P(16.3, 14.3), P(15.5, 17.0)], fill=(200, 206, 214, 255), width=int(K * 0.6))       # A-pillar / glass
    d.line([P(19.6, 14.1), P(19.6, 17.0)], fill=(200, 206, 214, 255), width=int(K * 0.6))       # B-pillar
    d.line([P(14.4, 17.1), P(24.0, 16.9)], fill=(200, 206, 214, 255), width=int(K * 0.6))       # belt line
    d.rectangle([P(24.3, 16.4), P(25.3, 19.4)], fill=(200, 206, 214, 255))                      # spare on the gate
    for cx in (14.8, 21.6):                                                                     # wheels
        d.ellipse([P(cx - 1.55, 19.2), P(cx + 1.55, 22.3)], fill=(44, 52, 66, 255), outline=(200, 206, 214, 255),
                  width=int(K * 0.8))
    # small text block under the car
    for i, w in enumerate((8.5, 6.5)):
        d.line([P(13.2, 24.6 + i * 1.7), P(13.2 + w, 24.4 + i * 1.7)], fill=(112, 122, 138, 255), width=int(K * 0.6))
    return im.resize((N, N), Image.BOX)


def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else OUT
    im = draw()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    print("WROTE %s" % out)
    if "--preview" in sys.argv:
        prev = sys.argv[sys.argv.index("--preview") + 1]
        bg = Image.new("RGBA", (N, N), (58, 58, 58, 255))
        bg.alpha_composite(im)
        bg.resize((N * 10, N * 10), Image.NEAREST).save(prev)
        print("WROTE %s" % prev)


if __name__ == "__main__":
    main()
