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

-- protection: guard on the front-left window, zombie thumps of 7 between checks
local v = newVehicle(9001)
local g = v.parts.CRVGuardFrontLeft
VehicleUtils.createPartInventoryItem(g)
Acc.Init(v, g)
assert(Acc.watch[9001], "not watched")
local w = v.parts.WindowFrontLeft
local unguarded = v.parts.WindowFrontRight
for t = 1, 3000 do -- 100 thumps
    if t % 30 == 0 then
        w.cond = w.cond - 7
        unguarded.cond = math.max(0, unguarded.cond - 7)
        if w.cond <= 0 then w.cond = 0; w.item = nil end
    end
    TICK()
end
print(string.format("GUARD after 100 thumps: guarded window %d (item %s), unguarded %d, guard %d, transmits %d",
    w.cond, tostring(w.item ~= nil), unguarded.cond, g.cond, v.sent))
assert(w.item ~= nil and w.cond == 100, "guarded window lost condition")
assert(g.cond < 100 and g.cond > 0, "guard did not wear")
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

-- bull bar: a crash takes 30 off the hood
local v2 = newVehicle(9002)
local bb = v2.parts.CRVBullbar
VehicleUtils.createPartInventoryItem(bb)
Acc.InstallComplete(v2, bb)
TICK(); TICK(); TICK()
v2.parts.EngineDoor.cond = 70
v2.parts.HeadlightLeft.cond = 40
TICK(); TICK(); TICK()
print(string.format("BULLBAR hood %d, headlight %d, bar %d", v2.parts.EngineDoor.cond, v2.parts.HeadlightLeft.cond, bb.cond))
assert(v2.parts.EngineDoor.cond == 100 and v2.parts.HeadlightLeft.cond == 100 and bb.cond == 100 - 10 - 20)

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
