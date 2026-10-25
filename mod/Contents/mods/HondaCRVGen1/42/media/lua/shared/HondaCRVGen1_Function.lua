--[[
Honda CR-V (RD1), function feature: the folded load floor, the hidden under-floor storage, the
owner's manual's know-how, the old-save migration of the fold-flat bed. Our own code.

Parts (scripts/features/function.py, added to every CR-V vehicle script), both without an item,
category nodisplay (not in the mechanics list), area TruckBed:
  * CRVFunctionCargo: what the folded rear seats add to the load space (capacity CARGO_CAPACITY on
    top of the trunk's). Its container test opens it only while the seats are folded as a load floor
    (HondaCRVGen1.Shared.isCargo, fold mode "cargo"; folded into a bed the bedding lies there and it
    stays shut): from inside the car, from the tailgate with the gate open, or through an open rear
    door. The seats go back up, or the bed is made up over it, only once it is empty (Shared.canUnfold).
  * CRVFunctionUnderfloor: the storage well under the cargo floor (the real RD1 hides one under the
    picnic-table floor panel), capacity 10. Hidden until someone lifts the floor (timed action
    ISCRVFunctionLiftFloor, its complete() on the authoritative side): State key
    function_floorFound, then open from the tailgate with the gate open.
  * CRVFunctionSeats: the rear bench itself (scripts/features/function.py lifts it out of the static
    cabin), three models: InteriorSeatsUp and InteriorSeatsFolded (the RD1's fold: seat bottom tilted
    forward, head restraint strapped behind it, seat-back down flat at the cargo deck's height), and
    InteriorBedding (foam pad, sleeping bag, pillow) on the folded seats in fold mode "bed". The
    part has no item and its script sets setAllModelsVisible = false, so the engine never shows or
    resets them: F.applySeats shows the bench upright or folded, and the bedding, from the synced fold
    state (Shared.isFolded, Shared.isBed), wherever the car is drawn (single player, every multiplayer
    client; never the dedicated server). It runs on the part's init (a car created, loaded or streamed
    in) and on every change of function_folded or function_foldMode (set on the authoritative side by
    ISCRVFoldSeats:complete, announced to every client by HondaCRVGen1.State).
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
F.CARGO_CAPACITY = 60                    -- on top of the trunk's 70 (BigTrunk1, 2026-10-22): the RD1's load space nearly doubles folded
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
    if not HondaCRVGen1.Shared.isCargo(vehicle) then return false end
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
-- the folded bed: a good bed (the game treats every vehicle as a bad one), better with a pillow. The rule is shared:
-- the sleeper's client answers getBedQuality with it (single player: that is the sleep), and in multiplayer the
-- server re-checks it before it sets the player's bed type (server/HondaCRVGen1_BedServer.lua), since the server
-- is where a sleeping player's stats run (IsoGameCharacter.updateStats_WakeState, 42.21: GameServer.server only)

-- the containers where a pillow counts on the folded bed: the cargo deck it runs onto (the trunk); vanilla's own
-- spot, the sleeper's seat container, is checked first. Not the folded load floor (CRVFunctionCargo): it is open in
-- fold mode "cargo" only (F.CargoAccess) and must be empty to make up the bed, so it never holds one on a bed
-- (I-DIFF-3)
F.BED_PILLOW_PARTS = { "TruckBed" }

local function hasPillow(cont)
    return cont ~= nil and cont:containsTag(ItemTag.PILLOW) == true
end

local function handPillow(chr)
    local a, b = chr:getPrimaryHandItem(), chr:getSecondaryHandItem()
    return (a ~= nil and a:hasTag(ItemTag.PILLOW)) or (b ~= nil and b:hasTag(ItemTag.PILLOW))
end

-- does chr, in the folded vehicle, have a pillow: in hand, in their seat's container (as vanilla's vehicle branch
-- of getBedQuality), or anywhere on the bed (F.BED_PILLOW_PARTS)
function F.bedPillow(chr, vehicle)
    if handPillow(chr) then return true end
    local seatPart = vehicle:getPartForSeatContainer(vehicle:getSeat(chr))
    if seatPart and hasPillow(seatPart:getItemContainer()) then return true end
    for _, id in ipairs(F.BED_PILLOW_PARTS) do
        local part = vehicle:getPartById(id)
        if part and hasPillow(part:getItemContainer()) then return true end
    end
    return false
end

-- is vehicle a made-up bed someone can sleep well in now: folded into a bed, the bench there (H-PLAY-3: with both
-- rear seats out nothing is drawn, so there is no bed; ISUninstallVehiclePart refuses them while folded, this covers
-- a car that lost them before that rule) and parked (I-PLAY-3: a bed in a parked car, not one being driven or towed)
function F.isMadeBed(vehicle)
    if not vehicle or not HondaCRVGen1.Shared.isBed(vehicle) or not F.benchFitted(vehicle) then return false end
    return vehicle:isStopped() == true
end

-- the bed type of chr sleeping in vehicle: "goodBed" / "goodBedPillow" on a made-up CR-V bed, else nil (the game's
-- answer stands)
function F.bedType(chr, vehicle)
    if not chr or not F.isMadeBed(vehicle) then return nil end
    return F.bedPillow(chr, vehicle) and "goodBedPillow" or "goodBed"
end

-- ---------------------------------------------------------------------------------------------
-- the rear seats' look: upright or folded flat (one bench model at a time), and the bedding on the folded
-- seats in fold mode "bed"

F.SEATS_PART = "CRVFunctionSeats"
F.SEAT_MODELS = { up = "InteriorSeatsUp", folded = "InteriorSeatsFolded", bedding = "InteriorBedding" }
F.seatsShown = {}                        -- vehicle id -> { vehicle =, folded =, bed =, fitted = } what this side last showed

-- is either rear seat's item fitted (the bench is drawn by CRVFunctionSeats, not by the seat parts: with both seats
-- taken out there is no bench to draw)
function F.benchFitted(vehicle)
    for _, id in ipairs(HondaCRVGen1.Shared.REAR_SEATS) do
        local p = vehicle:getPartById(id)
        if p and p:getInventoryItem() then return true end
    end
    return false
end

-- show the bench and the bedding as the synced state says, where the car is drawn; cheap and idempotent (a listener)
function F.applySeats(vehicle)
    if isServer() or not vehicle or not HondaCRVGen1.Shared.isCRV(vehicle) then return end
    local part = vehicle:getPartById(F.SEATS_PART)
    if not part then return end
    local fitted = F.benchFitted(vehicle)
    local folded = HondaCRVGen1.Shared.isFolded(vehicle) == true
    local bed = folded and HondaCRVGen1.Shared.isBed(vehicle) == true
    local id = vehicle:getId()
    local e = F.seatsShown[id]
    if e and e.vehicle == vehicle and e.folded == folded and e.bed == bed and e.fitted == fitted then return end
    part:setModelVisible(F.SEAT_MODELS.up, fitted and not folded)
    part:setModelVisible(F.SEAT_MODELS.folded, fitted and folded)
    part:setModelVisible(F.SEAT_MODELS.bedding, fitted and bed)
    F.seatsShown[id] = { vehicle = vehicle, folded = folded, bed = bed, fitted = fitted }
end

local function onFoldState(vehicle, key, value, old, how)
    F.applySeats(vehicle)
end
State.onChange(HondaCRVGen1.Shared.FOLD_KEY, onFoldState)
State.onChange(HondaCRVGen1.Shared.MODE_KEY, onFoldState)

-- a rear seat fitted or taken out (on a client the install / uninstall runs on the server: the State poll notices
-- the part's item change on every tracked car)
for _, id in ipairs(HondaCRVGen1.Shared.REAR_SEATS) do
    State.watchPart(id, function(vehicle, part) F.applySeats(vehicle) end)
end

-- drop the cars that left the world (streamed out, removed), as State.poll drops them from State.tracked: an entry
-- holds the BaseVehicle, which would otherwise stay referenced for the whole session
function F.pruneSeats()
    for id, e in pairs(F.seatsShown) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            F.seatsShown[id] = nil
        end
    end
end

-- (perf 2026-10-24: the cache is one of State's prunable caches, emptied of those cars by the client poll, instead
-- of a tick handler of its own)
if not isServer() then
    State.prunable(F.seatsShown)
end

-- H-SAVES-1: a car folded under 0.4.3 or earlier had one folded state, whose load floor was open; 0.4.4 reads a fold
-- without a mode as a bed, whose load floor is shut, so what the player stored there vanished (and the seats would
-- not go back up over it). Authoritative side, at the load floor's init: folded, no mode stored and things on the
-- load floor -> a load floor ("cargo"). A bed made up under 0.4.4+ is stored as no mode too ("bed" is the default),
-- but making up a bed needs that floor empty (Shared.canMakeBed), so it is never caught. Returns true when it changed
function F.migrateFoldMode(vehicle, part)
    if isClient() or not vehicle or not part or not HondaCRVGen1.Shared.isFolded(vehicle) then return false end
    local seat = HondaCRVGen1.Shared.bedPart(vehicle)
    local md = seat and seat:getModData()
    if not md or md[State.PREFIX .. HondaCRVGen1.Shared.MODE_KEY] ~= nil then return false end
    local cont = part:getItemContainer()
    if not cont or cont:isEmpty() then return false end
    return State.set(vehicle, HondaCRVGen1.Shared.MODE_KEY, HondaCRVGen1.Shared.MODE_CARGO) == true
end

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
        State.refresh(vehicle, HondaCRVGen1.Shared.MODE_KEY)
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
        F.migrateFoldMode(vehicle, part)
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

-- the vanilla actions grant their own XP once per item and car (addMechanicsItem keys); the success bonus
-- follows the same keys so taking a part off and on again cannot farm it. Vanilla records a key only on a SUCCESS
-- (ISInstallVehiclePart / ISUninstallVehiclePart:complete: addMechanicsItem in the success branch; a failure gives
-- its +1 and records nothing), so those keys alone cannot hold back a failure that is retried. The failure bonus (still
-- only while the item has not been done on that car) has its own memory too (H-PLAY-2): once per player and part of
-- the car per in-game day, kept in the car's mod data (key F.FAIL_XP_KEY), as the lift conversion keeps its XP
-- (Lift.giveXp)
local function fresh(character, key)
    return character:getMechanicsItem(key) == nil
end

F.FAIL_XP_KEY = "crvManualFailXP"
F.FAIL_XP_MEMORY_MS = 86400000           -- one in-game day (vanilla's own memory for mechanics XP keys)

local function gameMillis()
    if not getGameTime then return 0 end
    local ok, t = pcall(function() return getGameTime():getCalender():getTimeInMillis() end)
    return (ok and type(t) == "number") and t or 0
end

-- the failure bonus for character on part of vehicle, at most once per in-game day; returns the XP given
function F.failBonus(character, vehicle, part)
    if isClient() or not character or not vehicle or not part then return 0 end
    if not HondaCRVGen1.Shared.isCRV(vehicle) or not F.knows(character) then return 0 end
    local md = vehicle:getModData()
    local memory = type(md[F.FAIL_XP_KEY]) == "table" and md[F.FAIL_XP_KEY] or {}
    md[F.FAIL_XP_KEY] = memory
    local now = gameMillis()
    local old = {}
    for k, t in pairs(memory) do
        if type(t) ~= "number" or now - t >= F.FAIL_XP_MEMORY_MS or t > now then old[#old + 1] = k end
    end
    for _, k in ipairs(old) do memory[k] = nil end
    local who = (character.getUsername and character:getUsername()) or "player"
    local key = tostring(who) .. "|" .. tostring(part:getId())
    if memory[key] then return 0 end
    memory[key] = now
    return F.bonus(character, vehicle, F.XP.fail)
end

local installComplete = ISInstallVehiclePart.complete
function ISInstallVehiclePart:complete()
    local vehicle, item, part = self.vehicle, self.item, self.part
    local first = vehicle and item and fresh(self.character, item:getID() .. vehicle:getMechanicalID() .. "1")
    local result = installComplete(self)
    if vehicle and part and item and first then
        if part:getInventoryItem() == item then
            F.bonus(self.character, vehicle, F.XP.install)
        else
            F.failBonus(self.character, vehicle, part)
        end
    end
    return result
end

-- the picnic table IS the cargo floor's panel (the real RD1's): taking it out shows the storage well under it
local function tableOut(vehicle, part)
    if isClient() or not part or part:getId() ~= HondaCRVGen1.Shared.TABLE_PART or part:getInventoryItem() then return end
    if vehicle:getPartById(F.FLOOR_PART) and not F.isFloorFound(vehicle) then
        F.setFloorFound(vehicle)
    end
end

-- H-PLAY-3: a rear seat stays in while the seats are folded (the folded bench and the bed on it are drawn from those
-- two seats, Function.applySeats); the reason is IGUI_CRV_Function_SeatsAreFolded, as for getting in. Vanilla's
-- way: the uninstall test (Vehicles.UninstallTest.Default, which the rear seats' tables name) says no, so the
-- mechanics window greys "Uninstall" out and ISUninstallVehiclePart:isValid refuses; complete() refuses too, on the
-- authoritative side, which never runs a client's isValid. A mechanics cheat goes through, as in vanilla's Default
-- and ISUninstallVehiclePart:isValid: ISVehicleMechanics.cheat is the client's (client/ file: nil on a dedicated
-- server), chr:isMechanicsCheat() (IsoGameCharacter, the player's CheatType.MECHANICS, 42.21) is the server's
function F.seatUninstallBlocked(vehicle, part, chr)
    if not vehicle or not part then return false end
    if ISVehicleMechanics and ISVehicleMechanics.cheat then return false end
    if chr and chr.isMechanicsCheat and chr:isMechanicsCheat() == true then return false end
    local id = part:getId()
    for _, seat in ipairs(HondaCRVGen1.Shared.REAR_SEATS) do
        if id == seat then
            return HondaCRVGen1.Shared.isCRV(vehicle) and HondaCRVGen1.Shared.isFolded(vehicle) == true
        end
    end
    return false
end

function F.uninstallTest(vehicle, part, chr)
    if F.seatUninstallBlocked(vehicle, part, chr) then return false end
    return F.vanillaUninstallTest(vehicle, part, chr)
end

-- wrapped once per table, marked on the table (the armour feature's rule, Armour.wrapOnce: a later wrapper calls
-- ours, re-wrapping would loop); Vehicles.lua is a server file that loads after this shared one, so again at game
-- start. Returns true when it wrapped
F.UNINSTALL_MARK = "HondaCRVGen1FunctionWrapped"
function F.wrapUninstallTest()
    local t = Vehicles and Vehicles.UninstallTest
    if type(t) ~= "table" or type(t.Default) ~= "function" or rawget(t, F.UNINSTALL_MARK) then return false end
    rawset(t, F.UNINSTALL_MARK, true)
    F.vanillaUninstallTest = t.Default
    t.Default = F.uninstallTest
    return true
end
F.wrapUninstallTest()
if Events and Events.OnGameStart then Events.OnGameStart.Add(F.wrapUninstallTest) end
if Events and Events.OnServerStarted then Events.OnServerStarted.Add(F.wrapUninstallTest) end

local uninstallComplete = ISUninstallVehiclePart.complete
function ISUninstallVehiclePart:complete()
    local vehicle, part = self.vehicle, self.part
    if F.seatUninstallBlocked(vehicle, part, self.character) then return false end
    local item = part and part:getInventoryItem()
    local first = vehicle and item and fresh(self.character, item:getID() .. vehicle:getMechanicalID() .. "0")
    local result = uninstallComplete(self)
    if vehicle and item then
        if first then
            if not part:getInventoryItem() then
                F.bonus(self.character, vehicle, F.XP.uninstall)
            else
                F.failBonus(self.character, vehicle, part)
            end
        end
        if HondaCRVGen1.Shared.isCRV(vehicle) then tableOut(vehicle, part) end
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
