--[[
Honda CR-V (RD1) accessories: bull bar, roof rack basket, steel window guards, the soft spare-tyre
cover on the gate.

Our own code. KI5's damnlib may not be copied or modified, so nothing here comes from it.
scripts/gen_scripts.py hooks it into every accessory part:
    lua { create = HondaCRVGen1.Acc.Create, init = HondaCRVGen1.Acc.Init }
    table install / uninstall { complete = HondaCRVGen1.Acc.InstallComplete / UninstallComplete }
    container { test = HondaCRVGen1.Acc.RoofRackAccess }            (the roof rack)
    TrunkDoor: table uninstall { test = HondaCRVGen1.Acc.GateUninstallTest }   (cover off first)
The game draws a part's models only while an item is installed, so the parts need no visibility
code, with one exception: the roof rack's cargo. Part CRVRoofRack lists four models, the basket and
RackLoad1..3 (one mesh per fill state). The engine shows EVERY model of a part whenever its item is
set (VehiclePart.setInventoryItem -> setAllModelsVisible), model visibility is neither saved nor
synced (nothing reads updateFlags bit 64, VehiclePart's save / network code never touches the
model list), and the `update` lua hook never runs on multiplayer clients (VehicleParts.update
returns early there). The fill state is therefore HondaCRVGen1.State key "acc_rackLoad" (0 = empty
basket, 1..3 = RackLoad1..3) in the rack part's mod data: the authoritative side (single player, the
server) derives it from the container's weight on a throttled tick and State.set saves and syncs
it; every side that draws the car shows the matching model on init, on every change the State
module reports (set, or the server's announcement on a client), and whenever the rack's item
changes under a client (State.watchPart: an install the server completed reset the models there).
B42 runs a part's install / uninstall `complete` on the authoritative side (ISInstallVehiclePart
:complete), not on the acting client.

Protection. A zombie thumping a window takes its strength off the window's condition, and at 0 the
game smashes the glass and removes it (zombie.vehicles.VehicleWindow.damage). While a guard is
installed and has condition left, the glass it covers gets back what it lost within a few ticks
and the guard wears instead. The bull bar does the same for the hood and the headlights. This runs
where the game is authoritative: single player and the server.

Wear (2026-10-21, a player: "the durability is crazy, it's like a tank"): a protector loses condition
in PROPORTION to what it absorbs, Acc.RATE points per absorbed point (fractions kept in its mod data),
so it buys its part a fixed extra share of life. Before, the bars lost 0 or 1 a hit whatever the hit
(a window lasted ~7x as long, far more in a crowd or a crash) and the bull bar a third of it (~4x).
Now: the bars 2 per point (the window lasts ~1.5x), the bull bar 1.5 (hood and headlights ~1.7x).
]]

require "HondaCRVGen1_State"

HondaCRVGen1 = HondaCRVGen1 or {}
local Acc = {}
HondaCRVGen1.Acc = Acc
local State = HondaCRVGen1.State

-- percent of CR-Vs that spawn with the part fitted; the six window guards come as one set. The spare
-- cover: about half the cars carry the soft vinyl cover, the rest show the bare spare
Acc.SPAWN = { CRVBullbar = 18, CRVRoofRack = 25, CRVPicnicTable = 92, CRVSpareCover = 50 }
Acc.GUARD_SET_CHANCE = 6

-- parts that sit on another part and only spawn when it is fitted (the cover rides the gate)
Acc.NEEDS = { CRVSpareCover = "TrunkDoor" }
-- what must come off before the gate, besides WindshieldRear (the script's requireUninstalled;
-- Vehicles.UninstallTest.Default reads only one name): the cover is drawn by the gate's player
Acc.GATE_FIRST = { "CRVSpareCover" }

-- accessory part -> the parts it protects
Acc.COVERS = {
    CRVGuardWindshield = { "Windshield" },
    CRVGuardWindshieldRear = { "WindshieldRear" },
    CRVGuardFrontLeft = { "WindowFrontLeft" },
    CRVGuardFrontRight = { "WindowFrontRight" },
    CRVGuardRearLeft = { "WindowRearLeft" },
    CRVGuardRearRight = { "WindowRearRight" },
    CRVBullbar = { "EngineDoor", "HeadlightLeft", "HeadlightRight" },
}

Acc.EVERY = 3                      -- ticks between checks; a thump takes a zombie's strength (single digits)

-- roof rack cargo: the model shown for the container's fill (share of its weight capacity)
Acc.RACK_PART = "CRVRoofRack"
Acc.RACK_MODELS = { "RackLoad1", "RackLoad2", "RackLoad3" }
Acc.RACK_FILL = { 0.05, 0.35, 0.70 }     -- one duffel; duffel + tote + bedroll; a tarped heap
Acc.RACK_EVERY = 15                      -- ticks between fill checks (~4 a second)
Acc.RACK_KEY = "acc_rackLoad"            -- HondaCRVGen1.State key: derived on the authoritative side only
State.define(Acc.RACK_KEY, { part = Acc.RACK_PART, kind = "number", default = 0,
                             min = 0, max = #Acc.RACK_MODELS, integer = true })

-- protector condition lost per point of condition it gives back (Acc.wearAt): a protector of condition 100
-- absorbs 100 / rate, so its part lasts 1 + 1 / rate times as long. Acc.BAR_RATE for a protector not listed
Acc.BAR_RATE = 2.0                 -- the steel window bars: the glass lasts ~1.5x
Acc.RATE = { CRVBullbar = 1.5 }    -- the bull bar: hood and headlights ~1.7x (a feature may add its parts)

-- feature plugins (spec/feature-plugins.md) register protective parts the same way: Acc.COVERS[partId] =
-- { protected part ids }, Acc.WEAR[partId] = function(lost) -> condition the part loses (default: Acc.wearAt
-- at Acc.RATE[partId] or Acc.BAR_RATE), and their part's init hook calls HondaCRVGen1.Acc.Init(vehicle, part)
-- to be watched
Acc.WEAR = {}
-- (armour feature) Acc.WEAR functions also get the vehicle and the protector part: wear(lost, vehicle, acc),
-- so a protector can keep its own wear accumulator in its mod data
-- (armour feature) partId -> fn(vehicle, part), called from Acc.Init on every side: a guard part whose
-- item can be a variant (the window mesh) shows the installed item's model (HondaCRVGen1.Armour.guardHook)
Acc.PART_HOOKS = {}
-- (armour feature) partId -> fn(vehicle, acc, coveredPart) -> the lowest condition the covered part is
-- held at while the protector is active (nil: none; the armour over weakened glass, Armour.glassFloor).
-- A protector may also list ITSELF first in its COVERS (the arch guards): it then absorbs its own hits
-- and only its Acc.WEAR comes off it
Acc.FLOOR = {}

-- whole points a protector loses for absorbing `lost` at `rate` points per point; the fraction stays in its
-- mod data under `key` (saved with the car, server side only). Without the part: the same on average
function Acc.wearAt(rate, lost, acc, key)
    if not acc then
        local w = lost * rate
        local n = math.floor(w)
        return n + ((ZombRand(100) < 100 * (w - n)) and 1 or 0)
    end
    key = key or "crvWear"
    local md = acc:getModData()
    local w = (tonumber(md[key]) or 0) + lost * rate
    local n = math.floor(w)
    md[key] = w - n
    return n
end

-- the default wear of a protector part (the bars, the bull bar, a feature part without its own Acc.WEAR)
function Acc.wearDefault(accId, lost, vehicle, acc)
    return Acc.wearAt(Acc.RATE[accId] or Acc.BAR_RATE, lost, acc)
end

-- condition the accessory loses for absorbing `lost` condition of a protected part
local function wear(accId, lost, vehicle, acc)
    if Acc.WEAR[accId] then
        return Acc.WEAR[accId](lost, vehicle, acc)
    end
    return Acc.wearDefault(accId, lost, vehicle, acc)
end

-- function feature: sandbox option HondaCRVGen1.FunctionAccessoryChance (percent, 100 = the chances
-- above) scales every accessory's spawn chance; the picnic table is factory equipment and keeps its own.
-- Read here, at the part's create (the server, after the sandbox has loaded). Feature parts that roll
-- their own spawn can use Acc.scaledChance(percent) for the same scaling.
Acc.STOCK = { CRVPicnicTable = true }

function Acc.scaledChance(pct)
    local vars = SandboxVars and SandboxVars.HondaCRVGen1
    local k = vars and vars.FunctionAccessoryChance
    if type(k) ~= "number" or k < 0 then k = 100 end
    return math.min(100, pct * k / 100)
end

function Acc.Create(vehicle, part)
    local id = part:getId()
    local fit
    if Acc.SPAWN[id] then
        local chance = Acc.STOCK[id] and Acc.SPAWN[id] or Acc.scaledChance(Acc.SPAWN[id])
        fit = ZombRand(100) < chance
        local host = Acc.NEEDS[id] and vehicle:getPartById(Acc.NEEDS[id])
        if fit and Acc.NEEDS[id] and not (host and host:getInventoryItem()) then
            fit = false                                 -- no cover on a missing gate
        end
    else
        local md = vehicle:getModData()
        if md.crvGen1Guards == nil then
            md.crvGen1Guards = ZombRand(100) < Acc.scaledChance(Acc.GUARD_SET_CHANCE)
        end
        fit = md.crvGen1Guards
        local covers = Acc.COVERS[id]
        local glass = covers and vehicle:getPartById(covers[1])
        if fit and glass and not glass:getInventoryItem() then
            fit = false                                 -- no guard over an empty frame
        end
    end
    if fit then
        VehicleUtils.createPartInventoryItem(part)
    end
end

-- vehicles with something fitted, by vehicle id: { vehicle = BaseVehicle, snap = { partId = condition },
-- list = the fitted protectors (Acc.fittedList; nil: rebuild it on the next pass) }
Acc.watch = {}

-- the car's fitted protectors with their part objects, built once per change (init, install, uninstall, an item
-- that went away) rather than looked up on every pass (perf 2026-10-24: the loop asked every Acc.COVERS part of
-- every watched car for its item every 3 ticks): { { id =, part =, covered = { { id =, part = }, ... } }, ... }
function Acc.fittedList(vehicle)
    local list = {}
    for accId, covered in pairs(Acc.COVERS) do
        local acc = vehicle:getPartById(accId)
        if acc and acc:getInventoryItem() then
            local parts = {}
            for _, pid in ipairs(covered) do
                local p = vehicle:getPartById(pid)
                if p then parts[#parts + 1] = { id = pid, part = p } end
            end
            list[#list + 1] = { id = accId, part = acc, covered = parts }
        end
    end
    return list
end

-- the protector list of a watched car is stale (a protector installed, removed or re-made)
function Acc.dirty(vehicle)
    local e = vehicle and Acc.watch[vehicle:getId()]
    if e and e.vehicle == vehicle then e.list = nil end
end

function Acc.Init(vehicle, part)
    local hook = Acc.PART_HOOKS[part:getId()]            -- (armour feature) the guard's variant model
    if hook then hook(vehicle, part) end
    -- the rack's cargo first: this runs on every side (createPhysics -> VehicleParts.initParts)
    if part:getId() == Acc.RACK_PART and part:getInventoryItem() then
        Acc.resetRack(vehicle, part)
    end
    if isClient() then return end
    if not Acc.COVERS[part:getId()] or not part:getInventoryItem() then return end
    local id = vehicle:getId()
    local e = Acc.watch[id]
    if not e or e.vehicle ~= vehicle then
        Acc.watch[id] = { vehicle = vehicle, snap = {} }
    else
        e.list = nil                                     -- a protector (re)fitted: list them again
    end
end

-- runs where the install completes: single player or the server (ISInstallVehiclePart:complete)
function Acc.InstallComplete(vehicle, part)
    vehicle:doDamageOverlay()
    Acc.Init(vehicle, part)                      -- the rack: setInventoryItem just showed all three loads
end

function Acc.UninstallComplete(vehicle, part, item)
    if part:getId() == Acc.RACK_PART then
        local id = vehicle:getId()
        Acc.racks[id] = nil                      -- the loads went with the item
        Acc.shown[id] = nil
        State.set(vehicle, Acc.RACK_KEY, 0)
    end
    if Acc.COVERS[part:getId()] then Acc.dirty(vehicle) end
    vehicle:doDamageOverlay()
end

-- the rear seats' containers (vehicle script: part SeatRear* container test) refuse items while
-- the seats are folded, as a load floor or a bed (HondaCRVGen1_Shared.lua)
function Acc.RearSeatAccess(vehicle, part, chr)
    if HondaCRVGen1.Shared and HondaCRVGen1.Shared.isFolded(vehicle) then return false end
    return Vehicles.ContainerAccess.Seat(vehicle, part, chr)
end

-- TrunkDoor's uninstall test (vehicle script): the spare cover first, then the vanilla rules
function Acc.GateUninstallTest(vehicle, part, chr)
    for _, id in ipairs(Acc.GATE_FIRST) do
        local p = vehicle:getPartById(id)
        if p and p:getInventoryItem() then return false end
    end
    return Vehicles.UninstallTest.Default(vehicle, part, chr)
end

function Acc.RoofRackAccess(vehicle, part, chr)
    if chr:getVehicle() then return false end
    if not part:getInventoryItem() then return false end
    return vehicle:isInArea(part:getArea(), chr)
end

-- authoritative side: cars with a roof rack fitted whose fill is followed, by vehicle id: { vehicle = BaseVehicle }
Acc.racks = {}
-- drawing side: the cargo state each car's rack shows now, by vehicle id: { vehicle = BaseVehicle, state = 0..3 };
-- the State poll drops the cars that left the world
Acc.shown = State.prunable({})

-- 0 = empty or no rack, else the cargo state for the container's fill. ItemContainer.getMaxWeight()
-- is the capacity for a part container and getCapacityWeight() what is in it (both floats).
local fillState
function Acc.rackState(part)
    if not part or not part:getInventoryItem() then return 0 end
    return fillState(part)
end

-- the state for the rack container's fill (the rack's item already known to be there)
fillState = function(part)
    local c = part:getItemContainer()
    if not c then return 0 end
    local max = c:getMaxWeight()
    if not max or max <= 0 then return 0 end
    local r = c:getCapacityWeight() / max
    local state = 0
    for i, f in ipairs(Acc.RACK_FILL) do
        if r >= f then state = i end
    end
    return state
end

-- drawing side: show exactly the model of the stored state (HondaCRVGen1.State); a car whose rack
-- already shows it is left alone (no setModelVisible on idle ticks)
function Acc.showRack(vehicle, part)
    if isServer() then return end                 -- a dedicated server draws nothing
    part = part or vehicle:getPartById(Acc.RACK_PART)
    if not part or not part:getInventoryItem() then return end
    local id = vehicle:getId()
    local state = State.get(vehicle, Acc.RACK_KEY)
    local e = Acc.shown[id]
    if e and e.vehicle == vehicle and e.state == state then return state end
    for i, model in ipairs(Acc.RACK_MODELS) do
        part:setModelVisible(model, i == state)
    end
    Acc.shown[id] = { vehicle = vehicle, state = state }
    return state
end

-- authoritative side: the state follows the container (State.set saves, syncs and fires the listeners)
function Acc.updateRack(vehicle, part)
    if isClient() then return end
    State.set(vehicle, Acc.RACK_KEY, Acc.rackState(part))
end

-- the engine has just shown every model of the rack (item installed, car created or streamed in):
-- follow the fill again where that is decided, then show the state where the car is drawn
function Acc.resetRack(vehicle, part)
    local id = vehicle:getId()
    Acc.shown[id] = nil
    if not isClient() then
        local e = Acc.racks[id]
        if not e or e.vehicle ~= vehicle then
            Acc.racks[id] = { vehicle = vehicle }
        else
            e.part = nil                         -- a part init: look the part up again
        end
        Acc.updateRack(vehicle, part)
    end
    Acc.showRack(vehicle, part)
    State.sawPart(vehicle, part)                 -- the drawing side's poll now watches this item
end

State.onChange(Acc.RACK_KEY, function(vehicle, key, value, old, how)
    Acc.showRack(vehicle)
end)
-- a client saw the rack's item change (an install or removal the server completed): models reset
State.watchPart(Acc.RACK_PART, function(vehicle, part)
    Acc.shown[vehicle:getId()] = nil
    Acc.showRack(vehicle, part)
end)

-- perf 2026-10-24: the rack part is kept in its entry (Acc.resetRack, from the part's init, drops it), the stored
-- state is read from the part's mod data and State.set only runs when the fill moved to another state; a car no
-- player is within Acc.RACK_NEAR tiles of is looked at every Acc.RACK_SLOW-th pass (State.due: nobody can load it)
Acc.RACK_NEAR = 30
Acc.RACK_SLOW = 8
local rackTicks = 0
function Acc.OnTickRack()
    rackTicks = rackTicks + 1
    if rackTicks % Acc.RACK_EVERY ~= 0 then return end
    for id, e in pairs(Acc.racks) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            Acc.racks[id] = nil
        elseif State.due(e, v, Acc.RACK_NEAR, Acc.RACK_SLOW, rackTicks) then
            local part = e.part
            if part == nil then
                part = v:getPartById(Acc.RACK_PART) or false
                e.part = part
            end
            local state = part and part:getInventoryItem() and fillState(part)
            if not state then
                Acc.racks[id] = nil                 -- rack gone: its models went with the item
            elseif state ~= State.getFrom(part:getModData(), Acc.RACK_KEY) then
                Acc.updateRack(v, part)
            end
        end
    end
end

-- One pass over a vehicle (e: its Acc.watch entry, or a bare snapshot table for a one-off pass). Returns false
-- once nothing protective is fitted any more.
-- (re)build a watch entry's protector list; the parts no listed protector covers any more lose their snapshot, so
-- they follow from scratch when one is fitted again (an old snapshot would be given back as if it were a hit)
local function relist(vehicle, e)
    e.list = Acc.fittedList(vehicle)
    local keep = {}
    for _, f in ipairs(e.list) do
        for _, c in ipairs(f.covered) do keep[c.id] = true end
    end
    for pid, _ in pairs(e.snap) do
        if not keep[pid] then e.snap[pid] = nil end
    end
    return e.list
end

-- perf 2026-10-24: a pass costs one call per covered part while nothing happens to the car (its condition, compared
-- with the snapshot; a protector that covers itself, the arch guards, is that part). The protector's item, condition
-- and floor and the covered part's item are asked only when a covered part's condition moved, when it has no
-- snapshot or sits under its last known floor, and on every Acc.ITEM_EVERY-th pass (the sweep). An uninstall leaves a
-- part's condition as it was (42.21 VehiclePart.setInventoryItem(null) does not touch it), so a removal nobody
-- reported (Acc.dirty: every protector's uninstall complete calls it) is followed within ITEM_EVERY passes, long
-- before anything can be installed again; a covered part found with another item than the one it had (a swap between
-- two looks) is followed from its new condition, never given back the old item's. The floor (Acc.FLOOR) is asked once
-- per protector item: a FLOOR function answers from the protector's installed item alone
Acc.ITEM_EVERY = 8

function Acc.guard(vehicle, e)
    if e.snap == nil then e = { snap = e } end           -- (old form: Acc.guard(vehicle, snap))
    local snap = e.snap
    local list = e.list or relist(vehicle, e)
    if #list == 0 then return false end
    local pass = (e.pass or 0) + 1
    e.pass = pass
    local sweep = Acc.ITEM_EVERY <= 1 or pass % Acc.ITEM_EVERY == 1
    for _, f in ipairs(list) do
        local accId, acc = f.id, f.part
        local covered = f.covered
        local accCond = nil                              -- the protector's condition, read once a pass when needed
        local loaded, active, floorOf = false, false, nil
        for _, c in ipairs(covered) do
            local pid, p = c.id, c.part
            local own = pid == accId
            local now
            if own then
                if accCond == nil then accCond = acc:getCondition() end
                now = accCond
            else
                now = p:getCondition()
            end
            local was = snap[pid]
            local known = f.floors and f.floors[pid] or nil   -- the floor found for it before (no call)
            if sweep or was == nil or now ~= was or (known and was < known) then
                if not loaded then                       -- the protector, once this pass
                    loaded = true
                    local accItem = acc:getInventoryItem()
                    if accItem == nil then
                        e.list = nil                     -- it came off (a debug removal, a lift conversion): list again
                        break
                    end
                    if accCond == nil then accCond = acc:getCondition() end
                    active = accCond > 0
                    if not active and covered[1] and covered[1].id == accId then
                        active = (snap[accId] or 0) > 0  -- covers itself: a hit took it to 0 since the last pass
                    end
                    floorOf = active and Acc.FLOOR[accId] or nil
                    if f.item ~= accItem then
                        f.item, f.floors = accItem, {}   -- the floors are per protector item
                    end
                end
                local floor = nil
                if floorOf then
                    floor = f.floors[pid]
                    if floor == nil then
                        floor = floorOf(vehicle, acc, p) or false
                        f.floors[pid] = floor
                    end
                    floor = floor or nil
                end
                local item = own or p:getInventoryItem()
                if item and not own then
                    if c.item ~= nil and item ~= c.item then was = nil end   -- another item since: follow it
                    c.item = item
                end
                if item then
                    if floor and (was == nil or was < floor) then was = floor end
                    if active and was and now < was then
                        p:setCondition(was)
                        vehicle:transmitPartCondition(p)
                        snap[pid] = was
                        local w = wear(accId, was - now, vehicle, acc)
                        if w > 0 then
                            acc:setCondition(math.max(0, acc:getCondition() - w))
                            vehicle:transmitPartCondition(acc)
                            accCond = acc:getCondition()
                            active = accCond > 0
                        elseif own then
                            accCond = was                -- it gave itself back what it lost
                        end
                        if own then snap[pid] = accCond end     -- its own wear is not a hit
                    else
                        snap[pid] = now                  -- repaired, replaced, or unguarded: follow it
                    end
                else
                    snap[pid] = nil
                    c.item = nil
                end
            end
        end
    end
    if e.list == nil then return #relist(vehicle, e) > 0 end   -- one came off: anything left to watch?
    return true
end

-- a car no player is within Acc.NEAR tiles of is guarded every Acc.SLOW-th pass (State.due): what damages a car
-- comes from a player's doing (zombies thump a car they chase a player into or round, crashes, shots); the glass
-- floor (Armour.GLASS_FLOOR) covers several thumps between two passes anyway
Acc.NEAR = 60
Acc.SLOW = 4
local ticks = 0
function Acc.OnTick()
    ticks = ticks + 1
    if ticks % Acc.EVERY ~= 0 then return end
    for id, e in pairs(Acc.watch) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            Acc.watch[id] = nil
        elseif State.due(e, v, Acc.NEAR, Acc.SLOW, ticks) and not Acc.guard(v, e) then
            Acc.watch[id] = nil
        end
    end
end

if not isClient() then                  -- where the game is authoritative: protection, the rack's fill
    Events.OnTick.Add(Acc.OnTick)
    Events.OnTick.Add(Acc.OnTickRack)
end
