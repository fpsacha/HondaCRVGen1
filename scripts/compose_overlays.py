r"""
Mechanics-window overlay set for the CR-V (step 2 of 2, system Python + Pillow + scipy).

    python scripts\compose_overlays.py

Draws the CR-V's schematic in the game's own overlay language and writes
media/ui/vehicles/mechanic overlay/crv1_<img>.png plus the Lua that registers the set and the hit
rectangles. How the game draws it (ISVehicleMechanics.renderCarOverlay, B42): the window draws
<prefix>base.png untinted at CarList.x/y (10, 0), then every part's <prefix><img>.png at the same
spot, multiplied by the part's condition colour at alpha 0.9 (a missing part blinks red); the
mouse test (isMouseOverPart) uses PartList[id].vehicles[prefix] = {x, y, x2, y2} in WINDOW
coordinates, i.e. image coordinates + (10, 0). Every image is drawn on a 263 x 600 sheet and shipped cut
after its last drawn column and row (ship_crop: same screen pixels, a quarter to a thirtieth of the video memory).

The vanilla sheets (4door_, suv_ ...) are line art: the base holds every outline (white, ~2 px on the
body, ~1.6 px on the panels), the car's inside filled opaque black, the part icons (battery, engine,
spring + disc per wheel, tank, muffler) in thin 1 px frames joined to the car by thin leader lines;
each part image is a flat white fill of exactly one cell of that line art, so the condition colour
fills the cell and the white lines stay visible. This script draws the same thing from the CR-V's
own top view: the cells are polygons in model metres (x right = passenger side, y forward), taken
from the gen_overlays.py top-down masks of the real parts (stations in the comments, at 93 px/m),
drawn at PX_PER_M about (CX, CY). The icons are this mod's own drawings in the vanilla style.
Accessories (the mod's own part ids) are KI5-style framed icons beside the car, except the roof
rack and the spare cover, which sit where they are on the car.

Checks printed (a failure stops the build): every part image present and non-empty, no two hit
rectangles overlapping, each rectangle covering its part, no pixel or rectangle under the window's
title bar or status strip (rows SAFE_Y0 .. SAFE_Y1 - 1 only), and, when blender/overlay_raw holds the
rendered masks, each on-car cell's centre within ALIGN_TOL of the real part's along the car. The Lua
also makes an empty optional extra draw as its empty frame (OPTIONAL_LUA).
A game-faithful preview (base + every part tinted, a mixed-condition state, the hit boxes the
debug option draws) goes to blender/overlay_raw/_preview.png.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features  # noqa: E402  (scripts/features: the plugins' OVERLAYS and extra vehicle scripts)

ROOT = os.environ.get("CRV_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "blender", "overlay_raw")
MOD = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1")
OUT = os.path.join(MOD, "common", "media", "ui", "vehicles", "mechanic overlay")
LUA = os.path.join(MOD, "42", "media", "lua", "client", "HondaCRVGen1_MechanicsOverlay.lua")
PREFIX = "crv1_"
W, H = 263, 600                      # every vanilla overlay sheet
CAR_X, CAR_Y = 10, 0                 # CarList x / y: where the window draws the sheet
# Where the sheet may draw. The window (ISCollapsableWindow, 42.21) is 600 px tall at its minimum and
# default size and draws its title bar over rows 0 .. th - 1, th = max(16, Small font height + 1), with
# the close and (i) buttons in it at the left, and its status / resize strip (resizeWidget2, a child
# that takes the clicks) over the last rh = (Small + 6) / 2 + 2 rows. The Small font is 19 / 26 / 33 / 38
# px high at the 1x / 2x / 3x / 4x font sizes (media/fonts/EN/<n>x/zomboidSmall.fnt), so th <= 39 and
# rh <= 24: every pixel of the set stays in rows 40 .. 574, as vanilla's own sheets do (content ~46-558).
SAFE_Y0, SAFE_Y1 = 40, 575           # first and one-past-last sheet row the set may use
PX_PER_M = 78.0                      # body 1.75 m -> 137 px (vanilla SUV body ~145 px), 4.52 m long
NOSE_TIP_Y = 125                     # sheet row of the nose (under the armour band and the engine row)
CX, CY = 131.5, NOSE_TIP_Y + 2.145 * PX_PER_M   # model origin on the sheet
# the feature plugins' framed-icon bands (their OVERLAYS draw functions read these): a full-width band
# above the engine row (armour) and one under the tank / muffler row (off-road); frame rows y0 .. y1
TOP_BAND = (41, 70)
TOP_ROW_Y0 = TOP_BAND[1] + 7         # the engine frame's top row
SS = 4                               # supersampling; every line is anti-aliased by the 4x4 box
LW_BODY = 2.0                        # px, the body outline (vanilla ~2)
LW = 1.6                             # px, panel and icon lines (vanilla ~1.6-1.8)
LW_FRAME, FRAME_A = 1.0, 0.9         # icon frames: 1 px white at 0.9 (vanilla ~0.9)
LW_LEAD, LEAD_A = 1.0, 0.75          # leader lines: 1 px white at 0.75 (vanilla 0.6-0.95)
GAP = 0.15                           # px between a line and the fill of its cell
RAW_PX_PER_M, RAW_CY = 93.0, 300.0   # gen_overlays.py's camera
ALIGN_TOL = 0.12                     # m, cell centre vs the real part's along the car

# part id -> image name (ISCarMechanicsOverlay.PartList[id].img)
PARTS = {
    "EngineDoor": "hood", "TruckBed": "trunk", "Engine": "engine",
    "DoorFrontLeft": "door_front_left", "DoorFrontRight": "door_front_right",
    "DoorRearLeft": "door_rear_left", "DoorRearRight": "door_rear_right",
    "WindowFrontLeft": "window_front_left", "WindowFrontRight": "window_front_right",
    "WindowRearLeft": "window_rear_left", "WindowRearRight": "window_rear_right",
    "Windshield": "window_windshield", "WindshieldRear": "window_rear_windshield",
    "TireFrontLeft": "wheel_front_left", "TireFrontRight": "wheel_front_right",
    "TireRearLeft": "wheel_rear_left", "TireRearRight": "wheel_rear_right",
    "HeadlightLeft": "headlight_left", "HeadlightRight": "headlight_right",
    "Battery": "battery", "GasTank": "gastank", "Muffler": "muffler",
    "BrakeFrontLeft": "brake_front_left", "BrakeFrontRight": "brake_front_right",
    "BrakeRearLeft": "brake_rear_left", "BrakeRearRight": "brake_rear_right",
    "SuspensionFrontLeft": "suspension_front_left", "SuspensionFrontRight": "suspension_front_right",
    "SuspensionRearLeft": "suspension_rear_left", "SuspensionRearRight": "suspension_rear_right",
}
# accessory parts (gen_scripts.ACC_PARTS): the game has no PartList entry for them, the Lua adds one
ACC_PARTS = {
    "CRVBullbar": "acc_bullbar", "CRVRoofRack": "acc_roofrack",
    "CRVGuardWindshield": "acc_guard_ws", "CRVGuardWindshieldRear": "acc_guard_rear",
    "CRVGuardFrontLeft": "acc_guard_fl", "CRVGuardFrontRight": "acc_guard_fr",
    "CRVGuardRearLeft": "acc_guard_rl", "CRVGuardRearRight": "acc_guard_rr",
    "CRVPicnicTable": "acc_table", "CRVSpareCover": "acc_spare_cover",
}
# the feature plugins' parts (scripts/features OVERLAYS): each draws its own cell or framed icon (FEATURE_DRAW)
ACC_PARTS.update({part: spec["img"] for part, spec in features.overlays().items()})
PARTS.update(ACC_PARTS)
# cells drawn on the car whose centre is checked against the rendered mask (gen_overlays groups);
# tyres and doors are drawn outboard / as strips on purpose, so only their place along the car counts
ON_CAR = ["hood", "window_windshield", "window_rear_windshield", "trunk", "headlight_left", "headlight_right",
          "door_front_left", "door_front_right", "door_rear_left", "door_rear_right",
          "window_front_left", "window_front_right", "window_rear_left", "window_rear_right",
          "wheel_front_left", "wheel_front_right", "wheel_rear_left", "wheel_rear_right",
          "acc_roofrack", "acc_spare_cover"]
ON_CAR += [spec["img"] for spec in features.overlays().values() if spec["objects"]]
# every CR-V vehicle script shows this overlay set: the stock car and the features' second scripts (the lifted car)
VEHICLES = ["Base.HondaCRVGen1"] + ["Base." + n for n in features.vehicle_scripts()]
assert all(p.startswith("CRV") for p in ACC_PARTS), "accessory overlay parts are the mod's own CRV* ids"

# The optional extras in the window (appended to the generated Lua). renderCarOverlay (42.21) paints a part
# that has an install recipe and no item in the condition-0 red at the blinking alpha, as it does a broken
# part: a stock CR-V would blink red in every extra's cell. For a CR-V the window draws an empty extra as
# its empty frame (the outline in crv1_base) instead, through the per-car override vanilla itself uses for
# the SUV's rear windows (CarList[name].PartList[id], here an image list with nothing in it). A missing stock
# part (a door, a tyre) keeps vanilla's blink; the hover box and the "Missing" tooltip read the global
# PartList and are unchanged.
OPTIONAL_LUA = r'''
-- Optional extras: an empty one shows its empty frame, not vanilla's blinking red "missing" fill
-- (missing stock parts still blink). Drawing only: hover, tooltip and selection are vanilla's.
require "Vehicles/ISUI/ISVehicleMechanics"
local OPTIONAL = {
    %IDS%,
}
local EMPTY = {multipleImg = true, img = {}}
local renderCarOverlay = ISVehicleMechanics.renderCarOverlay
function ISVehicleMechanics:renderCarOverlay()
    local vehicle = self.vehicle
    local script = vehicle and vehicle:getScript()
    if script then
        local name = script:getCarMechanicsOverlay() or vehicle:getScriptName()
        local props = ISCarMechanicsOverlay.CarList[name]
        if props and props.imgPrefix == "%PREFIX%" then
            props.PartList = props.PartList or {}
            for i = 1, #OPTIONAL do
                local part = vehicle:getPartById(OPTIONAL[i])
                if part and not part:getInventoryItem() then
                    props.PartList[OPTIONAL[i]] = EMPTY
                else
                    props.PartList[OPTIONAL[i]] = nil
                end
            end
        end
    end
    return renderCarOverlay(self)
end'''


def px(x_m, y_m):
    """Model metres -> sheet px. The game's overlays show the car from above, nose up, driver's side
    (model -x) on the LEFT."""
    return CX + x_m * PX_PER_M, CY - y_m * PX_PER_M


# ----------------------------------------------------------------------------------- geometry (m)
# Right halves (x >= 0) from the top centre clockwise; sym() mirrors them. Stations measured on the
# gen_overlays masks (blender/overlay_raw at 93 px/m, rows every 4 px), rounded to the cm.
# Body: 1.75 m wide (half 0.876 from 1.56 m to -1.60 m), nose at 2.145, bumper end -2.205.
NOSE = [(0.0, 2.145), (0.30, 2.135), (0.414, 2.11), (0.52, 2.065), (0.59, 2.02), (0.665, 1.98), (0.737, 1.935),
        (0.775, 1.89), (0.80, 1.85), (0.82, 1.80), (0.84, 1.74), (0.858, 1.68), (0.87, 1.62), (0.876, 1.56)]
TAIL = [(0.876, -1.60), (0.866, -1.65), (0.855, -1.72), (0.845, -1.80), (0.835, -1.90), (0.825, -1.99),
        (0.81, -2.05), (0.775, -2.10), (0.71, -2.145), (0.60, -2.18), (0.45, -2.197), (0.0, -2.205)]
# hood: front edge 1.995 at the centre, half 0.70 at the sides, cowl 0.978 at the centre to 0.88 at the corner
HOOD_FRONT = [(0.0, 1.995), (0.31, 1.98), (0.425, 1.94), (0.50, 1.895), (0.575, 1.85), (0.635, 1.81),
              (0.675, 1.77), (0.695, 1.72)]
HOOD_SIDE = [(0.70, 1.60), (0.712, 1.25)]
COWL = [(0.715, 0.88), (0.66, 0.925), (0.55, 0.955), (0.40, 0.972), (0.0, 0.978)]
# windshield: base on the cowl, top edge 0.365 at the centre to 0.28 at the corners, half 0.70 -> 0.565
WS_TOP = [(0.0, 0.365), (0.33, 0.345), (0.45, 0.325), (0.52, 0.30), (0.565, 0.28)]
WS_SIDE = [(0.565, 0.28), (0.608, 0.39), (0.64, 0.47), (0.672, 0.56), (0.694, 0.65), (0.704, 0.75), (0.715, 0.88)]
# roof between the window strips (inner edge 0.59), rear glass 0.54 -> 0.66 wide from -1.79 to -2.06,
# the gate (vertical, a thin band from above) from there to the bumper
ROOF_SIDE = [(0.59, 0.18), (0.59, -1.74), (0.54, -1.79)]
REAR_GLASS = [(0.0, -1.79), (0.54, -1.79), (0.66, -2.06), (0.0, -2.06)]
GATE = [(0.0, -2.06), (0.74, -2.06), (0.69, -2.11), (0.60, -2.135), (0.45, -2.15), (0.0, -2.155)]
# side column: door skins 0.75-0.85 (front 0.84 -> -0.28, rear -> -1.22), glass 0.59-0.75 (front 0.51 ->
# -0.24 with the A-pillar slant, rear -0.31 -> -1.06, the fixed quarter glass -1.12 -> -1.70)
DOOR_IN, DOOR_OUT = 0.75, 0.85
DOOR_F = (0.84, -0.28)
DOOR_R = (-0.28, -1.22)
WIN_F = [(0.69, 0.51), (0.75, 0.51), (0.75, -0.24), (0.59, -0.24), (0.59, 0.16), (0.63, 0.31)]
WIN_R = [(0.63, -0.31), (0.75, -0.31), (0.75, -1.06), (0.67, -1.06), (0.59, -0.98), (0.59, -0.40)]
QUARTER = [(0.59, -1.12), (0.75, -1.12), (0.75, -1.58), (0.64, -1.70), (0.59, -1.70)]
MIRROR = [(0.85, 0.625), (0.965, 0.615), (1.0, 0.575), (0.995, 0.525), (0.85, 0.535)]
# headlamps: in front of the hood's front corners (mask rows 1.94: 0.46-0.52, 1.85: 0.51-0.68, 1.76: 0.73-0.78)
LAMP_OUT = [(0.80, 1.76), (0.745, 1.835), (0.68, 1.885), (0.60, 1.93), (0.52, 1.968), (0.45, 1.99)]
LAMP_X0 = 0.44
# tyres drawn just outboard of the body, vanilla style; axles at +-1.31 (wheelbase 2.62), 0.66 m tyres
WHEEL_Y = {"front": 1.31, "rear": -1.31}
TYRE_X = (0.893, 0.97)
TYRE_HALF = 0.33
# the tailgate spare (mask: x -0.06..0.61 behind the bumper), drawn behind the tail outline
SPARE = (-0.06, -2.245, 0.61, -2.355)
BOTTOM_ROW_Y0 = int(math.ceil(CY - SPARE[3] * PX_PER_M)) + 6     # the tank frame's top row, under the spare
BOTTOM_BAND = (BOTTOM_ROW_Y0 + 46, BOTTOM_ROW_Y0 + 86)
# roof rack basket (mask: x +-0.57, y -0.09..-1.61), inside the roof cell, with its cross bars
RACK = (-0.50, -0.10, 0.50, -1.62)
RACK_BARS = 3                        # cross bars between the end rails
RACK_TUBE = 5.0                      # px, rail width on the sheet (its line both sides + ~2 px of fill)


def chaikin(pts, n=2):
    """Corner-cutting smoothing of an open polyline, ends kept."""
    for _ in range(n):
        out = [pts[0]]
        for a, b in zip(pts[:-1], pts[1:]):
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        out.append(pts[-1])
        pts = out
    return pts


def sym(half):
    """Closed polygon from a right half (x >= 0, top centre clockwise to the bottom centre)."""
    return list(half) + [(-x, y) for x, y in reversed(half) if x > 1e-9]


def mirror(pts):
    return [(-x, y) for x, y in pts]


def to_px(pts):
    return [px(x, y) for x, y in pts]


def body_half():
    return chaikin(NOSE) + chaikin(TAIL)


def outline_x(y_m):
    """Body half-width at y_m (metres), from the smoothed outline."""
    pts = body_half()
    best = None
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        if min(y0, y1) <= y_m <= max(y0, y1) and y0 != y1:
            x = x0 + (x1 - x0) * (y_m - y0) / (y1 - y0)
            best = x if best is None else max(best, x)
    return best


def hood_half():
    return chaikin(HOOD_FRONT) + HOOD_SIDE + chaikin(COWL)


def lamp_poly():
    """Right headlamp: the hood's front edge from LAMP_X0 out (shared line), then forward by ~8 cm."""
    front = [p for p in chaikin(HOOD_FRONT) if p[0] >= LAMP_X0]
    return front + chaikin(LAMP_OUT)


# ------------------------------------------------------------------------------------ rasteriser
class Sheet:
    """The line art at SS x: a black fill layer, a white line layer, frames and leaders (dimmer),
    and one fill mask per part image."""

    def __init__(self):
        self.fill = np.zeros((H * SS, W * SS), bool)
        self.line = np.zeros((H * SS, W * SS), bool)
        self.frame = Image.new("L", (W * SS, H * SS), 0)
        self.lead = Image.new("L", (W * SS, H * SS), 0)
        self.parts = {}

    # shapes are tuples in sheet px: ("poly", pts) ("rrect", x0, y0, x1, y1, r) ("ellipse", cx, cy, rx, ry)
    # ("line", pts, width) ("arc", cx, cy, r0, r1, a0, a1)
    @staticmethod
    def _bbox(shape):
        k = shape[0]
        if k == "poly":
            xs = [p[0] for p in shape[1]]; ys = [p[1] for p in shape[1]]
            return min(xs), min(ys), max(xs), max(ys)
        if k == "rrect":
            return shape[1], shape[2], shape[3], shape[4]
        if k == "ellipse":
            return shape[1] - shape[3], shape[2] - shape[4], shape[1] + shape[3], shape[2] + shape[4]
        if k == "line":
            xs = [p[0] for p in shape[1]]; ys = [p[1] for p in shape[1]]; w = shape[2]
            return min(xs) - w, min(ys) - w, max(xs) + w, max(ys) + w
        if k == "arc":
            return shape[1] - shape[4], shape[2] - shape[4], shape[1] + shape[4], shape[2] + shape[4]
        raise ValueError(k)

    @staticmethod
    def _draw(d, shape, ox, oy, value):
        k = shape[0]
        f = lambda x, y: ((x - ox) * SS, (y - oy) * SS)
        if k == "poly":
            d.polygon([f(*p) for p in shape[1]], fill=value)
        elif k == "rrect":
            x0, y0 = f(shape[1], shape[2]); x1, y1 = f(shape[3], shape[4])
            d.rounded_rectangle([x0, y0, x1, y1], radius=shape[5] * SS, fill=value)
        elif k == "ellipse":
            x0, y0 = f(shape[1] - shape[3], shape[2] - shape[4]); x1, y1 = f(shape[1] + shape[3], shape[2] + shape[4])
            d.ellipse([x0, y0, x1, y1], fill=value)
        elif k == "line":
            pts = [f(*p) for p in shape[1]]
            w = shape[2] * SS
            d.line(pts, fill=value, width=int(round(w)), joint="curve")
            for p in (pts[0], pts[-1]):                       # round caps
                d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=value)
        elif k == "arc":
            cx, cy, r0, r1, a0, a1 = shape[1:]
            n = max(8, int(abs(a1 - a0) / 4))
            outer = [(cx + r1 * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r1 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
            inner = [(cx + r0 * math.cos(math.radians(a1 - (a1 - a0) * i / n)), cy + r0 * math.sin(math.radians(a1 - (a1 - a0) * i / n))) for i in range(n + 1)]
            d.polygon([f(*p) for p in outer + inner], fill=value)

    def _raster(self, add, sub, box):
        x0, y0, x1, y1 = box
        img = Image.new("L", (int((x1 - x0) * SS), int((y1 - y0) * SS)), 0)
        d = ImageDraw.Draw(img)
        for s in add:
            self._draw(d, s, x0, y0, 255)
        for s in sub:
            self._draw(d, s, x0, y0, 0)
        return np.asarray(img) > 127

    @staticmethod
    def _sdf(mask):
        """Signed distance to the mask's edge in sub-px, positive inside."""
        inside = ndimage.distance_transform_edt(mask)
        outside = ndimage.distance_transform_edt(~mask)
        return np.where(mask, inside - 0.5, 0.5 - outside)

    def _window(self, shapes, pad):
        bx = [self._bbox(s) for s in shapes]
        x0 = max(0, int(math.floor(min(b[0] for b in bx) - pad)))
        y0 = max(0, int(math.floor(min(b[1] for b in bx) - pad)))
        x1 = min(W, int(math.ceil(max(b[2] for b in bx) + pad)))
        y1 = min(H, int(math.ceil(max(b[3] for b in bx) + pad)))
        return x0, y0, x1, y1

    def cell(self, add, part=None, sub=(), lw=LW, details=(), dlw=LW, fill=True):
        """One cell of line art: the union of `add` minus `sub`, outlined by a lw line centred on its
        edge, filled black (fill) and, for a part, its inside (inset by half the line + GAP) as the
        part's image. details: polylines drawn white over it and cut out of the part."""
        add = list(add); sub = list(sub)
        box = self._window(add, lw + dlw + 3)
        x0, y0, x1, y1 = box
        sl = (slice(y0 * SS, y1 * SS), slice(x0 * SS, x1 * SS))
        m = self._raster(add, sub, box)
        sd = self._sdf(m)
        if fill:
            self.fill[sl] |= m
        self.line[sl] |= np.abs(sd) <= lw * SS / 2.0
        inner = sd >= (lw / 2.0 + GAP) * SS
        if details:
            dm = self._raster([("line", pts, dlw) for pts in details], [], box)
            self.line[sl] |= dm & m
            dd = ndimage.distance_transform_edt(~dm)
            inner &= dd > GAP * SS
        if part:
            if part not in self.parts:
                self.parts[part] = np.zeros((H * SS, W * SS), bool)
            self.parts[part][sl] |= inner
        return box

    def frame_box(self, x0, y0, x1, y1):
        """A 1 px icon frame on whole pixels (crisp after the reduction)."""
        d = ImageDraw.Draw(self.frame)
        w = LW_FRAME * SS
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            d.line([((a[0] + 0.5) * SS, (a[1] + 0.5) * SS), ((b[0] + 0.5) * SS, (b[1] + 0.5) * SS)], fill=255, width=int(w))
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            d.rectangle([x * SS, y * SS, (x + 1) * SS - 1, (y + 1) * SS - 1], fill=255)

    def leader(self, pts):
        """A 1 px leader line through pts (sheet px; whole-pixel coordinates land crisp)."""
        d = ImageDraw.Draw(self.lead)
        q = [((x + 0.5) * SS, (y + 0.5) * SS) for x, y in pts]
        d.line(q, fill=255, width=int(LW_LEAD * SS), joint="curve")

    @staticmethod
    def _reduce(a):
        a = np.asarray(a, dtype=np.float32)
        if a.max() > 1.0:
            a = a / 255.0
        return a.reshape(H, SS, W, SS).mean(axis=(1, 3))

    def images(self):
        fill = self._reduce(self.fill)
        line = np.clip(self._reduce(self.line) + FRAME_A * self._reduce(self.frame) + LEAD_A * self._reduce(self.lead), 0, 1)
        alpha = line + fill * (1.0 - line)                     # white lines over the black fill
        lum = np.where(alpha > 1e-4, line / np.maximum(alpha, 1e-4), 0.0)
        g = np.clip(lum * 255 + 0.5, 0, 255).astype(np.uint8)
        a = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
        out = {"base": Image.fromarray(np.dstack([g, g, g, a]), "RGBA")}
        white = np.full((H, W), 255, np.uint8)
        for name, m in self.parts.items():
            pa = np.clip(self._reduce(m) * 255 + 0.5, 0, 255).astype(np.uint8)
            out[name] = Image.fromarray(np.dstack([white, white, white, pa]), "RGBA")
        return out


# ----------------------------------------------------------------------------------------- icons
# The mod's own drawings in the vanilla manner: a white outlined body filled black in the base and
# white in the part image, the details as white lines the part leaves open. (cx, cy) = icon centre.

def icon_battery(s, cx, cy):
    body = ("rrect", cx - 15, cy - 7, cx + 15, cy + 10, 2.5)
    posts = [("rrect", cx - 11.5, cy - 11, cx - 5.5, cy - 6, 1.0), ("rrect", cx + 5.5, cy - 11, cx + 11.5, cy - 6, 1.0)]
    minus = [(cx - 10.5, cy + 2), (cx - 5.5, cy + 2)]
    plus_h = [(cx + 5.5, cy + 2), (cx + 10.5, cy + 2)]
    plus_v = [(cx + 8, cy - 0.5), (cx + 8, cy + 4.5)]
    lid = [(cx - 15, cy - 3), (cx + 15, cy - 3)]
    return s.cell([body] + posts, "battery", details=[minus, plus_h, plus_v, lid], dlw=1.3)


def icon_engine(s, cx, cy):
    """An inline four from the side: cam cover over the block, timing pulley at the front, oil pan."""
    head = ("rrect", cx - 20, cy - 17, cx + 20, cy - 6, 3)
    block = ("rrect", cx - 22, cy - 7, cx + 22, cy + 9, 2.5)
    pan = ("poly", [(cx - 15, cy + 8), (cx + 17, cy + 8), (cx + 13, cy + 16), (cx - 11, cy + 16)])
    pulley = ("ellipse", cx - 25, cy + 2, 7.5, 7.5)
    intake = ("rrect", cx + 18, cy - 14, cx + 30, cy - 4, 2)
    ribs = [[(cx - 13 + 7 * i, cy - 14.5), (cx - 13 + 7 * i, cy - 8.5)] for i in range(5)]
    seam = [(cx - 19, cy - 6.5), (cx + 19, cy - 6.5)]
    pan_seam = [(cx - 14, cy + 8.5), (cx + 16, cy + 8.5)]
    hub = ("ellipse", cx - 25, cy + 2, 2.2, 2.2)
    return s.cell([head, block, pan, pulley, intake], "engine", sub=[hub], details=ribs + [seam, pan_seam], dlw=1.3)


def _arc(cx, cy, r, a0, a1, n=16):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def icon_disc(s, cx, cy, part, flip):
    """A brake disc, its caliper hugging the top rear quarter, hub ring and centre bore."""
    a0, a1 = (-95, 5) if flip else (175, 275)
    disc = ("ellipse", cx, cy, 11.5, 11.5)
    caliper = ("arc", cx, cy, 7.0, 14.5, a0, a1)
    bore = ("ellipse", cx, cy, 2.2, 2.2)
    details = [_arc(cx, cy, 11.5, a0, a1), _arc(cx, cy, 7.0, a0 + 4, a1 - 4), _arc(cx, cy, 5.2, 0, 360, 24)]
    return s.cell([disc, caliper], part, sub=[bore], details=details, dlw=1.3)


def icon_spring(s, cx, cy, part):
    """An upright coil-over: the coil between its top and bottom seats, damper rod out of the top.
    One solid shape, the gaps between the coils drawn as slanted lines across it."""
    coil = ("rrect", cx - 7.5, cy - 10.5, cx + 7.5, cy + 11, 3)
    seats = [("rrect", cx - 11, cy - 14, cx + 11, cy - 10, 1.5), ("rrect", cx - 11, cy + 10.5, cx + 11, cy + 14.5, 1.5)]
    rod = ("rrect", cx - 2.2, cy - 18, cx + 2.2, cy - 13, 1)
    gaps = [[(cx - 9, cy + y + 2.4), (cx + 9, cy + y - 2.4)] for y in (-5.2, -0.4, 4.4)]
    seams = [[(cx - 7.5, cy - 10), (cx + 7.5, cy - 10)], [(cx - 7.5, cy + 10.5), (cx + 7.5, cy + 10.5)]]
    return s.cell([coil, rod] + seats, part, details=gaps + seams, dlw=1.3)


def icon_tank(s, cx, cy):
    """Fuel tank with straps, the filler neck rising to its cap."""
    tank = ("rrect", cx - 23, cy - 11, cx + 19, cy + 12, 5)
    neck = ("line", [(cx + 14, cy - 6), (cx + 25, cy - 16)], 4.5)
    cap = ("ellipse", cx + 26, cy - 17, 4.0, 4.0)
    straps = [[(cx - 10, cy - 11), (cx - 10, cy + 12)], [(cx + 5, cy - 11), (cx + 5, cy + 12)]]
    return s.cell([tank, neck, cap], "gastank", details=straps, dlw=1.3)


def icon_muffler(s, cx, cy):
    """Silencer lying across, inlet pipe in, tailpipe out."""
    body = ("rrect", cx - 14, cy - 8, cx + 12, cy + 8, 7)
    inlet = ("line", [(cx - 25, cy - 3), (cx - 13, cy - 3)], 4.4)
    tail = ("line", [(cx + 11, cy + 2.5), (cx + 24, cy + 2.5)], 4.4)
    rings = [[(cx - 6, cy - 8), (cx - 6, cy + 8)], [(cx + 4, cy - 8), (cx + 4, cy + 8)]]
    return s.cell([body, inlet, tail], "muffler", details=rings, dlw=1.3)


def _grid(x0, y0, x1, y1, nx, ny):
    lines = [[(x0 + (x1 - x0) * i / nx, y0 - 2), (x0 + (x1 - x0) * i / nx, y1 + 2)] for i in range(1, nx)]
    lines += [[(x0 - 2, y0 + (y1 - y0) * j / ny), (x1 + 2, y0 + (y1 - y0) * j / ny)] for j in range(1, ny)]
    return lines


def icon_side_guard(s, cx, cy, part, front_left):
    """A side window with its mesh guard; the pillar slant on the window's front."""
    t = 1 if front_left else -1
    pts = [(cx - 12 * t, cy + 8), (cx + 12 * t, cy + 8), (cx + 12 * t, cy - 8), (cx - 5 * t, cy - 8), (cx - 12 * t, cy - 1)]
    return s.cell([("poly", pts)], part, details=_grid(cx - 12, cy - 8, cx + 12, cy + 8, 3, 2), dlw=1.2)


def icon_screen_guard(s, cx, cy, part, w, h):
    """A windscreen seen from the front with its mesh guard."""
    pts = [(cx - w / 2, cy + h / 2), (cx + w / 2, cy + h / 2), (cx + w / 2 - 4, cy - h / 2), (cx - w / 2 + 4, cy - h / 2)]
    return s.cell([("poly", pts)], part, details=_grid(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, 4, 2), dlw=1.2)


def icon_bullbar(s, cx, cy):
    """Grille guard from the front: top hoop, two uprights, lower bar."""
    hoop = ("line", [(cx - 9, cy + 9), (cx - 9, cy - 6), (cx - 6, cy - 9), (cx + 6, cy - 9), (cx + 9, cy - 6), (cx + 9, cy + 9)], 4.0)
    bar = ("line", [(cx - 16, cy + 4), (cx + 16, cy + 4)], 4.0)
    mid = ("line", [(cx - 9, cy - 2), (cx + 9, cy - 2)], 3.0)
    return s.cell([hoop, bar, mid], "acc_bullbar")


def icon_table(s, cx, cy):
    """Folding picnic table from the side: the top and its crossed legs."""
    top = ("rrect", cx - 16, cy - 9, cx + 16, cy - 4, 1.5)
    legs = [("line", [(cx - 9, cy - 5), (cx + 9, cy + 9)], 3.6), ("line", [(cx + 9, cy - 5), (cx - 9, cy + 9)], 3.6)]
    return s.cell([top] + legs, "acc_table")


# ---------------------------------------------------------------------------------------- layout
def wheel_px(side, end):
    """Tyre rectangle in sheet px."""
    sx = -1 if side == "left" else 1
    y = WHEEL_Y[end]
    xa, xb = sorted((sx * TYRE_X[0], sx * TYRE_X[1]))
    (x0, y0), (x1, y1) = px(xa, y + TYRE_HALF), px(xb, y - TYRE_HALF)
    return x0, y0, x1, y1


def draw(s):
    boxes = {}                                   # icon part -> frame (for the hit rectangles)
    # ---- the car
    body = to_px(sym(body_half()))
    s.cell([("poly", body)], None, lw=LW_BODY)
    for sx in (1, -1):
        s.cell([("poly", to_px(mirror(MIRROR) if sx < 0 else MIRROR))], None)
    s.cell([("poly", to_px(sym(hood_half())))], "hood")
    ws = chaikin(WS_TOP) + chaikin(WS_SIDE) + chaikin(COWL)
    s.cell([("poly", to_px(sym(ws)))], "window_windshield")
    roof = chaikin(WS_TOP) + ROOF_SIDE + [(0.0, -1.79)]
    s.cell([("poly", to_px(sym(roof)))], None)
    s.cell([("poly", to_px(sym(REAR_GLASS)))], "window_rear_windshield")
    s.cell([("poly", to_px(sym(GATE)))], "trunk")
    lamp = lamp_poly()
    s.cell([("poly", to_px(lamp))], "headlight_right")
    s.cell([("poly", to_px(mirror(lamp)))], "headlight_left")
    for side, sx in (("right", 1), ("left", -1)):
        def rect(xa, xb, ya, yb):
            return [(sx * xa, ya), (sx * xb, ya), (sx * xb, yb), (sx * xa, yb)]
        s.cell([("poly", to_px(rect(DOOR_IN, DOOR_OUT, *DOOR_F)))], "door_front_" + side)
        s.cell([("poly", to_px(rect(DOOR_IN, DOOR_OUT, *DOOR_R)))], "door_rear_" + side)
        f = (lambda pts: pts) if sx > 0 else mirror
        s.cell([("poly", to_px(f(WIN_F)))], "window_front_" + side)
        s.cell([("poly", to_px(f(WIN_R)))], "window_rear_" + side)
        s.cell([("poly", to_px(f(QUARTER)))], None)
        for end in ("front", "rear"):
            x0, y0, x1, y1 = wheel_px(side, end)
            s.cell([("rrect", x0, y0, x1, y1, 2.5)], "wheel_%s_%s" % (end, side))
    # spare on the gate (its cover is the accessory) and the roof rack basket on the roof
    (sx0, sy0), (sx1, sy1) = px(SPARE[0], SPARE[1]), px(SPARE[2], SPARE[3])
    s.cell([("rrect", sx0, sy0, sx1, sy1, (sy1 - sy0) / 2.0)], "acc_spare_cover")
    # the rack as its tubes: a frame of RACK_TUBE px rails with cross bars, the bays open (black)
    (rx0, ry0), (rx1, ry1) = px(RACK[0], RACK[1]), px(RACK[2], RACK[3])
    t = RACK_TUBE
    ys = [ry0 + t] + [ry0 + (ry1 - ry0) * i / (RACK_BARS + 1) for i in range(1, RACK_BARS + 1)] + [ry1 - t]
    bays = [("rrect", rx0 + t, ys[i] + (0 if i == 0 else t / 2), rx1 - t, ys[i + 1] - (0 if i == len(ys) - 2 else t / 2), 1.5)
            for i in range(len(ys) - 1)]
    s.cell([("rrect", rx0, ry0, rx1, ry1, 4)], "acc_roofrack", sub=bays)

    # ---- icons around the car (frames on whole pixels)
    def framed(name, x0, y0, x1, y1):
        s.frame_box(x0, y0, x1, y1)
        boxes[name] = (x0, y0, x1, y1)
        return (x0 + x1) / 2.0, (y0 + y1) / 2.0

    # top row (under the armour band): engine (left) and battery (right) lead to the nose corners, the
    # front accessories between
    t0 = TOP_ROW_Y0
    ecx, ecy = framed("engine", 12, t0, 92, t0 + 44)
    icon_engine(s, ecx + 2, ecy + 1)
    bcx, bcy = framed("battery", 206, t0 + 6, 248, t0 + 38)
    icon_battery(s, bcx, bcy + 1)
    framed("acc_bullbar", 104, t0 + 6, 146, t0 + 38)
    icon_bullbar(s, 125, bcy)
    framed("acc_guard_ws", 156, t0 + 6, 196, t0 + 38)
    icon_screen_guard(s, 176, bcy, "acc_guard_ws", 30, 18)
    yc = 1.86
    xl, yl = px(-outline_x(yc), yc)
    xr, _ = px(outline_x(yc), yc)
    s.leader([(52, t0 + 44), (52, NOSE_TIP_Y + 8), (round(xl), round(yl))])
    s.leader([(227, t0 + 38), (227, NOSE_TIP_Y + 8), (round(xr) - 1, round(yl))])
    # sides: spring over disc per wheel, the tyre led to; the window guards between them
    for side, (bx0, bx1) in (("left", (5, 42)), ("right", (220, 257))):
        for end in ("front", "rear"):
            y = int(round(px(0, WHEEL_Y[end])[1]))
            fx0, fy0, fx1, fy1 = bx0, y - 35, bx1, y + 35
            s.frame_box(fx0, fy0, fx1, fy1)
            cx = (fx0 + fx1 + 1) / 2.0
            boxes["suspension_%s_%s" % (end, side)] = (fx0, fy0, fx1, y)
            boxes["brake_%s_%s" % (end, side)] = (fx0, y, fx1, fy1)
            icon_spring(s, cx, y - 16.5, "suspension_%s_%s" % (end, side))
            icon_disc(s, cx, y + 17.5, "brake_%s_%s" % (end, side), flip=(side == "right"))
            tx0, _, tx1, _ = wheel_px(side, end)
            if side == "left":
                s.leader([(fx1, y), (int(math.floor(tx0)) - 1, y)])
            else:
                s.leader([(int(math.ceil(tx1)), y), (fx0, y)])
        for name, ym, fl in (("acc_guard_f", 0.13, True), ("acc_guard_r", -0.60, False)):
            y = int(round(px(0, ym)[1]))
            key = name + ("l" if side == "left" else "r")
            framed(key, bx0, y - 15, bx1, y + 15)
            icon_side_guard(s, (bx0 + bx1) / 2.0, y, key, fl if side == "left" else not fl)
    # bottom row (under the spare, over the off-road band): tank (left) and muffler (right) lead to the
    # tail corners, the rear accessories between
    b0 = BOTTOM_ROW_Y0
    tcx, tcy = framed("gastank", 8, b0, 72, b0 + 40)
    icon_tank(s, tcx - 2, tcy + 2)
    framed("acc_guard_rear", 82, b0 + 6, 120, b0 + 34)
    icon_screen_guard(s, 101, b0 + 20, "acc_guard_rear", 26, 14)
    framed("acc_table", 128, b0 + 6, 168, b0 + 34)
    icon_table(s, 148, b0 + 20)
    mcx, mcy = framed("muffler", 186, b0 + 5, 248, b0 + 35)
    icon_muffler(s, mcx, mcy)
    yc = -2.06
    xl, yl = px(-outline_x(yc), yc)
    xr, _ = px(outline_x(yc), yc)
    s.leader([(40, b0), (40, b0 - 12), (round(xl), round(yl))])
    s.leader([(217, b0 + 5), (217, b0 - 12), (round(xr) - 1, round(yl))])
    return boxes


# ------------------------------------------------------------------------------------ hit rectangles
def _bbox(img, thr=127):
    a = np.asarray(img)[..., 3]
    ys, xs = np.where(a > thr)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def hit_rects(images, boxes):
    """Sheet-px rectangles per image: an icon's frame half (or whole frame), a car cell's own bounds.
    The game takes the first part whose rectangle holds the mouse, so they must not overlap: where some
    do (the lamps in the hood's front corners, the windows in the windshield's rear corners), the
    rectangle that loses the smallest share of its own pixels is shrunk to the best box clear of ALL
    its neighbours at once (one front cut for both lamps, not one side cut each). Every cut is
    reported, and check() fails a rectangle left holding under 60 % of its part."""
    rects, own = {}, {}
    for img, im in images.items():
        if img == "base":
            continue
        own[img] = np.asarray(im)[..., 3] > 127
        if img in boxes:
            x0, y0, x1, y1 = boxes[img]
            rects[img] = [x0 + 1, y0 + 1, x1, y1]
        else:
            rects[img] = list(_bbox(im))

    def kept(img, r):
        m = own[img]
        return m[r[1]:r[3], r[0]:r[2]].sum() / max(m.sum(), 1)

    def hits(a, b):
        ox, oy = _overlap(a, b)
        return ox > 0 and oy > 0

    def best_clear(img):
        """The box inside img's rectangle, with edges on its neighbours' edges, clear of every one of
        them and holding the most of img's pixels: (share lost, box)."""
        R = rects[img]
        S = [rects[o] for o in rects if o != img and hits(R, rects[o])]
        xs0 = {R[0]} | {s[2] for s in S if R[0] < s[2] < R[2]}
        xs1 = {R[2]} | {s[0] for s in S if R[0] < s[0] < R[2]}
        ys0 = {R[1]} | {s[3] for s in S if R[1] < s[3] < R[3]}
        ys1 = {R[3]} | {s[1] for s in S if R[1] < s[1] < R[3]}
        best = None
        for l in xs0:
            for r in xs1:
                for t in ys0:
                    for b in ys1:
                        c = [l, t, r, b]
                        if l < r and t < b and not any(hits(c, s) for s in S):
                            k = kept(img, c)
                            if best is None or k > best[0]:
                                best = (k, c)
        return (kept(img, R) - best[0], best[1]) if best else (1.0, None)

    cuts = []
    for _ in range(len(rects)):
        involved = sorted({n for n in rects for o in rects if o != n and hits(rects[n], rects[o])})
        if not involved:
            break
        options = []
        for n in involved:
            loss, box = best_clear(n)
            if box is not None:
                options.append((loss, n, box))
        lost, img, box = min(options, key=lambda t: (t[0], t[1]))
        others = [o for o in rects if o != img and hits(rects[img], rects[o])]
        rects[img] = box
        cuts.append("%s for %s (-%.0f%%)" % (img, "+".join(others), 100 * lost))
    return rects, cuts


def check(images, rects):
    """Fail loudly: every part has a non-empty image and a rectangle, no rectangles overlap, each
    rectangle still holds most of its part."""
    errors = []
    for pid, img in PARTS.items():
        if img not in images or _bbox(images[img]) is None:
            errors.append("%s: no image %s" % (pid, img))
        elif img not in rects:
            errors.append("%s: no rectangle" % pid)
    names = sorted(rects)
    solid = {n: np.asarray(images[n])[..., 3] > 127 for n in names}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ox, oy = _overlap(rects[a], rects[b])
            if ox > 0 and oy > 0:
                errors.append("rectangles %s and %s overlap" % (a, b))
            shared = int((solid[a] & solid[b]).sum())
            if shared:
                errors.append("images %s and %s share %d px (one would paint over the other)" % (a, b, shared))
    for img, r in rects.items():
        if r[0] < 0 or r[1] < 0 or r[2] > W or r[3] > H:
            errors.append("%s: rectangle %s off the sheet" % (img, r))
        elif r[1] < SAFE_Y0 or r[3] > SAFE_Y1:
            errors.append("%s: rectangle %s reaches under the title bar or the status strip (rows %d-%d only)"
                          % (img, r, SAFE_Y0, SAFE_Y1 - 1))
    for name, im in images.items():                      # every drawn pixel, the base's frames and leaders included
        rows = np.where(np.asarray(im)[..., 3].max(axis=1) > 0)[0]
        if len(rows) and (rows[0] < SAFE_Y0 or rows[-1] >= SAFE_Y1):
            errors.append("%s: pixels on rows %d-%d, the window covers all but rows %d-%d"
                          % (name, rows[0], rows[-1], SAFE_Y0, SAFE_Y1 - 1))
    worst = (2.0, "")
    for img, r in rects.items():
        a = np.asarray(images[img])[..., 3] > 127
        total = a.sum()
        inside = a[r[1]:r[3], r[0]:r[2]].sum()
        share = inside / max(total, 1)
        worst = min(worst, (share, img))
        if share < 0.6:
            errors.append("%s: its rectangle holds %.0f%% of it" % (img, 100 * share))
    if errors:
        raise SystemExit("OVERLAY CHECK FAILED: " + "; ".join(errors))
    return worst


def align(images):
    """Cell centre vs the rendered part's (gen_overlays masks), in metres along / across the car."""
    if not os.path.isdir(RAW):
        print("OVERLAY ALIGN skipped: no %s" % RAW)
        return
    worst = (0.0, None)
    lines = []
    for img in ON_CAR:
        p = os.path.join(RAW, img + ".png")
        if not os.path.exists(p):
            continue
        m = np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 127
        if not m.any():
            continue
        ys, xs = np.where(m)
        ry = (RAW_CY - ys.mean()) / RAW_PX_PER_M
        rx = (xs.mean() - CX) / RAW_PX_PER_M
        a = np.asarray(images[img])[..., 3] > 127
        ys, xs = np.where(a)
        cy = (CY - ys.mean()) / PX_PER_M
        cx = (xs.mean() - CX) / PX_PER_M
        dy, dx = cy - ry, cx - rx
        lines.append("%s %+.2f/%+.2f" % (img, dy, dx))
        if abs(dy) > abs(worst[0]):
            worst = (dy, img)
    print("OVERLAY ALIGN (cell - part, m along/across): " + ", ".join(lines))
    if abs(worst[0]) > ALIGN_TOL:
        raise SystemExit("OVERLAY ALIGN FAILED: %s sits %.2f m off its part along the car (tolerance %.2f)" % (worst[1], worst[0], ALIGN_TOL))
    print("OVERLAY ALIGN ok: worst %.2f m (%s)" % (abs(worst[0]), worst[1]))


# --------------------------------------------------------------------------------------- preview
GOOD, BAD = np.array([0.18, 0.80, 0.18]), np.array([0.85, 0.15, 0.15])


def cond_rgb(c):
    return BAD + (GOOD - BAD) * (c / 100.0)


def render_window(images, conds, hitboxes=None, scale=2):
    """The overlay as renderCarOverlay draws it: base untinted at (CAR_X, CAR_Y), each part
    multiplied by its condition colour at alpha 0.9 (missing: red at 0.6, mid-blink; a missing extra
    is not drawn, OPTIONAL_LUA)."""
    win = Image.new("RGBA", (300, H), (18, 20, 20, 255))
    win.alpha_composite(images["base"], (CAR_X, CAR_Y))
    for pid, img in PARTS.items():
        if img not in images:
            continue
        c = conds.get(pid, 100)
        if c is None and pid in ACC_PARTS:
            continue
        rgb, alpha = (cond_rgb(0), 0.6) if c is None else (cond_rgb(c), 0.9 if c >= 10 else 0.6)
        a = np.asarray(images[img]).astype(np.float32) / 255.0
        a[..., :3] *= rgb
        a[..., 3] *= alpha
        win.alpha_composite(Image.fromarray((a * 255 + 0.5).astype(np.uint8), "RGBA"), (CAR_X, CAR_Y))
    if hitboxes:
        d = ImageDraw.Draw(win)
        for r in hitboxes.values():                      # the pixels the mouse test accepts
            d.rectangle([r[0], r[1] + 1, r[2], r[3]], outline=(255, 0, 255, 255))
    return win.resize((300 * scale, H * scale), Image.NEAREST)


def preview(images, lua_rects, path):
    mixed = {pid: 100 for pid in PARTS}
    mixed.update({"EngineDoor": 74, "DoorFrontLeft": 60, "WindowRearRight": 35, "TireFrontLeft": 87, "Battery": 45,
                  "BrakeRearLeft": 20, "Muffler": 55, "Windshield": 92, "CRVGuardWindshield": None,
                  "CRVPicnicTable": None, "CRVGuardRearLeft": None, "CRVGuardRearRight": None, "CRVSpareCover": None,
                  "HeadlightRight": 5, "TireRearRight": None})
    panels = [render_window({"base": images["base"]}, {}), render_window(images, {}), render_window(images, mixed),
              render_window({"base": images["base"]}, {}, hitboxes=lua_rects)]
    sheet = Image.new("RGBA", (sum(p.width for p in panels) + 10 * (len(panels) - 1), panels[0].height), (0, 0, 0, 255))
    x = 0
    for p in panels:
        sheet.alpha_composite(p, (x, 0))
        x += p.width + 10
    sheet.save(path)
    return path


def ship_crop(im):
    """The sheet as shipped: cut after its last drawn column and row (one transparent texel kept), never on the
    left or top. Video memory (optimization pass, 2026-10-24, projectzomboid.jar B42): a loose PNG is padded
    to the next power of two per side (ImageData widthHW / heightHW) with no size cap, so every 263 x 600 sheet
    was a 512 x 1024 RGBA texture, 2 MB, 112 MB for the set once the mechanics window has drawn it (vanilla's
    own sheets sit in a packed atlas). UIElement.DrawTextureScaledUniform draws a texture at x + offsetX, y +
    offsetY, getWidth() x getHeight() times the scale: what is cut is fully transparent and drew nothing, the
    rest lands on the same screen pixels (the hit rectangles are Lua numbers, untouched)."""
    a = np.asarray(im.convert("RGBA"))[..., 3]
    ys, xs = np.nonzero(a)
    if not len(xs):
        return im
    return im.crop((0, 0, min(im.width, int(xs.max()) + 2), min(im.height, int(ys.max()) + 2)))


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.dirname(LUA), exist_ok=True)
    s = Sheet()
    boxes = draw(s)
    for part, spec in features.overlays().items():      # feature parts: a cell on the car (None) or a framed icon
        box = spec["draw"](s, sys.modules[__name__])
        if box:
            boxes[spec["img"]] = tuple(box)
    images = s.images()
    rects, cuts = hit_rects(images, boxes)
    worst = check(images, rects)
    for old in os.listdir(OUT):                          # nothing stale under our prefix
        if old.startswith(PREFIX) and old.endswith(".png"):
            os.remove(os.path.join(OUT, old))
    for img, im in images.items():
        ship_crop(im).save(os.path.join(OUT, PREFIX + img + ".png"))
    # window coordinates (the sheet is drawn at CAR_X, CAR_Y), in the form the mouse test reads them:
    # x >= x and x <= x2 and y > y and y <= y2 on whole pixels, so the half-open pixel box [x0, x1) x
    # [y0, y1) is x0, y0 - 1, x1 - 1, y1 - 1
    lua_rects = {img: (r[0] + CAR_X, r[1] - 1 + CAR_Y, r[2] - 1 + CAR_X, r[3] - 1 + CAR_Y) for img, r in rects.items()}
    lines = ["-- Generated by scripts/compose_overlays.py: mechanics-window overlay for the CR-V.",
             "-- Registers the crv1_ image set for the vehicle script and the hit rectangles per part",
             "-- (window coordinates: the sheet is drawn at x = %d, y = %d)." % (CAR_X, CAR_Y),
             'require "Vehicles/ISUI/ISCarMechanicsOverlay"', ""] + [
             'ISCarMechanicsOverlay.CarList["%s"] = {imgPrefix = "%s", x = %d, y = %d}' % (v, PREFIX, CAR_X, CAR_Y)
             for v in VEHICLES] + ["",
             "local P = ISCarMechanicsOverlay.PartList",
             "local function rect(id, x, y, x2, y2)",
             "    if not P[id] then return end",
             "    if not P[id].vehicles then P[id].vehicles = {} end",
             '    P[id].vehicles["%s"] = {x = x, y = y, x2 = x2, y2 = y2}' % PREFIX,
             "end",
             "-- the accessories are this mod's own part ids: give them the entry the game's parts have",
             "local function acc(id, img)",
             "    if not P[id] then P[id] = {img = img, vehicles = {}} end",
             "end"]
    for pid, img in ACC_PARTS.items():
        lines.append('acc("%s", "%s")' % (pid, img))
    for pid, img in PARTS.items():
        r = lua_rects[img]
        lines.append('rect("%s", %d, %d, %d, %d)' % (pid, r[0], r[1], r[2], r[3]))
    lines += OPTIONAL_LUA.replace("%PREFIX%", PREFIX).replace(
        "%IDS%", ",\n    ".join(", ".join('"%s"' % p for p in list(ACC_PARTS)[i:i + 4]) for i in range(0, len(ACC_PARTS), 4))
    ).split("\n")
    with open(LUA, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("WROTE %d overlay images to %s" % (len(images), OUT))
    print("WROTE", LUA)
    print("OVERLAY rects: %d parts, none overlapping, worst cover %.0f%% (%s)%s" % (
        len(PARTS), 100 * worst[0], worst[1], ("; cuts: " + ", ".join(cuts)) if cuts else ""))
    align(images)
    os.makedirs(RAW, exist_ok=True)
    print("OVERLAY preview", preview(images, lua_rects, os.path.join(RAW, "_preview.png")))


if __name__ == "__main__":
    main()
