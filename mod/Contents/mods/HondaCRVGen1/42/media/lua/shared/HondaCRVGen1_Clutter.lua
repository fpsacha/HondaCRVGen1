--[[
Honda CR-V (RD1), cargo clutter: what is loaded into the trunk shows in the cargo bay, and more of it the
fuller the trunk is. Our own code. scripts/features/clutter.py builds the meshes and writes the part.

Part CRVClutterCargo (every CR-V vehicle script, no item, category nodisplay, setAllModelsVisible = false,
so the engine never shows or resets its models: VehiclePart.setInventoryItem is the only caller of
setAllModelsVisible) lists seven models:
  * InteriorClutter1..3: what each trunk fill state ADDS (a duffel and a carton; + a cooler and a carton; + a
    backpack, a toolbox, a small carton, a gas can and a kit bag). State n shows models 1..n.
  * InteriorClutterFold1..3 (2026-10-24): the same for the folded load floor (part CRVFunctionCargo, the
    function feature's container while the rear seats are folded as a load floor, fold mode "cargo"): a few
    lean pieces lying on the folded seat backs. Shown only in fold mode "cargo"; nothing while the seats are
    up or made up as a bed.
  * InteriorClutterWell: a blanket over the soft stuff filling the well under the cargo floor, shown while the
    picnic table (part CRVPicnicTable, the floor panel) is out and the well holds something (the under-floor
    storage, part CRVFunctionUnderfloor) or the trunk is loaded (its pieces stand partly over the open well:
    without the blanket they would float over the hole).
Nothing shows while the rear seats are folded into the bed (HondaCRVGen1.Shared.isBed, fold mode "bed": the bed
lies there); folded as a bare load floor (mode "cargo") the trunk's load shows as with the seats up.

The fill states are HondaCRVGen1.State keys in this part's mod data: "clutter_load" (the trunk, 0 = empty, 1..3),
"clutter_fold" (the folded load floor, 0..3) and "clutter_well" (the under-floor storage holds something). The
game has no container-changed hook that reaches the server and every client (OnContainerUpdate is a
client-side UI refresh, triggered from Lua actions and a few Java paths; ItemContainer.addItem / Remove fire
nothing), and a client does not hold a car container's items it never opened, so, like the roof rack's cargo
(HondaCRVGen1Accessories.lua, Acc.updateRack), the authoritative side (single player, the server) derives them
from the containers (weight over capacity, with a little hysteresis so a load sitting on a threshold does not
flicker) on a throttled tick and State.set saves and syncs them. Every side that draws the car (single player,
each multiplayer client; never a dedicated server) shows the models from the synced states, the synced fold
state (State keys function_folded, function_foldMode) and the table part's synced item:
  * on the part's init (VehicleParts.initParts: a car created, spawned, loaded or streamed in);
  * on every change of a clutter key, function_folded or function_foldMode (State listeners: "set" where it
    changed, "sync" on a client that the server told, or its poll found the new mod data);
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
C.FOLD_PART = "CRVFunctionCargo"        -- the folded load floor's container (function feature, no item)
C.WELL_PART = "CRVFunctionUnderfloor"   -- the under-floor storage (function feature, no item)
C.TABLE = "CRVPicnicTable"              -- HondaCRVGen1.Shared.TABLE_PART: the floor panel over the well
C.MODELS = { "InteriorClutter1", "InteriorClutter2", "InteriorClutter3" }
C.FOLD_MODELS = { "InteriorClutterFold1", "InteriorClutterFold2", "InteriorClutterFold3" }
C.WELL = "InteriorClutterWell"
C.FILL = { 0.10, 0.40, 0.75 }           -- share of the container's weight capacity for states 1..3
C.HYST = 0.02                           -- a state goes down only below its threshold minus this
C.EVERY = 15                            -- ticks between fill checks (~4 a second), as the rack's
C.KEY = "clutter_load"
C.FOLD_KEY = "clutter_fold"
C.WELL_KEY = "clutter_well"
State.define(C.KEY, { part = C.PART, kind = "number", default = 0, min = 0, max = #C.MODELS, integer = true })
State.define(C.FOLD_KEY, { part = C.PART, kind = "number", default = 0, min = 0, max = #C.FOLD_MODELS, integer = true })
State.define(C.WELL_KEY, { part = C.PART, kind = "boolean", default = false })

C.cars = C.cars or {}                   -- authoritative side: vehicle id -> { vehicle = } whose containers are followed
-- drawing side: vehicle id -> { vehicle =, sig = } what this side shows (the State poll drops cars that left the world)
C.shown = State.prunable(C.shown or {})

-- the container of a part, or nil (needItem: the part must have its item installed, as the trunk). `part` may be
-- given (the authoritative tick keeps the car's part objects)
local function container(vehicle, partId, needItem, part)
    part = part or vehicle:getPartById(partId)
    if not part or (needItem and not part:getInventoryItem()) then return nil end
    return part:getItemContainer()
end

-- the fill (0..1) of a part's container, or nil without the part or container. ItemContainer.getMaxWeight() is
-- the part container's capacity (getCapacity), getCapacityWeight() the weight of what is in it
function C.fillOf(vehicle, partId, needItem, part)
    local c = container(vehicle, partId, needItem, part)
    if not c then return nil end
    local max = c:getMaxWeight()
    if not max or max <= 0 then return nil end
    return c:getCapacityWeight() / max
end

-- the trunk's fill (the trunk needs its item: no trunk lid, no load shown)
function C.fill(vehicle, part)
    return C.fillOf(vehicle, C.TRUNK, true, part)
end

-- does the under-floor storage hold anything
function C.wellUsed(vehicle, part)
    local c = container(vehicle, C.WELL_PART, false, part)
    return c ~= nil and not c:isEmpty()
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

-- a State key to `value` where it differs (State.set saves, syncs and fires the listeners)
local function follow(vehicle, key, value, cur)
    if value ~= cur then State.set(vehicle, key, value) end
end

-- authoritative side: the states follow the containers. e: the car's C.cars entry (its part objects, kept from
-- the part's init: VehicleParts are made with the car and re-made only with a new init)
-- (perf 2026-10-24: the parts' containers are kept with the parts (a part keeps its ItemContainer: 42.21 sets one
-- only when the parts are made, VehicleParts.setScript), the three states are read from the clutter part's mod
-- data at once; State.set still runs only for a state that changed)
local function fillIn(c)
    if not c then return nil end
    local max = c:getMaxWeight()
    if not max or max <= 0 then return nil end
    return c:getCapacityWeight() / max
end

function C.update(vehicle, e)
    if isClient() then return end
    local p = e and e.parts
    if not p then
        p = { trunk = vehicle:getPartById(C.TRUNK), fold = vehicle:getPartById(C.FOLD_PART),
              well = vehicle:getPartById(C.WELL_PART), host = vehicle:getPartById(C.PART) }
        p.trunkC = p.trunk and p.trunk:getItemContainer()
        p.foldC = p.fold and p.fold:getItemContainer()
        p.wellC = p.well and p.well:getItemContainer()
        if e then e.parts = p end
    end
    local md = p.host and p.host:getModData()
    local cur = State.getFrom(md, C.KEY)
    follow(vehicle, C.KEY, C.stateFor(p.trunk and p.trunk:getInventoryItem() and fillIn(p.trunkC), cur), cur)
    cur = State.getFrom(md, C.FOLD_KEY)
    follow(vehicle, C.FOLD_KEY, C.stateFor(fillIn(p.foldC), cur), cur)
    follow(vehicle, C.WELL_KEY, p.wellC ~= nil and not p.wellC:isEmpty(), State.getFrom(md, C.WELL_KEY))
end

-- what the drawing side should show: the number of trunk load models, of folded-floor load models, the well blanket
function C.wanted(vehicle)
    if Shared.isBed(vehicle) then return 0, 0, false end
    local n = State.get(vehicle, C.KEY) or 0
    local f = Shared.isCargo(vehicle) and (State.get(vehicle, C.FOLD_KEY) or 0) or 0
    local tbl = vehicle:getPartById(C.TABLE)
    local well = not (tbl and tbl:getInventoryItem()) and (n > 0 or State.get(vehicle, C.WELL_KEY) == true)
    return n, f, well
end

-- drawing side: show exactly that; a car that already shows it is left alone (cheap, idempotent: a listener)
function C.apply(vehicle)
    if isServer() or not vehicle or not Shared.isCRV(vehicle) then return end
    local part = vehicle:getPartById(C.PART)
    if not part then return end
    local n, f, well = C.wanted(vehicle)
    local sig = n + 4 * f + (well and 16 or 0)
    local id = vehicle:getId()
    local e = C.shown[id]
    if e and e.vehicle == vehicle and e.sig == sig then return sig end
    for i, model in ipairs(C.MODELS) do
        part:setModelVisible(model, i <= n)
    end
    for i, model in ipairs(C.FOLD_MODELS) do
        part:setModelVisible(model, i <= f)
    end
    part:setModelVisible(C.WELL, well)
    C.shown[id] = { vehicle = vehicle, sig = sig }
    return sig
end

local function onState(vehicle, key, value, old, how)
    C.apply(vehicle)
end
State.onChange(C.KEY, onState)
State.onChange(C.FOLD_KEY, onState)
State.onChange(C.WELL_KEY, onState)
State.onChange(Shared.FOLD_KEY, onState)
State.onChange(Shared.MODE_KEY, onState)
-- the table went in or out under a tracked car (single player or a client: the State poll)
State.watchPart(C.TABLE, function(vehicle, part)
    C.apply(vehicle)
end)

-- part init (every side): follow the containers where that is decided, show the states where the car is drawn
function C.Init(vehicle, part)
    if not vehicle or not part or part:getId() ~= C.PART then return end
    local id = vehicle:getId()
    if not isClient() then
        local e = C.cars[id]
        if not e or e.vehicle ~= vehicle then
            e = { vehicle = vehicle }
            C.cars[id] = e
        end
        e.parts = nil                           -- (re)made parts: look them up again
        C.update(vehicle, e)
    end
    if not isServer() then
        C.shown[id] = nil                       -- a fresh part shows nothing yet: apply afresh
    end
    C.apply(vehicle)
    State.refresh(vehicle, C.KEY)               -- tracks the car on a drawing side (the poll), fires the listeners
end

-- a car no player is within C.NEAR tiles of is looked at every C.SLOW-th pass (State.due): nobody can load it
C.NEAR = 30
C.SLOW = 8
local ticks = 0
function C.OnTick()
    ticks = ticks + 1
    if ticks % C.EVERY ~= 0 then return end
    for id, e in pairs(C.cars) do
        local v = e.vehicle
        if State.gone(v, id) then
            C.cars[id] = nil
        elseif State.due(e, v, C.NEAR, C.SLOW, ticks) then
            C.update(v, e)
        end
    end
end

if not isClient() then                          -- where the game is authoritative: the containers' fill
    Events.OnTick.Add(C.OnTick)
end
