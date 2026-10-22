--[[
Honda CR-V (RD1), cargo clutter: what is loaded into the trunk shows in the cargo bay, and more of it the
fuller the trunk is. Our own code. scripts/features/clutter.py builds the meshes and writes the part.

Part CRVClutterCargo (every CR-V vehicle script, no item, category nodisplay, setAllModelsVisible = false,
so the engine never shows or resets its models: VehiclePart.setInventoryItem is the only caller of
setAllModelsVisible) lists four models:
  * InteriorClutter1..3: what each fill state ADDS (a duffel and a carton; + a cooler and a carton; + a
    backpack, a toolbox, a small carton, a gas can and a kit bag). State n shows models 1..n.
  * InteriorClutterWell: a blanket over the soft stuff filling the well under the cargo floor, shown with
    the load while the picnic table (part CRVPicnicTable, the floor panel) is out, so nothing floats over
    the open well.
Nothing shows while the rear seats are folded into the bed (HondaCRVGen1.Shared.isBed, fold mode "bed": the bed
lies there); folded as a bare load floor (mode "cargo") the load shows as with the seats up.

The fill state is HondaCRVGen1.State key "clutter_load" (0 = empty, 1..3) in this part's mod data. The
game has no container-changed hook that reaches the server and every client (OnContainerUpdate is a
client-side UI refresh, triggered from Lua actions and a few Java paths; ItemContainer.addItem /
Remove fire nothing), so, like the roof rack's cargo (HondaCRVGen1Accessories.lua, Acc.updateRack),
the authoritative side (single player, the server) derives it from the trunk's container (part
TruckBed: weight over capacity, with a little hysteresis so a load sitting on a threshold does not
flicker) on a throttled tick and State.set saves and syncs it. Every side that draws the car (single
player, each multiplayer client; never a dedicated server) shows the models from the synced state, the
synced fold state (State keys function_folded, function_foldMode) and the table part's synced item:
  * on the part's init (VehicleParts.initParts: a car created, spawned, loaded or streamed in);
  * on every change of clutter_load, function_folded or function_foldMode (State listeners: "set" where it changed,
    "sync" on a client that the server told, or its poll found the new mod data);
  * when the table's item changes under a tracked car (State.watchPart, the client poll), so taking
    the table out or putting it back follows on every side.
]]

require "HondaCRVGen1_State"
require "HondaCRVGen1_Shared"

HondaCRVGen1 = HondaCRVGen1 or {}
local C = HondaCRVGen1.Clutter or {}
HondaCRVGen1.Clutter = C
local State = HondaCRVGen1.State
local Shared = HondaCRVGen1.Shared

C.PART = "CRVClutterCargo"
C.TRUNK = "TruckBed"                    -- the vanilla trunk (template Trunk/part/TruckBed)
C.TABLE = "CRVPicnicTable"              -- HondaCRVGen1.Shared.TABLE_PART: the floor panel over the well
C.MODELS = { "InteriorClutter1", "InteriorClutter2", "InteriorClutter3" }
C.WELL = "InteriorClutterWell"
C.FILL = { 0.10, 0.40, 0.75 }           -- share of the trunk's weight capacity for states 1..3
C.HYST = 0.02                           -- a state goes down only below its threshold minus this
C.EVERY = 15                            -- ticks between fill checks (~4 a second), as the rack's
C.KEY = "clutter_load"
State.define(C.KEY, { part = C.PART, kind = "number", default = 0, min = 0, max = #C.MODELS, integer = true })

C.cars = C.cars or {}                   -- authoritative side: vehicle id -> { vehicle = } whose trunk is followed
C.shown = C.shown or {}                 -- drawing side: vehicle id -> { vehicle =, sig = } what this side shows

-- the fill (0..1) of the car's trunk, or nil without a trunk or container. ItemContainer.getMaxWeight() is
-- the part container's capacity (getCapacity), getCapacityWeight() the weight of what is in it
function C.fill(vehicle)
    local part = vehicle:getPartById(C.TRUNK)
    if not part or not part:getInventoryItem() then return nil end
    local c = part:getItemContainer()
    if not c then return nil end
    local max = c:getMaxWeight()
    if not max or max <= 0 then return nil end
    return c:getCapacityWeight() / max
end

-- the state for fill r when the car shows state cur now (hysteresis on the way down)
function C.stateFor(r, cur)
    if not r or r <= 0 then return 0 end
    cur = cur or 0
    local state = 0
    for i, f in ipairs(C.FILL) do
        local need = f
        if i <= cur then need = f - C.HYST end
        if r >= need then state = i end
    end
    return state
end

-- authoritative side: the state follows the trunk (State.set saves, syncs and fires the listeners)
function C.update(vehicle)
    if isClient() then return end
    local cur = State.get(vehicle, C.KEY)
    State.set(vehicle, C.KEY, C.stateFor(C.fill(vehicle), cur))
end

-- what the drawing side should show: the number of load models and the well blanket
function C.wanted(vehicle)
    if Shared.isBed(vehicle) then return 0, false end
    local n = State.get(vehicle, C.KEY) or 0
    if n <= 0 then return 0, false end
    local tbl = vehicle:getPartById(C.TABLE)
    return n, not (tbl and tbl:getInventoryItem())
end

-- drawing side: show exactly that; a car that already shows it is left alone (cheap, idempotent: a listener)
function C.apply(vehicle)
    if isServer() or not vehicle or not Shared.isCRV(vehicle) then return end
    local part = vehicle:getPartById(C.PART)
    if not part then return end
    local n, well = C.wanted(vehicle)
    local sig = n * 2 + (well and 1 or 0)
    local id = vehicle:getId()
    local e = C.shown[id]
    if e and e.vehicle == vehicle and e.sig == sig then return sig end
    for i, model in ipairs(C.MODELS) do
        part:setModelVisible(model, i <= n)
    end
    part:setModelVisible(C.WELL, well)
    C.shown[id] = { vehicle = vehicle, sig = sig }
    return sig
end

local function onState(vehicle, key, value, old, how)
    C.apply(vehicle)
end
State.onChange(C.KEY, onState)
State.onChange(Shared.FOLD_KEY, onState)
State.onChange(Shared.MODE_KEY, onState)
-- the table went in or out under a tracked car (single player or a client: the State poll)
State.watchPart(C.TABLE, function(vehicle, part)
    C.apply(vehicle)
end)

-- part init (every side): follow the trunk where that is decided, show the state where the car is drawn
function C.Init(vehicle, part)
    if not vehicle or not part or part:getId() ~= C.PART then return end
    local id = vehicle:getId()
    if not isClient() then
        local e = C.cars[id]
        if not e or e.vehicle ~= vehicle then
            C.cars[id] = { vehicle = vehicle }
        end
        C.update(vehicle)
    end
    if not isServer() then
        C.shown[id] = nil                       -- a fresh part shows nothing yet: apply afresh
    end
    C.apply(vehicle)
    State.refresh(vehicle, C.KEY)               -- tracks the car on a drawing side (the poll), fires the listeners
end

local ticks = 0
function C.OnTick()
    ticks = ticks + 1
    if ticks % C.EVERY ~= 0 then return end
    for id, e in pairs(C.cars) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            C.cars[id] = nil
        else
            C.update(v)
        end
    end
end

if not isClient() then                          -- where the game is authoritative: the trunk's fill
    Events.OnTick.Add(C.OnTick)
end
