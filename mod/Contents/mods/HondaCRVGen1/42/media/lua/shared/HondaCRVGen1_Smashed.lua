--[[
Honda CR-V (RD1): crash-scene damage for the CR-V's vehicle scripts (H-PLAY-4, 2026-10-24). Our own code.

The game's crash scenes (RVSCarCrash, RVSBase: the random vehicle stories) call BaseVehicle.setSmashed("Front" /
"Left" / "Right"). In 42.21 that reads the Lua table SmashedCarDefinitions.cars[<the car's script name>], takes
the entry's string under the side in lower case ("front", "rear", "left", "right") and its integer "skin" (missing
= -1: keep the car's own skin), and only when it finds a script name there replaces the car with a NEW one of that
script: general part condition setGeneralPartCondition(0.5, 60), the engine at 0 and VehicleEngine.setSmashed(),
the glove box emptied and broken, the key id kept. A script with no entry is left untouched: a CR-V in a crash
scene stood there like new. Vanilla gives each car its own smashed models; the CR-V has none, so every side points
at the same script: the new car is a CR-V of the same kind with the vanilla crash damage, its own paint (no skin
entry) and our damage textures, which follow the part conditions.

Every CR-V script (HondaCRVGen1.State.VEHICLES: the stock car and the lifted ones the generated
HondaCRVGen1_Vehicles.lua registers) gets an entry. Vanilla's shared/Definitions/SmashedCarDefinitions.lua sets
SmashedCarDefinitions.cars = {} when it loads, so the entries are (re)made at load and again at OnGameBoot and
OnInitGlobalModData (after every Lua file is loaded, before the world spawns its stories), never replacing an entry
another mod made.
]]

require "HondaCRVGen1_Vehicles"

HondaCRVGen1 = HondaCRVGen1 or {}
local Smashed = HondaCRVGen1.Smashed or {}
HondaCRVGen1.Smashed = Smashed

Smashed.SIDES = { "front", "rear", "left", "right" }

-- add the CR-V entries to SmashedCarDefinitions.cars; returns how many were added
function Smashed.register()
    local State = HondaCRVGen1.State
    if not State or type(SmashedCarDefinitions) ~= "table" or type(SmashedCarDefinitions.cars) ~= "table" then return 0 end
    local cars = SmashedCarDefinitions.cars
    local n = 0
    for script, on in pairs(State.VEHICLES) do
        if on and cars[script] == nil then
            local e = {}
            for _, side in ipairs(Smashed.SIDES) do e[side] = script end
            cars[script] = e
            n = n + 1
        end
    end
    return n
end

Smashed.register()
Events.OnGameBoot.Add(Smashed.register)
if Events.OnInitGlobalModData then Events.OnInitGlobalModData.Add(Smashed.register) end
