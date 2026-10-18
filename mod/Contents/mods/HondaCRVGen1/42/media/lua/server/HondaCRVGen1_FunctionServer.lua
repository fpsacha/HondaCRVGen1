--[[
Honda CR-V (RD1), function feature, authoritative side: the owner's manual in every glove box.

OnSpawnVehicleEnd fires at the end of BaseVehicle.createPhysics, after the parts were created and the
containers filled (randomizeContainers), on whichever side runs it: a multiplayer client creates the
physics of every car it streams in too, so clients return here. createPhysics also runs again for a
loaded car, so the manual is put in once per car: the glove box part's mod data remembers it (saved
with the car), and a manual the owner took out is not put back on reload.
]]

if isClient() then return end

require "HondaCRVGen1_Function"

local F = HondaCRVGen1.Function

F.ROLLED = "crv_function_manualRolled"  -- GloveBox part mod data: the manual has been put in

-- returns true when a manual was put in the glove box
function F.OnSpawnVehicleEnd(vehicle)
    if not vehicle or not HondaCRVGen1.Shared.isCRV(vehicle) then return false end
    local box = vehicle:getPartById("GloveBox")
    local cont = box and box:getItemContainer()
    if not cont then return false end
    local md = box:getModData()
    if md[F.ROLLED] then return false end
    md[F.ROLLED] = true
    cont:AddItem(F.MANUAL)
    return true
end

Events.OnSpawnVehicleEnd.Add(F.OnSpawnVehicleEnd)
