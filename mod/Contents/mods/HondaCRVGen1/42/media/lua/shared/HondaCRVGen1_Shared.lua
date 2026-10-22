--[[
Honda CR-V (RD1): state shared by the client menus and the server rules.

The folded rear seats live in the rear-left seat part's mod data (HondaCRVGen1.State key
function_folded; old saves: crvBed = true), which the game saves and syncs, with what the folded space is
for (key function_foldMode, 2026-10-22: "cargo", the bare load floor, or "bed", the made-up bed; a car
folded before there was a choice is a bed). The picnic table is an ordinary removable part (CRVPicnicTable)
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

-- what the folded space is for (2026-10-22, the owner: "if the seats are folded, I want to have more trunk space
-- or a bed, should be able to choose"): "cargo" opens the load floor (Function.CargoAccess), draws no bedding and
-- gives no bed; "bed" draws the bedding (model InteriorBedding), sleeps as a good bed and keeps the load floor shut
-- (the bed lies on it). Same host part and rules as function_folded; the default "bed" is what a car folded before
-- the choice existed was (its mod data has no mode)
S.MODE_KEY = "function_foldMode"
S.MODE_BED, S.MODE_CARGO = "bed", "cargo"
HondaCRVGen1.State.define(S.MODE_KEY, { part = S.BED_PART, kind = "string", values = { S.MODE_BED, S.MODE_CARGO },
                                        default = S.MODE_BED, request = false })

-- are the rear seats folded flat (either mode)
function S.isFolded(vehicle)
    if not S.isCRV(vehicle) then return false end
    local part = S.bedPart(vehicle)
    if not part then return false end
    if HondaCRVGen1.State.get(vehicle, S.FOLD_KEY) == true then return true end
    return part:getModData()[S.LEGACY_BED_KEY] == true
end

-- "bed" | "cargo" while folded, nil while the seats are up
function S.foldMode(vehicle)
    if not S.isFolded(vehicle) then return nil end
    if HondaCRVGen1.State.get(vehicle, S.MODE_KEY) == S.MODE_CARGO then return S.MODE_CARGO end
    return S.MODE_BED
end

-- folded and made up as a bed (bedding drawn, good bed, load floor shut)
function S.isBed(vehicle)
    return S.foldMode(vehicle) == S.MODE_BED
end

-- folded as a bare load floor (the +60 load space open)
function S.isCargo(vehicle)
    return S.foldMode(vehicle) == S.MODE_CARGO
end

-- authoritative side only (single player, the server): State.set saves, transmits and announces it. on: fold in
-- `mode` (default "bed"), or switch the mode of folded seats; off: seats up, the mode back to its default. The mode
-- is set before the fold and cleared after it, so every listener sees a consistent pair
function S.setFold(vehicle, on, mode)
    local part = S.bedPart(vehicle)
    if not part then return false, "no part " .. S.BED_PART end
    part:getModData()[S.LEGACY_BED_KEY] = nil
    if on then
        local ok, why = HondaCRVGen1.State.set(vehicle, S.MODE_KEY, mode or S.MODE_BED)
        if not ok then return false, why end
        return HondaCRVGen1.State.set(vehicle, S.FOLD_KEY, true)
    end
    local ok, why = HondaCRVGen1.State.set(vehicle, S.FOLD_KEY, false)
    HondaCRVGen1.State.set(vehicle, S.MODE_KEY, nil)
    return ok, why
end

-- the seats folded into the bed (on) or put back (old name, kept for callers and tests)
function S.setBed(vehicle, on)
    return S.setFold(vehicle, on, S.MODE_BED)
end

-- Putting the seats back, or making up the bed over the load floor, needs the folded load floor empty (what lies
-- there would end up under the seats or the bedding)
function S.canUnfold(vehicle)
    local cargo = vehicle:getPartById(S.CARGO_PART)
    local cont = cargo and cargo:getItemContainer()
    if cont and not cont:isEmpty() then return false, "IGUI_CRV_Function_CargoNotEmpty" end
    return true
end
S.canMakeBed = S.canUnfold

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
