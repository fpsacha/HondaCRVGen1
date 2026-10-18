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
-- vanilla's player:getNearVehicle(): the nearest vehicle within a few tiles (what the polish scan uses)
function LOCAL:getNearVehicle()
    local best, bd = nil, 10 * 10
    for _, v in ipairs(CELL_LIST) do
        local dx, dy = v:getX() - self:getX(), v:getY() - self:getY()
        if dx * dx + dy * dy <= bd then best, bd = v, dx * dx + dy * dy end
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
function Veh:getSkinIndex() return self.skin or 0 end
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
function removeCar(v)
    for i = #CELL_LIST, 1, -1 do if CELL_LIST[i] == v then table.remove(CELL_LIST, i) end end
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
    s.run("car = spawnCar(1, 3)")                        # Milano Red
    h, sat, v = s.eval("car.h"), s.eval("car.s"), s.eval("car.v")
    check(abs(h - 0.982) < 1e-6 and abs(sat - 0.776) < 1e-6 and abs(v - 0.478) < 1e-6, "red skin paint HSV at spawn (got %s %s %s)" % (h, sat, v))
    s.run("TICK(60); triggerEvent('OnSpawnVehicleEnd', car)")   # a reload: createPhysics again
    check(s.eval("car.colourSets") == 1, "paint set once, not again on a reload or by the client half")
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
    # a skin index out of the table: left alone, no error
    s.run("odd = spawnCar(4, 12); TICK(30)")
    check(s.eval("odd.colourSets") is None, "unknown skin: paint left alone")
    # Viewpoint: nothing without it; registered once with it
    check(s.eval("HondaCRVGen1.Polish.viewpointRegistered") is False, "no Viewpoint: not registered")
    s.run("""REG = {}
             Viewpoint = { ModelPacks = { register = function(mod, manifest) REG[#REG + 1] = mod .. '|' .. manifest; return true end } }
             triggerEvent('OnGameStart'); triggerEvent('OnGameStart')""")
    check(s.eval("#REG") == 1 and s.eval("REG[1]") == "HondaCRVGen1|media/viewpoint/HondaCRVGen1.properties",
          "Viewpoint pack registered once")
    s.run("HondaCRVGen1.Polish.viewpointRegistered = false; Viewpoint.ModelPacks.register = function() error('bad pack') end")
    s.run("HondaCRVGen1.Polish.registerViewpoint()")       # an error inside Viewpoint is caught
    print("POLISH SP: paint HSV per skin at spawn, engine layer start / pitch / cross-fade / fallback / stop, range, "
          "volume option, other cars, Viewpoint pack: ok")


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
    check(s.eval("next(HondaCRVGen1.Polish.cars) == nil"), "a layer that failed to start is not tracked")
    check(s.eval("(function() local n = 0; for _, e in ipairs(EMITTERS) do n = n + e.pitchCalls end; return n end)()") == 0,
          "nothing pitched for a layer that failed to start")
    s.run("FAIL_PLAY = false; TICK(30)")
    check(len(playing(s)) == 2, "the next scan starts it once the clip plays")
    print("POLISH start guard: a failed start is dropped and retried: ok")


def mp_tests():
    net = Net()
    server = side("server", net)
    a = side("client", net, player="alice")
    b = side("client", net, player="bob")
    # the car is created on the server; each client streams it in (createPhysics there too), with the
    # random paint the server's doVehicleColor gave it until the server sets the skin's
    server.run("car = spawnCar(7, 5); car.engine = true; car.rpm = 3000")
    check(abs(server.eval("car.h") - 0.428) < 1e-6 and server.eval("SENT.colour") == 1,
          "the server sets the green skin's paint HSV and transmits it")

    def properties_packet():
        # VehicleUpdatePacket flag 4096 -> VehicleProperties.parse -> setColorHSV(server's h, s, v),
        # unconditionally, on every client (key in the ignition, blood from a zombie hit, rust ...)
        h, s_, v = server.eval("car.h"), server.eval("car.s"), server.eval("car.v")
        for c in (a, b):
            c.run("car.h, car.s, car.v = %r, %r, %r" % (h, s_, v))
    for c in (a, b):
        c.run("car = spawnCar(7, 5); car.engine = true; car.rpm = 3000")
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
    pitch_log_tests()
    start_guard_tests()
    mp_tests()
    print("POLISH LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
