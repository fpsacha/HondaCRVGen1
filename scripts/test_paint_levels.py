r"""
Paint levels the owner chose (bug wave 1, 2026-10-24: "yes I want a light silver"):

    python scripts\test_paint_levels.py

  * Sebring Silver (NH-552M) is levelled as a LIGHT metallic: paint_pass.SKIN_TUNE puts its belt well above the
    KI5-range 72 it shipped at (dark charcoal next to photos of the real car) and below Taffeta White's, so the
    two skins stay distinct;
  * the polish Lua's SKIN_HSV (the car's key / paint colour) follows the shipped sheets: silver's value is a light
    grey's (>= 0.42, was 0.322) under white's, and the silver is still a grey (low saturation);
  * spec/paint-colours.md records the new level and the reason.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paint_pass  # noqa: E402
import paint_textures as PT  # noqa: E402

ROOT = os.path.dirname(HERE)
LUA = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua", "shared", "HondaCRVGen1_PolishData.lua")


def fail(msg):
    raise SystemExit("FAIL " + msg)


def test_tune():
    silver = paint_pass.SKIN_TUNE.get("NH-552M", {})
    white = paint_pass.SKIN_TUNE.get("NH-578", {})
    belt = float(silver.get("belt", 0.0))
    if not 100.0 <= belt < float(white.get("belt", 255.0)) - 8.0:
        fail("Sebring Silver belt level %.0f: want a light silver (>= 100) under Taffeta White's %s" % (belt, white.get("belt")))
    print("PAINT tune: silver belt %.0f (up_k %.2f), white belt %.0f" % (belt, silver.get("up_k", 1.0), white["belt"]))


def test_lua_hsv():
    body = open(LUA, encoding="utf-8").read()
    rows = [tuple(float(x) for x in t) for t in re.findall(r"\{\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\s*\}", body)]
    order = [p[0] for p in PT.PAINTS]
    if len(rows) != len(order):
        fail("SKIN_HSV has %d rows for %d paints" % (len(rows), len(order)))
    hsv = dict(zip(order, rows))
    s, w = hsv["_silver"], hsv["_white"]
    if not (0.42 <= s[2] < w[2] and s[1] < 0.06):
        fail("SKIN_HSV silver %s: want a light grey (value >= 0.42, saturation < 0.06, under white %s; it was 0.322 "
             "as the dark charcoal)" % (s, w))
    print("PAINT Lua HSV: silver %s, white %s" % (s, w))


def test_spec():
    txt = open(os.path.join(ROOT, "spec", "paint-colours.md"), encoding="utf-8").read()
    if "2026-10-24" not in txt or "light silver" not in txt.lower():
        fail("spec/paint-colours.md does not record the 2026-10-24 light silver")
    print("PAINT spec: the light silver is recorded")


def main():
    test_tune()
    test_lua_hsv()
    test_spec()
    print("PAINT LEVEL TESTS OK")


if __name__ == "__main__":
    main()
