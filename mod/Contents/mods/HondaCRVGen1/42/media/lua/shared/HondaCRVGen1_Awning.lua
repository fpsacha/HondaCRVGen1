--[[
Honda CR-V (RD1), awning feature (scripts/features/awning.py): a roll-out side awning on the right roof rail.
Our own code.

Part CRVAwning (every CR-V vehicle script, item Base.CRVGen1_Awning, area SeatRearRight, a wrench and
Mechanics 1 to fit or remove) has three static models: the bag (Awning, the part's first model, shown by the
game whenever the item is installed), the canopy (AwningCanopy: canvas, rafters, front bar, valance) and the
poles (AwningPoles; the lifted scripts draw a longer pair). The rolled-out state is HondaCRVGen1.State key
awning_deployed (boolean, in the part's mod data: saved with the car and synced to every client), changed
only where the game is authoritative:
  * the timed action ISCRVAwning (complete(): single player or the server) rolls it out or up;
  * the car rolls it up itself when its engine runs or it moves (Awning.OnTick, authoritative side); moving
    faster than TEAR_KMH with it out tears it (condition -TEAR);
  * removing the part, or installing it, leaves it rolled up.
Model visibility is neither saved nor synced, and the engine shows every model of a part whenever its item is
set (VehiclePart.setInventoryItem -> setAllModelsVisible), so every side that draws the car shows the canopy
and the poles from the state: on the part's init (the car created, loaded or streamed in), on every change the
State module reports, and when the part's item changes under a client (State.watchPart), as the roof rack's
cargo does (HondaCRVGen1Accessories.lua).

The canopy hides whatever stands under it from the game's camera (it is drawn opaque, 2.74 x 1.8 m, 2 m up).
A client therefore leaves the canopy out of ITS OWN drawing while ITS player stands under it (Awning.localHide):
the poles stay, like the game's own roofs that cut away over the player in a building. Every other player
still sees it. Project Viewpoint's first- and third-person cameras look up at the canvas from under it: the
cut-away is skipped there (Awning.viewpointCamera).

Awning.isUnder(vehicle, character) is the footprint test (AREA, mesh metres, converted with the script's model
scale through BaseVehicle.getLocalPos, the game's own area test: BaseVehicle.isInArea): the rain protection
(server/HondaCRVGen1_AwningRain.lua) and the cut-away use it.
]]

require "HondaCRVGen1_State"

HondaCRVGen1 = HondaCRVGen1 or {}
local Awning = HondaCRVGen1.Awning or {}
HondaCRVGen1.Awning = Awning
local State = HondaCRVGen1.State

Awning.PART = "CRVAwning"
Awning.ITEM = "Base.CRVGen1_Awning"
Awning.KEY = "awning_deployed"
Awning.MODELS = { canopy = "AwningCanopy", poles = "AwningPoles" }
-- the ground under the canopy: mesh metres, +x the car's right, +y forward (features/awning.py footprint(); the
-- canopy is 1.8 m out from the car and 2.74 m along it; scripts/test_awning_lua.py checks the two agree)
Awning.AREA = { x0 = 0.735, x1 = 2.55, y0 = -2.09, y1 = 0.65 }
Awning.SPAWN = 3                  -- percent of CR-Vs that spawn with one (stowed), before the sandbox scale
Awning.MOVE_KMH = 1.0             -- faster than this, or the engine running: the car rolls it up
Awning.TEAR_KMH = 8.0             -- faster than this with it still out: it tears
Awning.TEAR = 20                  -- condition it loses then
Awning.EVERY = 20                 -- ticks between the authoritative side's checks of rolled-out awnings

State.define(Awning.KEY, { part = Awning.PART, kind = "boolean", default = false, request = false })

Awning.out = Awning.out or {}         -- vehicle id -> BaseVehicle, every rolled-out awning this side knows of
Awning.shown = Awning.shown or {}     -- drawing side: vehicle id -> { vehicle =, canopy =, poles = }

function Awning.part(vehicle)
    return vehicle and vehicle:getPartById(Awning.PART) or nil
end

function Awning.fitted(vehicle)
    local p = Awning.part(vehicle)
    return p ~= nil and p:getInventoryItem() ~= nil
end

function Awning.isDeployed(vehicle)
    return Awning.fitted(vehicle) and State.get(vehicle, Awning.KEY) == true
end

-- the car's speed (km/h, absolute) and whether its engine runs
local function speed(vehicle)
    local ok, v = pcall(function() return vehicle:getCurrentSpeedKmHour() end)
    return ok and type(v) == "number" and math.abs(v) or 0
end

function Awning.parked(vehicle)
    if vehicle:isEngineRunning() then return false, "Tooltip_CRV_Awning_EngineOn" end
    if speed(vehicle) > Awning.MOVE_KMH then return false, "Tooltip_CRV_Awning_Moving" end
    return true
end

-- ok, why: may character roll the awning out (on = true) or up (on = false) now (menu, action, server)
function Awning.canSet(vehicle, character, on)
    if not vehicle or not State.isCRV(vehicle) or not Awning.fitted(vehicle) then return false end
    if vehicle.isRemovedFromWorld and vehicle:isRemovedFromWorld() then return false end
    if Awning.isDeployed(vehicle) == (on == true) then return false end
    if character and character:getVehicle() then return false, "Tooltip_CRV_Awning_Inside" end
    if on then
        if Awning.part(vehicle):getCondition() <= 0 then return false, "Tooltip_CRV_Awning_Broken" end
        return Awning.parked(vehicle)
    end
    return true
end

-- authoritative side only (State.set saves, transmits, announces and fires the listeners)
function Awning.set(vehicle, on)
    return State.set(vehicle, Awning.KEY, on == true)
end

-- ---------------------------------------------------------------------------------------------
-- the footprint

local vec = nil
-- character's position in the car's mesh metres (+x right, +y forward), or nil
function Awning.meshPos(vehicle, character)
    if not vec then vec = Vector3f.new() end
    vehicle:getLocalPos(character:getX(), character:getY(), vehicle:getZ(), vec)
    local s = vehicle:getScript() and vehicle:getScript():getModelScale() or 1.0
    if not s or s <= 0 then s = 1.0 end
    return -vec:x() / s, vec:z() / s                     -- PZ local +x is the car's LEFT
end

function Awning.isUnder(vehicle, character)
    if not vehicle or not character or character:getVehicle() then return false end
    if not Awning.isDeployed(vehicle) then return false end
    if math.floor(character:getZ()) ~= math.floor(vehicle:getZ()) then return false end
    local x, y = Awning.meshPos(vehicle, character)
    local a = Awning.AREA
    return x >= a.x0 and x <= a.x1 and y >= a.y0 and y <= a.y1
end

-- the rolled-out awning character stands under, or nil
function Awning.shelterOf(character)
    for id, v in pairs(Awning.out) do
        if v:isRemovedFromWorld() or v:getId() ~= id then
            Awning.out[id] = nil
        elseif Awning.isUnder(v, character) then
            return v
        end
    end
    return nil
end

-- ---------------------------------------------------------------------------------------------
-- drawing side: the canopy and the poles from the state

-- Project Viewpoint's own cameras (first / third person: they look at the canvas from under it, no cut-away
-- there). Viewpoint exposes Viewpoint.View.next(), the view its cycle key goes to next (viewpoint.FP.nextView,
-- Viewpoint.jar 2026-10: "first" from the isometric view, "third" from first person, "isometric" from third
-- person); there is no getter for the current one, so it is read from that
function Awning.viewpointCamera()
    local vp = rawget(_G, "Viewpoint")
    local view = type(vp) == "table" and vp.View or nil
    if not view or view.next == nil then return false end
    local ok, nxt = pcall(view.next)
    return ok and (nxt == "third" or nxt == "isometric")
end

-- does a local player of this client stand under vehicle's canopy (the cut-away)
function Awning.localHide(vehicle)
    if isServer() or Awning.viewpointCamera() then return false end
    for i = 0, getNumActivePlayers() - 1 do
        local p = getSpecificPlayer(i)
        if p and not p:isDead() and Awning.isUnder(vehicle, p) then return true end
    end
    return false
end

function Awning.apply(vehicle)
    if isServer() or not vehicle then return end
    local part = Awning.part(vehicle)
    if not part or not part:getInventoryItem() then return end
    local out = Awning.isDeployed(vehicle)
    local canopy = out and not Awning.localHide(vehicle)
    local id = vehicle:getId()
    local e = Awning.shown[id]
    if not (e and e.vehicle == vehicle and e.canopy == canopy and e.poles == out) then
        part:setModelVisible(Awning.MODELS.canopy, canopy)
        part:setModelVisible(Awning.MODELS.poles, out)
        Awning.shown[id] = { vehicle = vehicle, canopy = canopy, poles = out }
    end
    State.sawPart(vehicle, part)
end

local function track(vehicle, on)
    if on and Awning.fitted(vehicle) then
        Awning.out[vehicle:getId()] = vehicle
    else
        Awning.out[vehicle:getId()] = nil
    end
end

State.onChange(Awning.KEY, function(vehicle, key, value, old, how)
    track(vehicle, value == true)
    Awning.apply(vehicle)
    -- the driver's client hears why it rolled up by itself (and whether it tore)
    if not isServer() and old == true and value ~= true and how ~= "init" then
        local v = speed(vehicle)
        local driver = vehicle:getDriver()
        if (vehicle:isEngineRunning() or v > Awning.MOVE_KMH) and driver and driver.isLocalPlayer and driver:isLocalPlayer()
                and HaloTextHelper then
            HaloTextHelper.addText(driver, getText(v > Awning.TEAR_KMH and "IGUI_CRV_Awning_Torn" or "IGUI_CRV_Awning_AutoStowed"))
        end
    end
end)
-- a client saw the part's item change (an install or removal the server completed): models reset
State.watchPart(Awning.PART, function(vehicle, part)
    Awning.shown[vehicle:getId()] = nil
    track(vehicle, Awning.isDeployed(vehicle))
    Awning.apply(vehicle)
end)

-- ---------------------------------------------------------------------------------------------
-- part hooks (vehicle script lua { create, init }, install / uninstall complete)

function Awning.Create(vehicle, part)
    local chance = Awning.SPAWN
    local Acc = HondaCRVGen1.Acc
    if Acc and type(Acc.scaledChance) == "function" then
        local ok, c = pcall(Acc.scaledChance, chance)
        if ok and type(c) == "number" then chance = c end
    end
    if chance > 0 and ZombRand(100) < chance then
        VehicleUtils.createPartInventoryItem(part)
    end
end

-- every side (createPhysics -> VehicleParts.initParts): the models of a fresh part show nothing yet of the state
function Awning.Init(vehicle, part)
    if not vehicle or not part then return end
    if not isServer() then Awning.shown[vehicle:getId()] = nil end
    -- a car saved with it out but without the part (a debug removal): back to rolled up where that is decided
    if not isClient() and State.get(vehicle, Awning.KEY) == true and not part:getInventoryItem() then
        Awning.set(vehicle, false)
    end
    track(vehicle, Awning.isDeployed(vehicle))
    Awning.apply(vehicle)
    State.refresh(vehicle, Awning.KEY)
end

-- single player / the server (ISInstallVehiclePart:complete): a fitted awning starts rolled up
function Awning.InstallComplete(vehicle, part)
    vehicle:doDamageOverlay()
    Awning.set(vehicle, false)
    Awning.shown[vehicle:getId()] = nil
    Awning.apply(vehicle)
end

function Awning.UninstallComplete(vehicle, part, item)
    Awning.set(vehicle, false)
    Awning.out[vehicle:getId()] = nil
    Awning.shown[vehicle:getId()] = nil
    vehicle:doDamageOverlay()
end

-- ---------------------------------------------------------------------------------------------
-- authoritative side: the car rolls it up when it is driven

function Awning.check(vehicle)
    if not Awning.isDeployed(vehicle) then
        Awning.out[vehicle:getId()] = nil
        if State.get(vehicle, Awning.KEY) == true then Awning.set(vehicle, false) end
        return
    end
    local v = speed(vehicle)
    if not vehicle:isEngineRunning() and v <= Awning.MOVE_KMH then return end
    if v > Awning.TEAR_KMH then
        local part = Awning.part(vehicle)
        part:setCondition(math.max(0, part:getCondition() - Awning.TEAR))
        vehicle:transmitPartCondition(part)
    end
    Awning.set(vehicle, false)
end

local ticks = 0
function Awning.OnTick()
    ticks = ticks + 1
    if ticks % Awning.EVERY ~= 0 then return end
    for id, v in pairs(Awning.out) do
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            Awning.out[id] = nil
        else
            Awning.check(v)
        end
    end
end

-- drawing side: the cut-away follows the local players as they walk in and out from under a canopy
local drawTicks = 0
function Awning.OnTickClient()
    drawTicks = drawTicks + 1
    if drawTicks % 5 ~= 0 then return end
    for id, v in pairs(Awning.out) do
        if not v:isRemovedFromWorld() and v:getId() == id then
            Awning.apply(v)
        end
    end
end

if not isClient() then Events.OnTick.Add(Awning.OnTick) end
if not isServer() then Events.OnTick.Add(Awning.OnTickClient) end
