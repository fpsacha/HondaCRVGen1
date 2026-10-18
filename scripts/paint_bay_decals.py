r"""
Paint the engine bay v2 decals (spec/engine-bay-v2.md) into blender/bake. System Python + Pillow.

    python scripts\paint_bay_decals.py [--only engine,intake]

Each group's paint module scripts/bay/paint_<group>.py defines IMAGES = {"bay_<group>_<what>.png": fn};
fn() returns a PIL RGB image. build.py runs this before the rebuild; the group modules' DECALS map
the files onto their faces (kit.register_decals).
"""
import importlib
import os
import sys

S = os.path.dirname(os.path.abspath(__file__))
if S not in sys.path:
    sys.path.insert(0, S)
import bay  # noqa: E402

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(S)
OUT = os.path.join(ROOT, "blender", "bake")


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")
    os.makedirs(OUT, exist_ok=True)
    n = 0
    for g in bay.GROUPS:
        if only and g not in only:
            continue
        try:
            mod = importlib.import_module("bay.paint_" + g)
        except ModuleNotFoundError as exc:
            if exc.name == "bay.paint_" + g:
                continue                                  # this group paints nothing (yet)
            raise
        for name, fn in getattr(mod, "IMAGES", {}).items():
            if not name.startswith("bay_%s_" % g):
                raise SystemExit("paint_bay_decals: %s must be named bay_%s_*.png" % (name, g))
            im = fn()
            im.convert("RGB").save(os.path.join(OUT, name))
            n += 1
            print("paint: %s %dx%d" % (name, im.size[0], im.size[1]))
    print("paint: %d bay decals written to %s" % (n, OUT))


if __name__ == "__main__":
    main()
