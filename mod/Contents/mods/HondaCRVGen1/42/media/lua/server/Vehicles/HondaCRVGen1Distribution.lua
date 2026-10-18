-- Loot for the CR-V's containers (glove box, trunk, seats). Vehicles are looked up in
-- VehicleDistributions[1] by script name without the module; an unregistered vehicle spawns with
-- empty containers. Same pattern as KI5's packs; we reuse the vanilla SUV's tables.
--
-- Function feature (2026-10-13): the CR-V gets its own copy of the SUV's table (Normal and every
-- Specific room, one level deep) with one container added, the hidden under-floor storage
-- (part CRVFunctionUnderfloor): what an owner keeps under the cargo floor. The vanilla tables are
-- shared by many vehicles, so they are copied, never changed. The folded load floor
-- (CRVFunctionCargo) gets nothing: every car spawns with its seats up.
-- The lifted car (a second vehicle script) is only ever made by converting a CR-V in place, and
-- the conversion moves the contents across, so it is deliberately left without a table here.
require "Vehicles/VehicleDistributions"

HondaCRVGen1 = HondaCRVGen1 or {}

HondaCRVGen1.UNDERFLOOR_LOOT = {
    rolls = 1,
    items = {
        "LugWrench", 8,
        "Jack", 4,
        "TirePump", 6,
        "DuctTape", 4,
        "Torch", 4,
        "Bandage", 4,
        "Rope", 3,
        "Screwdriver", 3,
        "Wrench", 2,
        "WaterBottle", 2,
        "Tarp", 2,
        "FirstAidKit", 1,
    },
}

local function withUnderfloor(room)
    local out = {}
    for k, v in pairs(room) do out[k] = v end
    out.CRVFunctionUnderfloor = HondaCRVGen1.UNDERFLOOR_LOOT
    return out
end

local distributionTable = VehicleDistributions and VehicleDistributions[1]
if distributionTable and distributionTable.SUV then
    local suv = distributionTable.SUV
    local own = { Normal = suv.Normal and withUnderfloor(suv.Normal) }
    if suv.Specific then
        own.Specific = {}
        for i, room in ipairs(suv.Specific) do own.Specific[i] = withUnderfloor(room) end
    end
    for k, v in pairs(suv) do
        if own[k] == nil then own[k] = v end
    end
    distributionTable["HondaCRVGen1"] = own
end
