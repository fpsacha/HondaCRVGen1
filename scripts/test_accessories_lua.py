"""
Mock-run the accessories Lua under Lua 5.1 (lupa; PZ's Kahlua is 5.1-like): spawn rolls, window
protection and guard wear, the bull bar, the roof rack access test, the roof rack's cargo states
(single player: the cargo state lives in HondaCRVGen1.State, scripts/test_state_lua.py runs it over
a fake multiplayer network).

    python scripts\test_accessories_lua.py
"""
import os

from lupa import lua51

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUA = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua")
SRC = os.path.join(LUA, "server", "Vehicles", "HondaCRVGen1Accessories.lua")
STATE = [os.path.join(LUA, *p.split("/")) for p in ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua",
                                                     "client/HondaCRVGen1_StateClient.lua")]
L = lua51.LuaRuntime(unpack_returned_tuples=True)
L.execute(r'''
math.randomseed(7)
function ZombRand(a, b) if b == nil then return math.random(0, a - 1) end return math.random(a, b - 1) end
function isClient() return false end
function isServer() return false end
function require(name) end
-- every registered tick (protection, rack fill, the State client poll); TICK() runs them all, as the game would
TICKS = {}
Events = { OnTick = { Add = function(f) TICKS[#TICKS + 1] = f end },
           OnClientCommand = { Add = function(f) end }, OnServerCommand = { Add = function(f) end } }
function TICK() for _, f in ipairs(TICKS) do f() end end
VehicleUtils = { createPartInventoryItem = function(part) part.item = { type = part.id } end }

local Cont = {}
Cont.__index = Cont
function Cont:getMaxWeight() return self.max end
function Cont:getCapacityWeight() return self.weight end

local Part = {}
Part.__index = Part
function Part:getId() return self.id end
function Part:getInventoryItem() return self.item end
function Part:getCondition() return self.cond end
function Part:setCondition(c) self.cond = c end
function Part:getArea() return self.area end
function Part:getItemContainer() return self.cont end
function Part:getModData() return self.md end
function Part:setModelVisible(id, vis)
    self.calls = self.calls + 1
    self.visible[id] = vis or nil
end
-- what VehiclePart.setInventoryItem does to a part's models (setAllModelsVisible)
function Part:setInventoryItem(item)
    self.item = item
    for _, m in ipairs(self.models or {}) do self.visible[m] = item and true or nil end
end

local Veh = {}
Veh.__index = Veh
function Veh:getPartById(id) return self.parts[id] end
function Veh:getModData() return self.md end
function Veh:getId() return self.id end
function Veh:isRemovedFromWorld() return self.removed or false end
function Veh:transmitPartCondition(p) self.sent = self.sent + 1 end
function Veh:transmitPartModData(p) end
function Veh:getScriptName() return "Base.HondaCRVGen1" end
function Veh:doDamageOverlay() end
function Veh:isInArea(area, chr) return chr.area == area end

function newVehicle(id)
    local v = setmetatable({ id = id, md = {}, parts = {}, sent = 0 }, Veh)
    for _, pid in ipairs({ "Windshield", "WindshieldRear", "WindowFrontLeft", "WindowFrontRight", "WindowRearLeft",
                           "WindowRearRight", "EngineDoor", "HeadlightLeft", "HeadlightRight", "TrunkDoor" }) do
        v.parts[pid] = setmetatable({ id = pid, item = { type = pid }, cond = 100 }, Part)
    end
    for _, pid in ipairs({ "CRVBullbar", "CRVRoofRack", "CRVGuardWindshield", "CRVGuardWindshieldRear", "CRVGuardFrontLeft",
                           "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVSpareCover" }) do
        v.parts[pid] = setmetatable({ id = pid, cond = 100, area = pid == "CRVRoofRack" and "RoofRack" or "x",
                                      calls = 0, visible = {}, md = {} }, Part)
    end
    local rack = v.parts.CRVRoofRack                        -- the script's four model blocks, a 50 kg container
    rack.models = { "CRVRoofRack", "RackLoad1", "RackLoad2", "RackLoad3" }
    rack.cont = setmetatable({ max = 50, weight = 0 }, Cont)
    return v
end
''')
for path in STATE + [SRC]:
    L.execute(open(path, encoding="utf-8").read())
L.execute(r'''
local Acc = HondaCRVGen1.Acc
-- spawn statistics over 4000 vehicles
local n, bull, rack, sets, partial = 4000, 0, 0, 0, 0
for i = 1, n do
    local v = newVehicle(i)
    for _, pid in ipairs({ "CRVBullbar", "CRVRoofRack", "CRVGuardWindshield", "CRVGuardWindshieldRear", "CRVGuardFrontLeft",
                           "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight" }) do
        Acc.Create(v, v.parts[pid])
    end
    if v.parts.CRVBullbar.item then bull = bull + 1 end
    if v.parts.CRVRoofRack.item then rack = rack + 1 end
    local g = 0
    for _, pid in ipairs({ "CRVGuardWindshield", "CRVGuardWindshieldRear", "CRVGuardFrontLeft", "CRVGuardFrontRight",
                           "CRVGuardRearLeft", "CRVGuardRearRight" }) do
        if v.parts[pid].item then g = g + 1 end
    end
    if g == 6 then sets = sets + 1 elseif g > 0 then partial = partial + 1 end
end
print(string.format("SPAWN bull bar %.1f%%, rack %.1f%%, full guard sets %.1f%%, partial %d", 100 * bull / n, 100 * rack / n, 100 * sets / n, partial))

-- protection: guard on the front-left window, zombie thumps of 7 between checks; the bars lose
-- Acc.BAR_RATE (2) per point they give back (2026-10-21: they lost 0 or 1 a thump, ~7x the window's life)
local v = newVehicle(9001)
local g = v.parts.CRVGuardFrontLeft
VehicleUtils.createPartInventoryItem(g)
Acc.Init(v, g)
assert(Acc.watch[9001], "not watched")
local w = v.parts.WindowFrontLeft
local unguarded = v.parts.WindowFrontRight
for t = 1, 180 do -- 6 thumps
    if t % 30 == 0 then
        w.cond = w.cond - 7
        unguarded.cond = math.max(0, unguarded.cond - 7)
        if w.cond <= 0 then w.cond = 0; w.item = nil end
    end
    TICK()
end
print(string.format("GUARD after 6 thumps: guarded window %d (item %s), unguarded %d, guard %d, transmits %d",
    w.cond, tostring(w.item ~= nil), unguarded.cond, g.cond, v.sent))
assert(w.item ~= nil and w.cond == 100, "guarded window lost condition")
assert(g.cond == 100 - 6 * 7 * 2, "guard wears 2 per absorbed point (got " .. tostring(g.cond) .. ")")
assert(g.md.crvWear == 0, "no fraction left over")

-- how long a window lasts under thumps of 3 (Normal zombies), bare and behind the bars: ~1.5x, not ~7x
local function thumpsToBreak(withGuard, id)
    local c = newVehicle(id)
    local gp = c.parts.CRVGuardRearLeft
    if withGuard then VehicleUtils.createPartInventoryItem(gp); Acc.Init(c, gp); TICK(); TICK(); TICK() end
    local win, n = c.parts.WindowRearLeft, 0
    while win.item and n < 10000 do
        win.cond = win.cond - 3
        if win.cond <= 0 then win.cond = 0; win.item = nil end
        n = n + 1
        TICK(); TICK(); TICK()
    end
    return n
end
local bare, barred = thumpsToBreak(false, 9010), thumpsToBreak(true, 9011)
print(string.format("WINDOW LIFE thumps of 3: bare %d, behind the bars %d (%.2fx)", bare, barred, barred / bare))
assert(bare == 34 and barred >= 49 and barred <= 52, "bars: the window lasts ~1.5x")
-- wear the guard out: the window takes damage again once it is at 0
g.cond = 1
for t = 1, 600 do
    if t % 30 == 0 and w.item then w.cond = w.cond - 7; if w.cond <= 0 then w.cond = 0; w.item = nil end end
    TICK()
end
print(string.format("WORN guard %d, window %d", g.cond, w.cond))
assert(g.cond == 0 and w.cond < 100, "a worn-out guard still protects")
-- repair the window: snapshot follows upward
-- uninstall everything: vehicle leaves the watch list
g.item = nil
TICK(); TICK(); TICK()
print("WATCH after uninstall:", Acc.watch[9001] == nil and "dropped" or "still watched")
assert(Acc.watch[9001] == nil)

-- bull bar: a crash takes 10 off the hood and 20 off a headlight; the bar pays 1.5 a point (Acc.RATE)
local v2 = newVehicle(9002)
local bb = v2.parts.CRVBullbar
VehicleUtils.createPartInventoryItem(bb)
Acc.InstallComplete(v2, bb)
TICK(); TICK(); TICK()
v2.parts.EngineDoor.cond = 90
v2.parts.HeadlightLeft.cond = 80
TICK(); TICK(); TICK()
print(string.format("BULLBAR hood %d, headlight %d, bar %d", v2.parts.EngineDoor.cond, v2.parts.HeadlightLeft.cond, bb.cond))
assert(v2.parts.EngineDoor.cond == 100 and v2.parts.HeadlightLeft.cond == 100 and bb.cond == 100 - 15 - 30)
-- an odd hit leaves the half point in the bar's mod data
v2.parts.EngineDoor.cond = 99
TICK(); TICK(); TICK()
assert(bb.cond == 54 and math.abs(bb.md.crvWear - 0.5) < 1e-9, "1 x 1.5: one point off, the half kept")
-- worn out: the hood takes the next crash itself
bb.cond = 0
v2.parts.EngineDoor.cond = 80
TICK(); TICK(); TICK()
assert(v2.parts.EngineDoor.cond == 80, "a worn-out bull bar protects nothing")
-- the default wear without the part (a feature's caller passing none): the same on average
local sum = 0
for i = 1, 2000 do sum = sum + Acc.wearAt(1.5, 3, nil) end
assert(math.abs(sum / 2000 - 4.5) < 0.1, "wearAt without a part averages lost x rate")

-- roof rack access
local v3 = newVehicle(9003)
local rr = v3.parts.CRVRoofRack
local chr = { area = "RoofRack", getVehicle = function() return nil end }
print("RACK empty slot:", tostring(Acc.RoofRackAccess(v3, rr, chr)))
VehicleUtils.createPartInventoryItem(rr)
print("RACK fitted, in area:", tostring(Acc.RoofRackAccess(v3, rr, chr)))
chr.area = "elsewhere"
print("RACK fitted, away:", tostring(Acc.RoofRackAccess(v3, rr, chr)))
print("LUA TESTS OK")
''')

# --- the spare-tyre cover: about half the cars, never on a missing gate, and the gate's uninstall
# test (TrunkDoor: test = HondaCRVGen1.Acc.GateUninstallTest) wants the cover off first
L.execute(r'''
local Acc = HondaCRVGen1.Acc
local n, covered, gateless = 4000, 0, 0
for i = 1, n do
    local v = newVehicle(20000 + i)
    if i % 4 == 0 then v.parts.TrunkDoor.item = nil end      -- a quarter of them spawned without the gate
    Acc.Create(v, v.parts.CRVSpareCover)
    if v.parts.CRVSpareCover.item then
        covered = covered + 1
        if not v.parts.TrunkDoor.item then gateless = gateless + 1 end
    end
end
local share = 100 * covered / (n * 3 / 4)
print(string.format("SPARE COVER on %.1f%% of the cars with a gate, %d on a missing gate", share, gateless))
assert(share > 45 and share < 55, "cover spawn share off: " .. share)
assert(gateless == 0, "a cover spawned on a missing gate")

Vehicles = Vehicles or {}
Vehicles.UninstallTest = { Default = function(v, p, chr) return "default" end }
local v = newVehicle(29001)
local gate, cover = v.parts.TrunkDoor, v.parts.CRVSpareCover
VehicleUtils.createPartInventoryItem(cover)
assert(Acc.GateUninstallTest(v, gate, {}) == false, "the gate came off under its cover")
cover.item = nil
assert(Acc.GateUninstallTest(v, gate, {}) == "default", "without the cover the vanilla test decides")
print("GATE uninstall: blocked while the cover is on, vanilla test once it is off")
print("LUA COVER TESTS OK")
''')

# --- the roof rack's cargo states (part CRVRoofRack: basket + RackLoad1..3, one shown per fill)
L.execute(r'''
local Acc = HondaCRVGen1.Acc
local function shown(p)
    local out = {}
    for _, m in ipairs({ "CRVRoofRack", "RackLoad1", "RackLoad2", "RackLoad3" }) do
        if p.visible[m] then out[#out + 1] = m end
    end
    return table.concat(out, "+")
end
local function tick(n) for i = 1, n do TICK() end end

-- 1. a saved car loads with a rack and 20 kg in it: the engine shows every model, Init trims them
local v = newVehicle(9201)
local rack = v.parts.CRVRoofRack
rack:setInventoryItem({ type = "CRVGen1_RoofRack" })
rack.cont.weight = 20
assert(shown(rack) == "CRVRoofRack+RackLoad1+RackLoad2+RackLoad3", "engine default: " .. shown(rack))
Acc.Init(v, rack)
print("RACK INIT 20/50 kg ->", shown(rack), "setModelVisible calls", rack.calls)
assert(shown(rack) == "CRVRoofRack+RackLoad2", shown(rack))
assert(rack.calls == 3, "one call per load model")
assert(Acc.racks[9201] and Acc.shown[9201].state == 2)
assert(HondaCRVGen1.State.get(v, Acc.RACK_KEY) == 2 and rack.md.crv_acc_rackLoad == 2, "state stored in the rack's mod data")

-- 2. fill changes are picked up by the tick; idle ticks make no calls
local before = rack.calls
tick(60)
assert(rack.calls == before, "idle ticks must not call setModelVisible")
for _, case in ipairs({ { 0, "CRVRoofRack" }, { 2.4, "CRVRoofRack" }, { 2.5, "CRVRoofRack+RackLoad1" },
                        { 17.4, "CRVRoofRack+RackLoad1" }, { 17.5, "CRVRoofRack+RackLoad2" },
                        { 35, "CRVRoofRack+RackLoad3" }, { 50, "CRVRoofRack+RackLoad3" }, { 1, "CRVRoofRack" } }) do
    rack.cont.weight = case[1]
    tick(Acc.RACK_EVERY)
    print(string.format("FILL %5.1f kg -> %s", case[1], shown(rack)))
    assert(shown(rack) == case[2], shown(rack))
end

-- 3. uninstall drops the watch; a fresh install shows all four until InstallComplete trims them
rack:setInventoryItem(nil)
Acc.UninstallComplete(v, rack, {})
assert(Acc.racks[9201] == nil and shown(rack) == "", "uninstalled rack keeps nothing: " .. shown(rack))
rack.cont.weight = 0
rack:setInventoryItem({ type = "CRVGen1_RoofRack" })
assert(shown(rack) == "CRVRoofRack+RackLoad1+RackLoad2+RackLoad3")
Acc.InstallComplete(v, rack)
print("RACK INSTALL empty ->", shown(rack))
assert(shown(rack) == "CRVRoofRack", shown(rack))

-- 4. a vehicle that leaves the world is dropped from the watch
v.removed = true
tick(Acc.RACK_EVERY)
assert(Acc.racks[9201] == nil, "removed vehicle still watched")

-- 5. no rack fitted: Init registers nothing and touches no model; the protection watch still works
local v2 = newVehicle(9202)
Acc.Init(v2, v2.parts.CRVRoofRack)
assert(Acc.racks[9202] == nil and v2.parts.CRVRoofRack.calls == 0)
local g = v2.parts.CRVGuardFrontLeft
VehicleUtils.createPartInventoryItem(g)
Acc.Init(v2, g)
assert(Acc.watch[9202], "protection watch lost")
print("RACK TESTS OK")
''')

# --- the fold-flat bed and the rear-seat container rule (HondaCRVGen1_Shared.lua + Acc.RearSeatAccess)
SHARED = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua", "shared", "HondaCRVGen1_Shared.lua")
L.execute(open(SHARED, encoding="utf-8").read())
L.execute(r'''
local S = HondaCRVGen1.Shared
local Acc = HondaCRVGen1.Acc
Vehicles = { ContainerAccess = { Seat = function(v, p, c) return "vanilla" end } }
local v = newVehicle(9100)
v.getScriptName = function(self) return "Base.HondaCRVGen1" end
v.isSeatOccupied = function(self, seat) return self.occupied and self.occupied[seat] or false end
v.transmitPartModData = function(self, p) self.sent = self.sent + 1 end
v.parts.SeatRearLeft = { id = "SeatRearLeft", item = {}, md = {}, cont = { items = 0 },
    getId = function(s) return s.id end, getInventoryItem = function(s) return s.item end,
    getModData = function(s) return s.md end, getItemContainer = function(s) return s.cont end }
v.parts.SeatRearLeft.cont.isEmpty = function(c) return c.items == 0 end
v.parts.SeatRearRight = { id = "SeatRearRight", item = {}, md = {}, cont = { items = 0 },
    getId = function(s) return s.id end, getInventoryItem = function(s) return s.item end,
    getModData = function(s) return s.md end, getItemContainer = function(s) return s.cont end }
v.parts.SeatRearRight.cont.isEmpty = function(c) return c.items == 0 end
assert(S.isCRV(v) and not S.isBed(v))
assert(S.canFold(v) == true, "empty rear seats should fold")
v.parts.SeatRearRight.cont.items = 2
local ok, why = S.canFold(v)
assert(ok == false and why == "IGUI_CRV_SeatsNotEmpty", "a loaded seat must block folding: " .. tostring(why))
v.parts.SeatRearRight.cont.items = 0
v.occupied = { [3] = true }
ok, why = S.canFold(v); assert(ok == false and why == "IGUI_CRV_SeatsOccupied", tostring(why))
v.occupied = nil
v.parts.SeatRearLeft.item = nil
ok, why = S.canFold(v); assert(ok == false and why == "IGUI_CRV_NoRearSeats", tostring(why))
v.parts.SeatRearLeft.item = {}
assert(Acc.RearSeatAccess(v, v.parts.SeatRearLeft, {}) == "vanilla", "unfolded: the vanilla rule")
S.setBed(v, true)
assert(S.isBed(v) and v.sent == 1, "bed flag set and transmitted")
assert(Acc.RearSeatAccess(v, v.parts.SeatRearLeft, {}) == false, "folded: rear seat containers refuse")
S.setBed(v, false)
assert(not S.isBed(v) and v.parts.SeatRearLeft.md.crvBed == nil)
local other = newVehicle(9101); other.getScriptName = function() return "Base.SUV" end
assert(not S.isBed(other), "other cars are never a bed")
print("BED fold rules: empty -> ok; loaded / occupied / missing seat -> blocked; folded -> containers refuse")
print("LUA BED TESTS OK")
''')

# --- perf (H-LUA-I1, 2026-10-24): the protection loop kept no list of what a car has fitted, so every pass (every 3
# ticks) asked every Acc.COVERS part of every watched car for its item. Now each watch entry holds the fitted
# protectors and their part objects (Acc.fittedList), rebuilt on init / install / uninstall or when one's item went:
# a car with one guard costs a handful of calls a pass, no part lookups; a refitted guard never gives back a stale
# snapshot of its window
L.execute(r'''
local Acc = HondaCRVGen1.Acc
CALLS = {}
local function counted(cls, name)
    local f = cls[name]
    cls[name] = function(...) CALLS[name] = (CALLS[name] or 0) + 1; return f(...) end
end
local v = newVehicle(9301)
local P = getmetatable(v.parts.Windshield)
local V = getmetatable(v)
for _, n in ipairs({ "getInventoryItem", "getCondition", "getId" }) do counted(P, n) end
counted(V, "getPartById")
local g = v.parts.CRVGuardFrontLeft
VehicleUtils.createPartInventoryItem(g)
Acc.Init(v, g)
TICK(); TICK(); TICK()                                   -- the first pass lists what is fitted
for id, _ in pairs(Acc.watch) do if id ~= 9301 then Acc.watch[id] = nil end end   -- this car alone
CALLS = {}
for i = 1, 30 do Acc.OnTick() end                        -- ten passes of the protection loop
local function total() local n = 0 for _, c in pairs(CALLS) do n = n + c end return n end
local nCovers = 0
for _ in pairs(Acc.COVERS) do nCovers = nCovers + 1 end
print(string.format("PROTECTION one guard, 10 passes: %d calls (%d part lookups), %d protector types",
    total(), CALLS.getPartById or 0, nCovers))
assert((CALLS.getPartById or 0) == 0, "no part lookups on a pass")
assert(total() <= 10 * 4, "one guard over one window: 4 calls a pass at most, got " .. total() / 10)
-- the guard off (a debug removal: no uninstall hook) and back on: the window's hits meanwhile are its own, the
-- refitted guard starts from the window as it is now
local w = v.parts.WindowFrontLeft
-- (perf 2026-10-24: a pass asks a protector for its item only when a covered part's condition moved, or every
-- Acc.ITEM_EVERY-th pass: a hit right after a removal nobody reported finds the guard gone before anything is given
-- back; with no hit the car leaves the watch within ITEM_EVERY passes)
local before = w.cond
g.item = nil
w.cond = before - 5                                      -- hit right after the guard came off
TICK(); TICK(); TICK()
assert(w.cond == before - 5, "a guard that came off gives nothing back: " .. w.cond)
assert(Acc.watch[9301] == nil, "nothing fitted: dropped from the watch at once")
VehicleUtils.createPartInventoryItem(g)
Acc.InstallComplete(v, g)
TICK(); TICK(); TICK()
g.item = nil                                             -- off again, no hit
for i = 1, 3 * Acc.ITEM_EVERY do TICK() end
assert(Acc.watch[9301] == nil, "nothing fitted, no hit: dropped within ITEM_EVERY passes")
w.cond = 60                                              -- hit while unguarded
VehicleUtils.createPartInventoryItem(g)
Acc.InstallComplete(v, g)
TICK(); TICK(); TICK()
assert(w.cond == 60, "a refitted guard gives back nothing it did not absorb: " .. w.cond)
w.cond = 53
TICK(); TICK(); TICK()
assert(w.cond == 60, "and protects from there: " .. w.cond)
-- an uninstall (the hook) relists at once; a second protector installed later is picked up
Acc.UninstallComplete(v, g, {}); g.item = nil
VehicleUtils.createPartInventoryItem(v.parts.CRVBullbar)
Acc.InstallComplete(v, v.parts.CRVBullbar)
TICK(); TICK(); TICK()                                   -- its first pass takes the hood's snapshot
v.parts.EngineDoor.cond = 90
TICK(); TICK(); TICK()
assert(v.parts.EngineDoor.cond == 100 and #Acc.watch[9301].list == 1 and Acc.watch[9301].list[1].id == "CRVBullbar",
       "the bull bar installed later is on the list and protects")
print("PROTECTION LIST TESTS OK")
''')

# --- I-DIFF-1 (2026-10-24 mutation hunt): what the protection list's caching must not lose. Between two sweeps
# (Acc.ITEM_EVERY passes) only the hooks tell the loop about a removal, so: an uninstall's Acc.dirty relists at once;
# a relist drops the snapshot of a part nothing covers any more (else a guard refitted later gives back the old
# condition: a free repair); a protector's floors are per item (a swapped item asks its own floor)
L.execute(r'''
local Acc = HondaCRVGen1.Acc
local saveEvery = Acc.ITEM_EVERY
Acc.ITEM_EVERY = 1000                                    -- the first pass sweeps, then only the hooks and hits count
local function pass() TICK(); TICK(); TICK() end
local function only(id) for k in pairs(Acc.watch) do if k ~= id then Acc.watch[k] = nil end end end
-- Acc.dirty (the protectors' uninstall complete)
local v = newVehicle(9401)
local g, bb, w = v.parts.CRVGuardFrontLeft, v.parts.CRVBullbar, v.parts.WindowFrontLeft
VehicleUtils.createPartInventoryItem(g); Acc.InstallComplete(v, g)
VehicleUtils.createPartInventoryItem(bb); Acc.InstallComplete(v, bb)
only(9401)
pass()
assert(#Acc.watch[9401].list == 2 and Acc.watch[9401].snap.WindowFrontLeft == 100, "guard and bull bar listed")
g.item = nil
Acc.UninstallComplete(v, g, {})
assert(Acc.watch[9401].list == nil, "Acc.dirty: the uninstall drops the protector list")
pass()
local list = Acc.watch[9401].list
assert(list and #list == 1 and list[1].id == "CRVBullbar", "relisted on the next pass: the bull bar alone")
local e = Acc.watch[9401]
Acc.dirty(newVehicle(9401))                              -- another car object under the same id: not this entry
assert(e.list == list, "Acc.dirty leaves another car's entry alone")
-- the relist dropped the window's snapshot: hits while unguarded stay, the refitted guard starts from there
assert(e.snap.WindowFrontLeft == nil, "relist: the uncovered window's snapshot dropped")
w.cond = 60
pass()
VehicleUtils.createPartInventoryItem(g); Acc.InstallComplete(v, g)
pass(); pass()
assert(w.cond == 60 and g.cond == 100, "refitted guard: no free repair of the hits taken unguarded (window "
       .. w.cond .. ", guard " .. g.cond .. ")")
-- floors per protector item: a swapped item asks its own floor
local saveFloor = Acc.FLOOR.CRVGuardFrontRight
Acc.FLOOR.CRVGuardFrontRight = function(vehicle, acc, p) return acc:getInventoryItem().floor end
local v2 = newVehicle(9402)
local g2, w2 = v2.parts.CRVGuardFrontRight, v2.parts.WindowFrontRight
w2.cond = 40
g2.item = { type = "CRVGuardFrontRight", floor = 30 }
Acc.InstallComplete(v2, g2)
only(9402)
pass()
assert(w2.cond == 40, "a floor under the window's condition changes nothing")
g2.item = { type = "CRVGuardFrontRight", floor = 90 }   -- another item swapped in between two looks
w2.cond = 35
pass()
assert(w2.cond == 90, "the swapped item's own floor (90), not the old item's cached one: window " .. w2.cond)
Acc.FLOOR.CRVGuardFrontRight = saveFloor
Acc.ITEM_EVERY = saveEvery
Acc.watch = {}
print("PROTECTION CACHES: an uninstall relists at once; a relist drops uncovered snapshots (no free repair); "
      .. "floors per protector item")
''')

# --- perf (I-5, 2026-10-24): the loot slider's thinning (HondaCRVGen1_Loot.lua, generated by gen_scripts.loot_lua)
# scanned every container the game filled. It now returns at once for a container type no procedural list of ours
# fills (read from Distributions once), and still thins the ones we add to
LOOT = os.path.join(LUA, "server", "Items", "HondaCRVGen1_Loot.lua")
L.execute(r'''
ProceduralDistributions = { list = { GarageMechanics = { items = {} }, CampingStoreTents = { items = {} } } }
Distributions = { {
    garage = { metal_shelves = { procedural = true, procList = { { name = "GarageMechanics", min = 0, max = 99 } } },
               counter = { procedural = true, procList = { { name = "StoreCounterCleaning", min = 0, max = 99 } } } },
    campingstore = { shelves = { procedural = true, procList = { { name = "CampingStoreTents", min = 0, max = 99 } } } },
    kitchen = { fridge = { rolls = 1, items = {} }, isShop = true },
    Bag_Satchel = { rolls = 1, items = {} },
} }
SandboxVars = { HondaCRVGen1 = { FunctionLootRarity = 1.0 } }
function ZombRandFloat(a, b) return a + math.random() * (b - a) end
Events.OnPreDistributionMerge = { Add = function(f) end }
Events.OnFillContainer = { Add = function(f) FILL = f end }
SCANS = 0
function lootCont(types)
    local t = {}
    for _, ty in ipairs(types) do t[#t + 1] = { ty = ty, getFullType = function(s) return s.ty end } end
    local list = { size = function() return #t end, get = function(_, i) return t[i + 1] end }
    return { t = t, getItems = function() SCANS = SCANS + 1; return list end,
             Remove = function(self, it) for i, x in ipairs(t) do if x == it then table.remove(t, i) return end end end }
end
''')
L.execute(open(LOOT, encoding="utf-8").read())
L.execute(r'''
local Loot = HondaCRVGen1.Loot
local types = Loot.containerTypes()
assert(types.metal_shelves and types.shelves and not types.counter and not types.fridge, "the container types we fill")
for i = 1, 200 do FILL("kitchen", "fridge", lootCont({ "Base.Milk" })); FILL("garage", "counter", lootCont({ "Base.Base" })) end
FILL("Zombie Bag", "Bag_Satchel", {})                    -- the game passes the bag's picker table here: never touched
-- I-DIFF-1 (mutation loot-types): no container type outside the collected ones is scanned, whatever its name
for _, ty in ipairs({ "crate", "counter", "shelves_x", "sidetable", "wardrobe", "other", "all" }) do
    FILL("bedroom", ty, lootCont({ "Base.CRVGen1_LiftKit" }))
end
assert(SCANS == 0, "containers we never fill are not scanned: " .. SCANS)
local kept = 0
for i = 1, 2000 do
    local c = lootCont({ "Base.CRVGen1_LiftKit", "Base.Wrench" })
    FILL("garage", "metal_shelves", c)
    for _, it in ipairs(c.t) do if it.ty == "Base.CRVGen1_LiftKit" then kept = kept + 1 end end
end
print(string.format("LOOT thin: 0 scans of 408 unrelated fills; garage shelves keep %d of 2000 kits (rarity 1 / headroom 4)", kept))
assert(SCANS == 2000 and kept > 400 and kept < 600, "our containers are still thinned")
print("LOOT TESTS OK")
''')

# --- H-DIFF-1 (2026-10-24): a room with no entry for a container type fills it from its "other" (else "all") entry
# and fires OnFillContainer with the REAL type (ItemPickerJava.fillContainerInternal, 42.21): a hall's sidetable
# filled from hall.other (MechanicSpecial) kept our armour at full x HEADROOM weight with the slider at 0, since
# sidetable is not a type any entry of ours is keyed by. Run on the game's own Distributions.lua.
import crv_paths                                                   # noqa: E402  (scripts/ is on sys.path)
VANILLA_DIST = os.path.join(crv_paths.GAME_MEDIA, "lua", "server", "Items", "Distributions.lua")
if not os.path.exists(VANILLA_DIST):
    raise SystemExit("FAIL the game's Distributions.lua is missing (%s): local_paths.json \"game\"" % VANILLA_DIST)
V = lua51.LuaRuntime(unpack_returned_tuples=True)
V.execute(r'''
next = nil                                                         -- Kahlua has no global next
function isClient() return false end
function require() end
Events = setmetatable({}, { __index = function(t, k) local e = { Add = function() end } rawset(t, k, e) return e end })
ProceduralDistributions = { list = {} }
Distributions = {}
ClutterTables = setmetatable({}, { __index = function() return {} end })
BagsAndContainers = setmetatable({}, { __index = function() return {} end })
''')
V.execute(open(VANILLA_DIST, encoding="utf-8", errors="replace").read())
V.execute(open(LOOT, encoding="utf-8").read())
print(V.execute(r'''
SandboxVars = { HondaCRVGen1 = { FunctionLootRarity = 0 } }       -- the slider at 0: none of our loot
function ZombRandFloat(a, b) return 0.5 end
SCANS = 0
local function cont()
    local items = { { getFullType = function() return "Base.CRVGen1_ArmourDoorFront" end },
                    { getFullType = function() return "Base.Wrench" end } }
    local c = { n = function() return #items end }
    function c:getItems() SCANS = SCANS + 1
        return { size = function() return #items end, get = function(_, i) return items[i + 1] end } end
    function c:Remove(x) for i, y in ipairs(items) do if y == x then table.remove(items, i) return end end end
    return c
end
local Loot = HondaCRVGen1.Loot
local D = Distributions[1]
local function oursIn(c)
    for _, p in ipairs(c and c.procList or {}) do if Loot.lists[p.name] then return true end end
    return false
end
assert(D.hall and D.hall.sidetable == nil and oursIn(D.hall.other), "vanilla's hall: no sidetable entry, other names ours")
local types = Loot.containerTypes()
assert(not types.sidetable, "sidetable is not a type an entry of ours is keyed by (else this test proves nothing)")
-- every (room, type) the room fills from its other / all entry naming ours is thinned
local pairsN, leaks = 0, {}
local universe = {}
for _, room in pairs(D) do
    if type(room) == "table" then for ct, c in pairs(room) do if type(c) == "table" then universe[ct] = true end end end
end
for name, room in pairs(D) do
    if type(room) == "table" and (oursIn(room.other) or (room.other == nil and oursIn(room.all))) then
        for ct in pairs(universe) do
            if ct ~= "other" and ct ~= "all" and room[ct] == nil and not types[ct] then
                pairsN = pairsN + 1
                local c = cont()
                local dropped = Loot.thin(name, ct, c)
                if dropped ~= 1 or c.n() ~= 1 then leaks[#leaks + 1] = name .. "/" .. ct end
            end
        end
    end
end
assert(pairsN > 100, "the other-filled (room, type) pairs were found: " .. pairsN)
assert(#leaks == 0, "fills from a room's other entry skip the thinning: " .. table.concat(leaks, ", ", 1, math.min(#leaks, 10)))
-- the perf win stays: a room with its own entry for the type (not ours), or a room whose other is not ours, is not scanned
SCANS = 0
local own = 0
for name, room in pairs(D) do
    if type(room) == "table" then
        for ct, c in pairs(room) do
            if type(c) == "table" and ct ~= "other" and ct ~= "all" and not types[ct] then
                own = own + 1
                Loot.thin(name, ct, cont())
            end
        end
    end
end
Loot.thin("kitchen", "fridge", cont())
assert(own > 100 and SCANS == 0, "a room's own entry for a type none of ours fills is never scanned: " .. SCANS .. " of " .. own)
local c = cont()
assert(Loot.thin("hall", nil, c) == 1, "an unknown container type is scanned")
return string.format("LOOT other/all fills: %d (room, type) pairs filled from a room's other / all entry naming our "
    .. "lists all thinned; %d own-entry fills unscanned", pairsN, own)
'''))
print("LOOT FALLBACK TESTS OK")
