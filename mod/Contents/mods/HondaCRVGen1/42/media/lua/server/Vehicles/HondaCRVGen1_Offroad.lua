--[[
Honda CR-V (RD1) off-road and rear parts (scripts/features/offroad.py): snorkel, skid plate, rear
steel bumper with its hitch, roof ladder, and the two jerry cans (on the spare on the tailgate, and
behind the roof rack basket). Our own code; KI5's damnlib is a reference only.

The parts are ordinary removable parts (gen_scripts.accessory_part): the game shows a part's model
while an item is installed and the vanilla install / uninstall actions run on the authoritative
side (ISInstallVehiclePart:complete), so nothing here mutates state from a client. The jerry cans
are the vanilla Base.JerryCan as the part item: the installed item is the same InventoryItem with
its FluidContainer (InventoryItem.save writes it through saveEntity, so it survives saves and the
item packets), and uninstalling hands that same object back with its fuel. Refuelling stays the
vanilla way: take the can off and pour it.

Rules this file adds (server folder: loaded on every side, the dedicated server and multiplayer
clients included, at game load):
  * Create (where the car is created): a rare roll per part, scaled by the function feature's
    FunctionAccessoryChance sandbox option exactly as the core accessories are
    (HondaCRVGen1.Acc.scaledChance); a can only on a car that has its host (the gate, the rack) and
    with a random amount of petrol in it;
  * the roof rack cannot come off while the roof can sits on it (Vehicles.UninstallTest.Default,
    which the rack's uninstall table names, is wrapped for that one part on a CR-V);
  * the gate cannot come off while the tailgate can rides it (HondaCRVGen1.Acc.GATE_FIRST);
  * drawing side: the roof can's model shows only while the rack is there too (a save edited by
    other means, a debug removal), recomputed on init and whenever either part's item changes
    under a client (State.watchPart), since model visibility is neither saved nor synced;
  * the rear steel bumper takes the rear knocks for the gate (2026-10-21): it registers with the core
    accessories' protection loop (HondaCRVGen1.Acc.COVERS / RATE, watched through Acc.Init) at the bull
    bar's rate, so the gate lasts ~1.7x. A rear crash takes the vanilla rear damage
    (BaseVehicle.addDamageRear: the gate, the rear glass, sometimes a rear door) and zombies at the back
    thump the gate (getNearestBodyworkPart). The skid plate and the snorkel protect nothing: the game
    deals no damage from underneath.
]]

require "HondaCRVGen1_State"
require "Vehicles/Vehicles"
require "Vehicles/HondaCRVGen1Accessories"

HondaCRVGen1 = HondaCRVGen1 or {}
local Offroad = HondaCRVGen1.Offroad or {}
HondaCRVGen1.Offroad = Offroad
local State = HondaCRVGen1.State

Offroad.SNORKEL = "CRVOffroadSnorkel"
Offroad.SKID = "CRVOffroadSkidPlate"
Offroad.BUMPER = "CRVOffroadRearBumper"
Offroad.LADDER = "CRVOffroadLadder"
Offroad.GATE_CAN = "CRVOffroadCanGate"
Offroad.ROOF_CAN = "CRVOffroadCanRoof"
Offroad.RACK = "CRVRoofRack"

-- percent of CR-Vs that spawn with the part (before the sandbox scale); the roof can only where the
-- rack spawned (25 % of the cars), so about 2 % of all cars carry one
Offroad.SPAWN = {
    [Offroad.SNORKEL] = 4, [Offroad.SKID] = 5, [Offroad.BUMPER] = 4, [Offroad.LADDER] = 3,
    [Offroad.GATE_CAN] = 5, [Offroad.ROOF_CAN] = 8,
}
-- parts that sit on another one: only spawned, and only drawn (roof can), while that one is fitted
Offroad.NEEDS = { [Offroad.GATE_CAN] = "TrunkDoor", [Offroad.ROOF_CAN] = Offroad.RACK }
Offroad.CANS = { [Offroad.GATE_CAN] = true, [Offroad.ROOF_CAN] = true }
Offroad.EMPTY_CHANCE = 35          -- percent of spawned cans that are empty; the others hold 2 l to full

-- a part's spawn chance in percent: its base rate scaled by the function feature's sandbox option
-- FunctionAccessoryChance through the core accessories' own scaling (HondaCRVGen1.Acc.scaledChance:
-- 100 = the base, 0 = bare cars, capped at 100 %). Read at create, on the side that creates the car,
-- after the sandbox has loaded. A part whose host is itself a removable accessory (the roof can on
-- the rack) keeps its base share: the host's roll already carries the scale, and scaling both would
-- square the option.
function Offroad.spawnChance(partId)
    local base = Offroad.SPAWN[partId] or 0
    if Offroad.NEEDS[partId] == Offroad.RACK then return base end
    local Acc = HondaCRVGen1.Acc
    if Acc and type(Acc.scaledChance) == "function" then
        local ok, c = pcall(Acc.scaledChance, base)
        if ok and type(c) == "number" then return c end
    end
    return base
end

-- a spawned can's petrol: empty, or 2 l up to full
function Offroad.fillRandom(item)
    if not item or not item.getFluidContainer then return end
    local fc = item:getFluidContainer()
    if not fc then return end
    fc:Empty()
    if ZombRand(100) < Offroad.EMPTY_CHANCE then return end
    local cap = fc:getCapacity()
    local amount = math.min(cap, 2 + ZombRand(math.max(1, math.floor(cap) - 1)))
    fc:addFluid(Fluid.Petrol, amount)
end

local function fitted(vehicle, partId)
    local p = vehicle:getPartById(partId)
    return p ~= nil and p:getInventoryItem() ~= nil
end

function Offroad.Create(vehicle, part)
    local id = part:getId()
    local chance = Offroad.spawnChance(id)
    if chance <= 0 or ZombRand(100) >= chance then return end
    local host = Offroad.NEEDS[id]
    if host and not fitted(vehicle, host) then return end
    VehicleUtils.createPartInventoryItem(part)
    if Offroad.CANS[id] then
        Offroad.fillRandom(part:getInventoryItem())
        Offroad.fullCondition(part)
    end
end

-- a jerry can's part shows its condition in the mechanics window; the vanilla can has no ConditionMax, so
-- it reads 10% whatever the fuel. The part is kept at 100 (its fuel is its own business)
function Offroad.fullCondition(part)
    if part:getInventoryItem() and part:getCondition() < 100 then
        part:setCondition(100)
    end
end

-- drawing side: the roof can's model only while the rack carries it (a no-op on a dedicated server)
function Offroad.showRoofCan(vehicle)
    if isServer() or not vehicle then return end
    local part = vehicle:getPartById(Offroad.ROOF_CAN)
    if not part then return end
    if part:getInventoryItem() then
        part:setModelVisible(Offroad.ROOF_CAN, fitted(vehicle, Offroad.RACK))
    end
    State.sawPart(vehicle, part)
end

-- the rear bumper's protection: the gate (HondaCRVGen1.Acc's loop restores it, the bumper wears at RATE)
Offroad.BUMPER_COVERS = { "TrunkDoor" }
Offroad.BUMPER_RATE = 1.5
local Acc = HondaCRVGen1.Acc
if Acc and Acc.COVERS then
    Acc.COVERS[Offroad.BUMPER] = Offroad.BUMPER_COVERS
    if Acc.RATE then Acc.RATE[Offroad.BUMPER] = Offroad.BUMPER_RATE end
end

-- runs on every side (createPhysics -> VehicleParts.initParts)
function Offroad.Init(vehicle, part)
    if part:getId() == Offroad.ROOF_CAN then
        Offroad.showRoofCan(vehicle)
    end
    -- the bumper: watched by the protection loop (Acc.Init does nothing on a multiplayer client)
    if part:getId() == Offroad.BUMPER and Acc and Acc.Init then
        Acc.Init(vehicle, part)
    end
    -- cars saved before this fix: only the authoritative side changes the condition
    if Offroad.CANS[part:getId()] and (isServer() or not isClient()) then
        Offroad.fullCondition(part)
    end
end

-- single player / the server (ISInstallVehiclePart:complete): the part's own model shows by itself
function Offroad.InstallComplete(vehicle, part)
    vehicle:doDamageOverlay()
    if Offroad.CANS[part:getId()] then
        Offroad.fullCondition(part)
    end
    if part:getId() == Offroad.ROOF_CAN then
        Offroad.showRoofCan(vehicle)
    end
    if part:getId() == Offroad.BUMPER and Acc and Acc.Init then
        Acc.Init(vehicle, part)                      -- protect the gate from now on
    end
end

function Offroad.UninstallComplete(vehicle, part, item)
    vehicle:doDamageOverlay()
    -- the bumper: the protection loop lists its protectors again at once (it asks their items only now and then)
    if part:getId() == Offroad.BUMPER and Acc and Acc.dirty then Acc.dirty(vehicle) end
end

-- the rack's item changed under a client, or the can's: draw the can again
State.watchPart(Offroad.RACK, function(vehicle, part) Offroad.showRoofCan(vehicle) end)
State.watchPart(Offroad.ROOF_CAN, function(vehicle, part) Offroad.showRoofCan(vehicle) end)

-- the gate comes off only once the can on its spare is off (the can is drawn by the gate's player)
if HondaCRVGen1.Acc and HondaCRVGen1.Acc.GATE_FIRST then
    local listed = false
    for _, id in ipairs(HondaCRVGen1.Acc.GATE_FIRST) do
        if id == Offroad.GATE_CAN then listed = true end
    end
    if not listed then table.insert(HondaCRVGen1.Acc.GATE_FIRST, Offroad.GATE_CAN) end
end

-- the rack comes off only once the roof can is off: its uninstall table names the vanilla test
function Offroad.RackUninstallTest(vehicle, part, chr)
    if part and part:getId() == Offroad.RACK and State.isCRV(vehicle) and fitted(vehicle, Offroad.ROOF_CAN) then
        return false
    end
    return nil
end

if Vehicles and Vehicles.UninstallTest and Vehicles.UninstallTest.Default
        and not Vehicles.UninstallTest.HondaCRVGen1OffroadWrapped then
    local default = Vehicles.UninstallTest.Default
    Vehicles.UninstallTest.HondaCRVGen1OffroadWrapped = default
    Vehicles.UninstallTest.Default = function(vehicle, part, chr)
        if Offroad.RackUninstallTest(vehicle, part, chr) == false then return false end
        return default(vehicle, part, chr)
    end
end
