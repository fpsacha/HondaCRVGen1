--[[
Honda CR-V (RD1): the cabin is always drawn. Our own code.

The interior shell (model Interior: floor, firewall, door cards, headliner, pillars) and the cabin furniture
(model InteriorCabin: dash, wheel, seats, tray) used to be models of the template's part GloveBox. That part has
an item, and the engine shows or hides every model of a part with its item (VehiclePart.setInventoryItem ->
setAllModelsVisible): taking the glove box out hid the whole interior, and a car spawned without a glove box had
none. Part CRVCabin (scripts/gen_scripts.py, cabin_part) carries them now. It has no item, so no install or
uninstall touches it, and its script sets setAllModelsVisible = false, so the engine never shows or resets its
models on its own (BaseVehicle.setModelVisible is reached only through setInventoryItem and Lua): Cabin.Init
shows both on the part's init, which runs on every side for every car created, loaded, streamed in or
re-scripted (BaseVehicle.createPhysics -> VehicleParts.initParts). Model visibility is neither saved nor sent,
so each side that draws the car does this itself; a dedicated server draws nothing and skips it.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
local Cabin = HondaCRVGen1.Cabin or {}
HondaCRVGen1.Cabin = Cabin

Cabin.PART = "CRVCabin"
Cabin.MODELS = { "Interior", "InteriorCabin" }

-- show every cabin model of this car (idempotent: the part's models were just (re)made, or already shown)
function Cabin.show(vehicle)
    if isServer() or not vehicle then return false end
    local part = vehicle:getPartById(Cabin.PART)
    if not part then return false end
    for _, m in ipairs(Cabin.MODELS) do
        part:setModelVisible(m, true)
    end
    return true
end

-- part init (CRVCabin, every side)
function Cabin.Init(vehicle, part)
    Cabin.show(vehicle)
    if HondaCRVGen1.Power then HondaCRVGen1.Power.fix(vehicle) end   -- pre-0.4.2 saves (HondaCRVGen1_Power.lua)
end
