--[[
Honda CR-V (RD1): survival armour, the protection (shared/HondaCRVGen1_Armour.lua has the parts' hooks).

Registered with the accessories' protection loop (server/Vehicles/HondaCRVGen1Accessories.lua), which
runs where the game is authoritative (single player, the server) every few ticks: a covered part's
condition comes back whenever it drops while its protector is fitted with condition left, and the
protector wears instead (spec/feature-plugins.md section 4):
  * door plate      covers its door (zombie thumps when the window cannot be hit, crashes)
  * window mesh     covers its window glass (the guard part's armour variant), and holds weakened
                    glass at GLASS_FLOOR: the game smashes a pane in the same call that takes it to 0
  * rear plate      covers the flip-up rear glass, the same way
  * arch guard      the only bodywork at its wheel, so zombies standing there thump IT
                    (BaseVehicle.getNearestBodyworkPart): it covers itself (wears at the armour's rate)
                    and the hits its tyre takes (roadkill chips, gunshots). Driving wear is not a hit:
                    the tyre's snapshot follows Vehicles.LowerCondition down (Armour.lowerCondition).
                    Suspension and brakes only wear by driving: nothing to protect there.
Wear: armour is VERY strong. Each absorbed point of condition adds WEAR_RATE / ArmourStrength (the
sandbox option, default 1) to an accumulator in the protector's mod data (server side only, saved
with the car); whole points come off its condition. At 1 and Normal zombies (strength 3): 0.06 per
thump, a plate or an arch guard lasts ~1,600 thumps where the bar guards last ~200.
The bar guards (the same parts with the bar item) keep their 0-1 per thump.
Every vanilla function this file and the shared one wrap is wrapped once per table (Armour.wrapOnce).

media/lua/server loads on every side (multiplayer clients too, GameLoadingState): the registrations
are tables and the model hook (Acc.PART_HOOKS, called from Acc.Init on every side) draws where the car
is drawn; the protection loop itself only runs where Acc starts it.
]]

require "HondaCRVGen1_State"
require "HondaCRVGen1_Armour"
require "Vehicles/HondaCRVGen1Accessories"

local Armour = HondaCRVGen1.Armour
local Acc = HondaCRVGen1.Acc
local State = HondaCRVGen1.State

Armour.WEAR_RATE = 0.02                 -- protector condition per absorbed condition at ArmourStrength 1

function Armour.strength()
    local vars = SandboxVars and SandboxVars.HondaCRVGen1
    local v = vars and vars.ArmourStrength
    if type(v) ~= "number" or v <= 0 then return 1.0 end
    return v
end

-- whole points the protector loses for absorbing `lost`; the fraction stays in its mod data
function Armour.wearArmour(lost, vehicle, acc)
    if not acc then
        return (ZombRand(100) < 100 * Armour.WEAR_RATE * lost / Armour.strength()) and 1 or 0   -- core without the args
    end
    local md = acc:getModData()
    local w = (tonumber(md.crvArmourWear) or 0) + lost * Armour.WEAR_RATE / Armour.strength()
    local n = math.floor(w)
    md.crvArmourWear = w - n
    return n
end

-- a guard part wears like the bars (0-1 a thump) with the bar item, like armour with the mesh / plate
function Armour.wearGuard(lost, vehicle, acc)
    if acc and Armour.isArmourItem(acc) then
        return Armour.wearArmour(lost, vehicle, acc)
    end
    return ZombRand(0, 2)
end

-- armour over weakened glass holds it: the game smashes a window in the same call that takes its
-- condition to 0 (VehicleWindow.damage), before any protection pass can give it back, so a pane at or
-- under one thump (zombie strength 1-5, a few thumps between two passes in a crowd) would break under
-- the mesh and let the arms through. While a mesh / rear plate with condition left is fitted the glass
-- is kept at GLASS_FLOOR or more; the armour pays for the points like for any absorbed hit
function Armour.glassFloor(vehicle, acc, part)
    if Armour.isArmourItem(acc) then return Armour.GLASS_FLOOR end
    return nil
end

-- authoritative side, when the armour goes on (or the car loads): raise the glass to the floor now
function Armour.holdGlass(vehicle, guard, win)
    if isClient() or not (guard and win and guard:getInventoryItem() and win:getInventoryItem()) then return end
    if guard:getCondition() <= 0 or not Armour.isArmourItem(guard) then return end
    local now = win:getCondition()
    if now >= Armour.GLASS_FLOOR then return end
    win:setCondition(Armour.GLASS_FLOOR)
    vehicle:transmitPartCondition(win)
    local w = Armour.wearArmour(Armour.GLASS_FLOOR - now, vehicle, guard)
    if w > 0 then
        guard:setCondition(math.max(0, guard:getCondition() - w))
        vehicle:transmitPartCondition(guard)
    end
    local e = Acc and Acc.watch[vehicle:getId()]
    if e and e.vehicle == vehicle then e.snap[win:getId()] = Armour.GLASS_FLOOR end
end

if Acc then
    for plate, door in pairs(Armour.DOOR_PLATES) do
        Acc.COVERS[plate] = { door }
        Acc.WEAR[plate] = Armour.wearArmour
    end
    -- an arch guard is the only bodywork at its wheel: zombies standing there thump it
    -- (BaseVehicle.getNearestBodyworkPart), so it covers itself first (it wears at the armour's rate,
    -- not a full zombie strength a thump), then the hits its tyre takes (roadkill chips, gunshots);
    -- the tyre's driving wear goes on as usual (Armour.lowerCondition)
    for arch, tyre in pairs(Armour.ARCH_TYRE) do
        Acc.COVERS[arch] = { arch, tyre }
        Acc.WEAR[arch] = Armour.wearArmour
    end
    Acc.FLOOR = Acc.FLOOR or {}
    for pid, _ in pairs(Armour.VARIANTS) do
        Acc.WEAR[pid] = Armour.wearGuard
        Acc.FLOOR[pid] = Armour.glassFloor
        if Acc.PART_HOOKS then
            Acc.PART_HOOKS[pid] = Armour.guardHook
        end
    end
end

-- a door with its armour plate on cannot come off (the plate is drawn by the door's player): the doors'
-- uninstall test is the vanilla Default, wrapped here for CR-Vs once Vehicles.lua is loaded
function Armour.uninstallTest(vehicle, part, chr)
    local plate = part and Armour.PLATE_OF_DOOR[part:getId()]
    if plate and State.isCRV(vehicle) then
        local p = vehicle:getPartById(plate)
        if p and p:getInventoryItem() then return false end
    end
    return Armour.vanillaUninstall(vehicle, part, chr)
end

-- wrapped once per table (Armour.wrapOnce): the off-road feature wraps the same function after this
-- file loads, and its wrapper calls ours; a table Vehicles.lua replaced is wrapped again at game start
function Armour.wrapUninstall()
    Armour.wrapOnce(Vehicles and Vehicles.UninstallTest, "Default", "HondaCRVGen1ArmourWrapped", Armour.uninstallTest,
                    function(f) Armour.vanillaUninstall = f end)
end

-- armour never comes on a spawned car: a guard part that can hold the bars or an armour variant gets
-- the bars when the game creates its item (VehicleUtils.createPartInventoryItem picks a random type of
-- the part's list unless the car already chose one under the key "<type>;<type>;": choose the first,
-- the bars, before it does). The core spawn roll (Acc.Create: the guard set) is left as it is.
function Armour.createItem(part)
    local vehicle = part and part:getVehicle()
    if vehicle and Armour.VARIANTS[part:getId()] and State.isCRV(vehicle) and not part:getInventoryItem() then
        local types = part:getItemType()
        local chosen = vehicle:getChoosenParts()
        if types and chosen and types:size() > 1 then
            local key = ""
            for i = 1, types:size() do key = key .. types:get(i - 1) .. ";" end
            if not chosen:get(key) then chosen:put(key, types:get(0)) end
        end
    end
    return Armour.vanillaCreateItem(part)
end

function Armour.wrapSpawn()
    Armour.wrapOnce(VehicleUtils, "createPartInventoryItem", "HondaCRVGen1ArmourWrapped", Armour.createItem,
                    function(f) Armour.vanillaCreateItem = f end)
end

-- driving wear of a tyre under an arch guard is wear, not a hit: the protection loop must not give it
-- back. Vehicles.Update.Tire takes it through Vehicles.LowerCondition (1 point per event); the guard's
-- snapshot of the tyre follows it down, so only what happens between (roadkill chips, gunshots) is
-- restored and charged to the guard
function Armour.lowerCondition(vehicle, part, elapsedMinutes)
    local before = part and part:getCondition()
    local r = Armour.vanillaLower(vehicle, part, elapsedMinutes)
    local e = before and vehicle and Acc and Acc.watch[vehicle:getId()]
    if e and e.vehicle == vehicle and e.snap[part:getId()] then
        local d = before - part:getCondition()
        if d > 0 then e.snap[part:getId()] = e.snap[part:getId()] - d end
    end
    return r
end

function Armour.wrapWear()
    Armour.wrapOnce(Vehicles, "LowerCondition", "HondaCRVGen1ArmourWrapped", Armour.lowerCondition,
                    function(f) Armour.vanillaLower = f end)
end

function Armour.wrapVanilla()
    Armour.wrapUninstall()
    Armour.wrapSpawn()
    Armour.wrapWear()
end

Armour.wrapVanilla()
if Events.OnGameStart then Events.OnGameStart.Add(Armour.wrapVanilla) end
if Events.OnServerStarted then Events.OnServerStarted.Add(Armour.wrapVanilla) end
