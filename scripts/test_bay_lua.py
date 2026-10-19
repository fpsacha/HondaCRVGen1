r"""
The engine bay's Lua (42/media/lua/shared/HondaCRVGen1_EngineBay.lua) under Lua 5.1 (lupa; PZ's Kahlua is a
Lua 5.1), single player and a dedicated server with two clients (scripts/lua_harness.py):

  * part CRVEngineBay draws exactly one model: EngineBay (the full bay) or EngineBayLow (the shut bay's stand-in);
    nothing before the part's init (no item, setAllModelsVisible = false), nothing ever on a dedicated server;
  * the bay shows from the moment ISOpenVehicleDoor:start runs on this side (the clip starts there, the door
    state only in complete()), falls back after OPEN_GRACE if the open never completes (a locked hood), shows
    while the door is open or the hood is gone, and is held CLOSE_HOLD of unpaused time after the door shuts;
  * every input is state the game syncs (the door, the hood's item): clients follow the server's door packets
    and item changes, a car streamed in or re-inited (lift conversion, script reload) starts right;
  * the wrap of ISOpenVehicleDoor.start: once per table (a second call, OnGameStart, another mod's wrapper on
    top), vanilla's start still runs and plays the clip, other cars and other doors pass through, an error
    inside ours never stops the door;
  * idle ticks call no setModelVisible; cars removed from the world leave the table.

    python scripts\test_bay_lua.py
"""
import sys

from lua_harness import Net, Side

BAY = ("shared/HondaCRVGen1_EngineBay.lua",)
GRACE, HOLD = 4000 // 16 + 2, 3000 // 16 + 2          # Bay.OPEN_GRACE / CLOSE_HOLD in 16 ms frames

# what the game gives the file beyond lua_harness's PRELUDE: doors, the clip call, the clock, the pause flag,
# vanilla's ISOpenVehicleDoor (42.21: start() plays the Open clip, complete() opens the door if not locked)
GAME = r'''
PRINTS = {}
function print(...) local t = {} for i = 1, select("#", ...) do t[i] = tostring((select(i, ...))) end PRINTS[#PRINTS + 1] = table.concat(t, " ") end
NOW_MS, PAUSED = 5000, false
function getTimestampMs() return NOW_MS end
function isGamePaused() return PAUSED end
function TICK(n) for i = 1, (n or 1) do NOW_MS = NOW_MS + 16; triggerEvent("OnTick") end end
Door = {}
Door.__index = Door
function Door:isOpen() return self.open end
function Door:setOpen(b) self.open = b end
function Door:isLocked() return self.locked end
function Part:getDoor() return self.door end
ANIMS = {}
function Veh:playPartAnim(p, anim) ANIMS[#ANIMS + 1] = p.id .. ":" .. anim end
function Veh:transmitPartDoor(p) if ROLE == "server" then PY_DOOR(self.id, p.id, p.door.open) end end
ISBaseTimedAction = {}
ISBaseTimedAction.__index = ISBaseTimedAction
function ISBaseTimedAction:derive(t) local o = {}; setmetatable(o, self); self.__index = self; o.Type = t; return o end
function ISBaseTimedAction.new(self, character)
    local o = {}; setmetatable(o, self); self.__index = self; o.character = character; return o
end
ISOpenVehicleDoor = ISBaseTimedAction:derive("ISOpenVehicleDoor")
function ISOpenVehicleDoor:start() self.vehicle:playPartAnim(self.part, "Open") end
function ISOpenVehicleDoor:complete()
    if not self.part:getDoor():isLocked() then self.part:getDoor():setOpen(true); self.vehicle:transmitPartDoor(self.part) end
    return true
end
function ISOpenVehicleDoor:new(character, vehicle, part)
    local o = ISBaseTimedAction.new(self, character); o.vehicle = vehicle; o.part = part; return o
end
-- a CR-V (the hood fitted and shut, the bay part with its two models, a door) or another car; createPhysics runs
-- every part's init (VehicleParts.initParts)
function crv(id, script)
    local v = newVehicle(id, { "EngineDoor", "CRVEngineBay", "DoorFrontLeft" }, script or "Base.HondaCRVGen1")
    v.parts.EngineDoor.item = newItem("EngineDoor1")
    v.parts.EngineDoor.door = setmetatable({ open = false, locked = false }, Door)
    v.parts.DoorFrontLeft.item = newItem("FrontCarDoor1")
    v.parts.DoorFrontLeft.door = setmetatable({ open = false, locked = false }, Door)
    v.parts.CRVEngineBay.models = { "EngineBay", "EngineBayLow" }
    return v
end
function createPhysics(v) if v.parts.CRVEngineBay then HondaCRVGen1.Bay.Init(v, v.parts.CRVEngineBay) end end
function shown(v)
    local p = v.parts.CRVEngineBay
    local t = {}
    for _, m in ipairs({ "EngineBay", "EngineBayLow" }) do if p.visible[m] then t[#t + 1] = m end end
    return table.concat(t, ",")
end
function hood(v, open) v.parts.EngineDoor.door.open = open end
'''

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


def side(role, net=None, player=None):
    s = Side(role, net, player=player)
    s.L.globals().PY_DOOR = lambda vid, pid, op: net.doors.append((vid, pid, op)) if net is not None else None
    s.run(GAME)
    s.load(*BAY)
    s.run("HondaCRVGen1.Bay.cars = {}")
    return s


def single_player():
    print("\n=== single player")
    s = side("sp")
    check(s.eval("rawget(ISOpenVehicleDoor, 'HondaCRVGen1BayWrapped')") is True, "ISOpenVehicleDoor:start wrapped at load")
    s.run("FIRST = ISOpenVehicleDoor.start; HondaCRVGen1.Bay.wrap(); triggerEvent('OnGameStart')")
    check(s.eval("ISOpenVehicleDoor.start == FIRST and FIRST == HondaCRVGen1.Bay.openStart"),
          "a second wrap (OnGameStart) leaves the wrapper alone")
    s.run("v = crv(1)")
    check(s.eval("shown(v)") == "", "nothing drawn before the part's init (no item, setAllModelsVisible = false)")
    s.run("createPhysics(v)")
    check(s.eval("shown(v)") == "EngineBayLow", "a car created with the hood shut: the stand-in")
    # open: the clip starts in start(), the door state in complete()
    s.run("ANIMS = {}; P = newPlayer('me'); a = ISOpenVehicleDoor:new(P, v, v.parts.EngineDoor); a:start()")
    check(s.eval("ANIMS[1]") == "EngineDoor:Open", "vanilla's start still plays the Open clip")
    check(s.eval("shown(v)") == "EngineBay", "the bay shows as the hood starts to open, before complete()")
    s.run("TICK(%d)" % (GRACE - 10))
    check(s.eval("shown(v)") == "EngineBay", "still shown within the grace while the action runs")
    s.run("a:complete(); TICK(%d)" % GRACE)
    check(s.eval("shown(v)") == "EngineBay", "shown while the door is open, past the grace")
    # shut: held while the clip swings it down
    s.run("hood(v, false); TICK(%d)" % (HOLD - 10))
    check(s.eval("shown(v)") == "EngineBay", "held while the hood swings shut")
    s.run("TICK(12)")
    check(s.eval("shown(v)") == "EngineBayLow", "the stand-in once the hold ran out")
    # the hold counts unpaused time only
    s.run("hood(v, true); TICK(1); hood(v, false); TICK(1); PAUSED = true; TICK(%d)" % (3 * HOLD))
    check(s.eval("shown(v)") == "EngineBay", "a paused game does not run the hold out")
    s.run("PAUSED = false; TICK(%d)" % HOLD)
    check(s.eval("shown(v)") == "EngineBayLow", "unpaused, the hold runs out")
    # a locked hood: the clip plays, the door never opens
    s.run("v.parts.EngineDoor.door.locked = true; a = ISOpenVehicleDoor:new(P, v, v.parts.EngineDoor); a:start(); a:complete()")
    check(s.eval("shown(v)") == "EngineBay" and s.eval("v.parts.EngineDoor.door.open") is False,
          "a locked hood: shown while its clip plays")
    s.run("TICK(%d)" % GRACE)
    check(s.eval("shown(v)") == "EngineBayLow", "a locked hood: the stand-in after the grace")
    s.run("v.parts.EngineDoor.door.locked = false")
    # the hood off and back on
    s.run("v.parts.EngineDoor:setInventoryItem(nil); TICK(1)")
    check(s.eval("shown(v)") == "EngineBay", "the hood removed: the bay is in plain view")
    s.run("v.parts.EngineDoor:setInventoryItem(newItem('EngineDoor1')); TICK(%d)" % HOLD)
    check(s.eval("shown(v)") == "EngineBayLow", "a shut hood refitted: the stand-in again")
    # idle ticks
    calls = s.eval("v.parts.CRVEngineBay.calls")
    s.run("TICK(200)")
    check(s.eval("v.parts.CRVEngineBay.calls") == calls, "idle ticks call no setModelVisible")
    # another door, another car
    s.run("ANIMS = {}; a = ISOpenVehicleDoor:new(P, v, v.parts.DoorFrontLeft); a:start()")
    check(s.eval("shown(v)") == "EngineBayLow" and s.eval("ANIMS[1]") == "DoorFrontLeft:Open", "a car door: no bay, the clip plays")
    s.run("o = newVehicle(2, { 'EngineDoor' }, 'Base.SUV'); o.parts.EngineDoor.item = newItem('EngineDoor1'); "
          "o.parts.EngineDoor.door = setmetatable({ open = false, locked = false }, Door); ANIMS = {}; "
          "a = ISOpenVehicleDoor:new(P, o, o.parts.EngineDoor); a:start(); TICK(2)")
    check(s.eval("ANIMS[1]") == "EngineDoor:Open" and s.eval("HondaCRVGen1.Bay.cars[2]") is None,
          "a vanilla car's hood: the clip plays, the car is not tracked")
    # an error inside ours never stops the door
    s.run("local f = HondaCRVGen1.Bay.opening; HondaCRVGen1.Bay.opening = function() error('boom') end; ANIMS = {}; "
          "a = ISOpenVehicleDoor:new(P, v, v.parts.EngineDoor); a:start(); HondaCRVGen1.Bay.opening = f")
    check(s.eval("ANIMS[1]") == "EngineDoor:Open" and "boom" in (s.eval("PRINTS[#PRINTS]") or ""),
          "an error in the bay code is logged, vanilla's start still runs")
    # another mod wraps on top of ours: one call each, no cycle
    s.run("OTHER = 0; local ours = ISOpenVehicleDoor.start; ISOpenVehicleDoor.start = function(self, ...) "
          "OTHER = OTHER + 1; return ours(self, ...) end; HondaCRVGen1.Bay.wrap(); ANIMS = {}; "
          "a = ISOpenVehicleDoor:new(P, v, v.parts.EngineDoor); a:start()")
    check(s.eval("OTHER") == 1 and s.eval("#ANIMS") == 1, "another mod's wrapper on top: each runs once")
    s.run("hood(v, false); TICK(%d)" % GRACE)
    # a car loaded with the hood open; re-init (lift conversion, script reload: the models were remade)
    s.run("w = crv(3); w.parts.EngineDoor.door.open = true; createPhysics(w)")
    check(s.eval("shown(w)") == "EngineBay", "a car loaded with the hood open: the bay at once")
    s.run("v.parts.CRVEngineBay.visible = {}; createPhysics(v)")
    check(s.eval("shown(v)") == "EngineBayLow", "re-init after the models were remade: applied afresh")
    s.run("L = crv(4, 'Base.HondaCRVGen1LiftSteel'); createPhysics(L)")
    check(s.eval("shown(L)") == "EngineBayLow", "the lifted car: the stand-in")
    # removed from the world / a new BaseVehicle under the same id
    s.run("w.removed = true; TICK(1)")
    check(s.eval("HondaCRVGen1.Bay.cars[3]") is None, "a car removed from the world leaves the table")
    s.run("v2 = crv(1); VEHICLES[1] = v2; v2.parts.EngineDoor.door.open = true; createPhysics(v2); TICK(1)")
    check(s.eval("shown(v2)") == "EngineBay" and s.eval("HondaCRVGen1.Bay.cars[1].vehicle == v2"),
          "a new BaseVehicle under the same id starts afresh")


class BayNet(Net):
    """lua_harness.Net plus the door packets (BaseVehicle.transmitPartDoor) and cars streaming in."""

    def __init__(self):
        super().__init__()
        self.doors = []

    def pump(self):
        n = super().pump()
        while self.doors:
            vid, pid, op = self.doors.pop(0)
            for c in self.clients:
                c.run("if VEHICLES[%d] then VEHICLES[%d].parts.%s.door.open = %s end" % (vid, vid, pid, "true" if op else "false"))
            n += 1
        return n

    def stream_in(self, vid, open_hood=False):
        for c in self.clients:
            c.run("v = crv(%d); v.parts.EngineDoor.door.open = %s; createPhysics(v)" % (vid, "true" if open_hood else "false"))

    def item(self, vid, pid, fitted):
        for c in self.clients:
            c.run("VEHICLES[%d].parts.%s:setInventoryItem(%s)" % (vid, pid, "newItem('EngineDoor1')" if fitted else "nil"))


def multiplayer():
    print("\n=== dedicated server + two clients")
    net = BayNet()
    S = side("server", net)
    A = side("client", net, player="alice")
    B = side("client", net, player="bob")
    check(S.eval("rawget(ISOpenVehicleDoor, 'HondaCRVGen1BayWrapped')") is None, "server: nothing wrapped (nothing drawn)")
    S.run("v = crv(7); createPhysics(v)")
    net.stream_in(7)
    for c in (A, B):
        check(c.eval("shown(v)") == "EngineBayLow", "%s: a streamed-in CR-V with the hood shut: the stand-in" % c.player)
    # alice opens the hood: her client runs start(), the server runs it again and completes it
    A.run("a = ISOpenVehicleDoor:new(PLAYER, v, v.parts.EngineDoor); a:start()")
    check(A.eval("shown(v)") == "EngineBay" and B.eval("shown(v)") == "EngineBayLow",
          "alice's client shows the bay at the action's start, bob's waits for the door")
    S.run("a = ISOpenVehicleDoor:new(newPlayer('alice'), v, v.parts.EngineDoor); a:start(); a:complete()")
    check(S.eval("v.parts.CRVEngineBay.calls") == 0 and S.eval("shown(v)") == "", "server: nothing drawn")
    net.pump()
    for c in (A, B):
        c.run("TICK(1)")
        check(c.eval("shown(v)") == "EngineBay", "%s: the bay once the open door is synced" % c.player)
    # a player streaming in while the hood is open
    C = side("client", net, player="carol")
    net.clients = [A, B, C]
    C.run("v = crv(7); v.parts.EngineDoor.door.open = true; createPhysics(v)")
    check(C.eval("shown(v)") == "EngineBay", "carol: a car streamed in with the hood open: the bay")
    # bob closes it (the server's door packet)
    S.run("hood(v, false); v:transmitPartDoor(v.parts.EngineDoor)")
    net.pump()
    for c in (A, B, C):
        c.run("TICK(10)")
        check(c.eval("shown(v)") == "EngineBay", "%s: held while the hood swings shut" % c.player)
        c.run("TICK(%d)" % HOLD)
        check(c.eval("shown(v)") == "EngineBayLow", "%s: the stand-in once the hood is down" % c.player)
    # the hood taken off on the server, refitted
    net.item(7, "EngineDoor", False)
    for c in (A, B, C):
        c.run("TICK(1)")
        check(c.eval("shown(v)") == "EngineBay", "%s: the hood removed: the bay" % c.player)
    net.item(7, "EngineDoor", True)
    for c in (A, B, C):
        c.run("TICK(%d)" % HOLD)
        check(c.eval("shown(v)") == "EngineBayLow", "%s: the hood refitted shut: the stand-in" % c.player)
    S.run("TICK(50)")
    check(S.eval("v.parts.CRVEngineBay.calls") == 0, "server: no setModelVisible, ever")


def main():
    single_player()
    multiplayer()
    print("\n%d FAIL(S)" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    if FAILS:
        return 1
    print("BAY LUA TESTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
