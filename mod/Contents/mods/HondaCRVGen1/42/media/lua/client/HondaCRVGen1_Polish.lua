--[[
Honda CR-V (RD1), polish feature (scripts/features/polish.py): the synthesised B20B engine layer.
Client only: local sound, recomputed on every client from what the game already syncs (engine
running, engine speed or road speed), so nothing needs the server. (The car's paint colour is set on
the authoritative side: server/HondaCRVGen1_PolishServer.lua.)

The vehicle script keeps the game's RPM-reactive VehicleEngineSmallCar event; on top of it every
running CR-V near the player gets two looped clips of our own (CRVGen1EngineLow, recorded at 1800 rpm,
and CRVGen1EngineHigh, 4800 rpm with the light whine), pitched to the engine speed and cross-faded
between 2600 and 3600 rpm. Each plays on a PRIVATE world emitter of its own that follows the car:
FMODSoundEmitter.setPitch (42.21) writes the pitch into every sound of the emitter it is called on, so
pitching on the vehicle's own emitter would bend the vanilla engine and the horn too, and two layers
on one emitter would share one pitch. Engine speed: BaseVehicle:getEngineSpeed() (rpm, the
dashboard's needle); a remote car whose speed reads 0 while running (not synced to every client:
unverified) falls back to an estimate from its road speed. Volume: sandbox PolishEngineVolume
(percent, default 100; 0 = off).

Update rate. The world ticks its emitters every 30 ms (IsoWorld.update), so position, volume and the
rpm smoothing run every UPDATE_MS, not every frame. setPitch writes a General log line ("Set pitch for
Instance") on EVERY call in 42.21 (FMODSoundEmitter.setPitch -> DebugLog.log, on in release builds), so
a layer is re-pitched only while it is heard, only when its pitch moved by more than PITCH_STEP, and at
most every PITCH_MS: idle and a steady cruise log nothing, a rev a few lines a second.
]]

if isServer() then return end

require "HondaCRVGen1_State"

HondaCRVGen1 = HondaCRVGen1 or {}
HondaCRVGen1.Polish = HondaCRVGen1.Polish or {}
local Polish = HondaCRVGen1.Polish
local State = HondaCRVGen1.State

Polish.SCAN = 30               -- ticks between scans of the cell's vehicles
Polish.RANGE = 45              -- tiles: farther cars keep the vanilla engine only
Polish.LOW_RPM, Polish.HIGH_RPM = 1800, 4800
Polish.XFADE = { 2600, 3600 }
Polish.LOW_PITCH = { 0.40, 1.90 }
Polish.HIGH_PITCH = { 0.55, 1.50 }
Polish.IDLE = 800
Polish.BASE_VOLUME = 0.55
Polish.UPDATE_MS = 50          -- position, volume and rpm smoothing (the emitters tick every 30 ms)
Polish.PITCH_MS = 50           -- at most one setPitch per layer this often
Polish.PITCH_STEP = 0.02       -- relative pitch change worth a setPitch (about a third of a semitone)
Polish.SILENT = 0.002          -- a layer this quiet is not re-pitched (it is when it is heard again)
Polish.SMOOTH = 0.25           -- rpm smoothing per 60 Hz frame: the gear changes glide

Polish.cars = {}               -- vehicle -> { emLow, emHigh, low, high, rpm, at, pitch = {}, pitchAt = {} }

local function clamp(x, a, b)
    if x < a then return a end
    if x > b then return b end
    return x
end

function Polish.volumeSetting()
    local sv = SandboxVars and SandboxVars.HondaCRVGen1
    local v = sv and tonumber(sv.PolishEngineVolume)
    if v == nil then v = 100 end
    return clamp(v, 0, 200) / 100
end

--- engine speed in rpm: the engine's own, or an estimate from the road speed when it reads 0
function Polish.rpm(vehicle)
    local r = 0
    if vehicle.getEngineSpeed then r = tonumber(vehicle:getEngineSpeed()) or 0 end
    if r > 100 then return r end
    local kmh = math.abs(tonumber(vehicle:getCurrentSpeedKmHour()) or 0)
    return Polish.IDLE + clamp(kmh * 45, 0, 4800)
end

--- {lowPitch, lowVolume, highPitch, highVolume} for an rpm (pure: tested by scripts/test_polish_lua.py)
function Polish.mix(rpm, master)
    local k = clamp((rpm - Polish.XFADE[1]) / (Polish.XFADE[2] - Polish.XFADE[1]), 0, 1)
    local loud = Polish.BASE_VOLUME * master * (0.45 + 0.55 * clamp((rpm - 700) / 5500, 0, 1))
    return clamp(rpm / Polish.LOW_RPM, Polish.LOW_PITCH[1], Polish.LOW_PITCH[2]), loud * (1 - k),
           clamp(rpm / Polish.HIGH_RPM, Polish.HIGH_PITCH[1], Polish.HIGH_PITCH[2]), loud * k
end

local function now()
    return getTimestampMs and getTimestampMs() or 0
end

function Polish.stop(vehicle)
    local c = Polish.cars[vehicle]
    if not c then return end
    if c.emLow and c.low and c.low ~= 0 then c.emLow:stopSound(c.low) end
    if c.emHigh and c.high and c.high ~= 0 then c.emHigh:stopSound(c.high) end
    Polish.cars[vehicle] = nil
end

-- one private emitter PER LAYER: setPitch pitches every sound of its emitter (42.21)
function Polish.start(vehicle)
    local world = getWorld()
    if not world then return nil end
    local x, y, z = vehicle:getX(), vehicle:getY(), vehicle:getZ()
    local emLow, emHigh = world:getFreeEmitter(x, y, z), world:getFreeEmitter(x, y, z)
    if not emLow or not emHigh or emLow == emHigh then return nil end
    local c = { emLow = emLow, emHigh = emHigh, rpm = Polish.rpm(vehicle), pitch = {}, pitchAt = {} }
    c.low = emLow:playSoundLoopedImpl("CRVGen1EngineLow")
    c.high = emHigh:playSoundLoopedImpl("CRVGen1EngineHigh")
    if not c.low or c.low == 0 or not c.high or c.high == 0 then
        -- a clip that did not start: keep neither (an empty emitter goes back to the world's pool, and
        -- one we kept moving and pitching could be handed to another sound); the next scan retries
        if c.low and c.low ~= 0 then emLow:stopSound(c.low) end
        if c.high and c.high ~= 0 then emHigh:stopSound(c.high) end
        return nil
    end
    emLow:setVolume(c.low, 0)
    emHigh:setVolume(c.high, 0)
    Polish.cars[vehicle] = c
    return c
end

-- re-pitch one layer only when it is heard, its pitch moved by more than PITCH_STEP, and the last
-- setPitch is PITCH_MS old (a layer that was silent is pitched at once, before it is heard)
local function pitchLayer(c, key, em, ref, p, vol, t)
    if vol <= Polish.SILENT then
        c.pitchAt[key] = nil                                     -- not heard: re-pitched when it is
        return
    end
    local last = c.pitch[key]
    if last then
        local r = p / last
        if r < 1 + Polish.PITCH_STEP and r > 1 / (1 + Polish.PITCH_STEP) then return end
        if c.pitchAt[key] and t - c.pitchAt[key] < Polish.PITCH_MS then return end
    end
    em:setPitch(ref, p)
    c.pitch[key], c.pitchAt[key] = p, t
end

function Polish.update(vehicle, c, t)
    t = t or now()
    local dt = c.at and (t - c.at) or (1000 / 60)
    if c.at and dt < Polish.UPDATE_MS then return end
    c.at = t
    local x, y, z = vehicle:getX(), vehicle:getY(), vehicle:getZ()
    c.emLow:setPos(x, y, z)
    c.emHigh:setPos(x, y, z)
    local k = 1 - (1 - Polish.SMOOTH) ^ (clamp(dt, 1, 500) / (1000 / 60))
    c.rpm = c.rpm + (Polish.rpm(vehicle) - c.rpm) * k
    local lp, lv, hp, hv = Polish.mix(c.rpm, Polish.volumeSetting())
    pitchLayer(c, "low", c.emLow, c.low, lp, lv, t)
    pitchLayer(c, "high", c.emHigh, c.high, hp, hv, t)
    c.emLow:setVolume(c.low, lv)
    c.emHigh:setVolume(c.high, hv)
end

local function near(vehicle, player)
    if not player then return false end
    local dx, dy = vehicle:getX() - player:getX(), vehicle:getY() - player:getY()
    return dx * dx + dy * dy <= Polish.RANGE * Polish.RANGE
end

local ticks = 0
function Polish.OnTick()
    ticks = ticks + 1
    if ticks % Polish.SCAN == 0 then
        -- the nearest vehicle to the player (vanilla's own lookup, ISVehicleMenu): the cell's vehicle list
        -- cannot be read here (its get() is nil in the game), and this is the one car whose engine we can hear
        local player = getPlayer()
        local seen = {}
        local v = player and player:getNearVehicle()
        if v and State.isCRV(v) and v:isEngineRunning() and Polish.volumeSetting() > 0 then
            seen[v] = true
            if not Polish.cars[v] then Polish.start(v) end
        end
        for v in pairs(Polish.cars) do
            if not seen[v] then Polish.stop(v) end
        end
    end
    local t = now()
    for v, c in pairs(Polish.cars) do
        local ok = pcall(Polish.update, v, c, t)
        if not ok then Polish.stop(v) end
    end
end

Events.OnTick.Add(Polish.OnTick)
