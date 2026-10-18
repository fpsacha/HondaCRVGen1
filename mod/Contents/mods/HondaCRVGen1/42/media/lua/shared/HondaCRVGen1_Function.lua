--[[
Honda CR-V (RD1), function feature: the folded load floor, the hidden under-floor storage, the
owner's manual's know-how, the old-save migration of the fold-flat bed. Our own code.

Parts (scripts/features/function.py, added to every CR-V vehicle script), both without an item,
category nodisplay (not in the mechanics list), area TruckBed:
  * CRVFunctionCargo: what the folded rear seats add to the load space (capacity CARGO_CAPACITY on
    top of the trunk's). Its container test opens it only while the seats are folded
    (HondaCRVGen1.Shared.isBed): from inside the car, from the tailgate with the gate open, or
    through an open rear door. The seats go back up only once it is empty (Shared.canUnfold).
  * CRVFunctionUnderfloor: the storage well under the cargo floor (the real RD1 hides one under the
    picnic-table floor panel), capacity 10. Hidden until someone lifts the floor (timed action
    ISCRVFunctionLiftFloor, its complete() on the authoritative side): State key
    function_floorFound, then open from the tailgate with the gate open.
  * CRVFunctionSeats: the rear bench itself (scripts/features/function.py lifts it out of the static
    cabin), two models: InteriorSeatsUp and InteriorSeatsFolded (the RD1's fold: seat bottom tilted
    forward, head restraint strapped behind it, seat-back down flat at the cargo deck's height). The
    part has no item and its script sets setAllModelsVisible = false, so the engine never shows or
    resets them: F.applySeats shows exactly one, from the synced fold state (Shared.isBed), wherever the
    car is drawn (single player, every multiplayer client; never the dedicated server). It runs on the
    part's init (a car created, loaded or streamed in) and on every change of function_folded (set on
    the authoritative side by ISCRVFoldSeats:complete, announced to every client by HondaCRVGen1.State).
Container tests run in the client's UI (ISInventoryPage lists only containers BaseVehicle
.canAccessContainer passes) and read only synced state (part mod data through HondaCRVGen1.State).

The owner's manual (Base.CRVGen1_OwnersManual, literature) teaches Basic Mechanics and the marker
KNOW_HOW. A character who knows it gets extra Mechanics XP for work on a CR-V: the vanilla
install / uninstall / engine repair actions are wrapped, and their complete() runs where the game is
authoritative (the server in multiplayer), where addXp is the server's own (GameServer.addXp).
isRecipeActuallyKnown is used, not isRecipeKnown: for a name that is no old-style Recipe the latter
returns true for everybody while the sandbox's SeeNotLearntRecipe is on (IsoGameCharacter 42.21).
]]

require "HondaCRVGen1_State"
require "HondaCRVGen1_Shared"
require "Vehicles/TimedActions/ISInstallVehiclePart"
require "Vehicles/TimedActions/ISUninstallVehiclePart"
require "Vehicles/TimedActions/ISRepairEngine"

HondaCRVGen1 = HondaCRVGen1 or {}
local F = HondaCRVGen1.Function or {}
HondaCRVGen1.Function = F
local State = HondaCRVGen1.State

F.CARGO_PART = "CRVFunctionCargo"
F.FLOOR_PART = "CRVFunctionUnderfloor"
F.CARGO_CAPACITY = 60                    -- the trunk is 55 (NormalTrunk1); the RD1's load space roughly doubles folded
F.FLOOR_CAPACITY = 10
F.FOUND_KEY = "function_floorFound"
F.MANUAL = "Base.CRVGen1_OwnersManual"
F.KNOW_HOW = "HondaCRVKnowHow"           -- the manual's marker recipe (LearnedRecipes; vanilla's Herbalist is one too)
F.XP = { install = 3, uninstall = 2, fail = 1, repair = 2 }

-- The manual is a print media item (vanilla newspapers and magazines): item mod data printMedia names the
-- window's title and layout (Print_Media.json) and the text behind its text button (Print_Text.json); reading
-- the item shows the designed page. scripts/features/function.py writes the strings, scripts/manual_art.py the page.
-- the manual's spreads, one print media page each (scripts/manual_art.py draws them, features/function.py writes
-- their Print_Media / Print_Text translations). The first is the item's own print media: reading the item opens
-- it; the client's page buttons (FunctionMenu) turn to the others.
F.MANUAL_SPREADS = {}
for i, id in ipairs({ "CRVGen1_Manual", "CRVGen1_Manual2", "CRVGen1_Manual3" }) do
    F.MANUAL_SPREADS[i] = {
        id = id,
        title = "Print_Media_" .. id .. "_title",
        info = "Print_Media_" .. id .. "_info",
        text = "Print_Text_" .. id .. "_info",
    }
end
F.PRINT_MEDIA = F.MANUAL_SPREADS[1]

-- the item's OnCreate (item script): vanilla's recipe-magazine set-up (the literature title that puts re-reads on
-- the cooldown), then the print media mod data
function F.OnCreateManual(item)
    if ItemCodeOnCreate and ItemCodeOnCreate.onCreateRecipeMagazine then
        ItemCodeOnCreate.onCreateRecipeMagazine(item)
    end
    local md = item:getModData()
    if not md.printMedia then
        md.printMedia = {
            id = F.PRINT_MEDIA.id, title = F.PRINT_MEDIA.title, info = F.PRINT_MEDIA.info, text = F.PRINT_MEDIA.text,
        }
    end
end

State.define(F.FOUND_KEY, { part = F.FLOOR_PART, kind = "boolean", default = false, request = false })

-- the tailgate side: in the TruckBed area with the gate open (or gone), as the vanilla trunk test
local function atOpenGate(vehicle, chr)
    if not vehicle:isInArea("TruckBed", chr) then return false end
    local gate = vehicle:getPartById("TrunkDoor")
    if not gate or not gate:getInventoryItem() then return true end
    local door = gate:getDoor()
    return door == nil or door:isOpen()
end

-- a rear door's side: in that seat's area with its door open (or gone)
local function atOpenRearDoor(vehicle, chr)
    for _, side in ipairs({ "Left", "Right" }) do
        if vehicle:isInArea("SeatRear" .. side, chr) then
            local p = vehicle:getPartById("DoorRear" .. side)
            if not p or not p:getInventoryItem() then return true end
            local door = p:getDoor()
            if door == nil or door:isOpen() then return true end
        end
    end
    return false
end

-- container test of CRVFunctionCargo (vehicle script)
function F.CargoAccess(vehicle, part, chr)
    if not HondaCRVGen1.Shared.isBed(vehicle) then return false end
    local inside = chr:getVehicle()
    if inside then return inside == vehicle end
    return atOpenGate(vehicle, chr) or atOpenRearDoor(vehicle, chr)
end

function F.isFloorFound(vehicle)
    return State.get(vehicle, F.FOUND_KEY) == true
end

-- container test of CRVFunctionUnderfloor (vehicle script)
function F.UnderfloorAccess(vehicle, part, chr)
    if not F.isFloorFound(vehicle) then return false end
    if chr:getVehicle() then return false end
    return atOpenGate(vehicle, chr)
end

-- ok, why: can chr lift the cargo floor of vehicle now (menu, action)
function F.canLiftFloor(vehicle, chr)
    if not vehicle or not HondaCRVGen1.Shared.isCRV(vehicle) then return false end
    if not vehicle:getPartById(F.FLOOR_PART) then return false end
    if F.isFloorFound(vehicle) then return false, "IGUI_CRV_Function_FloorAlreadyFound" end
    if not HondaCRVGen1.Shared.gateOpen(vehicle) then
        local gate = vehicle:getPartById("TrunkDoor")
        if gate and gate:getInventoryItem() then return false, "Tooltip_CRV_GateClosed" end
    end
    return true
end

-- authoritative side: the floor has been lifted
function F.setFloorFound(vehicle)
    return State.set(vehicle, F.FOUND_KEY, true)
end

-- ---------------------------------------------------------------------------------------------
-- the rear seats' look: upright or folded flat, one model of CRVFunctionSeats at a time

F.SEATS_PART = "CRVFunctionSeats"
F.SEAT_MODELS = { up = "InteriorSeatsUp", folded = "InteriorSeatsFolded" }
F.seatsShown = {}                        -- vehicle id -> { vehicle =, folded = } what this side last showed

-- show the bench as the synced state says, where the car is drawn; cheap and idempotent (a listener)
function F.applySeats(vehicle)
    if isServer() or not vehicle or not HondaCRVGen1.Shared.isCRV(vehicle) then return end
    local part = vehicle:getPartById(F.SEATS_PART)
    if not part then return end
    local folded = HondaCRVGen1.Shared.isBed(vehicle) == true
    local id = vehicle:getId()
    local e = F.seatsShown[id]
    if e and e.vehicle == vehicle and e.folded == folded then return end
    part:setModelVisible(F.SEAT_MODELS.up, not folded)
    part:setModelVisible(F.SEAT_MODELS.folded, folded)
    F.seatsShown[id] = { vehicle = vehicle, folded = folded }
end

State.onChange(HondaCRVGen1.Shared.FOLD_KEY, function(vehicle, key, value, old, how)
    F.applySeats(vehicle)
end)

-- part init (every part of the feature, every side): migrate an old save's bed flag where the game is
-- authoritative, then fire the listeners for this car (State.refresh also starts the client poll)
function F.Init(vehicle, part)
    if not vehicle or not part then return end
    if part:getId() == F.SEATS_PART then
        if not isServer() then
            F.seatsShown[vehicle:getId()] = nil         -- a fresh part shows nothing yet: apply afresh
        end
        F.applySeats(vehicle)
        State.refresh(vehicle, HondaCRVGen1.Shared.FOLD_KEY)
        return
    end
    if not isClient() and part:getId() == F.CARGO_PART then
        local seat = HondaCRVGen1.Shared.bedPart(vehicle)
        local md = seat and seat:getModData()
        if md and md[HondaCRVGen1.Shared.LEGACY_BED_KEY] == true then
            md[HondaCRVGen1.Shared.LEGACY_BED_KEY] = nil
            local ok, why = HondaCRVGen1.Shared.setBed(vehicle, true)
            if why == "unchanged" then vehicle:transmitPartModData(seat) end
        end
    end
    if part:getId() == F.CARGO_PART then
        State.refresh(vehicle, HondaCRVGen1.Shared.FOLD_KEY)
    elseif part:getId() == F.FLOOR_PART then
        State.refresh(vehicle, F.FOUND_KEY)
    end
end

-- ---------------------------------------------------------------------------------------------
-- the owner's manual: extra Mechanics XP on a CR-V for a character who read it

function F.knows(character)
    return character ~= nil and character:isRecipeActuallyKnown(F.KNOW_HOW) == true
end

-- give the bonus where the game is authoritative; returns the XP given
function F.bonus(character, vehicle, amount)
    if isClient() or not amount or amount <= 0 then return 0 end
    if not vehicle or not HondaCRVGen1.Shared.isCRV(vehicle) or not F.knows(character) then return 0 end
    addXp(character, Perks.Mechanics, amount)
    return amount
end

-- the vanilla actions grant their own XP once per item and car (addMechanicsItem keys); the bonus
-- follows the same keys so taking a part off and on again cannot farm it
local function fresh(character, key)
    return character:getMechanicsItem(key) == nil
end

local installComplete = ISInstallVehiclePart.complete
function ISInstallVehiclePart:complete()
    local vehicle, item, part = self.vehicle, self.item, self.part
    local first = vehicle and item and fresh(self.character, item:getID() .. vehicle:getMechanicalID() .. "1")
    local result = installComplete(self)
    if vehicle and part and item then
        if part:getInventoryItem() == item then
            if first then F.bonus(self.character, vehicle, F.XP.install) end
        else
            F.bonus(self.character, vehicle, F.XP.fail)
        end
    end
    return result
end

local uninstallComplete = ISUninstallVehiclePart.complete
function ISUninstallVehiclePart:complete()
    local vehicle, part = self.vehicle, self.part
    local item = part and part:getInventoryItem()
    local first = vehicle and item and fresh(self.character, item:getID() .. vehicle:getMechanicalID() .. "0")
    local result = uninstallComplete(self)
    if vehicle and item then
        if not part:getInventoryItem() then
            if first then F.bonus(self.character, vehicle, F.XP.uninstall) end
        else
            F.bonus(self.character, vehicle, F.XP.fail)
        end
    end
    return result
end

local repairComplete = ISRepairEngine.complete
function ISRepairEngine:complete()
    local vehicle, part = self.vehicle, self.part
    local before = part and part:getCondition()
    local first = vehicle and fresh(self.character, vehicle:getMechanicalID() .. "2")
    local result = repairComplete(self)
    if vehicle and part and first and part:getCondition() > before then
        F.bonus(self.character, vehicle, F.XP.repair)
    end
    return result
end
