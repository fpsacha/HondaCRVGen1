"""
The polish feature's Lua under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1), on scripts/lua_harness.py:
the synthesised engine layer (private emitter, pitch / cross-fade from the engine speed, the road-speed
fallback, stop when the engine stops or the car leaves, the sandbox volume, setPitch only when the pitch
moved and at most PITCH_MS apart: 42.21 logs a line per call), each CR-V's paint HSV set from its skin on
the authoritative side and transmitted (never by a client), the Project Viewpoint pack registration, and
the multiplayer split.

    python scripts\\test_polish_lua.py
"""
import sys

from lua_harness import Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
POLISH = ("shared/HondaCRVGen1_PolishData.lua", "server/HondaCRVGen1_PolishServer.lua",
          "client/HondaCRVGen1_Polish.lua", "client/HondaCRVGen1_PolishViewpoint.lua")

# what the polish Lua calls beyond the harness: the cell's vehicle list, the world's free emitters,
# the local player, the clock, and the BaseVehicle / BaseSoundEmitter methods it uses
FAKES = r'''
HondaCRVGen1.State.registerVehicle("Base.HondaCRVGen1")
EMITTERS = {}
Emit = {}
Emit.__index = Emit
local nextId = 0
FAIL_PLAY = false                 -- playSoundLoopedImpl returns 0 (a clip that cannot start)
function newEmitter(x, y, z)
    local e = setmetatable({ x = x, y = y, z = z, sounds = {}, pitchCalls = 0 }, Emit)
    EMITTERS[#EMITTERS + 1] = e
    return e
end
function Emit:playSoundLoopedImpl(name)
    if FAIL_PLAY then return 0 end
    nextId = nextId + 1
    self.sounds[nextId] = { name = name, pitch = 1, volume = 1, playing = true }
    return nextId
end
function Emit:stopSound(id) if self.sounds[id] then self.sounds[id].playing = false end return 0 end
-- 42.21 FMODSoundEmitter.setPitch: the pitch lands on EVERY sound of the emitter, and every call whose
-- ref matches a sound writes a "Set pitch for Instance" line to the General log
LOGGED = 0
function Emit:setPitch(id, p)
    self.pitchCalls = self.pitchCalls + 1
    for ref, s in pairs(self.sounds) do
        s.pitch = p
        if ref == id then LOGGED = LOGGED + 1 end
    end
end
function Emit:setVolume(id, v) if self.sounds[id] then self.sounds[id].volume = v end end
function Emit:setPos(x, y, z) self.x, self.y, self.z = x, y, z end
WORLD = {}
function WORLD:getFreeEmitter(x, y, z) return newEmitter(x, y, z) end
function getWorld() return WORLD end
CELL_LIST = {}
local List = {}
List.__index = List
function List:size() return #CELL_LIST end
function List:get(i) return CELL_LIST[i + 1] end
CELL = { list = setmetatable({}, List) }
function CELL:getVehicles() return self.list end
function getCell() return CELL end
LOCAL = newPlayer(PLAYER_NAME or "me", 100, 100)
function getPlayer() return LOCAL end
-- 42.21 IsoPlayer.getNearVehicle, its rules (bytecode): null while the player is IN a vehicle; otherwise the
-- nearest car closer than 4 tiles (DistToSquared < 16) that the player FACES (a line along the forward direction,
-- PolygonalMap2.intersectLineWithVehicle). FACING = false: the player has turned away
FACING = true
function LOCAL:getNearVehicle()
    if self:getVehicle() ~= nil then return nil end
    if not FACING then return nil end
    local best, bd = nil, 16
    for _, v in ipairs(CELL_LIST) do
        local dx, dy = v:getX() - self:getX(), v:getY() - self:getY()
        if dx * dx + dy * dy < bd then best, bd = v, dx * dx + dy * dy end
    end
    return best
end
-- the clock: 60 frames a second
NOW = 1000000
function getTimestampMs() return NOW end
local tick0 = TICK
function TICK(n) for i = 1, (n or 1) do NOW = NOW + 1000 / 60; tick0(1) end end
function Veh:getZ() return 0 end
function Veh:isEngineRunning() return self.engine == true end
function Veh:getEngineSpeed() return self.rpm or 0 end
function Veh:getCurrentSpeedKmHour() return self.kmh or 0 end
-- BaseVehicle.getTransmissionNumber: the TransmissionNumber index (R -1, N 0, Speed1.. 1..)
function Veh:getTransmissionNumber() return self.gear or 0 end
-- 42.21 CarController.control_Reverse(kmh) on the engine speed, one 60 Hz frame (GameTime multiplier / 0.8 = 1):
-- toward 50 x kmh at most 100 rpm a frame down, toward 7000 at 0.02 (Speed Demon 0.06) of the gap up; the gear is R
function reverseFrame(car, demon)
    local e, s = car.rpm or 0, 1.5 * (car.kmh or 0)
    car.gear = -1
    e = e - math.min(0.5 * (e - 1000 * s / 30), 100)
    e = e - math.min((demon and 0.06 or 0.02) * (e - 7000), 30 - s)
    car.rpm = e
end
function Veh:getSkinIndex() return self.skin or 0 end
-- the game's skin list: `template! = SUV` loads the vanilla SUV template's skin first, then our 8
-- (VehicleScript.Load reads elements in order, 42.21), so 9 skins and skin 0 = vehicle_suvshell
SKIN_COUNT = 9
function Veh:getScript()
    return { getSkinCount = function() return SKIN_COUNT end }
end
-- BaseVehicle.setSkinIndex: ignored below 0 or above the count
function Veh:setSkinIndex(i) if i >= 0 and i <= SKIN_COUNT then self.skin = i; self.skinSets = (self.skinSets or 0) + 1 end end
function Veh:updateSkin() self.skinUpdates = (self.skinUpdates or 0) + 1 end
function Veh:transmitSkinIndex() SENT.skin = (SENT.skin or 0) + 1 end
function Veh:getColorHue() return self.h end
function Veh:getColorSaturation() return self.s end
function Veh:getColorValue() return self.v end
function Veh:setColorHSV(h, s, v) self.h, self.s, self.v = h, s, v; self.colourSets = (self.colourSets or 0) + 1 end
-- BaseVehicle.transmitColorHSV: updateFlags 4096 on a server only (the next VehicleUpdatePacket)
function Veh:transmitColorHSV()
    SENT.colour = (SENT.colour or 0) + 1
end
function Veh:getEmitter() self.vemit = self.vemit or newEmitter(0, 0, 0); return self.vemit end
-- doVehicleColor's random paint (BaseVehicle.setScript): what every car has before anyone sets it
function addCar(id, skin, script)
    local v = newVehicle(id, {}, script)
    v.skin = skin
    v.h, v.s, v.v = 0.3, 0.9, 0.6
    CELL_LIST[#CELL_LIST + 1] = v
    return v
end
-- BaseVehicle.createPhysics ends with OnSpawnVehicleEnd on every side (a new car, a loaded car, a
-- car a multiplayer client streams in)
function spawnCar(id, skin, script)
    local v = addCar(id, skin, script)
    triggerEvent("OnSpawnVehicleEnd", v)
    return v
end
-- the car leaves the world (streamed out or removed: BaseVehicle.removeFromWorld sets removedFromWorld)
function removeCar(v)
    for i = #CELL_LIST, 1, -1 do if CELL_LIST[i] == v then table.remove(CELL_LIST, i) end end
    v.removed = true
end
-- 42.21 PZAPI.ModOptions (client/PZAPI/ModOptions.lua), the part the mod uses: create, getOptions, addSlider,
-- addDescription, getOption, getValue, load (reads ModOptions.ini: MODOPTIONS_FILE here)
MODOPTIONS_FILE = {}
function makeModOptionsApi()
    local Options = {}
    Options.__index = Options
    local api = { Dict = {}, Data = {} }
    function api:create(id, name)
        local o = setmetatable({ id = id, name = name, data = {}, dict = {} }, Options)
        table.insert(self.Data, o); self.Dict[id] = o
        return o
    end
    function api:getOptions(id) return self.Dict[id] end
    function api:load()
        for id, vals in pairs(MODOPTIONS_FILE) do
            local o = self.Dict[id]
            if o then for k, v in pairs(vals) do if o.dict[k] then o.dict[k].value = v end end end
        end
    end
    function Options:addSlider(id, name, min, max, step, value)
        local opt = { type = "slider", id = id, name = name, min = min, max = max, step = step, value = value }
        function opt:getValue() return self.value end
        table.insert(self.data, opt); self.dict[id] = opt
        return opt
    end
    function Options:addDescription(text) table.insert(self.data, { type = "description", text = text }) end
    function Options:getOption(id) return self.dict[id] end
    return api
end
'''


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)


def side(role, net=None, player=None):
    s = Side(role, net, player=player) if role != "sp" else Side("sp")
    s.load(*STATE)
    s.run("PLAYER_NAME = %r" % (player or "me"))
    s.run(FAKES)
    s.load(*POLISH)
    return s


def sounds(s):
    """[(name, pitch, volume, playing)] over every emitter but the vehicles' own."""
    return s.eval("""(function()
        local out = {}
        for _, e in ipairs(EMITTERS) do
            for _, snd in pairs(e.sounds) do out[#out + 1] = { snd.name, snd.pitch, snd.volume, snd.playing } end
        end
        return out end)()""")


def playing(s):
    return sorted(str(t[1]) for t in sounds(s).values() if t[4])


def layer(s, name):
    """(pitch, volume) of the playing layer `name`."""
    for t in sounds(s).values():
        if t[4] and str(t[1]) == name:
            return t[2], t[3]
    return None


def sp_tests():
    s = side("sp")
    s.run("car = spawnCar(1, 4)")                        # Milano Red (game skin 4: the SUV template's is 0)
    h, sat, v = s.eval("car.h"), s.eval("car.s"), s.eval("car.v")
    check(abs(h - 0.982) < 1e-6 and abs(sat - 0.776) < 1e-6 and abs(v - 0.478) < 1e-6, "red skin paint HSV at spawn (got %s %s %s)" % (h, sat, v))
    s.run("TICK(60); triggerEvent('OnSpawnVehicleEnd', car)")   # a reload: createPhysics again
    check(s.eval("car.colourSets") == 1, "paint set once, not again on a reload or by the client half")
    check(s.eval("car.skinSets") is None, "one of our skins: the skin is left alone")
    check(playing(s) == [], "engine off: no layer")
    # engine on at idle
    s.run("car.engine = true; car.rpm = 820; TICK(30)")
    check(playing(s) == ["CRVGen1EngineHigh", "CRVGen1EngineLow"], "engine on: both layers (%s)" % playing(s))
    check(s.eval("car.vemit == nil or car.vemit.pitchCalls == 0"), "the vehicle's own emitter is never pitched")
    s.run("TICK(40)")                                    # let the smoothing settle
    lp, lv, hp, hv = (s.eval("({HondaCRVGen1.Polish.mix(820, 1)})[%d]" % i) for i in (1, 2, 3, 4))
    check(abs(lp - 820 / 1800.0) < 1e-6 and hv == 0 and lv > 0, "idle: low layer only, pitch 0.456 (%s %s %s %s)" % (lp, lv, hp, hv))
    vols = {str(t[1]): t[3] for t in sounds(s).values() if t[4]}
    check(vols["CRVGen1EngineHigh"] == 0 and vols["CRVGen1EngineLow"] > 0, "idle volumes %s" % vols)
    # every sound of the private emitter carries the last pitch set (the 42.21 setPitch); our two loops
    # are on emitters of their own, and the low one sits on its idle pitch
    pl, _vl = layer(s, "CRVGen1EngineLow")
    check(abs(pl / lp - 1) < 0.025, "the low layer's pitch follows the idle rpm (%s vs %s)" % (pl, lp))
    # high revs
    s.run("car.rpm = 6000; TICK(60)")
    vols = {str(t[1]): t[3] for t in sounds(s).values() if t[4]}
    check(vols["CRVGen1EngineLow"] < 1e-3 and vols["CRVGen1EngineHigh"] > 0.3, "6000 rpm: the high layer (%s)" % vols)
    hp = s.eval("({HondaCRVGen1.Polish.mix(6000, 1)})[3]")
    check(abs(hp - 1.25) < 1e-6, "high pitch at 6000 rpm %s" % hp)
    ph, _vh = layer(s, "CRVGen1EngineHigh")
    check(abs(ph / hp - 1) < 0.025, "the high layer's pitch follows 6000 rpm (%s vs %s)" % (ph, hp))
    # engine speed 0 while running (a remote car): road speed fallback
    check(abs(s.eval("(function() car.rpm = 0; car.kmh = 60; return HondaCRVGen1.Polish.rpm(car) end)()") - (800 + 2700)) < 1e-6,
          "road-speed fallback")
    # the emitter follows the car
    s.run("car.x = 110; car.y = 95; TICK(6)")
    check(s.eval("EMITTERS[#EMITTERS].x") == 110, "emitter follows the car")
    # engine off: stopped
    s.run("car.engine = false; TICK(30)")
    check(playing(s) == [], "engine off: layers stopped")
    # too far away: none; back near: again
    s.run("car.engine = true; car.x = 300; TICK(30)")
    check(playing(s) == [], "car 200 tiles away: no layer")
    s.run("car.x = 105; TICK(30)")
    check(len(playing(s)) == 2, "back in range")
    # the car leaves the cell
    s.run("removeCar(car); TICK(30)")
    check(playing(s) == [], "car gone from the cell: stopped")
    # sandbox volume 0 = off, 200 = double
    s.run("SandboxVars = { HondaCRVGen1 = { PolishEngineVolume = 0 } }; car2 = spawnCar(2, 0); car2.engine = true; TICK(30)")
    check(playing(s) == [], "PolishEngineVolume 0: off")
    s.run("SandboxVars.HondaCRVGen1.PolishEngineVolume = 200; TICK(30)")
    check(len(playing(s)) == 2 and abs(s.eval("HondaCRVGen1.Polish.volumeSetting()") - 2) < 1e-9, "volume 200 %%")
    # not a CR-V: untouched
    s.run("other = spawnCar(3, 0, 'Base.SmallCar'); other.x = 150; other.engine = true; TICK(30)")
    check(s.eval("other.colourSets") is None and len(playing(s)) == 2, "another car (50 tiles off): no paint, no layer")
    # a skin index that is not ours (out of the table): moved to one of ours and painted, no error
    s.run("odd = spawnCar(4, 12); TICK(30)")
    check(1 <= s.eval("odd.skin") <= 8 and s.eval("odd.colourSets") == 1, "unknown skin: one of ours, painted")
    print("POLISH SP: paint HSV per skin at spawn, engine layer start / pitch / cross-fade / fallback / stop, range, "
          "volume option, other cars: ok")
    skin_tests(s)


def skin_tests(s):
    """The first-spawn texture report (2026-10-22): skin 0 is the vanilla SUV template's sheet, which
    Rand.Next(9) gave one new CR-V in nine. Every such car moves to one of our 8 skins, at random, on the
    authoritative side, and is painted as that skin."""
    s.run("SENT.skin = 0; seen = {}; for i = 1, 400 do local c = spawnCar(100 + i, 0); seen[c.skin] = (seen[c.skin] or 0) + 1 end")
    hist = {int(k): int(v) for k, v in s.eval("seen").items()}
    check(set(hist) == set(range(1, 9)), "skin 0 is replaced by each of our 8 skins (got %s)" % hist)
    check(s.eval("SENT.skin") == 400, "each replacement is transmitted")
    s.run("c0 = spawnCar(600, 0)")
    check(s.eval("c0.skinUpdates") == 1, "the model is rebound to the new skin (updateSkin)")
    k = s.eval("c0.skin")
    hsv = [s.eval("HondaCRVGen1.Polish.SKIN_HSV[%d][%d]" % (k, j)) for j in (1, 2, 3)]
    check(all(abs(a - b) < 1e-6 for a, b in zip(hsv, (s.eval("c0.h"), s.eval("c0.s"), s.eval("c0.v"))))
          and s.eval("c0.colourSets") == 1, "painted as the skin it was moved to")
    s.run("triggerEvent('OnSpawnVehicleEnd', c0)")      # loaded again: kept
    check(s.eval("c0.skin") == k and s.eval("c0.skinSets") == 1, "a car on one of ours keeps it on every later load")
    # without the template's skin (8 skins, a future script): skin 0 is ours (Electron Blue) and kept
    s.run("SKIN_COUNT = 8; c8 = spawnCar(700, 0); SKIN_COUNT = 9")
    check(s.eval("c8.skin") == 0 and s.eval("c8.skinSets") is None and abs(s.eval("c8.h") - 0.657) < 1e-6,
          "8 skins: skin 0 is ours, kept and painted Electron Blue")
    print("POLISH skins: the SUV template's skin is never drawn (moved to ours, transmitted, rebound): ok")


def viewpoint_tests():
    s = side("sp")
    # Viewpoint: nothing without it; registered once with it
    check(s.eval("HondaCRVGen1.Polish.viewpointRegistered") is False, "no Viewpoint: not registered")
    s.run("""REG = {}
             Viewpoint = { ModelPacks = { register = function(mod, manifest) REG[#REG + 1] = mod .. '|' .. manifest; return true end } }
             triggerEvent('OnGameStart'); triggerEvent('OnGameStart')""")
    check(s.eval("#REG") == 1 and s.eval("REG[1]") == "HondaCRVGen1|media/viewpoint/HondaCRVGen1.properties",
          "Viewpoint pack registered once")
    s.run("HondaCRVGen1.Polish.viewpointRegistered = false; Viewpoint.ModelPacks.register = function() error('bad pack') end")
    s.run("HondaCRVGen1.Polish.registerViewpoint()")       # an error inside Viewpoint is caught
    print("POLISH Viewpoint pack: ok")


def pitch_log_tests():
    """Finding 'Engine layer calls FMODSoundEmitter.setPitch twice per tick per car': 42.21's setPitch
    writes a General log line on every call whose ref matches. Idle and a steady cruise must write
    none; a rev writes a few per second; the pitch still follows the engine."""
    s = side("sp")
    s.run("car = spawnCar(1, 0); car.engine = true; car.rpm = 820; TICK(120)")   # start, settle
    s.run("LOGGED = 0; TICK(600)")                                               # ten seconds at idle
    check(s.eval("LOGGED") == 0, "idle for 10 s: %d 'Set pitch' log lines (want 0)" % s.eval("LOGGED"))
    # a rev from idle to 4000 rpm over two seconds, then held: few lines, the pitch arrives
    s.run("LOGGED = 0; for i = 1, 120 do car.rpm = 820 + (4000 - 820) * i / 120; TICK(1) end")
    rev = s.eval("LOGGED")
    check(0 < rev <= 2 * 2 * 20, "a 2 s rev: %d log lines (want at most 20 a second per layer)" % rev)
    s.run("TICK(30); LOGGED = 0; TICK(600)")                                    # the smoothing's tail, then held
    check(s.eval("LOGGED") == 0, "holding 4000 rpm for 10 s: %d log lines (want 0)" % s.eval("LOGGED"))
    lp, _lv, hp, _hv = (s.eval("({HondaCRVGen1.Polish.mix(4000, 1)})[%d]" % i) for i in (1, 2, 3, 4))
    ph, vh = layer(s, "CRVGen1EngineHigh")
    check(abs(ph / hp - 1) < 0.025 and vh > 0.3, "at 4000 rpm the high layer is heard at its pitch (%s vs %s)" % (ph, hp))
    # a steady cruise with the engine speed jittering a few rpm: nothing logged
    s.run("""LOGGED = 0
             for i = 1, 600 do car.rpm = 2200 + ((i % 7) - 3) * 4; TICK(1) end
             LOGGED = 0
             for i = 1, 600 do car.rpm = 2200 + ((i % 7) - 3) * 4; TICK(1) end""")
    check(s.eval("LOGGED") == 0, "cruise at 2200 +- 12 rpm for 10 s: %d log lines (want 0)" % s.eval("LOGGED"))
    # a full minute of stop-and-go driving: an order of magnitude under the 120 lines a second of before
    s.run("""LOGGED = 0
             for i = 1, 3600 do
                 local t = (i % 600) / 600
                 car.rpm = t < 0.3 and (900 + 9000 * t) or (t < 0.6 and 3600 or 900)
                 TICK(1)
             end""")
    per_s = s.eval("LOGGED") / 60.0
    check(per_s < 10, "stop-and-go minute: %.1f log lines a second (want < 10; was 120)" % per_s)
    print("POLISH pitch log: idle 0, a 2 s rev %d, held revs 0, cruise 0, stop-and-go %.1f lines/s: ok" % (rev, per_s))


def start_guard_tests():
    """A layer whose clip cannot start (handle 0) is not kept: no orphan emitter is moved or pitched."""
    s = side("sp")
    s.run("FAIL_PLAY = true; car = spawnCar(1, 0); car.engine = true; car.rpm = 1500; TICK(60)")
    check(s.eval("(function() for _ in pairs(HondaCRVGen1.Polish.cars) do return false end return true end)()"), "a layer that failed to start is not tracked")
    check(s.eval("(function() local n = 0; for _, e in ipairs(EMITTERS) do n = n + e.pitchCalls end; return n end)()") == 0,
          "nothing pitched for a layer that failed to start")
    s.run("FAIL_PLAY = false; TICK(30)")
    check(len(playing(s)) == 2, "the next scan starts it once the clip plays")
    print("POLISH start guard: a failed start is dropped and retried: ok")


def occupant_tests():
    """H-LUA-1 / H-COMPAT-1: the layer followed IsoPlayer.getNearVehicle(), which the game answers with nil while the
    player sits in a car and otherwise only for a car within 4 tiles the player faces: the driver never heard it.
    Now the car the player sits in, then the tracked CR-Vs within RANGE, nearest first (at most MAX_CARS)."""
    s = side("sp")
    s.run("car = spawnCar(1, 4); car.engine = true; car.rpm = 2000; car.x, car.y = 102, 100; TICK(31)")
    check(len(playing(s)) == 2, "on foot, 2 tiles, facing: the layer plays (%s)" % playing(s))
    s.run("LOCAL.vehicle = car; LOCAL.x, LOCAL.y = car.x, car.y; TICK(31)")
    check(s.eval("LOCAL:getNearVehicle() == nil"), "the fake answers as the game: nil inside a car")
    check(len(playing(s)) == 2, "the driver inside the running CR-V hears it (%s)" % playing(s))
    s.run("car.x = 400; LOCAL.x = 400; TICK(200)")                 # driving away: the layer stays with the car
    check(len(playing(s)) == 2 and s.eval("EMITTERS[#EMITTERS].x") == 400, "driving: the layer follows the car")
    s.run("LOCAL.vehicle = nil; car.x = 102; LOCAL.x = 95; TICK(31)")
    check(len(playing(s)) == 2, "on foot 7 tiles away (RANGE %d): still heard" % s.eval("HondaCRVGen1.Polish.RANGE"))
    s.run("LOCAL.x = 100; FACING = false; TICK(31)")
    check(len(playing(s)) == 2, "2 tiles away, facing away: still heard")
    s.run("LOCAL.x = 100 - 50; TICK(31)")
    check(playing(s) == [], "50 tiles away: none")
    # a passenger in another, stopped car hears the running CR-V beside it; and its own engine first
    s.run("LOCAL.x = 100; FACING = true; other = spawnCar(2, 3, 'Base.SmallCar'); LOCAL.vehicle = other; TICK(31)")
    check(len(playing(s)) == 2, "sitting in another car next to a running CR-V: heard")
    # several running CR-Vs: the nearest MAX_CARS, the one the player sits in first
    s.run("""LOCAL.vehicle = nil; LOCAL.x, LOCAL.y = 100, 100
             cars = {}
             for i = 1, 5 do local c = spawnCar(10 + i, 2); c.engine = true; c.rpm = 1500; c.x = 100 + i * 5; cars[i] = c end
             TICK(31)""")
    n = s.eval("HondaCRVGen1.Polish.MAX_CARS")
    started = s.eval("(function() local t = {} for v in pairs(HondaCRVGen1.Polish.cars) do t[#t + 1] = v:getId() end table.sort(t) return table.concat(t, ',') end)()")
    check(started == "1,11,12", "the %d nearest running CR-Vs get the layer (%s)" % (n, started))
    s.run("LOCAL.vehicle = cars[5]; LOCAL.x = cars[5].x; TICK(31)")
    check(s.eval("HondaCRVGen1.Polish.cars[cars[5]] ~= nil"), "the car the player sits in is always among them")
    # a car that left the world is never started from its stale tracking entry
    s.run("removeCar(cars[4]); TICK(31)")
    check(s.eval("HondaCRVGen1.Polish.cars[cars[4]] == nil"), "a removed car: no layer")
    print("POLISH OCCUPANTS: driver / passenger hear the layer, on foot within RANGE whatever the facing, nearest %d: ok" % n)


def option_tests():
    """I-DATA-2: the player's own volume (Options > Mods, PZAPI.ModOptions), independent of the server's sandbox
    volume: default on at the recorded level, 0 = off, the saved value counts from the game's start."""
    s = side("sp")
    check(s.eval("HondaCRVGen1.Polish.clientVolume()") == 1, "no options API: full volume")
    s.run("PZAPI = { ModOptions = makeModOptionsApi() }; triggerEvent('OnGameBoot')")
    check(s.eval("PZAPI.ModOptions:getOptions('HondaCRVGen1') ~= nil"), "the options are registered at OnGameBoot")
    check(s.eval("PZAPI.ModOptions:getOptions('HondaCRVGen1'):getOption('engineVolume'):getValue()") == 100, "default 100 %")
    s.run("car = spawnCar(1, 0); car.engine = true; car.rpm = 2000; TICK(31)")
    check(len(playing(s)) == 2, "default: the layer plays")
    _lp, lv100, _hp, _hv = (s.eval("({HondaCRVGen1.Polish.mix(2000, HondaCRVGen1.Polish.volumeSetting())})[%d]" % i) for i in (1, 2, 3, 4))
    s.run("MODOPTIONS_FILE = { HondaCRVGen1 = { engineVolume = 50 } }; triggerEvent('OnGameStart')")
    check(abs(s.eval("HondaCRVGen1.Polish.volumeSetting()") - 0.5) < 1e-9, "the saved 50 % is read at the game's start")
    s.run("TICK(10)")
    vol = layer(s, "CRVGen1EngineLow")[1]
    check(abs(vol - lv100 * 0.5) < 1e-6, "50 %%: the layer at half volume (%s vs %s)" % (vol, lv100))
    s.run("SandboxVars = { HondaCRVGen1 = { PolishEngineVolume = 200 } }")
    check(abs(s.eval("HondaCRVGen1.Polish.volumeSetting()") - 1.0) < 1e-9, "times the server's sandbox volume")
    # R2-AUD-1 (2026-10-24): both at 200 % multiplied to 4x the recorded level; the product is held at 2x
    s.run("PZAPI.ModOptions:getOptions('HondaCRVGen1'):getOption('engineVolume').value = 200")
    check(abs(s.eval("HondaCRVGen1.Polish.volumeSetting()") - 2.0) < 1e-9,
          "200 %% x 200 %%: held at 2x (%s)" % s.eval("HondaCRVGen1.Polish.volumeSetting()"))
    s.run("TICK(10)")
    vol = layer(s, "CRVGen1EngineLow")[1]
    check(abs(vol - lv100 * 2) < 1e-6, "the layer at twice its default volume, not four times (%s vs %s)" % (vol, lv100))
    lv4 = s.eval("({HondaCRVGen1.Polish.mix(2000, 4)})[2]")
    check(abs(lv4 - lv100 * 2) < 1e-6, "Polish.mix holds a master over 2 at 2 (%s vs %s)" % (lv4, lv100 * 2))
    s.run("PZAPI.ModOptions:getOptions('HondaCRVGen1'):getOption('engineVolume').value = 0; TICK(31)")
    check(playing(s) == [], "0: the layer off for this player")
    print("POLISH OPTION: per-player engine volume (default 100 %, saved value read at start, x sandbox, 0 = off): ok")


def reverse_tests():
    """Player report (0.5.1): "strange whining noise when you go in reverse? very high pitch". 42.21's reverse
    holds the engine speed at about 2100 rpm (Speed Demon: 5430) whatever the road speed; 5430 put the high layer
    (the whine) at full volume while the car crawled backwards. In reverse the layer follows the road speed
    through a short reverse gear on the low layer only; forward is unchanged."""
    s = side("sp")
    ceiling = 2400 / 1800.0          # a short reverse gear: at most 2400 rpm on the 1800 rpm low clip
    s.run("car = spawnCar(1, 0); car.engine = true; car.rpm = 800; car.gear = 0; TICK(60)")
    for demon, settle in ((False, 2100), (True, 5433)):
        # ten seconds holding reverse: 0 to the game's ~27 km/h reverse top speed (maxSpeedReverse 40 / 1.5)
        s.run("""car.rpm = 800; car.kmh = 0; car.gear = 0; TICK(120)
                 MAXHV, MAXLP, MINLV = 0, 0, 1
                 for i = 1, 600 do
                     car.kmh = -27 * math.min(1, i / 400)
                     reverseFrame(car, %s)
                     TICK(1)
                     if i > 30 then
                         for _, e in ipairs(EMITTERS) do
                             for _, snd in pairs(e.sounds) do
                                 if snd.playing and snd.name == 'CRVGen1EngineHigh' then MAXHV = math.max(MAXHV, snd.volume) end
                                 if snd.playing and snd.name == 'CRVGen1EngineLow' then
                                     MAXLP = math.max(MAXLP, snd.pitch); MINLV = math.min(MINLV, snd.volume)
                                 end
                             end
                         end
                     end
                 end""" % ("true" if demon else "false"))
        who = "Speed Demon" if demon else "a driver"
        check(abs(s.eval("car.rpm") - settle) < 60, "the game model: %s reverses at %d rpm (%s)" % (who, settle, s.eval("car.rpm")))
        hv, lp, lv = s.eval("MAXHV"), s.eval("MAXLP"), s.eval("MINLV")
        check(hv <= 0.01, "%s reversing: the high (whine) layer stays under 0.01 (max %.3f)" % (who, hv))
        check(lp <= ceiling + 0.03, "%s reversing: the low layer's pitch stays under %.2f (max %.3f)" % (who, ceiling, lp))
        check(lv > 0.05, "%s reversing: the low layer is heard (min volume %.3f)" % (who, lv))
    check(s.eval("HondaCRVGen1.Polish.REVERSE_MAX") < s.eval("HondaCRVGen1.Polish.XFADE[1]"),
          "the reverse ceiling sits under the cross-fade (the high layer stays silent)")
    # the reverse layer rpm: idle plus the road speed through the gear, a little throttle, the ceiling
    rpm = lambda e, kmh, gear: s.eval("(function() car.rpm = %r; car.kmh = %r; car.gear = %r; return HondaCRVGen1.Polish.rpm(car) end)()" % (e, kmh, gear))
    check(abs(rpm(2000, 0, -1) - 1200) < 1e-6, "reverse against a wall: idle + slip (%s)" % rpm(2000, 0, -1))
    check(abs(rpm(2000, -10, -1) - 1800) < 1e-6, "reverse at 10 km/h: 1800 rpm (%s)" % rpm(2000, -10, -1))
    check(rpm(5333, -27, -1) == s.eval("HondaCRVGen1.Polish.REVERSE_MAX"), "Speed Demon at full reverse: the ceiling")
    # a remote car whose engine speed reads 0: the reverse estimate, not the forward one
    check(abs(rpm(0, -25, -1) - 2300) < 1e-6, "remote car reversing at 25 km/h, no engine speed: 2300 rpm (%s)" % rpm(0, -25, -1))
    # forward unchanged: the game's rpm, and the road-speed fallback (abs) when it reads 0
    check(rpm(6000, 120, 4) == 6000 and rpm(2000, 30, 1) == 2000, "forward: the game's engine speed as before")
    check(abs(rpm(0, 60, 3) - 3500) < 1e-6 and abs(rpm(0, 0, 0) - 800) < 1e-6, "forward fallback as before")
    check(rpm(900, -3, 0) == 900, "rolling back in neutral: the game's (idle) engine speed")
    # no getTransmissionNumber (an older build): a road speed under -1 km/h counts as reverse
    s.run("Veh.getTransmissionNumber = nil")
    check(abs(rpm(5333, -10, None) - 1800) < 1e-6 and rpm(5333, 10, None) == 5333, "without the gear: the road speed's sign")
    print("POLISH REVERSE: the layer stays on the low clip under %.2fx in reverse (2100 / Speed Demon 5430 rpm in game), "
          "forward unchanged: ok" % ceiling)


def mp_tests():
    net = Net()
    server = side("server", net)
    a = side("client", net, player="alice")
    b = side("client", net, player="bob")
    # the car is created on the server; each client streams it in (createPhysics there too), with the
    # random paint the server's doVehicleColor gave it until the server sets the skin's
    server.run("car = spawnCar(7, 6); car.engine = true; car.rpm = 3000")   # Clover Green: game skin 6
    check(abs(server.eval("car.h") - 0.428) < 1e-6 and server.eval("SENT.colour") == 1,
          "the server sets the green skin's paint HSV and transmits it")

    def properties_packet():
        # VehicleUpdatePacket flag 4096 -> VehicleProperties.parse -> setColorHSV(server's h, s, v),
        # unconditionally, on every client (key in the ignition, blood from a zombie hit, rust ...)
        h, s_, v = server.eval("car.h"), server.eval("car.s"), server.eval("car.v")
        for c in (a, b):
            c.run("car.h, car.s, car.v = %r, %r, %r" % (h, s_, v))
    for c in (a, b):
        c.run("car = spawnCar(7, 6); car.engine = true; car.rpm = 3000")
    # a car the server put on the SUV template's skin: the server moves it (and transmits), a client never
    server.run("suv = spawnCar(8, 0); suv.x = 900")
    check(1 <= server.eval("suv.skin") <= 8 and server.eval("SENT.skin") == 1, "the server moves skin 0 to ours and transmits it")
    a.run("suv = spawnCar(8, 0); suv.x = 900")
    check(a.eval("suv.skin") == 0 and a.eval("suv.skinSets") is None, "a client leaves the skin to the server's packet")
    properties_packet()                                  # the full update a client gets when the car streams in
    for _ in range(40):
        for s in (server, a, b):
            s.run("TICK(1)")
        net.pump()
        properties_packet()                              # e.g. a zombie hit's transmitBlood every tick
    check(server.eval("#EMITTERS") == 0, "dedicated server: no sound")
    for s, who in ((a, "alice"), (b, "bob")):
        check(len(playing(s)) == 2, "%s hears the layer" % who)
        check(abs(s.eval("car.h") - 0.428) < 1e-6, "%s draws the green skin's paint HSV after every properties packet" % who)
        check(s.eval("car.colourSets") is None, "%s never sets the paint itself (the server owns it)" % who)
    # one client's car stops (its engine state arrives with the vehicle update): only that side stops
    a.run("car.engine = false; TICK(30)")
    b.run("TICK(30)")
    check(playing(a) == [] and len(playing(b)) == 2, "each client follows the engine state it is sent")
    check(server.eval("SENT.transmitModData") == 0, "no mod data traffic")
    print("POLISH MP: the server owns the paint HSV (set once, transmitted), clients keep it through property "
          "packets and play the layer for themselves: ok")


def main():
    sp_tests()
    viewpoint_tests()
    pitch_log_tests()
    start_guard_tests()
    occupant_tests()
    option_tests()
    reverse_tests()
    mp_tests()
    print("POLISH LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
