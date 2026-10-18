-- Where the CR-V turns up in the world. Same pattern as KI5's packs: append to the vanilla
-- zone tables from media/lua/shared/VehicleZoneDefinition.lua. spawnChance is a weight against
-- the other entries in that zone (each vanilla zone sums to about 100; vanilla SUV: medium 5,
-- good 20, professional 20, evacuee 25).
--
-- Roadmap zones (function feature, 2026-10-13): suburbs and driveways (medium, good, middleClass,
-- professional, bad), rural and farms (farm, trailerpark), parking lots (parkingstall), traffic
-- jams (the four trafficjam* zones share one vanilla table), plus the odd wreck in a junkyard.
-- VehicleType.init reads spawnChance as a float and normalises each zone, so scaled weights may be fractions.
--
-- Sandbox option HondaCRVGen1.FunctionSpawnRate (percent, 100 = these weights) scales every entry.
-- SandboxVars are not loaded yet when this file runs; the game reads VehicleZoneDistribution lazily
-- (IsoChunk.AddVehicles -> VehicleType.init, only once the world is up), and OnLoadedMapZones fires
-- after SandboxOptions.load (IsoWorld.init), so the scaled weights are written there.
HondaCRVGen1 = HondaCRVGen1 or {}

HondaCRVGen1.SPAWN_CAR = "Base.HondaCRVGen1"
HondaCRVGen1.SPAWN_ZONES = {
    parkingstall = 6,
    medium = 6,
    good = 10,
    middleClass = 8,
    professional = 6,
    bad = 3,
    evacuee = 8,
    trailerpark = 2,
    farm = 3,
    junkyard = 2,
    trafficjamn = 4,
    trafficjams = 4,
    trafficjame = 4,
    trafficjamw = 4,
}

-- the sandbox percent (0..500), 100 when unset or not a number
function HondaCRVGen1.spawnRate()
    local vars = SandboxVars and SandboxVars.HondaCRVGen1
    local pct = vars and vars.FunctionSpawnRate
    if type(pct) ~= "number" or pct < 0 then return 100 end
    return pct
end

-- write the weights for `pct` percent; 0 takes the CR-V out of every zone. Returns the zones written.
function HondaCRVGen1.applySpawnRate(pct)
    if not VehicleZoneDistribution then return 0 end
    pct = pct or 100
    local n = 0
    for zone, chance in pairs(HondaCRVGen1.SPAWN_ZONES) do
        local z = VehicleZoneDistribution[zone]
        if z and z.vehicles then
            local w = chance * pct / 100
            if w > 0 then
                z.vehicles[HondaCRVGen1.SPAWN_CAR] = { index = -1, spawnChance = w }
            else
                z.vehicles[HondaCRVGen1.SPAWN_CAR] = nil
            end
            n = n + 1
        end
    end
    return n
end

HondaCRVGen1.applySpawnRate(100)

if Events and Events.OnLoadedMapZones then
    Events.OnLoadedMapZones.Add(function()
        HondaCRVGen1.applySpawnRate(HondaCRVGen1.spawnRate())
    end)
end
