--[[
Honda CR-V (RD1), polish feature: data the polish Lua reads.

SKIN_HSV: each CR-V skin's paint as hue, saturation, value (0..1), in the vehicle script's skin order:
the median of the door paint on the shipped Shell sheets, measured by
scripts/features/polish.py (its COMPOSE warns when a rebuilt skin moved away from these numbers).
server/HondaCRVGen1_PolishServer.lua makes it each CR-V's paint colour (instead of the game's random
one) on the authoritative side: the colour the game tints the car's keys with, and what any other code
reading the car's colour sees. The damage shader takes the dent hue from the skin's texel itself
(vehicle_crvgen1_norandom), so this table is not what colours the dents. Order: Electron Blue
(default), Taffeta White, Nighthawk Black, Milano Red, Supermarine Blue, Clover Green, Sebring Silver,
Naples Gold.

Our skins are the LAST #SKIN_HSV of the script's skins, not all of them: `template! = SUV` loads the
vanilla SUV template's body first (VehicleScript.Load reads the block's elements in order, 42.21
bytecode), and that body has a skin of its own (`texture = Vehicles/vehicle_suvshell`), so the game
lists 9 skins and skin 0 is the vanilla SUV's sheet. createPhysics gives a new car Rand.Next(9): one CR-V
in nine was drawn with the SUV's sheet on our UVs (the "first spawn had broken textures, a mosaic of
triangles" report, 2026-10-22). Polish.firstSkin(vehicle) finds where ours start from the script's skin
count, so it stays right if the template's skin ever goes away.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
HondaCRVGen1.Polish = HondaCRVGen1.Polish or {}

HondaCRVGen1.Polish.SKIN_HSV = {
    { 0.657, 0.575, 0.435 },
    { 0.208, 0.029, 0.525 },
    { 0.646, 0.14, 0.196 },
    { 0.982, 0.776, 0.478 },
    { 0.591, 0.67, 0.365 },
    { 0.428, 0.842, 0.275 },
    { 0.556, 0.017, 0.447 },
    { 0.106, 0.135, 0.4 },
}

--- the game's skin index of our first skin (the script's skins before it are a template's, never ours)
function HondaCRVGen1.Polish.firstSkin(vehicle)
    local ok, n = pcall(function() return vehicle:getScript():getSkinCount() end)
    local own = #HondaCRVGen1.Polish.SKIN_HSV
    if not ok or type(n) ~= "number" or n < own then return 0 end
    return n - own
end

--- our skin's paint HSV for the car's skin index, nil when the index is not one of ours
function HondaCRVGen1.Polish.skinHSV(vehicle)
    local idx = vehicle:getSkinIndex()
    if type(idx) ~= "number" then return nil end
    return HondaCRVGen1.Polish.SKIN_HSV[idx - HondaCRVGen1.Polish.firstSkin(vehicle) + 1]
end
