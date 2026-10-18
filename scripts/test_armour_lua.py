"""
The armour feature's Lua under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1) on scripts/lua_harness.py:
single player, then a multiplayer server with two clients.

    python scripts\test_armour_lua.py

Checks: the guard part shows only the installed item's model (bars / mesh / rear plate) on init, after
an install and, on a multiplayer client, once the State poll sees the item change; an armoured window
is shut on install and cannot be opened (client and server), closing still works; the door plate keeps
its door's condition and wears through the fractional accumulator scaled by ArmourStrength; a plate
at 0 protects nothing; the mesh variant wears like armour and the bars like bars; a door with its plate
cannot be uninstalled; protection runs only where the game is authoritative.
"""
import sys

from lua_harness import Net, Side

FILES = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua",
         "shared/HondaCRVGen1_Armour.lua", "server/Vehicles/HondaCRVGen1Accessories.lua",
         "server/Vehicles/HondaCRVGen1_ArmourServer.lua")

# what the harness lacks for this feature, kept in this test (lua_harness stays generic)
FAKES = r'''
function Item:getFullType() return self.type end
SandboxVars = { HondaCRVGen1 = { ArmourStrength = 1.0 } }
-- vanilla createPartInventoryItem: a random type of the part's list unless the car chose one under the key
JList = {}
JList.__index = JList
function JList:size() return #self end
function JList:get(i) return self[i + 1] end
JMap = {}
JMap.__index = JMap
function JMap:get(k) return self.t[k] end
function JMap:put(k, v) self.t[k] = v end
function Part:getItemType() return self.types end
function Veh:getChoosenParts() self.chosen = self.chosen or setmetatable({ t = {} }, JMap); return self.chosen end
VehicleUtils = { createPartInventoryItem = function(part)
    local types = part:getItemType()
    if not types or types:size() == 0 then part.item = newItem("Base.X"); return end
    local key = ""
    for i = 1, types:size() do key = key .. types:get(i - 1) .. ";" end
    local t = part:getVehicle():getChoosenParts():get(key)
    if not t then
        t = types:get(ZombRand(types:size()))
        part:getVehicle():getChoosenParts():put(key, t)
    end
    part.item = newItem(t)
end }
Window = {}
Window.__index = Window
function Window:isOpen() return self.open end
function Window:setOpen(o) self.open = o end
function Window:isDestroyed() return false end
function Part:getWindow() return self.window end
function Veh:transmitPartWindow(p) SENT.window = (SENT.window or 0) + 1 end
-- the vanilla pieces the armour wraps
ISOpenCloseVehicleWindow = {}
function ISOpenCloseVehicleWindow.isValid(self) return self.window ~= nil and self.window:isOpen() ~= self.open end
function ISOpenCloseVehicleWindow.new(self, character, part, open)
    return setmetatable({ character = character, part = part, vehicle = part.vehicle, window = part.window, open = open },
                        { __index = ISOpenCloseVehicleWindow })
end
Vehicles = { UninstallTest = { Default = function(vehicle, part, chr) return part:getInventoryItem() ~= nil end },
             Update = {} }
-- vanilla driving wear (Vehicles.lua): 1 point per event through Vehicles.LowerCondition, called by name
function Vehicles.LowerCondition(vehicle, part, elapsedMinutes)
    if part:getInventoryItem() and part:getCondition() > 0 then part:setCondition(part:getCondition() - 1) end
    return 1
end
function Vehicles.Update.Tire(vehicle, part, elapsedMinutes) return Vehicles.LowerCondition(vehicle, part, elapsedMinutes) end
HALO = 0
HaloTextHelper = { addText = function(chr, text) HALO = HALO + 1 end }

PARTS = { "DoorFrontLeft", "DoorRearLeft", "WindowFrontLeft", "WindowRearLeft", "WindshieldRear", "TrunkDoor",
          "CRVGuardFrontLeft", "CRVGuardRearLeft", "CRVGuardWindshieldRear", "CRVArmourDoorFrontLeft",
          "CRVArmourDoorRearLeft", "CRVArmourArchFrontLeft", "TireFrontLeft" }
function crv(id)
    local v = newVehicle(id, PARTS)
    for _, pid in ipairs({ "DoorFrontLeft", "DoorRearLeft", "WindowFrontLeft", "WindowRearLeft", "WindshieldRear", "TrunkDoor",
                           "TireFrontLeft" }) do
        v.parts[pid].item = newItem("Base." .. pid)
    end
    for _, pid in ipairs({ "WindowFrontLeft", "WindowRearLeft", "WindshieldRear" }) do
        v.parts[pid].window = setmetatable({ open = false }, Window)
    end
    v.parts.CRVGuardFrontLeft.models = { "CRVGuardFrontLeft", "ArmourMesh" }
    v.parts.CRVGuardRearLeft.models = { "CRVGuardRearLeft", "ArmourMesh" }
    v.parts.CRVGuardWindshieldRear.models = { "CRVGuardWindshieldRear", "ArmourPlate" }
    v.parts.CRVArmourDoorFrontLeft.models = { "CRVArmourDoorFrontLeft" }
    return v
end
-- what ISInstallVehiclePart:complete does on the authoritative side: set the item, then the part's complete Lua
function install(v, pid, itemType, complete)
    local p = v.parts[pid]
    p:setInventoryItem(newItem(itemType))
    complete(v, p)
end
function visibleList(p)
    local out = {}
    for _, m in ipairs(p.models or {}) do if p.visible[m] then out[#out + 1] = m end end
    return table.concat(out, ",")
end
'''

A = "HondaCRVGen1.Armour"
ACC = "HondaCRVGen1.Acc"


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)


def side(role, net=None, player=None):
    s = Side(role, net, player=player)
    s.run(FAKES)
    s.load(*FILES)
    return s


def single_player():
    sp = side("sp", player="tester")
    sp.run("v = crv(1)")
    g = "v.parts.CRVGuardFrontLeft"
    # bars: the part's own model only
    sp.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_GuardWindowFront', %s.InstallComplete)" % ACC)
    check(sp.eval("visibleList(%s)" % g) == "CRVGuardFrontLeft", "bars show the bar model only: %s" % sp.eval("visibleList(%s)" % g))
    sp.run("%s:setInventoryItem(nil)" % g)
    check(sp.eval("visibleList(%s)" % g) == "", "uninstalled: nothing shows")
    # the window is open when the mesh goes on: it is shut, and cannot be opened again
    sp.run("v.parts.WindowFrontLeft.window.open = true")
    sp.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront', %s.InstallComplete)" % ACC)
    check(sp.eval("visibleList(%s)" % g) == "ArmourMesh", "mesh shows the mesh model only")
    check(sp.eval("v.parts.WindowFrontLeft.window.open") is False and sp.eval("SENT.window") == 1, "window shut on install")
    check(sp.eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowFrontLeft, true):isValid()") is False, "cannot open")
    check(sp.eval("HALO") == 1, "the player is told why")
    sp.run("v.parts.WindowFrontLeft.window.open = true")
    check(sp.eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowFrontLeft, false):isValid()") is True, "can close")
    sp.run("v.parts.WindowFrontLeft.window.open = false")
    check(sp.eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowRearLeft, true):isValid()") is True,
          "an unguarded window opens")
    # init on a loaded car (the engine showed every model): the mesh again
    sp.run("%s:setInventoryItem(%s.item); %s.Init(v, %s)" % (g, g, ACC, g))
    check(sp.eval("visibleList(%s)" % g) == "ArmourMesh", "init shows the mesh only")
    # rear plate variant on the gate glass guard
    sp.run("install(v, 'CRVGuardWindshieldRear', 'Base.CRVGen1_ArmourRearPlate', %s.InstallComplete)" % ACC)
    check(sp.eval("visibleList(v.parts.CRVGuardWindshieldRear)") == "ArmourPlate", "rear plate shows the plate only")

    # protection: the door plate keeps the door; 0.02 per absorbed point at strength 1
    sp.run("install(v, 'CRVArmourDoorFrontLeft', 'Base.CRVGen1_ArmourDoorFront', %s.InstallComplete)" % A)
    check(sp.eval("%s.watch[1] ~= nil" % ACC), "the car is watched")
    sp.run("TICK(3)")                                         # the snapshot
    d, p = "v.parts.DoorFrontLeft", "v.parts.CRVArmourDoorFrontLeft"
    for hit in range(7):
        sp.run("%s:setCondition(%s:getCondition() - 7); TICK(3)" % (d, d))
        check(sp.eval("%s:getCondition()" % d) == 100, "door restored after hit %d" % hit)
    check(sp.eval("%s:getCondition()" % p) == 100, "7 hits x 7 x 0.02 = 0.98: no whole point yet")
    sp.run("%s:setCondition(93); TICK(3)" % d)
    check(sp.eval("%s:getCondition()" % p) == 99, "8th hit: one point off the plate")
    check(abs(sp.eval("%s.md.crvArmourWear" % p) - 0.12) < 1e-6, "the fraction stays in the plate's mod data")
    # ArmourStrength 2: half the wear
    sp.run("SandboxVars.HondaCRVGen1.ArmourStrength = 2.0; %s.md.crvArmourWear = 0" % p)
    for _ in range(14):
        sp.run("%s:setCondition(93); TICK(3)" % d)
    check(sp.eval("%s:getCondition()" % p) == 99, "strength 2: 14 hits still under one point (0.98)")
    sp.run("%s:setCondition(93); TICK(3)" % d)
    check(sp.eval("%s:getCondition()" % p) == 98, "strength 2: the 15th makes it")
    # a plate at 0 protects nothing
    sp.run("%s:setCondition(0); TICK(3); %s:setCondition(80); TICK(3)" % (p, d))
    check(sp.eval("%s:getCondition()" % d) == 80, "a worn-out plate lets the door take the damage")
    sp.run("%s:setCondition(100); TICK(3)" % p)
    # the mesh wears like armour, the bars like bars
    sp.run("SandboxVars.HondaCRVGen1.ArmourStrength = 1.0")
    w = "v.parts.WindowFrontLeft"
    for _ in range(20):
        sp.run("%s:setCondition(%s:getCondition() - 7); TICK(3)" % (w, w))
    check(sp.eval("%s:getCondition()" % w) == 100, "mesh keeps the glass")
    check(sp.eval("%s:getCondition()" % g) == 98, "mesh: 20 x 7 x 0.02 = 2.8 -> 2 points (got %s)" % sp.eval("%s:getCondition()" % g))
    sp.run("%s:setInventoryItem(nil); install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_GuardWindowFront', %s.InstallComplete)" % (g, ACC))
    sp.run("%s:setCondition(100)" % g)
    for _ in range(40):
        sp.run("%s:setCondition(%s:getCondition() - 7); TICK(3)" % (w, w))
    bars = sp.eval("%s:getCondition()" % g)
    check(70 <= bars <= 92, "bars keep their 0-1 a thump (40 thumps -> %s)" % bars)
    # the door cannot come off under its plate; without it the vanilla test decides
    check(sp.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorFrontLeft, PLAYER)") is False, "door locked by its plate")
    check(sp.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorRearLeft, PLAYER)") is True, "a bare door comes off")
    sp.run("%s:setInventoryItem(nil)" % p)
    check(sp.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorFrontLeft, PLAYER)") is True, "plate off: door comes off")
    # a car that is not a CR-V is left alone
    sp.run("o = newVehicle(9, {'DoorFrontLeft', 'CRVArmourDoorFrontLeft'}, 'Base.SUV'); "
           "o.parts.DoorFrontLeft.item = newItem('Base.Door'); o.parts.CRVArmourDoorFrontLeft.item = newItem('x')")
    check(sp.eval("Vehicles.UninstallTest.Default(o, o.parts.DoorFrontLeft, PLAYER)") is True, "other cars untouched")
    # armour never spawns
    sp.run("%s.Create(v, v.parts.CRVArmourArchFrontLeft)" % A)
    check(sp.eval("v.parts.CRVArmourArchFrontLeft.item") is None, "no spawned armour")
    # a spawned guard set always comes as bars (the game's random pick of the part's types is pre-empted)
    spawn = r'''
    function spawnGuard(id, script)
        local c = newVehicle(id, { "CRVGuardFrontLeft" }, script)
        c.parts.CRVGuardFrontLeft.types = setmetatable({ "Base.CRVGen1_GuardWindowFront", "Base.CRVGen1_ArmourMeshFront" }, JList)
        VehicleUtils.createPartInventoryItem(c.parts.CRVGuardFrontLeft)
        return c.parts.CRVGuardFrontLeft.item.type
    end
    '''
    sp.run(spawn)
    got = {sp.eval("spawnGuard(%d)" % (100 + i)) for i in range(30)}
    check(got == {"Base.CRVGen1_GuardWindowFront"}, "spawned guards are bars: %s" % got)
    got = {sp.eval("spawnGuard(%d, 'Base.SUV')" % (200 + i)) for i in range(30)}
    check(len(got) == 2, "another car's random pick is untouched: %s" % got)
    # vanilla Vehicles.lua loading after the mod file replaces the tables: OnGameStart wraps them again
    sp.run("v.parts.CRVArmourDoorFrontLeft:setInventoryItem(newItem('Base.CRVGen1_ArmourDoorFront'))")
    sp.run("Vehicles = { UninstallTest = { Default = function() return true end } }; triggerEvent('OnGameStart')")
    check(sp.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorFrontLeft, PLAYER)") is False, "re-wrapped at game start")
    sp.run("triggerEvent('OnGameStart')")
    check(sp.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorRearLeft, PLAYER)") is True, "wrapped once, not twice")
    print("ARMOUR single player: variant models, window shut and locked, plate protection + accumulator x strength, "
          "worn plate, mesh vs bar wear, door uninstall lock ok")


def multiplayer():
    net = Net()
    server = side("server", net)
    alice = side("client", net, player="alice")
    bob = side("client", net, player="bob")
    for s in (server, alice, bob):
        s.run("v = crv(5)")
    # the car streams in: init runs on every side (Acc.Init for the guard parts: the clients start tracking)
    for s in (server, alice, bob):
        s.run("%s.Init(v, v.parts.CRVGuardFrontLeft)" % ACC)
    # the server completes the mesh install (ISInstallVehiclePart:complete), the item reaches the clients
    server.run("v.parts.WindowFrontLeft.window.open = true")
    for c in (alice, bob):
        c.run("v.parts.WindowFrontLeft.window.open = true")
    server.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront', %s.InstallComplete)" % ACC)
    check(server.eval("v.parts.WindowFrontLeft.window.open") is False and server.eval("SENT.window") == 1,
          "server shuts the window and transmits it")
    check(server.eval("v.parts.CRVGuardFrontLeft.calls") == 0, "a dedicated server draws nothing")
    net.sync_item(5, "CRVGuardFrontLeft")
    for c in (alice, bob):
        check(c.eval("visibleList(v.parts.CRVGuardFrontLeft)") == "CRVGuardFrontLeft,ArmourMesh", "engine showed both")
        c.run("TICK(HondaCRVGen1.State.POLL)")
        check(c.eval("visibleList(v.parts.CRVGuardFrontLeft)") == "ArmourMesh", "client poll: the mesh only")
        check(c.eval("SENT.window or 0") == 0, "clients never transmit the window")
        # the window packet reaches them (transmitPartWindow); then opening is refused on the client
        c.run("v.parts.WindowFrontLeft.window.open = false")
        check(c.eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowFrontLeft, true):isValid()") is False,
              "client refuses to open")
    check(server.eval("ISOpenCloseVehicleWindow:new(nil, v.parts.WindowFrontLeft, true):isValid()") is False,
          "server refuses to open (the networked action re-checks)")
    # a late joiner streams the car in: init reads the item and shows the mesh at once
    carol = side("client", net, player="carol")
    carol.run("v = crv(5); v.parts.CRVGuardFrontLeft:setInventoryItem(newItem('Base.CRVGen1_ArmourMeshFront'))")
    carol.run("%s.Init(v, v.parts.CRVGuardFrontLeft)" % ACC)
    check(carol.eval("visibleList(v.parts.CRVGuardFrontLeft)") == "ArmourMesh", "late joiner: the mesh only")
    # protection only where the game is authoritative: a client's copy is not touched by its own ticks
    for s in (server, alice):
        s.run("install(v, 'CRVArmourDoorFrontLeft', 'Base.CRVGen1_ArmourDoorFront', %s.InstallComplete)" % A)
        s.run("TICK(3); v.parts.DoorFrontLeft:setCondition(90); TICK(3)")
    check(server.eval("v.parts.DoorFrontLeft:getCondition()") == 100, "server restores the door")
    check(alice.eval("v.parts.DoorFrontLeft:getCondition()") == 90, "a client never restores (server-side only)")
    check(alice.eval("HondaCRVGen1.Acc.watch[5] == nil"), "clients watch nothing")
    # the door uninstall lock holds on both sides (the mechanics UI greys it, the server refuses)
    check(server.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorFrontLeft, nil)") is False, "server: door locked")
    check(alice.eval("Vehicles.UninstallTest.Default(v, v.parts.DoorFrontLeft, PLAYER)") is False, "client: door locked")
    # removing the mesh on the server: the engine hides every model on the clients
    server.run("v.parts.CRVGuardFrontLeft:setInventoryItem(nil)")
    net.sync_item(5, "CRVGuardFrontLeft")
    for c in (alice, bob):
        c.run("TICK(HondaCRVGen1.State.POLL)")
        check(c.eval("visibleList(v.parts.CRVGuardFrontLeft)") == "", "removed: nothing shows")
        check(c.eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowFrontLeft, true):isValid()") is True,
              "no guard: the window opens again")
    print("ARMOUR multiplayer: server install -> item sync -> client poll shows the mesh; window shut by the server, "
          "locked on clients and server; late joiner; protection server-only; door lock both sides ok")


OFFROAD = "server/Vehicles/HondaCRVGen1_Offroad.lua"
# the instruction budget a test call gets before it counts as an endless loop (Kahlua turns the
# wrappers' `return f(...)` into tail calls: a cycle never overflows the stack, the game just hangs)
LOOP_GUARD = r'''
function guarded(fn, ...)
    local args = { ... }
    debug.sethook(function() error("LOOP: still running after 2e6 instructions") end, "", 2000000)
    local ok, res = pcall(function() return fn(unpack(args)) end)
    debug.sethook()
    if not ok then return "ERROR " .. tostring(res) end
    return res
end
'''


def load_order():
    """The real files in the game's load order (42.21 LuaManager.LoadDirBase: vanilla first, then the
    mod's server/Vehicles files sorted case-insensitively: _ArmourServer (which requires Accessories
    first), _Offroad, Accessories), then the start events. Both features wrap
    Vehicles.UninstallTest.Default; the armour's start-event re-wrap used to close a cycle with the
    off-road wrapper (Armour -> Offroad -> Armour ...: every uninstall test on every car hung)."""
    for role, event in (("sp", "OnGameStart"), ("client", "OnGameStart"), ("server", "OnServerStarted")):
        s = side(role, player="tester")
        s.load(OFFROAD)
        s.run(LOOP_GUARD)
        s.trigger(event)
        s.trigger(event)                                   # twice: a second start (or a Lua reload) changes nothing
        s.run("w = crv(31); w:addPart('CRVRoofRack'); w:addPart('CRVOffroadCanRoof'); w:addPart('TireFrontLeft')")
        s.run("w.parts.CRVRoofRack.item = newItem('Base.CRVGen1_RoofRack'); w.parts.TireFrontLeft.item = newItem('Base.Tire')")
        s.run("w.parts.CRVArmourDoorFrontLeft.item = newItem('Base.CRVGen1_ArmourDoorFront')")
        d = "Vehicles.UninstallTest.Default"
        got = s.eval("guarded(%s, w, w.parts.TireFrontLeft, PLAYER)" % d)
        check(got is True, "%s: a tyre's uninstall test returns (got %r)" % (role, got))
        got = s.eval("guarded(%s, w, w.parts.DoorFrontLeft, PLAYER)" % d)
        check(got is False, "%s: a door under its plate stays locked (got %r)" % (role, got))
        got = s.eval("guarded(%s, w, w.parts.CRVRoofRack, PLAYER)" % d)
        check(got is True, "%s: the rack without its can comes off (got %r)" % (role, got))
        s.run("w.parts.CRVOffroadCanRoof.item = newItem('Base.CRVGen1_OffroadJerryCan')")
        got = s.eval("guarded(%s, w, w.parts.CRVRoofRack, PLAYER)" % d)
        check(got is False, "%s: the rack under the roof can stays locked (got %r)" % (role, got))
        got = s.eval("guarded(HondaCRVGen1.Acc.GateUninstallTest, w, w.parts.TrunkDoor, PLAYER)")
        check(got is True, "%s: the gate's own test returns (got %r)" % (role, got))
        s.run("o = newVehicle(32, {'TireFrontLeft'}, 'Base.SUV'); o.parts.TireFrontLeft.item = newItem('Base.Tire')")
        got = s.eval("guarded(%s, o, o.parts.TireFrontLeft, PLAYER)" % d)
        check(got is True, "%s: a vanilla car's tyre test returns (got %r)" % (role, got))
    print("ARMOUR load order: armour + off-road uninstall wraps in the game's order, start events fired twice, "
          "sp / client / server: no loop, door and rack lockouts hold")


def foreign_wraps():
    """Another mod wrapping the same vanilla functions after ours (createPartInventoryItem, the window
    action's isValid, the uninstall test), then the start events: every chain still ends."""
    s = side("sp", player="tester")
    s.run(LOOP_GUARD)
    s.run(r'''
    OTHER = { spawn = 0, window = 0, uninstall = 0 }
    local spawn = VehicleUtils.createPartInventoryItem
    VehicleUtils.createPartInventoryItem = function(part) OTHER.spawn = OTHER.spawn + 1; return spawn(part) end
    local valid = ISOpenCloseVehicleWindow.isValid
    ISOpenCloseVehicleWindow.isValid = function(self) OTHER.window = OTHER.window + 1; return valid(self) end
    local un = Vehicles.UninstallTest.Default
    Vehicles.UninstallTest.Default = function(v, p, c) OTHER.uninstall = OTHER.uninstall + 1; return un(v, p, c) end
    ''')
    s.trigger("OnGameStart")
    s.run("v = crv(41)")
    s.run("v.parts.CRVGuardFrontLeft.types = setmetatable({ 'Base.CRVGen1_GuardWindowFront', 'Base.CRVGen1_ArmourMeshFront' }, JList)")
    got = s.eval("guarded(VehicleUtils.createPartInventoryItem, v.parts.CRVGuardFrontLeft)")
    check(not (isinstance(got, str) and got.startswith("ERROR")), "spawn chain ends (got %r)" % got)
    check(s.eval("OTHER.spawn") == 1 and s.eval("v.parts.CRVGuardFrontLeft.item.type") == "Base.CRVGen1_GuardWindowFront",
          "the other mod's spawn wrapper ran once, the armour's still picks the bars")
    got = s.eval("guarded(function() return ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowRearLeft, true):isValid() end)")
    check(got is True and s.eval("OTHER.window") == 1, "window chain ends (got %r, other %s)" % (got, s.eval("OTHER.window")))
    got = s.eval("guarded(Vehicles.UninstallTest.Default, v, v.parts.DoorRearLeft, PLAYER)")
    check(got is True and s.eval("OTHER.uninstall") == 1, "uninstall chain ends (got %r)" % got)
    print("ARMOUR foreign wraps: another mod's wrappers of the spawn, window and uninstall functions after ours: "
          "every chain ends, each wrapper runs once")


def arches_and_glass():
    """The arch guard absorbs the thumps it takes (the only bodywork at its wheel) at the armour's rate
    and its tyre's hits, never its driving wear; armour over weakened glass holds it above a burst of
    thumps (the game smashes a pane in the call that takes it to 0, before any pass)."""
    sp = side("sp", player="tester")
    sp.run("v = crv(51)")
    a, t = "v.parts.CRVArmourArchFrontLeft", "v.parts.TireFrontLeft"
    sp.run("install(v, 'CRVArmourArchFrontLeft', 'Base.CRVGen1_ArmourArchFront', %s.InstallComplete)" % A)
    check(sp.eval("%s.watch[51] ~= nil" % ACC), "an arch guard is watched")
    sp.run("TICK(3)")
    # 50 zombie thumps of strength 3 on the guard itself (AttackVehicleState: setCondition(cond - strength))
    for _ in range(50):
        sp.run("%s:setCondition(%s:getCondition() - 3); TICK(3)" % (a, a))
    arch = sp.eval("%s:getCondition()" % a)
    check(arch == 97, "50 thumps x 3 x 0.02 = 3 points off the guard, not 150 (got %s)" % arch)
    # a roadkill chip on the tyre (addDamageFrontHitAChr: 1-2) is restored and charged to the guard
    sp.run("%s.md.crvArmourWear = 0; %s:setCondition(%s:getCondition() - 2); TICK(3)" % (a, t, t))
    check(sp.eval("%s:getCondition()" % t) == 100, "the guard keeps its tyre's hits")
    check(abs(sp.eval("%s.md.crvArmourWear" % a) - 0.04) < 1e-6, "2 points x 0.02 on the guard's accumulator")
    # driving wear goes on: 30 wear events through Vehicles.Update.Tire -> Vehicles.LowerCondition
    for _ in range(30):
        sp.run("Vehicles.Update.Tire(v, %s, 1); TICK(3)" % t)
    check(sp.eval("%s:getCondition()" % t) == 70, "tyre wear is not given back (got %s)" % sp.eval("%s:getCondition()" % t))
    # wear and a chip in the same pass: only the chip comes back
    sp.run("Vehicles.Update.Tire(v, %s, 1); %s:setCondition(%s:getCondition() - 2); TICK(3)" % (t, t, t))
    check(sp.eval("%s:getCondition()" % t) == 69, "wear stays, the chip is restored (got %s)" % sp.eval("%s:getCondition()" % t))
    # a guard that a hit took to 0 since the last pass still absorbed it; a worn-out one protects nothing
    sp.run("%s:setCondition(2); %s.watch[51].snap.CRVArmourArchFrontLeft = 2; TICK(3)" % (a, ACC))   # worn down to 2
    sp.run("%s:setCondition(0); TICK(3)" % a)                                                          # a thump of 3
    check(sp.eval("%s:getCondition()" % a) == 2, "a hit to 0 is absorbed like any other (got %s)" % sp.eval("%s:getCondition()" % a))
    sp.run("%s:setCondition(0); %s.watch[51].snap.CRVArmourArchFrontLeft = 0; TICK(3)" % (a, ACC))
    sp.run("%s:setCondition(60); TICK(3); %s:setCondition(55); TICK(3)" % (t, t))
    check(sp.eval("%s:getCondition()" % t) == 55, "a worn-out guard lets the tyre take it")
    # weakened glass: a mesh fitted over a window at 3 holds it at the floor at once (the pass comes 3 ticks
    # later: a strength-3 thump in between would have smashed it), and every pass keeps it there
    w, g = "v.parts.WindowFrontLeft", "v.parts.CRVGuardFrontLeft"
    floor = sp.eval("HondaCRVGen1.Armour.GLASS_FLOOR")
    sp.run("%s:setCondition(3)" % w)
    sp.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront', %s.InstallComplete)" % ACC)
    check(sp.eval("%s:getCondition()" % w) == floor, "the glass is held at the floor on install")
    for _ in range(40):                         # three superhuman thumps (5) between every two passes
        sp.run("%s:setCondition(%s:getCondition() - 15); TICK(3)" % (w, w))
        check(sp.eval("%s:getCondition()" % w) >= floor, "glass held")
    check(sp.eval("%s:getCondition()" % g) < 100, "the mesh paid for it (%s)" % sp.eval("%s:getCondition()" % g))
    # the bars keep the core rule: no floor (they are not the armour)
    sp.run("%s:setInventoryItem(nil); %s:setCondition(4); TICK(3)" % (g, w))
    sp.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_GuardWindowFront', %s.InstallComplete); TICK(3)" % ACC)
    check(sp.eval("%s:getCondition()" % w) == 4, "the bars do not raise the glass")
    # the rear plate does the same for the rear glass
    sp.run("v.parts.WindshieldRear:setCondition(1)")
    sp.run("install(v, 'CRVGuardWindshieldRear', 'Base.CRVGen1_ArmourRearPlate', %s.InstallComplete); TICK(3)" % ACC)
    check(sp.eval("v.parts.WindshieldRear:getCondition()") == floor, "the rear plate holds the rear glass")
    # a client never raises anything (the server does; its condition reaches the client)
    c = side("client", Net(), player="alice")
    c.run("v = crv(52); v.parts.WindowFrontLeft:setCondition(3)")
    c.run("install(v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront', %s.InstallComplete)" % ACC)
    check(c.eval("v.parts.WindowFrontLeft:getCondition()") == 3, "a client does not touch the glass")
    print("ARMOUR arches and glass: arch absorbs its thumps at the armour rate and its tyre's hits, tyre wear "
          "passes, worn-out guard inert; weakened glass held at %d under the mesh and the rear plate, not under the bars"
          % floor)


def main():
    load_order()
    foreign_wraps()
    arches_and_glass()
    single_player()
    multiplayer()
    print("ARMOUR LUA TESTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
