--[[
Honda CR-V (RD1): state shared by the client menus and the server rules.

The fold-flat bed lives in the rear-left seat part's mod data (HondaCRVGen1.State key
function_folded; old saves: crvBed = true), which the game saves and syncs. The picnic table is an ordinary removable part (CRVPicnicTable)
whose item is a moveable (Base.CRVGen1_PicnicTable): out of the car it is placed like furniture.
]]

require "HondaCRVGen1_State"

HondaCRVGen1 = HondaCRVGen1 or {}
local S = {}
HondaCRVGen1.Shared = S

S.VEHICLE = "Base.HondaCRVGen1"
S.TABLE_PART = "CRVPicnicTable"
S.TABLE_ITEM = "Base.CRVGen1_PicnicTable"
S.BED_PART = "SeatRearLeft"
S.REAR_SEATS = { "SeatRearLeft", "SeatRearRight" }
S.REAR_SEAT_INDEX = { [2] = true, [3] = true }       -- seat numbers of the rear bench (PassengerSeat4)

-- every CR-V vehicle script (HondaCRVGen1.State.registerVehicle: the lifted car is a second script)
function S.isCRV(vehicle)
    return HondaCRVGen1.State.isCRV(vehicle)
end

function S.bedPart(vehicle)
    return vehicle:getPartById(S.BED_PART)
end

-- function feature (2026-10-13, multiplayer fix): the folded state is HondaCRVGen1.State key
-- "function_folded" in the rear-left seat part's mod data (crv_function_folded), set only on the
-- authoritative side (ISCRVFoldSeats:complete) and synced to every client. Saves from before kept
-- crvBed = true in the same mod data: still read here, moved onto the key by HondaCRVGen1.Function.Init
S.FOLD_KEY = "function_folded"
S.LEGACY_BED_KEY = "crvBed"
S.CARGO_PART = "CRVFunctionCargo"                    -- the folded load floor's container (function feature)
HondaCRVGen1.State.define(S.FOLD_KEY, { part = S.BED_PART, kind = "boolean", default = false, request = false })

function S.isBed(vehicle)
    if not S.isCRV(vehicle) then return false end
    local part = S.bedPart(vehicle)
    if not part then return false end
    if HondaCRVGen1.State.get(vehicle, S.FOLD_KEY) == true then return true end
    return part:getModData()[S.LEGACY_BED_KEY] == true
end

-- authoritative side only (single player, the server): State.set saves, transmits and announces it
function S.setBed(vehicle, on)
    local part = S.bedPart(vehicle)
    if not part then return false, "no part " .. S.BED_PART end
    part:getModData()[S.LEGACY_BED_KEY] = nil
    return HondaCRVGen1.State.set(vehicle, S.FOLD_KEY, on and true or false)
end

-- Putting the seats back needs the folded load floor empty (what lies there would end up under the seats)
function S.canUnfold(vehicle)
    local cargo = vehicle:getPartById(S.CARGO_PART)
    local cont = cargo and cargo:getItemContainer()
    if cont and not cont:isEmpty() then return false, "IGUI_CRV_Function_CargoNotEmpty" end
    return true
end

-- Folding needs both rear seats fitted, empty and unoccupied
function S.canFold(vehicle)
    for _, id in ipairs(S.REAR_SEATS) do
        local part = vehicle:getPartById(id)
        if not part or not part:getInventoryItem() then return false, "IGUI_CRV_NoRearSeats" end
        local cont = part:getItemContainer()
        if cont and not cont:isEmpty() then return false, "IGUI_CRV_SeatsNotEmpty" end
    end
    for seat, _ in pairs(S.REAR_SEAT_INDEX) do
        if vehicle:isSeatOccupied(seat) then return false, "IGUI_CRV_SeatsOccupied" end
    end
    return true
end

function S.tablePart(vehicle)
    return vehicle:getPartById(S.TABLE_PART)
end

function S.gateOpen(vehicle)
    local gate = vehicle:getPartById("TrunkDoor")
    return gate ~= nil and gate:getDoor() ~= nil and gate:getDoor():isOpen()
end
