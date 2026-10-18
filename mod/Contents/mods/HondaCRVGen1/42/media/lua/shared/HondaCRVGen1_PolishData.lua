--[[
Honda CR-V (RD1), polish feature: data the polish Lua reads.

SKIN_HSV: each skin's paint as hue, saturation, value (0..1), in the vehicle script's skin order (the
script's skin index + 1): the median of the door paint on the shipped Shell sheets, measured by
scripts/features/polish.py (its COMPOSE warns when a rebuilt skin moved away from these numbers).
server/HondaCRVGen1_PolishServer.lua makes it each CR-V's paint colour (instead of the game's random
one) on the authoritative side: the colour the game tints the car's keys with, and what any other code
reading the car's colour sees. The damage shader takes the dent hue from the skin's texel itself
(vehicle_crvgen1_norandom), so this table is not what colours the dents. Order: Electron Blue
(default), Taffeta White, Nighthawk Black, Milano Red, Supermarine Blue, Clover Green, Sebring Silver,
Naples Gold.
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
    { 0.167, 0.009, 0.322 },
    { 0.106, 0.135, 0.4 },
}
