--[[
Honda CR-V (RD1): engine power for cars saved before 0.4.2. Our own code.

0.4.2 halved the scripts' mass to KI5's scale (stock 950 -> 700, lifted 990 -> 740: the game adds every part's
and the cargo's weight on top, and Bullet's 6000 N per-wheel force cap let a loaded car bottom out) and lowered
engineForce to match (stock 4800 -> 3850, lifted 4500 -> 3640). A car's engine power is set once, when it is
created (vanilla Vehicles.Create.Engine: engineForce x max(0.6, min(1, quality x 1.6 / 100)), or engineForce
itself under the sandbox's VehicleEasyUse) and saved with the car, so a car made before would keep the old,
higher power on the lighter body and pull about 25 % harder.

Power.fix recomputes the power the car would have been given under its current script from its saved engine
quality, and lowers the power to it when it is higher. A new car already has exactly that power, so nothing
changes for it; running it again changes nothing; it never raises a power. It runs where the game is
authoritative (single player, the server), from the CRVCabin part's init (HondaCRVGen1_Cabin.lua), which runs
for every car created, loaded or streamed in.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
local Power = HondaCRVGen1.Power or {}
HondaCRVGen1.Power = Power

-- the power vanilla Vehicles.Create.Engine would give this car under its current script
function Power.expected(vehicle)
    local ok, force = pcall(function() return vehicle:getScript():getEngineForce() end)
    if not ok or not force or force <= 0 then return nil end
    if SandboxVars and SandboxVars.VehicleEasyUse then return force end
    local quality = vehicle:getEngineQuality() or 100
    local boosted = math.min(quality * 1.6, 100)
    return force * math.max(0.6, boosted / 100)
end

-- lower a power left over from the old, heavier tuning; returns true when it changed
function Power.fix(vehicle)
    if not vehicle or isClient() then return false end
    local want = Power.expected(vehicle)
    local have = vehicle:getEnginePower()
    if not want or not have or have <= want * 1.02 + 1 then return false end
    vehicle:setEngineFeature(vehicle:getEngineQuality(), vehicle:getEngineLoudness(), math.floor(want + 0.5))
    return true
end
