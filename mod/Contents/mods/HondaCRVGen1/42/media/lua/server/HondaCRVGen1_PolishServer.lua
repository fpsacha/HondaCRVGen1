--[[
Honda CR-V (RD1), polish feature, authoritative side: each CR-V's paint colour is its skin's.

The game gives every car a random hue / saturation / value (BaseVehicle.doVehicleColor); our skins are
painted sheets, so that colour is wrong for a CR-V wherever the game still uses it: the colour of the
car's keys (createVehicleKey tints the key with it), the debug colour dialog, other mods reading the
car's colour. The damage shader no longer reads it (vehicle_crvgen1_norandom takes the dent hue from the
skin's own texel, gen_shaders.py), so nothing on screen flickers with it any more.

Set where the car's state is owned, single player or the server, never by a client: a client that
wrote it locally was overwritten by every VehicleProperties packet (key in the ignition, blood from a
zombie hit, rust...), which carries the server's colour. OnSpawnVehicleEnd fires at the end of
BaseVehicle.createPhysics (after the skin index is chosen) for a new car and again for every car
loaded from the save, so old saves are corrected the first time a car loads; the colour is saved with
the car and transmitColorHSV (updateFlags 4096) sends it to every client in range (a client that
streams the car in later gets it with the car's full update). transmitColorHSV does nothing outside a
server. Skin HSV table: shared/HondaCRVGen1_PolishData.lua.

The same place keeps every CR-V on one of OUR skins (ensureOwnSkin): the script inherits the vanilla
SUV's skin from `template! = SUV`, and a car given that one was drawn with the SUV's sheet on our UVs.
A saved car already on it is moved to one of ours the first time it loads.
]]

if isClient() then return end

require "HondaCRVGen1_State"
require "HondaCRVGen1_PolishData"

HondaCRVGen1 = HondaCRVGen1 or {}
HondaCRVGen1.Polish = HondaCRVGen1.Polish or {}
local Polish = HondaCRVGen1.Polish
local State = HondaCRVGen1.State

Polish.PAINT_EPS = 0.002

--- one of our skins on the car: a car on a skin that is not ours (the vanilla SUV template's sheet,
--- skin 0, which createPhysics' Rand.Next(getSkinCount()) picks for one new car in nine: see
--- HondaCRVGen1_PolishData.lua) gets one of ours at random. updateSkin rebinds an already-built model
--- (single player); transmitSkinIndex (updateFlags 4096) sends it, and each client's
--- VehicleProperties.parse runs setSkinIndex + updateSkin. Returns true when it changed the skin
function Polish.ensureOwnSkin(vehicle)
    if Polish.skinHSV(vehicle) then return false end
    vehicle:setSkinIndex(Polish.firstSkin(vehicle) + ZombRand(#Polish.SKIN_HSV))
    pcall(function() vehicle:updateSkin() end)
    vehicle:transmitSkinIndex()
    return true
end

--- the skin's paint HSV on the car, transmitted; returns true when it changed anything
function Polish.applyPaint(vehicle)
    if not vehicle or not State.isCRV(vehicle) then return false end
    local reskinned = Polish.ensureOwnSkin(vehicle)
    local hsv = Polish.skinHSV(vehicle)
    if not hsv then return reskinned end
    local e = Polish.PAINT_EPS
    if math.abs((vehicle:getColorHue() or 0) - hsv[1]) <= e and math.abs((vehicle:getColorSaturation() or 0) - hsv[2]) <= e
            and math.abs((vehicle:getColorValue() or 0) - hsv[3]) <= e then
        return reskinned
    end
    vehicle:setColorHSV(hsv[1], hsv[2], hsv[3])
    vehicle:transmitColorHSV()
    return true
end

function Polish.OnSpawnVehicleEnd(vehicle)
    local ok, err = pcall(Polish.applyPaint, vehicle)
    if not ok then print("[HondaCRVGen1] polish paint: " .. tostring(err)) end
end

Events.OnSpawnVehicleEnd.Add(Polish.OnSpawnVehicleEnd)
