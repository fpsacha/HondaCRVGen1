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
(percent, default 100; 0 = off) times the player's own mod option (Options > Mods, percent, default 100; 0 = off),
held at MAX_MASTER (2x) when both are turned up.
Which cars: the one the player sits in, then the nearest tracked running CR-Vs within RANGE (Polish.candidates).

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

-- the player's own volume for the layer (PZAPI.ModOptions, 42.21 client/PZAPI/ModOptions.lua: Options > Mods):
-- percent, 0 = off, default 100; on top of the server's sandbox PolishEngineVolume
Polish.OPTIONS_ID = "HondaCRVGen1"
Polish.OPTION_VOLUME = "engineVolume"
Polish.options = Polish.options or nil

function Polish.createOptions()
    if Polish.options or not (PZAPI and PZAPI.ModOptions and PZAPI.ModOptions.create) then return Polish.options end
    local opts = PZAPI.ModOptions:getOptions(Polish.OPTIONS_ID)
    if not opts then
        opts = PZAPI.ModOptions:create(Polish.OPTIONS_ID, "UI_CRV_Options_Name")
        opts:addSlider(Polish.OPTION_VOLUME, "UI_CRV_Options_EngineVolume", 0, 200, 10, 100)
        opts:addDescription("UI_CRV_Options_EngineVolume_Info")
    end
    Polish.options = opts
    return opts
end

-- 0..2 (1 = the recorded level); 1 without the options API or before the options exist
function Polish.clientVolume()
    local opts = Polish.options
    local opt = opts and opts.getOption and opts:getOption(Polish.OPTION_VOLUME)
    local v = opt and tonumber(opt:getValue())
    if v == nil then return 1 end
    return clamp(v, 0, 200) / 100
end

Polish.MAX_MASTER = 2.0       -- the layer's loudest: twice the recorded level, whatever the two settings multiply to

-- sandbox x player option, 0..MAX_MASTER: each goes to 200 %, and their product (up to 4x) is held at 2x (R2-AUD-1)
function Polish.volumeSetting()
    local sv = SandboxVars and SandboxVars.HondaCRVGen1
    local v = sv and tonumber(sv.PolishEngineVolume)
    if v == nil then v = 100 end
    return clamp(clamp(v, 0, 200) / 100 * Polish.clientVolume(), 0, Polish.MAX_MASTER)
end

-- the options file is read when the options screen builds its mod panel; read it at the start of a game too, so the
-- saved value counts before anyone opens the options
function Polish.OnGameStart()
    Polish.createOptions()
    if Polish.options and PZAPI.ModOptions.load then pcall(PZAPI.ModOptions.load, PZAPI.ModOptions) end
end

Polish.createOptions()                     -- PZAPI loads after this file (sorted paths): OnGameBoot, below
Events.OnGameBoot.Add(Polish.createOptions)
Events.OnGameStart.Add(Polish.OnGameStart)

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
    master = clamp(tonumber(master) or 0, 0, Polish.MAX_MASTER)
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
    -- (perf 2026-10-24) the emitters move only when the car did, and a volume is set only when it changed: an
    -- emitter keeps its position and a sound its volume (an idling car sends nothing on most updates)
    local x, y, z = vehicle:getX(), vehicle:getY(), vehicle:getZ()
    if x ~= c.x or y ~= c.y or z ~= c.z then
        c.emLow:setPos(x, y, z)
        c.emHigh:setPos(x, y, z)
        c.x, c.y, c.z = x, y, z
    end
    local k = 1 - (1 - Polish.SMOOTH) ^ (clamp(dt, 1, 500) / (1000 / 60))
    c.rpm = c.rpm + (Polish.rpm(vehicle) - c.rpm) * k
    local lp, lv, hp, hv = Polish.mix(c.rpm, Polish.volumeSetting())
    pitchLayer(c, "low", c.emLow, c.low, lp, lv, t)
    pitchLayer(c, "high", c.emHigh, c.high, hp, hv, t)
    if lv ~= c.lv then
        c.emLow:setVolume(c.low, lv)
        c.lv = lv
    end
    if hv ~= c.hv then
        c.emHigh:setVolume(c.high, hv)
        c.hv = hv
    end
end

local function dist2(vehicle, player)
    local dx, dy = vehicle:getX() - player:getX(), vehicle:getY() - player:getY()
    return dx * dx + dy * dy
end

Polish.MAX_CARS = 3            -- the nearest running CR-Vs that get the layer (the player's own first)

-- the running CR-Vs the player hears, nearest first: the car the player sits in, then every CR-V this client tracks
-- (HondaCRVGen1.State.tracked: each CR-V drawn here, pruned when it leaves the world) within RANGE. Not
-- IsoPlayer.getNearVehicle: 42.21 returns nil while the player is IN a vehicle, and otherwise only a car within
-- 4 tiles the player faces; the cell's vehicle list cannot be read here either (its get() is nil in the game)
function Polish.candidates(player)
    local list = {}
    if not player then return list end
    local own = player:getVehicle()
    if own and State.isCRV(own) and own:isEngineRunning() then list[1] = { v = own, d = -1 } end
    local r2 = Polish.RANGE * Polish.RANGE
    for _, e in pairs(State.tracked) do
        local v = e.vehicle
        if v and v ~= own and not v:isRemovedFromWorld() and v:isEngineRunning() and State.isCRV(v) then
            local d = dist2(v, player)
            if d <= r2 then list[#list + 1] = { v = v, d = d } end
        end
    end
    table.sort(list, function(a, b) return a.d < b.d end)
    local out = {}
    for i = 1, math.min(#list, Polish.MAX_CARS) do out[i] = list[i].v end
    return out
end

-- every CR-V the client creates or streams in (BaseVehicle.createPhysics ends with OnSpawnVehicleEnd on every side)
-- is tracked, whether or not a feature's part init has run for it yet
function Polish.OnSpawnVehicleEnd(vehicle)
    if vehicle and State.isCRV(vehicle) then State.track(vehicle) end
end
Events.OnSpawnVehicleEnd.Add(Polish.OnSpawnVehicleEnd)

local ticks = 0
function Polish.OnTick()
    ticks = ticks + 1
    if ticks % Polish.SCAN == 0 then
        local player = getPlayer()
        local seen = {}
        if Polish.volumeSetting() > 0 then
            for _, v in ipairs(Polish.candidates(player)) do
                seen[v] = true
                if not Polish.cars[v] then Polish.start(v) end
            end
        end
        for v in pairs(Polish.cars) do
            if not seen[v] then Polish.stop(v) end
        end
    end
    local t = nil
    for v, c in pairs(Polish.cars) do
        t = t or now()
        if not (c.at and t - c.at < Polish.UPDATE_MS) then  -- (Polish.update's own gate, before the pcall)
            local ok = pcall(Polish.update, v, c, t)
            if not ok then Polish.stop(v) end
        end
    end
end

Events.OnTick.Add(Polish.OnTick)
