"""
The off-road parts' Lua (server/Vehicles/HondaCRVGen1_Offroad.lua) under Lua 5.1 (lupa; PZ's Kahlua is a
Lua 5.1) on scripts/lua_harness.py: spawn rolls and their hosts, the cans' random petrol, the function
feature's FunctionAccessoryChance sandbox option scaling the rolls (counted over spawned cars), the rack and
gate uninstall rules, the jerry can's fuel through an install / uninstall round trip
(the item object stays the same), and the roof can's model drawn only with the rack, in single player
and over a two-client multiplayer round trip (the server never touches model visibility; each client
recomputes it when the part items arrive).

    python scripts\\test_offroad_lua.py
"""
import sys

from lua_harness import Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
FILES = STATE + ("server/Vehicles/HondaCRVGen1Accessories.lua", "server/Vehicles/HondaCRVGen1_Offroad.lua")
OFFROAD = ["CRVOffroadSnorkel", "CRVOffroadSkidPlate", "CRVOffroadRearBumper", "CRVOffroadLadder",
           "CRVOffroadCanGate", "CRVOffroadCanRoof"]
CORE = ["TrunkDoor", "WindshieldRear", "CRVRoofRack", "CRVSpareCover"]

# what the harness does not fake: the vanilla Vehicles tests, VehicleUtils, the petrol can and its FluidContainer
GAME = r'''
Fluid = { Petrol = "Petrol" }
FC = {}
FC.__index = FC
function newFC(cap, amount) return setmetatable({ cap = cap, amount = amount or 0, fluid = amount and amount > 0 and "Petrol" or nil }, FC) end
function FC:getCapacity() return self.cap end
function FC:getAmount() return self.amount end
function FC:Empty() self.amount = 0; self.fluid = nil end
function FC:addFluid(f, a) self.fluid = f; self.amount = math.min(self.cap, self.amount + a) end
function newCan(amount)
    local it = newItem("Base.JerryCan")
    it.fc = newFC(20.0, amount or 20.0)       -- the vanilla script's Fluids { Petrol:1.0 }: created full
    it.getFluidContainer = function(self) return self.fc end
    return it
end
VehicleUtils = { createPartInventoryItem = function(part)
    local item = part.itemType == "Base.JerryCan" and newCan() or newItem(part.id)
    part:setInventoryItem(item)
    return item
end }
UNINSTALL_DEFAULT_CALLS = 0
Vehicles = { UninstallTest = { Default = function(v, p, chr) UNINSTALL_DEFAULT_CALLS = UNINSTALL_DEFAULT_CALLS + 1; return true end },
             InstallTest = { Default = function() return true end },
             ContainerAccess = { Seat = function() return true end } }
function car(id, script)
    local ids = { "TrunkDoor", "WindshieldRear", "CRVRoofRack", "CRVSpareCover",
                  "CRVOffroadSnorkel", "CRVOffroadSkidPlate", "CRVOffroadRearBumper", "CRVOffroadLadder",
                  "CRVOffroadCanGate", "CRVOffroadCanRoof" }
    local v = newVehicle(id, ids, script)
    for _, pid in ipairs(ids) do v.parts[pid].models = { pid } end
    v.parts.CRVOffroadCanGate.itemType = "Base.JerryCan"
    v.parts.CRVOffroadCanRoof.itemType = "Base.JerryCan"
    v.parts.TrunkDoor:setInventoryItem(newItem("TrunkDoor"))
    return v
end
O = HondaCRVGen1 and HondaCRVGen1.Offroad
'''


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)
    print("ok   " + msg)


def side(role, net=None, player=None, seed=7):
    s = Side(role, net, player=player, seed=seed)
    s.run(GAME)
    s.load(*FILES)
    s.run("O = HondaCRVGen1.Offroad")
    return s


def single_player():
    sp = side("sp", player="tester")
    # spawn: every roll forced on; the roof can only where the rack spawned, the gate can only with the gate
    sp.run("for k, _ in pairs(O.SPAWN) do O.SPAWN[k] = 100 end; O.EMPTY_CHANCE = 0")
    sp.run("v = car(1); v.parts.TrunkDoor:setInventoryItem(nil)")
    sp.run("for _, p in ipairs({'CRVOffroadSnorkel', 'CRVOffroadSkidPlate', 'CRVOffroadRearBumper', 'CRVOffroadLadder', "
           "'CRVOffroadCanGate', 'CRVOffroadCanRoof'}) do O.Create(v, v.parts[p]) end")
    check(all(sp.eval("v.parts.%s.item ~= nil" % p) for p in OFFROAD[:4]), "the four bolt-ons spawn when rolled")
    check(sp.eval("v.parts.CRVOffroadCanRoof.item == nil"), "no roof can on a car without the rack")
    check(sp.eval("v.parts.CRVOffroadCanGate.item == nil"), "no gate can on a car without its gate")
    sp.run("w = car(2); w.parts.CRVRoofRack:setInventoryItem(newItem('CRVRoofRack')); O.Create(w, w.parts.CRVOffroadCanGate); "
           "O.Create(w, w.parts.CRVOffroadCanRoof)")
    check(sp.eval("w.parts.CRVOffroadCanGate.item ~= nil and w.parts.CRVOffroadCanRoof.item ~= nil"), "both cans with their hosts")
    amounts = [sp.eval("w.parts.%s.item.fc:getAmount()" % p) for p in ("CRVOffroadCanGate", "CRVOffroadCanRoof")]
    check(all(2.0 <= a <= 20.0 for a in amounts), "spawned cans hold 2 l up to full (%s)" % amounts)
    check(sp.eval("w.parts.CRVOffroadCanGate.item:getType()") == "Base.JerryCan", "the part item is the vanilla petrol can")
    # empty cans and the sandbox hook (the function feature's FunctionAccessoryChance)
    sp.run("O.EMPTY_CHANCE = 100; u = car(3); u.parts.CRVRoofRack:setInventoryItem(newItem('CRVRoofRack')); "
           "O.Create(u, u.parts.CRVOffroadCanRoof)")
    check(sp.eval("u.parts.CRVOffroadCanRoof.item.fc:getAmount()") == 0, "an empty spawned can")
    sp.run("SandboxVars = { HondaCRVGen1 = { FunctionAccessoryChance = 0 } }; x = car(4); O.Create(x, x.parts.CRVOffroadSnorkel)")
    check(sp.eval("x.parts.CRVOffroadSnorkel.item == nil"), "accessory chance 0 % spawns nothing, even a 100 % roll")
    sp.run("SandboxVars = nil; O.Create(x, x.parts.CRVOffroadSnorkel)")
    check(sp.eval("x.parts.CRVOffroadSnorkel.item ~= nil"), "no sandbox values: the base chance")
    sp.run("for k, _ in pairs(O.SPAWN) do O.SPAWN[k] = 0 end; y = car(5); "
           "for _, p in ipairs({'CRVOffroadSnorkel', 'CRVOffroadLadder'}) do O.Create(y, y.parts[p]) end")
    check(sp.eval("y.parts.CRVOffroadSnorkel.item == nil and y.parts.CRVOffroadLadder.item == nil"), "chance 0: nothing")

    # the fuel survives install / uninstall: the same item object goes in and comes back (as the vanilla actions do)
    sp.run("can = newCan(13.5); p = w.parts.CRVOffroadCanRoof; p:setInventoryItem(nil); p:setInventoryItem(can); "
           "O.InstallComplete(w, p); back = p:getInventoryItem(); p:setInventoryItem(nil); O.UninstallComplete(w, p, back)")
    check(sp.eval("back == can and can.fc:getAmount() == 13.5 and can.fc.fluid == 'Petrol'"),
          "a 13.5 l can comes back from the roof with 13.5 l of petrol")

    # the rack stays while the roof can sits on it; other parts and other cars go to the vanilla test
    sp.run("p:setInventoryItem(can); UNINSTALL_DEFAULT_CALLS = 0")
    check(sp.eval("Vehicles.UninstallTest.Default(w, w.parts.CRVRoofRack, PLAYER)") is False, "rack refused under the roof can")
    check(sp.eval("UNINSTALL_DEFAULT_CALLS") == 0, "refused before the vanilla test runs")
    check(sp.eval("Vehicles.UninstallTest.Default(w, w.parts.CRVOffroadCanRoof, PLAYER)") is True, "the can itself comes off")
    sp.run("p:setInventoryItem(nil)")
    check(sp.eval("Vehicles.UninstallTest.Default(w, w.parts.CRVRoofRack, PLAYER)") is True, "rack free once the can is off")
    sp.run("s = newVehicle(9, {'CRVRoofRack', 'CRVOffroadCanRoof'}, 'Base.SUV'); s.parts.CRVOffroadCanRoof:setInventoryItem(newCan())")
    check(sp.eval("Vehicles.UninstallTest.Default(s, s.parts.CRVRoofRack, PLAYER)") is True, "another car's parts are not ours")
    # loading the file twice wraps once and lists the gate can once
    sp.load("server/Vehicles/HondaCRVGen1_Offroad.lua")
    sp.run("n = 0; for _, id in ipairs(HondaCRVGen1.Acc.GATE_FIRST) do if id == 'CRVOffroadCanGate' then n = n + 1 end end")
    check(sp.eval("n") == 1, "GATE_FIRST lists the gate can once")
    sp.run("p:setInventoryItem(can); UNINSTALL_DEFAULT_CALLS = 0; r = Vehicles.UninstallTest.Default(w, w.parts.CRVRoofRack, PLAYER)")
    check(sp.eval("r") is False and sp.eval("UNINSTALL_DEFAULT_CALLS") == 0, "still one wrapper after a reload")
    # the gate stays while the can rides it (core GateUninstallTest + GATE_FIRST)
    check(sp.eval("HondaCRVGen1.Acc.GateUninstallTest(w, w.parts.TrunkDoor, PLAYER)") is False, "gate refused under its can")
    sp.run("w.parts.CRVOffroadCanGate:setInventoryItem(nil)")
    check(sp.eval("HondaCRVGen1.Acc.GateUninstallTest(w, w.parts.TrunkDoor, PLAYER)") is True, "gate free once the can is off")

    # the roof can's model: shown with the rack, hidden without it (init), back when the rack returns (client poll)
    sp.run("rc = w.parts.CRVOffroadCanRoof; O.Init(w, rc)")
    check(sp.eval("rc.visible.CRVOffroadCanRoof") is True, "roof can drawn on the rack")
    sp.run("w.parts.CRVRoofRack:setInventoryItem(nil); O.Init(w, rc)")
    check(sp.eval("rc.visible.CRVOffroadCanRoof") is None, "roof can hidden with no rack under it")
    sp.run("w.parts.CRVRoofRack:setInventoryItem(newItem('CRVRoofRack')); TICK(HondaCRVGen1.State.POLL)")
    check(sp.eval("rc.visible.CRVOffroadCanRoof") is True, "drawn again once the rack's item changed (watchPart)")


def sandbox_chance():
    """The function feature's FunctionAccessoryChance (percent, 100 = the base rates) scales the off-road
    rolls the way it scales the core accessories (HondaCRVGen1.Acc.scaledChance, read at create): 0 gives
    bare cars, 500 five times the base (a roll caps at 100 %). The roof can's roll is a share of the cars
    whose RACK spawned, and the rack's own roll already carries the scale, so the can's share is not
    scaled again (it would square the option). Counted over many spawned cars with the shipped rates."""
    sp = side("sp", player="tester", seed=11)
    ids = "{'CRVOffroadSnorkel', 'CRVOffroadSkidPlate', 'CRVOffroadRearBumper', 'CRVOffroadLadder', 'CRVOffroadCanGate'}"
    count = ("function spawned(n) local c = {} for i = 1, n do local v = car(1000 + i) "
             "for _, p in ipairs(%s) do O.Create(v, v.parts[p]); if v.parts[p].item then c[p] = (c[p] or 0) + 1 end end end "
             "return c end" % ids)
    sp.run(count)
    n = 2000
    got = {}
    for pct in (0, 100, 300):
        sp.run("SandboxVars = { HondaCRVGen1 = { FunctionAccessoryChance = %d } }; c = spawned(%d)" % (pct, n))
        got[pct] = {p: sp.eval("c.%s or 0" % p) for p in OFFROAD[:5]}
        print("     accessory chance %3d %%: %s" % (pct, ", ".join("%s %d" % (p[10:], got[pct][p]) for p in OFFROAD[:5])))
    check(all(v == 0 for v in got[0].values()), "accessory chance 0 %%: none of %d cars gets a snorkel, skid plate, bumper, "
          "ladder or gate can" % n)
    for p in OFFROAD[:5]:
        base = sp.eval("O.SPAWN.%s" % p)
        lo, hi = 0.55 * base * n / 100, 1.45 * base * n / 100
        check(lo <= got[100][p] <= hi, "100 %%: %s near its base %d %% (%d of %d)" % (p, base, got[100][p], n))
        check(got[300][p] >= 2.0 * got[100][p], "300 %%: %s about three times as often (%d vs %d)" % (p, got[300][p], got[100][p]))
    # the chance itself: scaled, capped at 100, the base without sandbox values; the roof can keeps its share
    sp.run("SandboxVars = { HondaCRVGen1 = { FunctionAccessoryChance = 500 } }")
    check(sp.eval("O.spawnChance('CRVOffroadSnorkel')") == 20, "500 %: the snorkel's 4 % becomes 20 %")
    check(sp.eval("O.spawnChance('CRVOffroadCanRoof')") == sp.eval("O.SPAWN.CRVOffroadCanRoof"),
          "the roof can's share of racked cars is not scaled twice")
    sp.run("O.SPAWN.CRVOffroadLadder = 40")
    check(sp.eval("O.spawnChance('CRVOffroadLadder')") == 100, "a scaled roll caps at 100 %")
    sp.run("SandboxVars = nil")
    check(sp.eval("O.spawnChance('CRVOffroadSkidPlate')") == sp.eval("O.SPAWN.CRVOffroadSkidPlate"), "no sandbox: the base")
    # the roof can still follows the option through its host: at 0 % no rack spawns, so no roof can either
    sp.run("SandboxVars = { HondaCRVGen1 = { FunctionAccessoryChance = 0 } }; HondaCRVGen1.Acc.SPAWN.CRVRoofRack = 100; "
           "r = car(3000); HondaCRVGen1.Acc.Create(r, r.parts.CRVRoofRack); O.Create(r, r.parts.CRVOffroadCanRoof)")
    check(sp.eval("r.parts.CRVRoofRack.item == nil and r.parts.CRVOffroadCanRoof.item == nil"),
          "0 %: no rack, so no roof can")


def multiplayer():
    net = Net()
    server = side("server", net)
    alice = side("client", net, player="alice")
    bob = side("client", net, player="bob")
    for s in (server, alice, bob):
        s.run("v = car(7); v.parts.CRVRoofRack:setInventoryItem(newItem('CRVRoofRack'))")
        s.run("for _, p in pairs(v.parts) do O.Init(v, p) end")          # createPhysics: init on every side
    # the server completes an install (ISInstallVehiclePart:complete), the item packet reaches the clients
    server.run("can = newCan(9.0); v.parts.CRVOffroadCanRoof:setInventoryItem(can); O.InstallComplete(v, v.parts.CRVOffroadCanRoof)")
    check(server.eval("v.parts.CRVOffroadCanRoof.calls") == 0, "the server never sets model visibility")
    net.sync_item(7, "CRVOffroadCanRoof")
    for c in (alice, bob):
        c.run("TICK(HondaCRVGen1.State.POLL)")
        check(c.eval("v.parts.CRVOffroadCanRoof.visible.CRVOffroadCanRoof") is True, "%s draws the roof can" % c.player)
    # a debug removal of the rack on the server: each client hides the can on its own next poll
    server.run("v.parts.CRVRoofRack:setInventoryItem(nil)")
    net.sync_item(7, "CRVRoofRack")
    for c in (alice, bob):
        c.run("TICK(HondaCRVGen1.State.POLL)")
        check(c.eval("v.parts.CRVOffroadCanRoof.visible.CRVOffroadCanRoof") is None, "%s hides the can without the rack" % c.player)
    server.run("v.parts.CRVRoofRack:setInventoryItem(newItem('CRVRoofRack'))")
    net.sync_item(7, "CRVRoofRack")
    for c in (alice, bob):
        c.run("TICK(HondaCRVGen1.State.POLL)")
        check(c.eval("v.parts.CRVOffroadCanRoof.visible.CRVOffroadCanRoof") is True, "%s draws it again" % c.player)
    # the rack rule holds on both sides (a client's menu and the server's isValid)
    for s, who in ((server, "server"), (alice, "alice")):
        s.run("v.parts.CRVOffroadCanRoof:setInventoryItem(v.parts.CRVOffroadCanRoof.item or newCan(1))")
        check(s.eval("Vehicles.UninstallTest.Default(v, v.parts.CRVRoofRack, nil)") is False, "%s refuses the rack under the can" % who)
    check(net.pump() == 0, "nothing of ours on the wire (the game's item packets carry it)")
    check(server.eval("can.fc:getAmount()") == 9.0, "the server's can keeps its 9 l")


def rear_bumper():
    """The rear steel bumper takes rear knocks for the gate at the bull bar's rate (1.5 a point: the gate
    lasts ~1.7x), where the game is authoritative only; worn out it protects nothing; the skid plate and the
    snorkel protect nothing (2026-10-21)."""
    sp = side("sp", player="tester")
    check(sp.eval("HondaCRVGen1.Acc.COVERS.CRVOffroadRearBumper[1]") == "TrunkDoor", "the bumper covers the gate")
    check(sp.eval("HondaCRVGen1.Acc.RATE.CRVOffroadRearBumper") == 1.5, "at the bull bar's rate")
    check(sp.eval("HondaCRVGen1.Acc.COVERS.CRVOffroadSkidPlate == nil and HondaCRVGen1.Acc.COVERS.CRVOffroadSnorkel == nil"),
          "the skid plate and the snorkel cover nothing")
    sp.run("v = car(30); b = v.parts.CRVOffroadRearBumper; b:setInventoryItem(newItem('CRVGen1_OffroadRearBumper')); "
           "O.InstallComplete(v, b); TICK(3)")
    check(sp.eval("HondaCRVGen1.Acc.watch[30] ~= nil"), "an installed bumper is watched")
    sp.run("g = v.parts.TrunkDoor; g:setCondition(90); TICK(3)")       # a rear crash: 10 off the gate
    check(sp.eval("g:getCondition()") == 100 and sp.eval("b:getCondition()") == 85, "gate kept, bumper -15")
    # the gate's life against rear knocks of 6: alone 17, bumpered ~28 (1.67x)
    sp.run("b:setCondition(100); b.md.crvWear = 0")
    hits = 0
    while sp.eval("g:getCondition()") > 0 and hits < 1000:
        sp.run("g:setCondition(math.max(0, g:getCondition() - 6)); TICK(3)")
        hits += 1
    check(26 <= hits <= 29, "a bumpered gate lasts ~1.7x a bare one's 17 knocks of 6 (got %d)" % hits)
    check(sp.eval("b:getCondition()") == 0, "the bumper wore out on the way")
    # loaded on a car (init): watched again after a save / load
    sp.run("w = car(31); w.parts.CRVOffroadRearBumper:setInventoryItem(newItem('CRVGen1_OffroadRearBumper')); "
           "O.Init(w, w.parts.CRVOffroadRearBumper)")
    check(sp.eval("HondaCRVGen1.Acc.watch[31] ~= nil"), "init watches a fitted bumper")
    # I-DIFF-1 (mutation offroad-dirty): its uninstall complete tells the protection loop (Acc.dirty), which between
    # two sweeps never asks the bumper for its item: the car leaves the watch on the next pass, not ITEM_EVERY later
    sp.run("HondaCRVGen1.Acc.ITEM_EVERY = 1000; u = car(33); ub = u.parts.CRVOffroadRearBumper; "
           "ub:setInventoryItem(newItem('CRVGen1_OffroadRearBumper')); O.InstallComplete(u, ub); TICK(3)")
    check(sp.eval("HondaCRVGen1.Acc.watch[33] ~= nil and #HondaCRVGen1.Acc.watch[33].list == 1"), "the bumper is listed")
    sp.run("local it = ub:getInventoryItem(); ub:setInventoryItem(nil); O.UninstallComplete(u, ub, it)")
    check(sp.eval("HondaCRVGen1.Acc.watch[33].list") is None, "the uninstall drops the protector list (Acc.dirty)")
    sp.run("TICK(3)")
    check(sp.eval("HondaCRVGen1.Acc.watch[33] == nil"), "nothing left fitted: off the watch on the next pass")
    sp.run("HondaCRVGen1.Acc.ITEM_EVERY = 8")
    # a multiplayer client never restores anything (the server does; the condition reaches the client)
    c = side("client", Net(), player="alice")
    c.run("v = car(32); b = v.parts.CRVOffroadRearBumper; b:setInventoryItem(newItem('CRVGen1_OffroadRearBumper')); "
          "O.Init(v, b); TICK(3); v.parts.TrunkDoor:setCondition(90); TICK(3)")
    check(c.eval("v.parts.TrunkDoor:getCondition()") == 90 and c.eval("HondaCRVGen1.Acc.watch[32] == nil"),
          "a client does not protect")


def main():
    single_player()
    sandbox_chance()
    multiplayer()
    rear_bumper()
    print("OFFROAD LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
