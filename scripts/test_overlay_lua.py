"""
Run the mechanics-overlay Lua under Lua 5.1 (lupa; PZ's Kahlua is 5.1-like) on top of the game's own
ISCarMechanicsOverlay.lua and ISVehicleMechanics.lua, and replay the window's hit test
(ISVehicleMechanics.isMouseOverPart / getMouseOverPart, B42) and its drawing (renderCarOverlay) over the
shipped images.

    python scripts\test_overlay_lua.py          (CRV_ROOT picks a scratch data root, as for build.py)

Checks:
- the CR-V's CarList entries (every CR-V script); every vanilla PartList id the car carries (all but the
  trailer compartments) and every accessory id has a crv1_ rectangle and an image of the sheet size. The
  accessory ids are the core ten plus every feature plugin's OVERLAYS part, and must be exactly the ids the
  shipped Lua registers with acc() (the old hand list left the 14 armour and off-road parts untested).
- each part's own pixels, drawn where the window draws them (+ CarList x / y), are found by the game's mouse
  test as that part and no other; every rectangle sits in the overlay area, left of the part lists
  (ISVehicleMechanics.xCarTexOffset 300).
- nothing of the set (no rectangle, no pixel of any image) lies under the window's title bar, its close and
  (i) buttons, or its status / resize strip at ANY font size: the bars' heights come from the game's own
  Small font files (1x-4x) and ISCollapsableWindow's formulas.
- drawing (the game's own renderCarOverlay, run here): before the fix a stock CR-V painted every empty
  extra in the blinking condition-0 red (reproduced on the registration alone); with the shipped Lua an
  empty extra draws nothing over its frame, a fitted one its condition colour, a missing stock part still
  blinks red, a vanilla car is untouched, and the empty extra is still found by the mouse test.
- the vanilla cars' PartList entries are untouched.
"""
import os
import re
import sys

import numpy as np
from lupa import lua51
from PIL import Image
import crv_paths as _crv_paths  # noqa: E402  (machine paths: local_paths.json)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features  # noqa: E402  (the plugins' OVERLAYS parts and second vehicle scripts)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = _crv_paths.GAME
VANILLA = os.path.join(GAME, "media", "lua", "client", "Vehicles", "ISUI", "ISCarMechanicsOverlay.lua")
MECHANICS = os.path.join(GAME, "media", "lua", "client", "Vehicles", "ISUI", "ISVehicleMechanics.lua")
FONTS = os.path.join(GAME, "media", "fonts", "EN")
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
OURS = os.path.join(MOD, "42", "media", "lua", "client", "HondaCRVGen1_MechanicsOverlay.lua")
IMG = os.path.join(MOD, "common", "media", "ui", "vehicles", "mechanic overlay")
SCRIPT = "Base.HondaCRVGen1"
SCRIPTS = [SCRIPT] + ["Base." + n for n in features.vehicle_scripts()]
X_CAR_TEX_OFFSET = 300               # ISVehicleMechanics:new, where the part lists start
WINDOW_H = 600                       # ISVehicleMechanics:new height = minimumHeight
TRAILER_ONLY = {"TrailerAnimalFood", "TrailerAnimalEggs"}
CORE_ACC = ["CRVBullbar", "CRVRoofRack", "CRVGuardWindshield", "CRVGuardWindshieldRear", "CRVGuardFrontLeft",
            "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVPicnicTable", "CRVSpareCover"]
ACC = CORE_ACC + list(features.overlays())


def snapshot(L, prefix_filter):
    """Every PartList entry's default rect and its per-prefix rects except prefix_filter, as plain data."""
    out = {}
    P = L.globals().ISCarMechanicsOverlay.PartList
    for pid, e in P.items():
        rects = {}
        if e.vehicles:
            for pre, r in e.vehicles.items():
                if pre != prefix_filter:
                    rects[pre] = (r.x, r.y, r.x2, r.y2)
        out[pid] = (e.img, e.x, e.y, e.x2, e.y2, tuple(sorted(rects.items())))
    return out


def window_bars():
    """(title bar rows, status strip rows, close + info button right edge) at the largest font size: the
    Small font's line height from the game's 1x-4x font files through ISCollapsableWindow's formulas
    (titleBarHeight = max(16, h + 1); resizeWidgetHeight = (h + 6) / 2 + 2; buttons th - 2 square at x 1
    and 1 + bh + offset, offset <= 1 + 4 * 2)."""
    best = None
    for n in ("1x", "2x", "3x", "4x"):
        txt = open(os.path.join(FONTS, n, "zomboidSmall.fnt"), encoding="utf-8", errors="replace").read()
        h = int(re.search(r"lineHeight=(\d+)", txt).group(1))
        th, rh = max(16, h + 1), (h + 6) / 2.0 + 2
        bars = (th, int(np.ceil(rh)), 1 + 2 * (th - 2) + 9)
        best = bars if best is None else tuple(max(a, b) for a, b in zip(best, bars))
    return best


def runtime():
    """The game's two files the mod's Lua requires: the overlay tables and the window (its functions)."""
    L = lua51.LuaRuntime(unpack_returned_tuples=True)
    L.execute('function require() end')
    L.execute(open(VANILLA, encoding="utf-8").read())
    L.execute(STUBS)
    L.execute(open(MECHANICS, encoding="utf-8").read())
    return L


# the part of the game the window's drawing touches, faked: the window object, vehicles and parts
STUBS = r'''
ISCollapsableWindow = {}
function ISCollapsableWindow:derive(name)
    local o = {Type = name}
    o.__index = o
    return setmetatable(o, {__index = self})
end
UIFont = {Small = 1, Medium = 2, Large = 3}
function getTextManager() return {getFontHeight = function(self, f) return 19 end} end
Events = setmetatable({}, {__index = function(t, k) local e = {Add = function() end}; rawset(t, k, e); return e end})
UIManager = {getMillisSinceLastRender = function() return 33.3 end}
function getTexture(path) return path end
function getDebug() return false end

function crv_part(id, cond, fitted, install)
    local p = {}
    function p:getId() return id end
    function p:getCondition() return cond end
    function p:getInventoryItem() if fitted then return {} end return nil end
    function p:getTable(name) if name == "install" and install then return {} end return nil end
    return p
end
function crv_vehicle(scriptName, parts)
    local v, byId = {}, {}
    for _, p in ipairs(parts) do byId[p:getId()] = p end
    function v:getScriptName() return scriptName end
    function v:getScript() return {getCarMechanicsOverlay = function() return nil end} end
    function v:getPartCount() return #parts end
    function v:getPartByIndex(i) return parts[i + 1] end
    function v:getPartById(id) return byId[id] end
    return v
end
function crv_window(vehicle)
    local w = setmetatable({vehicle = vehicle, draws = {}, mx = 0, my = 0}, {__index = ISVehicleMechanics})
    function w:getConditionRGB(c) return {r = 1 - c / 100, g = c / 100, b = 0} end
    function w:drawTextureScaledUniform(tex, x, y, scale, a, r, g, b)
        table.insert(self.draws, {tex = tex, x = x, y = y, a = a, r = r, g = g, b = b})
    end
    function w:renderCarOverlayTooltip() return false end
    function w:isMouseOver() return true end
    function w:drawRectBorder() end
    return w
end
'''


def draw_runtime(lua_text):
    """Vanilla overlay tables + vanilla ISVehicleMechanics (its real renderCarOverlay) + lua_text."""
    L = runtime()
    L.execute(lua_text)
    return L


def draws_of(L, script, parts):
    """{image name: (alpha, r, g, b)} renderCarOverlay drew for a car of `script` with `parts`
    [(id, condition, fitted, has install)]."""
    G = L.globals()
    lp = [G.crv_part(pid, c, fitted, inst) for pid, c, fitted, inst in parts]
    win = G.crv_window(G.crv_vehicle(script, L.table_from(lp)))
    G.ISVehicleMechanics.alphaOverlay = 0.4
    G.ISVehicleMechanics.alphaOverlayInc = True
    G.ISVehicleMechanics.renderCarOverlay(win)
    out = {}
    for _i, d in win.draws.items():
        name = os.path.basename(d.tex)[:-4]
        out[name] = (round(d.a, 3), round(d.r, 3), round(d.g, 3), round(d.b, 3))
    return out, win


def drawing_checks(errors):
    text = open(OURS, encoding="utf-8").read()
    marker = "\n-- Optional extras:"
    if marker not in text:
        errors.append("the shipped Lua has no optional-extras block")
        return
    registration = text[:text.index(marker)]          # the Lua as it shipped before the fix
    # a stock CR-V: no extra fitted except the bull bar (worn) and the snorkel; a tyre missing, a door hurt
    fitted = {"CRVBullbar": 70, "CRVOffroadSnorkel": 100}
    stock = ["EngineDoor", "DoorFrontLeft", "TireFrontLeft", "TireRearRight", "Battery", "GasTank"]
    parts = [(p, 100 if p != "DoorFrontLeft" else 40, p != "TireRearRight", True) for p in stock]
    parts += [(p, fitted.get(p, 0), p in fitted, True) for p in ACC]
    red, blink = (1.0, 0.0, 0.0), 0.48                # getConditionRGB(0) here; alphaOverlay 0.4 + 0.08 (one frame)
    # 1. the bug, reproduced on the registration alone: every empty extra blinks red
    L = draw_runtime(registration)
    before, _w = draws_of(L, SCRIPT, parts)
    reds = [p for p in ACC if p not in fitted and before.get(PREFIX_IMG(L, p)) == (blink,) + red]
    if len(reds) != len(ACC) - len(fitted):
        errors.append("could not reproduce the red blink before the fix (%d of %d empty extras)" % (len(reds), len(ACC) - len(fitted)))
    # 2. the shipped Lua
    L = draw_runtime(text)
    G = L.globals()
    for script in SCRIPTS:
        after, win = draws_of(L, script, parts)
        for pid in ACC:
            img = PREFIX_IMG(L, pid)
            if pid in fitted:
                c = fitted[pid] / 100.0
                if after.get(img) != (0.9, round(1 - c, 3), round(c, 3), 0.0):
                    errors.append("%s on %s: fitted extra drawn as %s" % (pid, script, after.get(img)))
            elif img in after:
                errors.append("%s on %s: empty extra still drawn %s" % (pid, script, after[img]))
        if after.get("crv1_wheel_rear_right") != (blink,) + red:
            errors.append("%s: a missing stock tyre no longer blinks red (%s)" % (script, after.get("crv1_wheel_rear_right")))
        if after.get("crv1_door_front_left") != (0.9, 0.6, 0.4, 0.0):
            errors.append("%s: a worn stock door drawn %s" % (script, after.get("crv1_door_front_left")))
        if "crv1_base" not in after:
            errors.append("%s: no base drawn" % script)
        # the empty extra is still under the mouse (hover, tooltip "Missing", right-click install)
        pid = "CRVGuardFrontLeft"
        r = G.ISCarMechanicsOverlay.PartList[pid].vehicles["crv1_"]
        part = win.vehicle.getPartById(win.vehicle, pid)
        if not G.ISVehicleMechanics.isMouseOverPart(win, r.x + 2, r.y + 2, part):
            errors.append("%s: the empty %s is no longer found by the mouse test" % (script, pid))
    # a vanilla car keeps vanilla's drawing (its own empty parts blink)
    van, _w = draws_of(L, "Base.CarNormal", [("TireRearRight", 100, False, True), ("EngineDoor", 100, True, True)])
    if van.get("4door_wheel_rear_right") != (blink,) + red or van.get("4door_hood") != (0.9, 0.0, 1.0, 0.0):
        errors.append("vanilla Base.CarNormal drawing changed: %s" % van)
    print("DRAW stock CR-V: before the fix %d empty extras blinked red; now 0 of %d drawn, %d fitted in their condition "
          "colour, a missing stock tyre blinks; %d CR-V scripts, vanilla car untouched"
          % (len(reds), len(ACC) - len(fitted), len(fitted), len(SCRIPTS)))


def PREFIX_IMG(L, pid):
    return "crv1_" + L.globals().ISCarMechanicsOverlay.PartList[pid].img


def main():
    L = runtime()
    before = snapshot(L, "crv1_")
    vanilla_ids = set(L.globals().ISCarMechanicsOverlay.PartList.keys()) - TRAILER_ONLY
    text = open(OURS, encoding="utf-8").read()
    L.execute(text)
    after = snapshot(L, "crv1_")
    G = L.globals().ISCarMechanicsOverlay
    errors = []

    for script in SCRIPTS:
        car = G.CarList[script]
        if car is None:
            errors.append("no CarList entry for " + script)
    car = G.CarList[SCRIPT]
    assert car is not None, "no CarList entry for " + SCRIPT
    prefix, cx, cy = car.imgPrefix, car.x, car.y
    print("CARLIST %s -> prefix %s at (%d, %d)" % (", ".join(SCRIPTS), prefix, cx, cy))
    for pid in vanilla_ids:
        if before[pid] != after[pid]:
            errors.append("vanilla entry %s changed" % pid)
    registered = re.findall(r'^acc\("([^"]+)"', text, re.M)
    if sorted(registered) != sorted(ACC):
        errors.append("the Lua registers %s, the build has %s" % (sorted(set(registered) ^ set(ACC)), len(ACC)))

    # the window's own test, verbatim in logic (isMouseOverPart): x >= x1 and x <= x2 and y > y1 and y <= y2
    L.execute('''
    function crv_mouse_over(id, x, y, prefix)
        local p = ISCarMechanicsOverlay.PartList[id]
        if not p then return false end
        local x1, y1, x2, y2 = p.x, p.y, p.x2, p.y2
        if p.vehicles and p.vehicles[prefix] then
            local r = p.vehicles[prefix]
            x1, y1, x2, y2 = r.x, r.y, r.x2, r.y2
        end
        return x1 ~= nil and y1 ~= nil and x2 ~= nil and y2 ~= nil and x >= x1 and x <= x2 and y > y1 and y <= y2
    end''')
    over = L.globals().crv_mouse_over
    ids = sorted(vanilla_ids) + ACC
    th, rh, bx = window_bars()
    top, bottom = th, WINDOW_H - rh                    # window rows a part may use: top .. bottom - 1
    print("WINDOW at the largest font: title bar rows 0-%d (close / info buttons x <= %d), status strip rows %d-%d"
          % (th - 1, bx, bottom, WINDOW_H - 1))
    P = G.PartList
    images = {}
    for pid in ids:
        e = P[pid]
        if e is None:
            errors.append("%s: no PartList entry" % pid)
            continue
        r = e.vehicles and e.vehicles[prefix]
        if r is None:
            errors.append("%s: no %s rectangle" % (pid, prefix))
            continue
        if not (0 <= r.x < r.x2 <= X_CAR_TEX_OFFSET and 0 <= r.y < r.y2 <= WINDOW_H):
            errors.append("%s: rectangle (%d, %d, %d, %d) outside the overlay area" % (pid, r.x, r.y, r.x2, r.y2))
        if r.y + 1 < top or r.y2 >= bottom:            # the mouse test accepts rows y + 1 .. y2
            errors.append("%s: rectangle rows %d-%d reach under the title bar (0-%d) or the status strip (%d-)"
                          % (pid, r.y + 1, r.y2, top - 1, bottom))
        f = os.path.join(IMG, prefix + e.img + ".png")
        if not os.path.exists(f):
            errors.append("%s: no image %s" % (pid, os.path.basename(f)))
            continue
        im = Image.open(f)
        if im.size != (263, 600):
            errors.append("%s: image %dx%d" % (pid, im.size[0], im.size[1]))
        images[pid] = np.asarray(im.convert("RGBA"))[..., 3] > 127
    base = os.path.join(IMG, prefix + "base.png")
    if not os.path.exists(base):
        errors.append("no %sbase.png" % prefix)
    # every drawn pixel of the set (base frames and leaders, every part image) clear of both bars
    for f in [base] + [os.path.join(IMG, prefix + P[p].img + ".png") for p in images]:
        a = np.asarray(Image.open(f).convert("RGBA"))[..., 3]
        rows = np.where(a.max(axis=1) > 0)[0] + cy
        if len(rows) and (rows[0] < top or rows[-1] >= bottom):
            errors.append("%s: pixels on window rows %d-%d, under the title bar (0-%d) or the status strip (%d-)"
                          % (os.path.basename(f), rows[0], rows[-1], top - 1, bottom))

    # every part's own pixels, where the window draws them: the game must pick that part, and only it
    # Rectangles cannot follow a curved cell exactly: a few of the hood's front-corner pixels sit in a
    # lamp's rectangle. Bound it: at least MIN_OWN of a part's pixels name it, at most MAX_FOREIGN name
    # another part, and no pixel is claimed by two rectangles (the game would take the first part).
    MIN_OWN, MAX_FOREIGN = 0.6, 0.2
    probes = 0
    worst_own, worst_foreign = (2.0, ""), (-1.0, "")
    stacked = {}
    for pid, m in images.items():
        ys, xs = np.where(m)
        own = foreign = 0
        for x, y in zip(xs, ys):
            wx, wy = int(x) + cx, int(y) + cy                     # the mouse on that pixel (whole numbers)
            hit = [o for o in images if over(o, wx, wy, prefix)]
            if len(hit) > 1:
                stacked[tuple(sorted(hit))] = stacked.get(tuple(sorted(hit)), 0) + 1
            own += pid in hit
            foreign += bool(hit) and pid not in hit
        n = max(len(xs), 1)
        probes += len(xs)
        worst_own = min(worst_own, (own / n, pid))
        worst_foreign = max(worst_foreign, (foreign / n, pid))
        if own / n < MIN_OWN:
            errors.append("%s: only %.0f%% of its pixels name it" % (pid, 100 * own / n))
        if foreign / n > MAX_FOREIGN:
            errors.append("%s: %.0f%% of its pixels name another part" % (pid, 100 * foreign / n))
    for parts, n in sorted(stacked.items(), key=lambda kv: -kv[1]):
        errors.append("%d part pixels lie in the rectangles of %s at once" % (n, ", ".join(parts)))
    if len(images) != len(ids):
        errors.append("hit-tested %d of %d parts" % (len(images), len(ids)))
    print("HIT TEST %d parts (%d vanilla, %d extras), %d pixels: worst own %.0f%% (%s), worst foreign %.0f%% (%s), "
          "%d pixels in two or more rectangles" % (len(images), len(vanilla_ids), len(ACC), probes, 100 * worst_own[0],
                                                   worst_own[1], 100 * worst_foreign[0], worst_foreign[1], sum(stacked.values())))
    drawing_checks(errors)
    if errors:
        raise SystemExit("OVERLAY LUA TEST FAILED:\n  " + "\n  ".join(errors))
    print("vanilla entries untouched (%d ids), accessories registered (%d)" % (len(vanilla_ids), len(ACC)))
    print("LUA OVERLAY TESTS OK")


if __name__ == "__main__":
    main()
