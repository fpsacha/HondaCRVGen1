r"""
Lua cost per tick of every event handler the mod registers, under realistic loads (the optimisation pass of
2026-10-24). Runs the whole mod in the fake game of scripts/test_all_lua.py (every Lua file in the game's own load
order, lua_harness runtimes, Lua 5.1 like Kahlua) and counts, per handler and per tick:

  * java   calls into the game: every method of the fake game objects (BaseVehicle, VehiclePart, ItemContainer,
           IsoPlayer, the climate, sound emitters...) and every game global (isServer, getPlayer, getTimestampMs,
           getOnlinePlayers, sendServerCommand...) the mod's Lua makes; in Kahlua each one is a reflective Java call
  * instr  Lua VM instructions run by the mod's own code (the fake game's are left out)
  * kb     Lua memory the mod allocates (tables, closures, strings: the garbage it leaves per tick), GC stopped

Scenarios (a fixed seed, 600 ticks = 10 s at 60 fps):
  sp      single player, 20 CR-Vs in a traffic jam: 14 stock, 3 lifted alloy, 3 lifted steel; 5 fully armoured,
          5 roof racks (3 loaded), 3 awnings (2 rolled out), 2 with window bars, a bull bar on 4, loaded trunks,
          folded seats (bed / load floor); it rains; the player stands under a rolled-out awning beside cars it can
          hear (3 engines idling, one CR-V driving by)
  server  a dedicated server with 8 players and 40 CR-Vs (the same mix twice); 3 players by the first cluster
          (one under an awning), 2 by the second, one driving a CR-V, 2 far from every car; it rains
  client  one of those players' clients, the 20 CR-Vs of its area streamed in

    python scripts\lua_profile.py [--lua DIR] [--ticks N] [--json OUT]     # DIR: another 42/media/lua tree

Also prints the one-off costs: a car streaming in (every part's init hook, by hook) and OnFillContainer for a
container type our loot lists fill and one they do not. scripts/test_lua_perf.py holds the ceilings.
"""
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import test_all_lua as T  # noqa: E402
from test_all_lua import Game, WorldNet  # noqa: E402

TICKS = 600

# the fake game, extended for the loads (after boot): the climate, rain and wetness, emitters, online players,
# speeds and engine rpm per car, all as metatable classes so the counter wraps their methods
EXTEND = r'''
RAINING = true
Climate = {}
Climate.__index = Climate
CLIMATE = setmetatable({}, Climate)
function Climate:isRaining() return RAINING end
function Climate:getTemperature() return 12 end
function Climate:getAirTemperatureForCharacter(p) return 12 end
ClimateManager = { getInstance = function() return CLIMATE end }
CharacterStat = CharacterStat or {}
CharacterStat.WETNESS = "WETNESS"
GameTime = {}
GameTime.__index = GameTime
GAMETIME = setmetatable({}, GameTime)
function GameTime:getMultiplier() return 1 end
function GameTime:getCalender() return { getTimeInMillis = function() return 1 end } end
function getGameTime() return GAMETIME end
function getTimeInMillis() return NOW_MS end
function sendDamage(p) end
Emitter = {}
Emitter.__index = Emitter
function Emitter:playSoundLoopedImpl() return 1 end
function Emitter:setVolume() end
function Emitter:setPitch() end
function Emitter:setPos() end
function Emitter:stopSound() end
function Emitter:isPlaying() return true end
World = {}
World.__index = World
WORLD_OBJ = setmetatable({}, World)
function World:getFreeEmitter() EMITTERS = EMITTERS + 1; return setmetatable({ id = EMITTERS }, Emitter) end
function getWorld() return WORLD_OBJ end
-- wetness: the stats, the body parts, the worn clothes
Stats = {}
Stats.__index = Stats
function Stats:get(k) if k == "FATIGUE" then return 0.6 end return self[k] or 0 end
function Stats:set(k, v) self[k] = v end
BodyPart = {}
BodyPart.__index = BodyPart
function BodyPart:getWetness() return self.w end
function BodyPart:setWetness(w) self.w = w end
Body = {}
Body.__index = Body
function Body:getBodyParts() return self.list end
Worn = {}
Worn.__index = Worn
function Worn:size() return #self.t end
function Worn:getItemByIndex(i) return self.t[i + 1] end
function Item:IsClothing() return self.clothing == true end
function Item:getWetness() return self.wet or 0 end
function Item:setWetness(w) self.wet = w end
function dress(p)
    p.stats = setmetatable({ WETNESS = 0 }, Stats)
    local parts = {}
    for i = 1, 17 do parts[i] = setmetatable({ w = 0 }, BodyPart) end
    p.body = setmetatable({ list = newJList(parts) }, Body)
    local clothes = {}
    for i = 1, 6 do local c = newItem("Base.Tshirt"); c.clothing = true; clothes[i] = c end
    p.worn = setmetatable({ t = clothes }, Worn)
    p.onlineId = p.onlineId or 0
end
function Player:getStats() return self.stats end
function Player:getBodyDamage() return self.body end
function Player:getWornItems() return self.worn end
function Player:getOnlineID() return self.onlineId end
ONLINE = {}
function getOnlinePlayers() return newJList(ONLINE) end
function Veh:getCurrentSpeedKmHour() return self.speed or 0 end
function Veh:getEngineSpeed() return self.running and (self.rpm or 850) or 0 end
'''

# the loads: helpers to fit a car out, in Lua (authoritative side)
FIT = r'''
function fitPart(v, pid)
    local p = v.parts[pid]
    if not p or p:getInventoryItem() then return end
    local types = p:getItemType()
    if not types or types:size() == 0 then return end
    p:setInventoryItem(newItem(types:get(0), 5))
    local fn = p.spec.lua and p.spec.lua.init
    if fn then VehicleUtils.callLua(fn, v, p) end
end
function unfitPart(v, pid)
    local p = v.parts[pid]
    if p and p:getInventoryItem() then p:setInventoryItem(nil) end
end
ARMOUR = { "CRVArmourArchFrontLeft", "CRVArmourArchFrontRight", "CRVArmourArchRearLeft", "CRVArmourArchRearRight",
           "CRVArmourDoorFrontLeft", "CRVArmourDoorFrontRight", "CRVArmourDoorRearLeft", "CRVArmourDoorRearRight",
           "CRVGuardFrontLeft", "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVGuardWindshield",
           "CRVGuardWindshieldRear", "CRVBullbar", "CRVOffroadRearBumper", "CRVOffroadSkidPlate" }
BARS = { "CRVGuardFrontLeft", "CRVGuardFrontRight", "CRVGuardRearLeft", "CRVGuardRearRight", "CRVGuardWindshield",
         "CRVGuardWindshieldRear" }
-- car i (0-based) of a cluster of 20: what it carries
function outfit(v, i)
    for _, pid in ipairs({ "CRVBullbar", "CRVRoofRack", "CRVAwning", "CRVSpareCover", "CRVOffroadCanRoof",
                           "CRVOffroadCanGate", "CRVOffroadLadder", "CRVOffroadSnorkel", "CRVOffroadRearBumper",
                           "CRVOffroadSkidPlate" }) do unfitPart(v, pid) end
    for _, pid in ipairs(BARS) do unfitPart(v, pid) end
    HondaCRVGen1.Acc.watch[v.id] = nil
    if i < 5 then for _, pid in ipairs(ARMOUR) do fitPart(v, pid) end end
    if i == 5 or i == 6 then for _, pid in ipairs(BARS) do fitPart(v, pid) end end
    if i >= 5 and i < 10 then
        fitPart(v, "CRVRoofRack")
        if i < 8 then v.parts.CRVRoofRack:getItemContainer():AddItem(newItem("Base.Plank", 4 * (i - 4))) end
        HondaCRVGen1.Acc.Init(v, v.parts.CRVRoofRack)
    end
    if i >= 10 and i < 13 then
        fitPart(v, "CRVAwning")
        if i < 12 then HondaCRVGen1.Awning.set(v, true) end
    end
    if i >= 13 and i < 17 then fitPart(v, "CRVBullbar") end
    if i % 3 == 0 then fitPart(v, "CRVSpareCover") end
    if i % 4 == 1 then fitPart(v, "CRVOffroadSnorkel") end
    local trunk = v.parts.TruckBed:getItemContainer()
    if trunk and i % 2 == 0 then for k = 1, 1 + i % 5 do trunk:AddItem(newItem("Base.Log", 6)) end end
    if i == 15 then HondaCRVGen1.Shared.setFold(v, true, "bed") end
    if i == 16 then
        HondaCRVGen1.Shared.setFold(v, true, "cargo")
        v.parts.CRVFunctionCargo:getItemContainer():AddItem(newItem("Base.Log", 20))
    end
    createPhysics(v)                           -- every part's init again, as a car loaded from the save
end
'''


def lua_scripts(i):
    return "Base.HondaCRVGen1" if i % 20 < 14 else ("Base.HondaCRVGen1LiftAlloy" if i % 20 < 17 else "Base.HondaCRVGen1LiftSteel")


# the counter: wraps the fake game's methods and globals (outermost call only), every handler of every event and
# every part hook; ARM / DISARM become the instruction counter (the hang guard is off while profiling)
PROFILE = r'''
local INSTR = 0
local function hook() INSTR = INSTR + 1 end
function ARM() debug.sethook(hook, "", 1) end
function DISARM() debug.sethook() end
JAVA, FAKE_I, FAKE_KB, DEPTH = 0, 0, 0, 0
JAVA_BY = {}
local count = collectgarbage
local function done(i0, m0, ...)
    FAKE_I = FAKE_I + (INSTR - i0)
    FAKE_KB = FAKE_KB + (count("count") - m0)
    DEPTH = 0
    return ...
end
local function wrapf(name, f)
    return function(...)
        if DEPTH > 0 then return f(...) end
        DEPTH = 1
        JAVA = JAVA + 1
        JAVA_BY[name] = (JAVA_BY[name] or 0) + 1
        return done(INSTR, count("count"), f(...))
    end
end
local CLASSES = { Veh = Veh, Part = Part, Door = Door, Win = Win, Cont = Cont, Player = Player, Item = Item,
                  JList = JList, JMap = JMap, V3 = V3, Climate = Climate, Emitter = Emitter, World = World,
                  Stats = Stats, BodyPart = BodyPart, Body = Body, Worn = Worn, GameTime = GameTime }
for cname, cls in pairs(CLASSES) do
    local names = {}
    for k, f in pairs(cls) do if type(f) == "function" and k ~= "__index" then names[#names + 1] = k end end
    for _, k in ipairs(names) do cls[k] = wrapf(cname .. ":" .. k, cls[k]) end
end
local GLOBALS = { "isServer", "isClient", "getPlayer", "getSpecificPlayer", "getNumActivePlayers", "getOnlinePlayers",
                  "getTimestampMs", "getTimeInMillis", "isGamePaused", "getVehicleById", "getWorld", "getCell",
                  "getGameTime", "getText", "ZombRand", "ZombRandFloat", "sendServerCommand", "sendClientCommand",
                  "getSquare", "instanceof", "print", "getTexture", "sendDamage", "getCore", "getPlayerRadialMenu",
                  "getServerOptions", "instanceItem", "addXp", "getPlayerData", "getPlayerMechanicsUI" }
for _, k in ipairs(GLOBALS) do
    if type(_G[k]) == "function" then rawset(_G, k, wrapf(k, _G[k])) end
end
ClimateManager.getInstance = wrapf("ClimateManager.getInstance", ClimateManager.getInstance)
if Vector3f and Vector3f.new then Vector3f.new = wrapf("Vector3f.new", Vector3f.new) end

-- readable names: the mod's tables two levels down (HondaCRVGen1.X.f, HondaCRVGen1.X.Y.f)
local NAMES = {}
local function scan(t, prefix, depth)
    for k, v in pairs(t) do
        if type(k) == "string" then
            if type(v) == "function" and not NAMES[v] then NAMES[v] = prefix .. k
            elseif type(v) == "table" and depth > 0 and k ~= "tracked" and k ~= "watch" then scan(v, prefix .. k .. ".", depth - 1) end
        end
    end
end
scan(HondaCRVGen1, "", 2)
function LABEL(fn)
    if NAMES[fn] then return NAMES[fn] end
    local info = debug.getinfo(fn, "S")
    return (info.short_src:gsub("^.*/", "")) .. ":" .. info.linedefined
end

STATS = {}
local function stat(label)
    local s = STATS[label]
    if not s then s = { n = 0, java = 0, instr = 0, kb = 0 }; STATS[label] = s end
    return s
end
local function fin(label, outer, j0, i0, f0, k0, fk0, ...)
    local i1, k1 = INSTR, count("count")
    local s = stat(label)
    s.n = s.n + 1
    s.java = s.java + (JAVA - j0)
    s.instr = s.instr + (i1 - i0) - (FAKE_I - f0)
    s.kb = s.kb + (k1 - k0) - (FAKE_KB - fk0)
    DEPTH = outer
    return ...
end
local function measured(label, fn)
    return function(...)
        local outer = DEPTH
        DEPTH = 0
        return fin(label, outer, JAVA, INSTR, FAKE_I, count("count"), FAKE_KB, fn(...))
    end
end
-- every handler of every event: "<Event> <name>"
for ev, list in pairs(EVENTS) do
    for i, fn in ipairs(list) do list[i] = measured(ev .. " " .. LABEL(fn), fn) end
end
-- every part hook the vehicle scripts name (create / init), by name: "hook <name>"
HOOKS = {}
for _, parts in pairs(SCRIPT_PARTS) do
    for _, spec in ipairs(parts) do
        for _, which in ipairs({ "init", "create" }) do
            local name = spec.lua and spec.lua[which]
            if name and name:find("^HondaCRVGen1%.") then HOOKS[name] = true end
        end
    end
end
for name, _ in pairs(HOOKS) do
    local t, last = _G, nil
    local segs = {}
    for seg in name:gmatch("[^%.]+") do segs[#segs + 1] = seg end
    for i = 1, #segs - 1 do t = t[segs[i]] end
    last = segs[#segs]
    if type(t[last]) == "function" then t[last] = measured("hook " .. name:gsub("^HondaCRVGen1%.", ""), t[last]) end
end
function PROFILE_RESET()
    STATS = {}
    JAVA_BY = {}
    JAVA, FAKE_I, FAKE_KB, DEPTH = 0, 0, 0, 0
end
function PROFILE_TICKS(n)
    count("stop")
    for i = 1, n do TICK(1) end
    count("restart")
end
'''


def _stats(g):
    out = {}
    for label, s in g.eval("STATS").items():
        out[label] = {"n": s.n, "java": s.java, "instr": s.instr, "kb": s.kb}
    return out


def _java_by(g):
    return dict(g.eval("JAVA_BY").items())


def _boot(role, net=None, name=None):
    g = Game(role, net, name=name).boot()
    g.run(EXTEND)
    g.run(FIT)
    return g


def _player(g, name, x, y, online_id=0):
    g.run("local p = newPlayer(%r, %r, %r); p.onlineId = %d; dress(p); table.insert(ONLINE, p)" % (name, x, y, online_id))
    return g.eval("PLAYERS[%r]" % name)


def _cluster(g, n, x0, y0, first_index=0):
    """n CR-Vs in a jam along +x from (x0, y0), outfitted by their index in the cluster; returns their ids."""
    ids = []
    for i in range(n):
        vid = g.eval("createVehicle(%r, %r, %r, true).id" % (lua_scripts(i), x0 + 5.0 * i + 0.5, y0 + 0.5))
        g.run("outfit(VEHICLES[%d], %d)" % (vid, (first_index + i) % 20))
        ids.append(vid)
    return ids


def scenario_sp():
    g = _boot("sp")
    ids = _cluster(g, 20, 100, 100)
    # 3 engines idling (one the player can hear up close), one CR-V driving by
    for k in (1, 2, 3):
        g.run("VEHICLES[%d].running = true" % ids[k])
    g.run("VEHICLES[%d].running = true; VEHICLES[%d].speed = 40; VEHICLES[%d].rpm = 2900" % ((ids[19],) * 3))
    # the player under car 10's rolled-out awning (right of the car: +x mesh = -x world here, so west), in the rain
    v10 = g.eval("VEHICLES[%d]" % ids[10])
    _player(g, "tester", v10.x - 1.5, v10.y - 0.5)
    g.run("PLAYER = PLAYERS['tester']")
    return {"sp": g}


def scenario_mp(client_cars=20):
    net = WorldNet()
    server = _boot("server", net)
    server.run("PLAYER = nil")
    a = _cluster(server, 20, 100, 100)
    b = _cluster(server, 20, 100, 300, first_index=0)
    va10 = server.eval("VEHICLES[%d]" % a[10])
    spots = [("bob", va10.x - 1.5, va10.y - 0.5),      # under cluster A's rolled-out awning
             ("ann", 112.0, 102.0), ("cid", 150.0, 98.0),
             ("dee", 130.0, 302.0), ("eve", 170.0, 298.0),
             ("fay", 400.0, 200.0),                    # driving (below)
             ("gus", 900.0, 900.0), ("hal", 1200.0, 50.0)]
    for k, (name, x, y) in enumerate(spots):
        _player(server, name, x, y, online_id=k + 1)
    # fay drives a CR-V of cluster B away down the road
    vb = b[19]
    server.run("local v = VEHICLES[%d]; v.x, v.y = 400.5, 200.5; v.running = true; v.speed = 60; v.rpm = 3200;"
               "v.seats[0] = PLAYERS['fay']; PLAYERS['fay'].vehicle = v" % vb)
    for k in (1, 2, 3):
        server.run("VEHICLES[%d].running = true; VEHICLES[%d].running = true" % (a[k], b[k]))
    client = _boot("client", net, name="bob")
    _player(client, "bob", va10.x - 1.5, va10.y - 0.5)
    client.run("PLAYER = PLAYERS['bob']")
    for vid in a[:client_cars]:
        net.stream_in(client, vid)
    for vid in a[:client_cars]:
        sv = server.eval("VEHICLES[%d]" % vid)
        client.run("VEHICLES[%d].running = %s" % (vid, "true" if sv.running else "false"))
    net.pump()
    return {"server": server, "client": client, "net": net}


def one_off(g, vid):
    """Costs a car pays once: streaming in (createPhysics: every part's init) and OnFillContainer."""
    g.run("PROFILE_RESET()")
    g.run("collectgarbage('stop'); local v = VEHICLES[%d]; v.removed = false; createPhysics(v); collectgarbage('restart')" % vid)
    inits = _stats(g)
    g.run("PROFILE_RESET()")
    g.run("collectgarbage('stop'); FILLC = newContainer(50); for i = 1, 12 do FILLC:AddItem(newItem('Base.Wrench')) end"
          "; FILLC:AddItem(newItem('Base.CRVGen1_LiftKit')); collectgarbage('restart')")
    g.run("triggerEvent('OnFillContainer', 'garage', 'shelves', FILLC)")
    g.run("triggerEvent('OnFillContainer', 'kitchen', 'fridge', FILLC)")
    fills = _stats(g)
    return inits, fills


WARMUP = 150


def _tick_all(sides, net):
    for name in ("sp", "server", "client"):
        if name in sides:
            sides[name].run("TICK(1)")
            if name == "server" and net is not None:
                net.pump()


def measure(sides, ticks):
    """Install the counter on every side, run WARMUP ticks (the first passes fill the loops' caches), then `ticks`
    ticks counted (server, network, client in turn); return per side {label: {n, java, instr, kb}} and the java calls
    by method."""
    net = sides.get("net")
    for _ in range(WARMUP):
        _tick_all(sides, net)
    for name, g in sides.items():
        if name != "net":
            g.run(PROFILE)
            g.run("PROFILE_RESET()")
    for name, g in sides.items():
        if name != "net":
            g.run("collectgarbage('stop')")
    for _ in range(ticks):
        _tick_all(sides, net)
    for name, g in sides.items():
        if name != "net":
            g.run("collectgarbage('restart')")
    out = {}
    for name, g in sides.items():
        if name != "net":
            out[name] = {"handlers": _stats(g), "java_by": _java_by(g), "errors": list(g.errors)}
    return out


def table_rows(handlers, ticks):
    rows = []
    for label, s in handlers.items():
        rows.append((label, s["java"] / ticks, s["instr"] / ticks, s["kb"] / ticks, s["n"]))
    rows.sort(key=lambda r: (-r[1], -r[2]))
    return rows


def report(result, ticks, out=print):
    for side, r in result.items():
        if side.startswith("_"):
            continue
        rows = table_rows(r["handlers"], ticks)
        tj = sum(x[1] for x in rows)
        ti = sum(x[2] for x in rows)
        tk = sum(x[3] for x in rows)
        out("== %s: %.1f java calls / tick, %.0f Lua instructions / tick, %.2f KB / tick" % (side, tj, ti, tk))
        out("   %8s %9s %8s  %s" % ("java/t", "instr/t", "KB/t", "handler"))
        for label, j, i, k, n in rows:
            out("   %8.2f %9.1f %8.3f  %s" % (j, i, k, label))
        top = sorted(r["java_by"].items(), key=lambda kv: -kv[1])[:10]
        out("   top calls: " + ", ".join("%s %.1f" % (k, v / ticks) for k, v in top))
        if r["errors"]:
            out("   errors: %s" % r["errors"][:3])


def run_all(ticks=TICKS):
    T.SCRIPTS = T.scripts_lua()
    import test_all_lua
    test_all_lua.SCRIPTS = T.SCRIPTS
    sp = scenario_sp()
    mp = scenario_mp()
    res = {}
    res.update(measure(sp, ticks))
    res.update(measure(mp, ticks))
    # one-off costs on the single-player side (the counter is installed): a stock car streaming in again
    inits, fills = one_off(sp["sp"], 1)
    res["_once"] = {"stream_in": inits, "fill": fills}
    return res


def main():
    ticks = TICKS
    if "--lua" in sys.argv:
        T.LUA_DIR = os.path.abspath(sys.argv[sys.argv.index("--lua") + 1])
    if "--ticks" in sys.argv:
        ticks = int(sys.argv[sys.argv.index("--ticks") + 1])
    print("Lua tree:", T.LUA_DIR)
    res = run_all(ticks)
    report(res, ticks)
    once = res["_once"]
    print("== once: a CR-V streaming in (createPhysics: every part init), single player")
    tj = sum(s["java"] for s in once["stream_in"].values())
    ti = sum(s["instr"] for s in once["stream_in"].values())
    print("   total %d java calls, %d instructions" % (tj, ti))
    for label, s in sorted(once["stream_in"].items(), key=lambda kv: -kv[1]["java"]):
        print("   %6d java %7d instr  x%-3d %s" % (s["java"], s["instr"], s["n"], label))
    print("== once: OnFillContainer (a matching shelf, then a fridge)")
    for label, s in once["fill"].items():
        print("   %6.1f java %7.1f instr per call  %s" % (s["java"] / s["n"], s["instr"] / s["n"], label))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump({"ticks": ticks, "result": res}, f, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
