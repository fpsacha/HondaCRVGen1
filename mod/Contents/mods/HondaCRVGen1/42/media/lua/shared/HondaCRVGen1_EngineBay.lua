--[[
Honda CR-V (RD1): the engine bay is drawn only while someone can see it (performance pass, 2026-10-19).
Our own code.

The bay model (crvgen1_engine_block, ~3,600 triangles) was drawn on every car every frame, hood shut
or not. Part CRVEngineBay (scripts/gen_scripts.py) now carries two models: EngineBay, the full bay, and
EngineBayLow, a stand-in of a few dark boxes (scripts/bay/standin.py: the radiator and the engine's
mass) for the little the grille slots and the hood seams show of a shut bay. The part has no item and
its script sets setAllModelsVisible = false, so the engine never shows or resets its models
(VehiclePart.setInventoryItem is the only caller of setAllModelsVisible): Bay.apply shows exactly one,
wherever the car is drawn (single player, every multiplayer client; never a dedicated server).

The full bay shows while
  * the hood (part EngineDoor) is missing: no item, the bay is in plain view;
  * its door is open (VehicleDoor.isOpen: saved with the car and sent to every client by the game,
    BaseVehicle.transmitPartDoor), so a car loaded, streamed in or opened by another player follows;
  * the open action has just started HERE: ISOpenVehicleDoor:start plays the hood's Open clip at once
    (BaseVehicle.playPartAnim) but the door state only turns open in complete(), after the character's
    animation; so start() shows the bay for up to OPEN_GRACE ms (an action that fails, a locked hood,
    falls back to the door state: the clip ends and the game snaps the hood shut, "Closed");
  * the door turned shut less than CLOSE_HOLD ms ago: ISCloseVehicleDoor:start plays the Close clip and
    complete() shuts the door when the character is done, while the hood may still be swinging down
    (hood_opening at rate 0.65: ~2 s). The holds count only unpaused time (isGamePaused), as the clip does.
Nothing here is saved or sent: every input is state the game already syncs, and each side derives the
model from it on the part's init (a car created, loaded, streamed in or re-scripted: BaseVehicle
.createPhysics -> VehicleParts.initParts runs every part's init on every side) and on a tick over the
cars it has seen.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
local Bay = HondaCRVGen1.Bay or {}
HondaCRVGen1.Bay = Bay

Bay.PART = "CRVEngineBay"
Bay.HOOD = "EngineDoor"
Bay.MODELS = { full = "EngineBay", low = "EngineBayLow" }
Bay.OPEN_GRACE = 4000                    -- ms (unpaused) the full bay shows after this side started opening the hood
Bay.CLOSE_HOLD = 3000                    -- ms (unpaused) it stays after the door state turned shut
Bay.cars = Bay.cars or {}                -- vehicle id -> { vehicle =, full = shown (bool or nil), open =, opening =, hold = }

local function now()
    return getTimestampMs()
end

-- the hood leaves the bay in view: missing, or its door open
function Bay.hoodOpen(vehicle)
    local hood = vehicle:getPartById(Bay.HOOD)
    if not hood or not hood:getInventoryItem() then return true end
    local door = hood:getDoor()
    return door ~= nil and door:isOpen()
end

-- the drawing side's entry for a car (a new BaseVehicle under the same id starts afresh)
local function entry(vehicle)
    local id = vehicle:getId()
    local e = Bay.cars[id]
    if not e or e.vehicle ~= vehicle then
        e = { vehicle = vehicle, full = nil, open = Bay.hoodOpen(vehicle), opening = 0, hold = 0 }
        Bay.cars[id] = e
    end
    return e
end

-- show exactly one of the two models; only on a change (no setModelVisible on idle ticks)
local function show(vehicle, e, full)
    if e.full == full then return end
    local part = vehicle:getPartById(Bay.PART)
    if not part then return end
    part:setModelVisible(Bay.MODELS.full, full)
    part:setModelVisible(Bay.MODELS.low, not full)
    e.full = full
end

-- one car, dt ms of unpaused time since the last pass
function Bay.update(vehicle, dt)
    local e = entry(vehicle)
    dt = dt or 0
    if e.opening > 0 then e.opening = math.max(0, e.opening - dt) end
    if e.hold > 0 then e.hold = math.max(0, e.hold - dt) end
    local open = Bay.hoodOpen(vehicle)
    if open then
        e.opening = 0                    -- the door state carries it from here
    elseif e.open then
        e.hold = Bay.CLOSE_HOLD          -- just shut: the Close clip may still be playing
    end
    e.open = open
    show(vehicle, e, open or e.opening > 0 or e.hold > 0)
    return e.full
end

-- part init (CRVEngineBay, every side): models start hidden on a fresh part; draw the right one now
function Bay.Init(vehicle, part)
    if isServer() or not vehicle then return end
    local e = entry(vehicle)
    e.full = nil                         -- the part's models were just (re)made: apply afresh
    e.open = Bay.hoodOpen(vehicle)       -- a car loaded with the hood shut shows the stand-in at once
    Bay.update(vehicle, 0)
end

-- this side started opening the hood (ISOpenVehicleDoor:start, before the clip plays)
function Bay.opening(vehicle)
    if isServer() or not vehicle or not vehicle:getPartById(Bay.PART) then return end
    local e = entry(vehicle)
    e.opening = Bay.OPEN_GRACE
    Bay.update(vehicle, 0)
end

local last = nil
function Bay.OnTick()
    local t = now()
    local dt = last and (t - last) or 0
    last = t
    if dt < 0 or isGamePaused() then dt = 0 end
    for id, e in pairs(Bay.cars) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id or not v:getPartById(Bay.PART) then
            Bay.cars[id] = nil
        else
            Bay.update(v, dt)
        end
    end
end

-- ISOpenVehicleDoor:start, wrapped once per table (the playbook's rule: marked on the table itself)
function Bay.openStart(self, ...)
    if self and self.part and self.vehicle and self.part:getId() == Bay.HOOD then
        local ok, err = pcall(Bay.opening, self.vehicle)
        if not ok then print("HondaCRVGen1.Bay: " .. tostring(err)) end
    end
    return Bay.vanillaOpenStart(self, ...)
end

function Bay.wrap()
    local t = ISOpenVehicleDoor
    if type(t) ~= "table" or type(t.start) ~= "function" or rawget(t, "HondaCRVGen1BayWrapped") then return false end
    rawset(t, "HondaCRVGen1BayWrapped", true)
    Bay.vanillaOpenStart = t.start
    t.start = Bay.openStart
    return true
end

if not isServer() then
    require "Vehicles/TimedActions/ISOpenVehicleDoor"
    Bay.wrap()
    if Events and Events.OnGameStart then Events.OnGameStart.Add(Bay.wrap) end
    if Events and Events.OnTick then Events.OnTick.Add(Bay.OnTick) end
end
