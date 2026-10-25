--[[
Honda CR-V (RD1): the trunk and the picnic table's access. Our own code.

The trunk (part TruckBed, scripts/gen_scripts.py: TRUNK_ITEMS). 0.4.4 swapped the SUV template's Base.NormalTrunk
(NormalTrunk1 = 55 at mechanicType 1) for Base.BigTrunk (BigTrunk1 = 70). With BigTrunk alone a car saved before
could never refit the NormalTrunk1 it came with once it was out, and no standard trunk fitted at all. The part
takes both families now, big first: VehicleScript.Loaded turns them into Base.BigTrunk1;Base.NormalTrunk1.

  * Trunk.Create (the part's create): a new car gets BigTrunk1. Vanilla's VehicleUtils.createPartInventoryItem
    picks one of a list's items at random (ZombRand(100) > 100 - 100 / count, else the last: about half the cars
    would get the 55), unless the car's chosen-parts map already names one for the list; Create names the first
    (BigTrunk1) there, then lets vanilla make the item, its condition and all.
  * Trunk.Init (the part's init, every side, every car created, loaded or streamed in): a car whose trunk is
    still the NormalTrunk1 it was made with before 0.4.4 gets a BigTrunk1 in the same condition, once (part mod
    data TRUNK_KEY marks every car seen, so a standard trunk a player fits later stays). Where the game is
    authoritative only (single player, the server); the server sends the new item to the clients.

The picnic table (part CRVPicnicTable) lies under the cargo floor behind the tailgate: the mechanics screen may
take it out or put it back only with the gate open or gone (Trunk.TableInstallTest / TableUninstallTest, its
install / uninstall tests), as the take-out menu (HondaCRVGen1_Menu.lua) already asked.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
local Trunk = HondaCRVGen1.Trunk or {}
HondaCRVGen1.Trunk = Trunk

Trunk.PART = "TruckBed"
Trunk.BIG = "Base.BigTrunk1"
Trunk.OLD = "Base.NormalTrunk1"
Trunk.TRUNK_KEY = "crv_trunk70"

-- vanilla's key for a part's item list in the car's chosen-parts map (VehicleUtils.createPartInventoryItem)
function Trunk.chosenKey(part)
    local types = part:getItemType()
    if not types or types:isEmpty() then return nil end
    local key = ""
    for i = 1, types:size() do key = key .. types:get(i - 1) .. ";" end
    return key, types:get(0)
end

-- part create (TruckBed): the first item of the list, BigTrunk1, through vanilla's own item maker
function Trunk.Create(vehicle, part)
    if not part:getInventoryItem() then
        local key, first = Trunk.chosenKey(part)
        local chosen = vehicle:getChoosenParts()
        if key and chosen then chosen:put(key, first) end
    end
    return VehicleUtils.createPartInventoryItem(part)
end

-- a pre-0.4.4 car's NormalTrunk1 -> a BigTrunk1 in the same condition, once per car; true when it changed
function Trunk.fix(vehicle, part)
    if not vehicle or not part or isClient() then return false end
    local md = part:getModData()
    if md[Trunk.TRUNK_KEY] then return false end
    md[Trunk.TRUNK_KEY] = true
    local old = part:getInventoryItem()
    if not old or old:getFullType() ~= Trunk.OLD then return false end
    local new = instanceItem(Trunk.BIG)
    if not new then return false end
    new:setConditionNoSound(old:getCondition())
    part:setInventoryItem(new)
    if isServer() then vehicle:transmitPartItem(part) end
    return true
end

-- part init (TruckBed, every side)
function Trunk.Init(vehicle, part)
    Trunk.fix(vehicle, part)
end

-- the tailgate open, or no gate to open
function Trunk.gateReachable(vehicle)
    local gate = vehicle:getPartById("TrunkDoor")
    if not gate or not gate:getInventoryItem() then return true end
    local door = gate:getDoor()
    return door == nil or door:isOpen()
end

local function cheat()
    return ISVehicleMechanics ~= nil and ISVehicleMechanics.cheat == true
end

-- install / uninstall tests of CRVPicnicTable: vanilla's Default, behind an open (or missing) gate
function Trunk.TableInstallTest(vehicle, part, chr)
    if not cheat() and not Trunk.gateReachable(vehicle) then return false end
    return Vehicles.InstallTest.Default(vehicle, part, chr)
end

function Trunk.TableUninstallTest(vehicle, part, chr)
    if not cheat() and not Trunk.gateReachable(vehicle) then return false end
    return Vehicles.UninstallTest.Default(vehicle, part, chr)
end
