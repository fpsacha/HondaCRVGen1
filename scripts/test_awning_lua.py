"""
The awning feature's Lua (shared/HondaCRVGen1_Awning.lua, shared/TimedActions/ISCRVAwning.lua,
server/HondaCRVGen1_AwningRain.lua, client/HondaCRVGen1_AwningMenu.lua) under Lua 5.1 (lupa; PZ's Kahlua is a
Lua 5.1) on scripts/lua_harness.py, single player and a dedicated server with two clients:

  * fitting it shows the bag alone; rolling it out (the timed action's complete(), authoritative side only)
    shows the canopy and the poles on every side that draws the car, rolling it up hides them again;
  * the rules: engine off, standing still, out of the car, not broken; the car rolls it up itself when its
    engine runs, and tears it when it moves fast with it out; removing it rolls it up;
  * the footprint (Awning.AREA is features/awning.py's footprint(), the canopy the build makes; the car's local
    frame through getLocalPos and the script's model scale; its ends and edges) and the cut-away:
    a client hides the canopy (not the poles) while ITS player stands under it, every other client keeps it;
    Project Viewpoint's first / third person keep it;
  * the rain: where the game is authoritative (single player, the server; never a multiplayer client), a
    player under a rolled-out awning keeps the wetness it had when it stepped under (the stat, every body
    part, every worn clothing item) while it rains, dries at the indoor rate, and gets wet again once out;
  * the menus: the right-click option and the radial slice, greyed with the reason when blocked;
  * NetTimedAction: every new() parameter of ISCRVAwning is stored under its own name.

    python scripts\\test_awning_lua.py
"""
import sys

from features import awning
from lua_harness import Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
FILES = STATE + ("shared/HondaCRVGen1_Awning.lua", "shared/HondaCRVGen1_Lift.lua", "shared/TimedActions/ISCRVAwning.lua",
                 "server/HondaCRVGen1_AwningRain.lua")
MENU = ("client/HondaCRVGen1_AwningMenu.lua",)

# what the harness does not fake: timed actions, the car's frame and engine, players' wetness, the climate
GAME = r'''
ISBaseTimedAction = {}
ISBaseTimedAction.__index = ISBaseTimedAction
function ISBaseTimedAction:derive(t) local o = {}; setmetatable(o, self); self.__index = self; o.Type = t; return o end
function ISBaseTimedAction.new(self, character)
    local o = {}; setmetatable(o, self); self.__index = self; o.character = character; return o
end
function ISBaseTimedAction:perform() self.performed = true end
function ISBaseTimedAction:stop() self.stopped = true end
function ISBaseTimedAction:setActionAnim(a) self.anim = a end
HALO = {}
HaloTextHelper = { addText = function(c, t) HALO[#HALO + 1] = t end, addBadText = function(c, t) HALO[#HALO + 1] = "BAD:" .. t end }
VehicleUtils = { createPartInventoryItem = function(part) local it = newItem("Base.CRVGen1_Awning"); part:setInventoryItem(it); return it end }

-- joml Vector3f and the car's frame: the car faces north (-y), its left is west (-x); local units = mesh metres x scale
V3 = {}
V3.__index = V3
Vector3f = { new = function() return setmetatable({ X = 0, Y = 0, Z = 0 }, V3) end }
function V3:x() return self.X end
function V3:y() return self.Y end
function V3:z() return self.Z end
SCALE = 0.9
function Veh:getScript() return { getModelScale = function() return SCALE end } end
function Veh:getZ() return self.z or 0 end
function Veh:getLocalPos(x, y, z, out)
    out.X = -(x - self.x); out.Y = z - (self.z or 0); out.Z = -(y - self.y)
    return out
end
function Veh:isEngineRunning() return self.running == true end
function Veh:getCurrentSpeedKmHour() return self.speed or 0 end
function Veh:getDriver() return self.driver end
-- a point of the car's mesh (metres, +x right, +y forward) in the world
function worldAt(v, mx, my) return v.x + mx * SCALE, v.y - my * SCALE end

-- players: wetness (stat, body parts, worn clothing), floors, online ids
CharacterStat = { WETNESS = "WETNESS" }
NEXT_ONLINE = 0
local newPlayer0 = newPlayer
function newPlayer(name, x, y)
    local p = newPlayer0(name, x, y)
    NEXT_ONLINE = NEXT_ONLINE + 1
    p.onlineId, p.z, p.dead, p.num = NEXT_ONLINE, 0, false, 0
    p.stat = 0
    p.parts = {}
    for i = 1, 3 do p.parts[i] = { w = 0 } end
    p.worn = { { clothing = true, w = 0 }, { clothing = false, w = 0 } }
    return p
end
BP = {}
BP.__index = BP
function BP:getWetness() return self.w end
function BP:setWetness(w) self.w = w end
function Player:getZ() return self.z end
function Player:isDead() return self.dead end
function Player:getPlayerNum() return self.num end
function Player:getOnlineID() return self.onlineId end
function Player:getStats()
    local p = self
    return { get = function(_, s) return p.stat end, set = function(_, s, v) p.stat = v end }
end
function Player:getBodyDamage()
    local p = self
    return { getBodyParts = function()
        return { size = function() return #p.parts end, get = function(_, i) return setmetatable(p.parts[i + 1], BP) end }
    end }
end
function Player:getWornItems()
    local p = self
    return { size = function() return #p.worn end, getItemByIndex = function(_, i)
        local w = p.worn[i + 1]
        return { IsClothing = function() return w.clothing end, getWetness = function() return w.w end,
                 setWetness = function(_, v) w.w = v end, w = w }
    end }
end
function Player:faceThisObject() end
function Player:shouldBeTurning() return false end
function Player:isTimedActionInstant() return false end
function Player:SetVariable() end
function Player:playSound() return 3 end
function Player:stopOrTriggerSound() end
function Player:getEmitter() return { isPlaying = function() return true end } end
-- the worn items are rebuilt per call above: the clothing table key must be stable (the game hands the same
-- InventoryItem object each time), so cache them
local worn0 = Player.getWornItems
function Player:getWornItems()
    self.wornObjs = self.wornObjs or {}
    local base = worn0(self)
    local p = self
    return { size = base.size, getItemByIndex = function(_, i)
        if not p.wornObjs[i] then p.wornObjs[i] = base:getItemByIndex(i) end
        return p.wornObjs[i]
    end }
end
LOCAL = {}
function getNumActivePlayers() return #LOCAL end
function getSpecificPlayer(i) return LOCAL[i + 1] end
ONLINE = {}
function getOnlinePlayers() return { size = function() return #ONLINE end, get = function(_, i) return ONLINE[i + 1] end } end
RAINING, TEMP = false, 15
ClimateManager = { getInstance = function() return { isRaining = function() return RAINING end,
                                                     getTemperature = function() return TEMP end } end }
function getGameTime() return { getMultiplier = function() return 1.0 end } end
NOW = 0
function getTimeInMillis() return NOW end
DAMAGE_SENT = 0
function sendDamage(p) DAMAGE_SENT = DAMAGE_SENT + 1 end

function car(id)
    local v = newVehicle(id, { "CRVAwning" })
    v.parts.CRVAwning.models = { "CRVAwning", "AwningCanopy", "AwningPoles" }
    return v
end
function vis(v) local p = v.parts.CRVAwning
    return (p.visible.CRVAwning and "B" or "-") .. (p.visible.AwningCanopy and "C" or "-") .. (p.visible.AwningPoles and "P" or "-")
end
function rain(p, k)                 -- what one tick of the game's rain adds
    p.stat = p.stat + k
    for _, bp in ipairs(p.parts) do bp.w = bp.w + k end
    for _, w in ipairs(p.worn) do w.w = w.w + k end
end
function wet(p) return string.format("%.3f/%.3f/%.3f/%.3f", p.stat, p.parts[1].w, p.worn[1].w, p.worn[2].w) end
A = HondaCRVGen1 and HondaCRVGen1.Awning
'''

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


def side(role, net=None, player=None, extra=()):
    s = Side(role, net, player=player)
    s.run(GAME)
    if player:
        s.run("PLAYER = newPlayer(%r)" % player)        # again: GAME's players carry wetness and a floor
    s.load(*(FILES + tuple(extra)))
    s.run("A = HondaCRVGen1.Awning")
    return s


def single_player():
    print("-- single player")
    sp = side("sp")
    sp.run("PLAYER = newPlayer('sam', 100, 100); LOCAL = { PLAYER }; v = car(1); A.Init(v, v.parts.CRVAwning)")
    check(sp.eval("vis(v)") == "---", "no item: nothing drawn")
    sp.run("v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(v, v.parts.CRVAwning)")
    check(sp.eval("vis(v)") == "B--", "fitted: the bag alone (%s)" % sp.eval("vis(v)"))
    check(sp.eval("A.isDeployed(v)") is False, "fitted rolled up")
    # the rules
    sp.run("v.running = true; ok1, why1 = A.canSet(v, PLAYER, true); v.running = false")
    check(sp.eval("ok1") is False and sp.eval("why1") == "Tooltip_CRV_Awning_EngineOn", "engine running: refused")
    sp.run("v.speed = 5; ok2, why2 = A.canSet(v, PLAYER, true); v.speed = 0")
    check(sp.eval("ok2") is False and sp.eval("why2") == "Tooltip_CRV_Awning_Moving", "moving: refused")
    sp.run("PLAYER.vehicle = v; ok3, why3 = A.canSet(v, PLAYER, true); PLAYER.vehicle = nil")
    check(sp.eval("ok3") is False and sp.eval("why3") == "Tooltip_CRV_Awning_Inside", "from inside the car: refused")
    sp.run("v.parts.CRVAwning.cond = 0; ok4, why4 = A.canSet(v, PLAYER, true); v.parts.CRVAwning.cond = 100")
    check(sp.eval("ok4") is False and sp.eval("why4") == "Tooltip_CRV_Awning_Broken", "broken: refused")
    check(sp.eval("A.canSet(v, PLAYER, false)") is False, "rolling up a rolled-up awning: refused")
    # the timed action: perform() is feedback only, complete() changes the state
    sp.run("act = ISCRVAwning:new(PLAYER, v, true)")
    check(sp.eval("act.character == PLAYER and act.vehicle == v and act.on == true"), "new() keeps character, vehicle, on")
    check(sp.eval("act:isValid()") is True, "the action is valid")
    sp.run("HALO = {}; act:start(); act:perform()")
    check(sp.eval("A.isDeployed(v)") is False and sp.eval("#HALO") == 0,
          "perform(): no state, no outcome text yet (the authoritative side may still refuse)")
    check(sp.eval("act:complete()") is True and sp.eval("A.isDeployed(v)") is True, "complete(): rolled out")
    check(sp.eval("HALO[#HALO]") == "IGUI_CRV_Awning_Deployed", "complete(): the player is told it is out")
    check(sp.eval("vis(v)") == "BCP", "rolled out: bag, canopy, poles (%s)" % sp.eval("vis(v)"))
    check(sp.eval("v.parts.CRVAwning.md.crv_awning_deployed") is True, "the state is in the part's mod data")
    # the footprint and the cut-away: the Lua's AREA is the canopy features/awning.py builds (footprint())
    x0, x1, y0, y1 = awning.footprint()
    lua = tuple(sp.eval("A.AREA.%s" % k) for k in ("x0", "x1", "y0", "y1"))
    check(all(abs(a - b) < 1e-6 for a, b in zip(lua, (x0, x1, y0, y1))),
          "Awning.AREA %s is the built canopy's footprint %s" % (lua, tuple(round(c, 4) for c in (x0, x1, y0, y1))))
    check(abs((y1 - y0) - 2.74) < 0.01 and abs((x1 - x0) - 1.815) < 0.01,
          "the footprint is 2.74 m along the car, 1.8 m out from it (%.3f x %.3f)" % (y1 - y0, x1 - x0))
    sp.run("PLAYER.x, PLAYER.y = worldAt(v, 1.6, -0.6); TICK(5)")
    check(sp.eval("A.isUnder(v, PLAYER)") is True, "a player beside the right doors is under it")
    check(sp.eval("vis(v)") == "B-P", "the player under it: canopy cut away, poles kept (%s)" % sp.eval("vis(v)"))
    for (mx, my, what) in ((1.6, y1 - 0.1, "under its front end (by the front door's hinge)"),
                           (1.6, y0 + 0.1, "under its rear end (behind the rear wheel)"),
                           (x1 - 0.05, -0.6, "just inside the poles")):
        sp.run("PLAYER.x, PLAYER.y = worldAt(v, %r, %r)" % (mx, my))
        check(sp.eval("A.isUnder(v, PLAYER)") is True, "under it: %s" % what)
    for (mx, my, what) in ((-1.6, -0.6, "the left side"), (x1 + 0.25, -0.6, "past the poles"), (1.6, y1 + 0.2, "ahead of it"),
                           (1.6, y0 - 0.2, "behind it"), (0.5, -0.6, "the car's own roof line")):
        sp.run("PLAYER.x, PLAYER.y = worldAt(v, %r, %r)" % (mx, my))
        check(sp.eval("A.isUnder(v, PLAYER)") is False, "not under it: %s" % what)
    sp.run("TICK(5)")
    check(sp.eval("vis(v)") == "BCP", "out from under it: the canopy is back")
    sp.run("PLAYER.x, PLAYER.y = worldAt(v, 1.6, -0.6); PLAYER.z = 1")
    check(sp.eval("A.isUnder(v, PLAYER)") is False, "a floor up: not under it")
    sp.run("PLAYER.z = 0; Viewpoint = { View = { next = function() return 'third' end } }; TICK(5)")
    check(sp.eval("vis(v)") == "BCP", "Viewpoint first person: the canopy stays")
    sp.run("Viewpoint.View.next = function() return 'first' end; TICK(5)")
    check(sp.eval("vis(v)") == "B-P", "Viewpoint's isometric view: cut away")
    sp.run("Viewpoint = nil")
    # the rain: held while under it, dries at the indoor rate, soaks again out from under it
    sp.run("PLAYER.stat = 10; for _, bp in ipairs(PLAYER.parts) do bp.w = 10 end; PLAYER.worn[1].w = 20; RAINING = true; TICK(1)")
    sp.run("w0 = wet(PLAYER); for i = 1, 50 do rain(PLAYER, 0.5); TICK(1) end")
    st, bp, cl, other = (float(x) for x in sp.eval("wet(PLAYER)").split("/"))
    check(st <= 10.0 and bp <= 10.0 and cl <= 20.0 and st > 9.0, "under it in the rain: held (%s from %s)"
          % (sp.eval("wet(PLAYER)"), sp.eval("w0")))
    check(st < 10.0 and cl < 20.0, "under it: drying at the indoor rate (%s)" % sp.eval("wet(PLAYER)"))
    check(other > 20.0, "an item that is no clothing is left alone (%.1f)" % other)
    check(sp.eval("DAMAGE_SENT") == 0, "single player: no sendDamage")
    # the drying rate follows the air temperature at the character (UpdateWetness reads
    # getAirTemperatureForCharacter), the climate's own when that is missing
    base = sp.eval("A.Rain.dryStep(PLAYER)")
    sp.run("AIRT = 35; local get = ClimateManager.getInstance; ClimateManager.getInstance = function() local c = get(); "
           "c.getAirTemperatureForCharacter = function(self, p) return AIRT end; return c end")
    warm = sp.eval("A.Rain.dryStep(PLAYER)")
    check(abs(base - 0.011) < 1e-6 and abs(warm - 0.031) < 1e-6,
          "drying at the character's air temperature (15 C climate %.4f, 35 C beside a fire %.4f)" % (base, warm))
    sp.run("PLAYER.x, PLAYER.y = worldAt(v, -1.6, -0.6); s0 = PLAYER.stat; rain(PLAYER, 1.0); TICK(1)")
    check(sp.eval("PLAYER.stat") == sp.eval("s0") + 1.0, "out from under it: the rain counts again")
    sp.run("PLAYER.x, PLAYER.y = worldAt(v, 1.6, -0.6); RAINING = false; TICK(1); s0 = PLAYER.stat; rain(PLAYER, 1.0); TICK(1)")
    check(sp.eval("PLAYER.stat") == sp.eval("s0") + 1.0, "no rain: the game's own rules (nothing held)")
    # auto-stow: the engine starts
    sp.run("v.running = true; v.driver = PLAYER; TICK(20)")
    check(sp.eval("A.isDeployed(v)") is False and sp.eval("vis(v)") == "B--", "engine started: rolled up by itself")
    check(sp.eval("v.parts.CRVAwning.cond") == 100, "rolled up at rest: no damage")
    check(sp.eval("HALO[#HALO]") == "IGUI_CRV_Awning_AutoStowed", "the driver is told")
    sp.run("v.running = false; A.set(v, true); v.speed = 20; TICK(20)")
    check(sp.eval("A.isDeployed(v)") is False and sp.eval("v.parts.CRVAwning.cond") == 80, "moved fast with it out: torn (-20)")
    check(sp.eval("HALO[#HALO]") == "IGUI_CRV_Awning_Torn", "the driver is told it tore")
    sp.run("v.speed = 0; v.driver = nil")
    # removal rolls it up; an old save with it out but no part item goes back
    sp.run("A.set(v, true); it = v.parts.CRVAwning.item; v.parts.CRVAwning:setInventoryItem(nil); A.UninstallComplete(v, v.parts.CRVAwning, it)")
    check(sp.eval("A.isDeployed(v)") is False and sp.eval("v.parts.CRVAwning.md.crv_awning_deployed") is None,
          "removed: rolled up")
    sp.run("w = car(2); w.parts.CRVAwning.md.crv_awning_deployed = true; A.Init(w, w.parts.CRVAwning)")
    check(sp.eval("w.parts.CRVAwning.md.crv_awning_deployed") is None, "out without the part: back to rolled up")
    # the spawn roll
    sp.run("n = 0; for i = 1, 2000 do local c = car(100 + i); A.Create(c, c.parts.CRVAwning); if c.parts.CRVAwning.item then n = n + 1 end end")
    n = sp.eval("n")
    check(20 <= n <= 110, "spawns on ~3%% of the cars (%d of 2000)" % n)


def menus():
    print("-- menus")
    sp = Side("sp")
    sp.run(GAME)
    sp.run(r'''
ISVehicleMenu = { FillMenuOutsideVehicle = function() return "vanilla" end, showRadialMenuOutside = function() end,
                  getVehicleToInteractWith = function() return VEH end }
ISWorldObjectContextMenu = { addToolTip = function() return {} end }
QUEUE = {}
ISTimedActionQueue = { add = function(a) QUEUE[#QUEUE + 1] = a end }
ISPathFindAction = { pathToVehicleArea = function(self, p, v, area) return { Type = "walk", area = area } end }
function getTexture(p) return p end
RAD = newRadial()
function getPlayerRadialMenu() return RAD end
Ctx = {}
Ctx.__index = Ctx
function newCtx() return setmetatable({ options = {} }, Ctx) end
function Ctx:addOption(text, target, fn, a, b) local o = { name = text, target = target, fn = fn, a = a, b = b }
    table.insert(self.options, o); return o end
''')
    sp.load(*(FILES + MENU))
    sp.run("A = HondaCRVGen1.Awning; PLAYER = newPlayer('sam'); LOCAL = { PLAYER }; VEH = car(1); A.Init(VEH, VEH.parts.CRVAwning)")
    sp.run("ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, VEH)")
    check(sp.eval("#ctx.options") == 0, "no awning fitted: no option")
    sp.run("VEH.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(VEH, VEH.parts.CRVAwning)")
    sp.run("ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, VEH)")
    check(sp.eval("ctx.options[1] and ctx.options[1].name") == "ContextMenu_CRV_Awning_Deploy", "fitted: roll it out")
    sp.run("ctx.options[1].fn(ctx.options[1].target, ctx.options[1].a, ctx.options[1].b)")
    check(sp.eval("QUEUE[1].area") == "SeatRearRight" and sp.eval("QUEUE[2].Type") == "ISCRVAwning" and sp.eval("QUEUE[2].on") is True,
          "the option walks to the right rear door, then the action")
    sp.run("VEH.running = true; ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, VEH)")
    check(sp.eval("ctx.options[1].notAvailable") is True and sp.eval("ctx.options[1].toolTip.description") == "Tooltip_CRV_Awning_EngineOn",
          "engine running: greyed, with why")
    sp.run("ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(sp.eval("RAD:texts()") == "ContextMenu_CRV_Awning_Deploy [Tooltip_CRV_Awning_EngineOn]!", "radial: a blocked slice (%s)"
          % sp.eval("RAD:texts()"))
    sp.run("VEH.running = false; A.set(VEH, true); RAD = newRadial(); ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(sp.eval("RAD:texts()") == "ContextMenu_CRV_Awning_Stow", "rolled out: the radial rolls it up (%s)" % sp.eval("RAD:texts()"))
    sp.run("QUEUE = {}; RAD:pick(RAD.slices[1])")
    check(sp.eval("QUEUE[2] and QUEUE[2].on") is False, "the slice queues rolling it up")


def multiplayer():
    print("-- multiplayer: a dedicated server, two clients")
    net = Net()
    server = side("server", net)
    a = side("client", net, player="ann")
    b = side("client", net, player="bob")
    check(server.eval("countHandlers and 1 or 1") == 1, "loaded")
    check(a.eval("EVENTS.OnTick and #EVENTS.OnTick") == 2, "a client runs the state poll and the cut-away, no rain loop (%s)"
          % a.eval("EVENTS.OnTick and #EVENTS.OnTick"))
    check(server.eval("EVENTS.OnTick and #EVENTS.OnTick") == 2, "the server runs the auto-stow and the rain loop (%s)"
          % server.eval("EVENTS.OnTick and #EVENTS.OnTick"))
    server.run("ANN = newPlayer('ann', 100, 100); BOB = newPlayer('bob', 100, 100); ONLINE = { ANN, BOB }")
    for s in (server, a, b):
        s.run("v = car(1); A.Init(v, v.parts.CRVAwning)")
    for c in (a, b):
        c.run("LOCAL = { PLAYER }")
    # the server installs it: the clients get the item (all models shown), their poll puts the canopy away
    server.run("v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(v, v.parts.CRVAwning)")
    net.sync_item(1, "CRVAwning")
    net.pump()
    check(a.eval("vis(v)") == "BCP", "client: the item arrived, every model shown by the engine")
    for c in (a, b):
        c.run("TICK(30)")
    check(a.eval("vis(v)") == "B--" and b.eval("vis(v)") == "B--", "clients: the poll leaves the bag alone (%s %s)"
          % (a.eval("vis(v)"), b.eval("vis(v)")))
    # a client's action: complete() on the server (NetTimedAction), the clients draw it
    a.run("act = ISCRVAwning:new(PLAYER, v, true)")
    check(a.eval("act:isValid()") is True, "client: the action is valid")
    a.run("act:perform()")
    check(a.eval("A.isDeployed(v)") is False, "client perform(): no state change on the client")
    server.run("sact = ISCRVAwning:new(ANN, v, true)")
    check(server.eval("sact:complete()") is True, "server complete(): rolled out")
    net.pump()
    check(a.eval("A.isDeployed(v)") is True and b.eval("A.isDeployed(v)") is True, "both clients know")
    check(a.eval("vis(v)") == "BCP" and b.eval("vis(v)") == "BCP", "both clients draw the canopy and the poles")
    check(a.eval("act:isValid()") is True, "client: the state flipping under the action does not cancel it")
    check(a.eval("(A.set(v, false))") is False, "a client cannot set the state")
    # ann walks under it: only ann's client cuts it away
    a.run("PLAYER.x, PLAYER.y = worldAt(v, 1.6, -0.6); TICK(5)")
    b.run("TICK(5)")
    check(a.eval("vis(v)") == "B-P" and b.eval("vis(v)") == "BCP", "ann under it: her client cuts the canopy away, bob's keeps it")
    # rain on the server for ann (under it) and bob (beside the car's left)
    server.run("ANN.x, ANN.y = worldAt(v, 1.6, -0.6); BOB.x, BOB.y = worldAt(v, -1.6, -0.6); ANN.stat, BOB.stat = 5, 5")
    server.run("RAINING = true; TICK(1); for i = 1, 30 do rain(ANN, 0.5); rain(BOB, 0.5); NOW = NOW + 100; TICK(1) end")
    check(server.eval("ANN.stat") <= 5.0 and server.eval("BOB.stat") == 20.0, "server: ann held at %.2f, bob soaked to %.1f"
          % (server.eval("ANN.stat"), server.eval("BOB.stat")))
    sent = server.eval("DAMAGE_SENT")
    check(2 <= sent <= 4, "server: the body damage sent about once a second (%d in 3 s)" % sent)
    a.run("PLAYER.stat = 5; RAINING = true; rain(PLAYER, 1.0); TICK(3)")
    check(a.eval("PLAYER.stat") == 6.0, "client: no wetness changes (the server owns them)")
    # the engine starts on the server's copy: rolled up everywhere
    server.run("RAINING = false; v.running = true; TICK(20)")
    net.pump()
    check(a.eval("A.isDeployed(v)") is False and a.eval("vis(v)") == "B--" and b.eval("vis(v)") == "B--",
          "engine started: rolled up on the server, every client hides it")


def reach_and_outcome():
    """H-LUA-I3 / I4 (2026-10-24): the server never runs isValid for a client's action, so complete() re-checks the
    player is at the car (State.near); and perform() no longer shows "rolled out" before the authoritative side has
    decided: complete() reports the outcome (Lift.report: a halo in single player, the server's "result" command to
    the acting client in multiplayer)."""
    print("-- reach and outcome")
    sp = side("sp")
    sp.run("PLAYER = newPlayer('sam', 100, 100); LOCAL = { PLAYER }; v = car(1); A.Init(v, v.parts.CRVAwning); "
           "v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(v, v.parts.CRVAwning)")
    sp.run("HALO = {}; act = ISCRVAwning:new(PLAYER, v, true); act:start(); act:perform(); PLAYER.x = 100 + HondaCRVGen1.State.REACH + 1")
    check(sp.eval("act:complete()") is False and sp.eval("A.isDeployed(v)") is False and sp.eval("#HALO") == 0,
          "the player walked off before complete(): refused, nothing said, nothing rolled out")
    sp.run("PLAYER.x = 100; v.running = true")
    check(sp.eval("act:complete()") is False and sp.eval("HALO[#HALO]") == "BAD:Tooltip_CRV_Awning_EngineOn",
          "refused at complete(): the reason, as a bad halo (%s)" % sp.eval("HALO[#HALO]"))
    sp.run("v.running = false")
    check(sp.eval("act:complete()") is True and sp.eval("HALO[#HALO]") == "IGUI_CRV_Awning_Deployed", "done: the halo")
    # multiplayer: ann's client performs, the server decides and answers her client only with the outcome
    net = Net()
    server = side("server", net)
    a = side("client", net, player="ann")
    server.run("ANN = newPlayer('ann', 100, 100); ONLINE = { ANN }; v = car(1); A.Init(v, v.parts.CRVAwning); "
               "v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(v, v.parts.CRVAwning)")
    a.run("v = car(1); v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.Init(v, v.parts.CRVAwning); "
          "RESULTS = {}; Events.OnServerCommand.Add(function(m, c, args) if m == HondaCRVGen1.Lift.COMMAND then "
          "RESULTS[#RESULTS + 1] = tostring(args.ok) .. ':' .. tostring(args.key) end end)")
    a.run("HALO = {}; act = ISCRVAwning:new(PLAYER, v, true); act:perform()")
    check(a.eval("#HALO") == 0, "ann's perform(): no 'rolled out' halo before the server decides")
    server.run("ANN.x = 100 + HondaCRVGen1.State.REACH + 2; sact = ISCRVAwning:new(ANN, v, true)")
    check(server.eval("sact:complete()") is False and server.eval("A.isDeployed(v)") is False, "server: ann too far, refused")
    server.run("ANN.x = 100; v.running = true")
    check(server.eval("sact:complete()") is False, "server: the engine runs, refused")
    server.run("v.running = false")
    check(server.eval("sact:complete()") is True, "server: rolled out")
    net.pump()
    check(a.eval("table.concat(RESULTS, ',')") == "false:Tooltip_CRV_Awning_EngineOn,true:IGUI_CRV_Awning_Deployed",
          "ann's client hears the refusal's reason and the success (%s)" % a.eval("table.concat(RESULTS, ',')"))
    print("REACH / OUTCOME: complete() re-checks the reach; the outcome comes from the authoritative side")


def prune_client():
    """H-LUA-3 (2026-10-24): Awning.shown (and, on a client, Awning.out: the cut-away's list, which only the server's
    tick pruned) kept every CR-V a client drew; the State poll / the cut-away tick now drop the cars that left."""
    print("-- caches")
    c = side("client", Net(), player="bob")
    c.run("LOCAL = { PLAYER }; for id = 1, 40 do local v = car(id); v.parts.CRVAwning.item = newItem('Base.CRVGen1_Awning'); "
          "v.parts.CRVAwning.md.crv_awning_deployed = true; A.Init(v, v.parts.CRVAwning) end")
    count = "(function() local n, m = 0, 0 for _ in pairs(A.shown) do n = n + 1 end for _ in pairs(A.out) do m = m + 1 end return n .. '/' .. m end)()"
    check(c.eval(count) == "40/40", "40 rolled-out awnings drawn (%s)" % c.eval(count))
    c.run("for id = 1, 40 do VEHICLES[id].removed = true; VEHICLES[id] = nil end; TICK(HondaCRVGen1.State.POLL)")
    check(c.eval(count) == "0/0", "they left the world: shown / out empty (%s)" % c.eval(count))


def _reorder_run(order_of, strip_seq=False):
    """The hunt's probe (H-MP-1): ann's client sees the awning rolled out (C1 command, U1 mod data), then the driver
    starts the engine and the server stows it (C2, U2). Every server -> client packet of the two changes is delivered
    in the order order_of(packets) picks, the client polling between packets. Returns (client, server) deployed.
    strip_seq: the announcements without their numbers (the pre-fix client), to show what the test catches."""
    net = Net()
    server = side("server", net)
    a = side("client", net, player="ann")
    server.run("ANN = newPlayer('ann', 100, 100); ONLINE = { ANN }")
    for s in (server, a):
        s.run("v = car(1); A.Init(v, v.parts.CRVAwning)")
    a.run("LOCAL = { PLAYER }")
    server.run("v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); A.InstallComplete(v, v.parts.CRVAwning)")
    net.sync_item(1, "CRVAwning")
    net.pump()
    a.run("TICK(30)")
    server.run("sact = ISCRVAwning:new(ANN, v, true); assert(sact:complete())")
    first = net.take()
    server.run("v.running = true; TICK(20)")
    packets = first + net.take()
    if strip_seq:
        packets = [(k, (p[0], p[1], {x: y for x, y in p[2].items() if x not in ("seq", "session")}) + tuple(p[3:]))
                   if k == "cmd" else (k, p) for k, p in packets]
    net.deliver(order_of(packets), between=lambda pk: a.run("TICK(30)"))
    a.run("TICK(300)")
    return a.eval("A.isDeployed(v)"), server.eval("A.isDeployed(v)"), packets


def reordered_delivery():
    """H-MP-1 (2026-10-24): server commands are RELIABLE but UNORDERED in 42.21 (PacketTypes.ClientCommand), the part
    mod data rides the ORDERED VehicleUpdate: a resent old "changed" landing after a newer one used to write the old
    value into the client's mod data for good (the hunt: a late C1 left ann's client drawing the awning out after the
    server stowed it). State numbers every announcement; the client drops one older than what it applied. Every
    delivery order the net allows (Net.legal_orders) must leave the client where the server is."""
    print("-- multiplayer: every delivery order of two quick changes")
    _, _, packets = _reorder_run(lambda p: p)
    cmds = [p for k, p in packets if k == "cmd" and p[0] == "HondaCRVGen1" and p[1] == "changed"]
    check(len(cmds) == 2 and all(isinstance(c[2].get("seq"), (int, float)) for c in cmds)
          and cmds[0][2]["seq"] < cmds[1][2]["seq"] and cmds[0][2]["session"] == cmds[1][2]["session"],
          "the two announcements carry rising numbers of one server run (%s)" % [c[2] for c in cmds])
    orders = list(Net.legal_orders(packets))
    check(len(orders) >= 12, "%d packets, %d legal delivery orders" % (len(packets), len(orders)))
    bad, bad_old = 0, 0
    for i in range(len(orders)):
        cl, sv, _ = _reorder_run(lambda p, i=i: list(Net.legal_orders(p))[i])
        bad += cl != sv
        cl, sv, _ = _reorder_run(lambda p, i=i: list(Net.legal_orders(p))[i], strip_seq=True)
        bad_old += cl != sv
    check(bad == 0, "%d of %d legal delivery orders leave the client wrong for good" % (bad, len(orders)))
    check(bad_old > 0, "the test catches the bug: without the numbers %d of %d orders desync" % (bad_old, len(orders)))


def towing():
    """H-MP-I2 (2026-10-24): a hitched car (towing or towed: BaseVehicle.getVehicleTowing / getVehicleTowedBy) cannot
    roll the awning out, and the authoritative side rolls one up that is out when the car gets hitched (a towed car
    moves without its engine and could be under its tear speed, so the speed test alone left it out)."""
    print("-- towing")
    sp = side("sp", player="tester")
    sp.run("v = car(1); A.Init(v, v.parts.CRVAwning); v.parts.CRVAwning:setInventoryItem(newItem('Base.CRVGen1_Awning')); "
           "A.InstallComplete(v, v.parts.CRVAwning); other = newVehicle(9, {}, 'Base.SUV')")
    sp.run("function Veh:getVehicleTowing() return self.towing end; function Veh:getVehicleTowedBy() return self.towedBy end")
    for field in ("towing", "towedBy"):
        sp.run("v.%s = other; ok, why = A.canSet(v, PLAYER, true)" % field)
        check(sp.eval("ok") is False and sp.eval("why") == "Tooltip_CRV_Lift_Trailer", "%s: rolling out refused (%s)"
              % (field, sp.eval("why")))
        sp.run("v.%s = nil" % field)
    check(sp.eval("(A.canSet(v, PLAYER, true))") is True, "unhitched: allowed")
    sp.run("sact = ISCRVAwning:new(PLAYER, v, true); assert(sact:complete())")
    check(sp.eval("A.isDeployed(v)") is True, "rolled out")
    sp.run("v.towedBy = other; TICK(A.EVERY)")
    check(sp.eval("A.isDeployed(v)") is False and sp.eval("v.parts.CRVAwning:getCondition()") == 100,
          "towed away (standing still, engine off): rolled up by the car, not torn")
    sp.run("v.towedBy = nil; sact = ISCRVAwning:new(PLAYER, v, true); assert(sact:complete()); v.towing = other; TICK(A.EVERY)")
    check(sp.eval("A.isDeployed(v)") is False, "hitched to a trailer with it out: rolled up")


def main():
    single_player()
    menus()
    multiplayer()
    reach_and_outcome()
    prune_client()
    reordered_delivery()
    towing()
    print("\n%d FAIL" % len(FAILS) if FAILS else "\nALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
