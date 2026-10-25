r"""
The cargo clutter's Lua (shared/HondaCRVGen1_Clutter.lua, scripts/features/clutter.py) under Lua 5.1 (lupa;
PZ's Kahlua is a Lua 5.1), single player and a multiplayer server with two clients (scripts/lua_harness.py):

  * the fill state follows the trunk (part TruckBed's container weight over its capacity) on the
    authoritative side's 15-tick tick: 0 / 1 / 2 / 3 at 10 / 40 / 75 %, with hysteresis on the way down;
  * the drawing side shows models 1..n (incremental), the well blanket only while the picnic table is out,
    nothing while the rear seats are folded; repeated ticks make no setModelVisible calls;
  * no trunk item: empty; a car removed from the world is dropped;
  * multiplayer: the server derives and syncs (command, or the mod data packet alone through the client's
    poll), never draws; clients never derive; a table taken out on the server reaches both clients; a car
    streamed in later shows its state at init; the fold hides it everywhere.

    python scripts\test_clutter_lua.py
"""
import sys

from lua_harness import Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
FILES = ("shared/HondaCRVGen1_Shared.lua", "shared/HondaCRVGen1_Clutter.lua")
MODELS = ("InteriorClutter1", "InteriorClutter2", "InteriorClutter3")
WELL = "InteriorClutterWell"

GAME = r'''
-- a CR-V with what the feature reads: the trunk (55 kg, a NormalTrunk item), the picnic table (its item),
-- the rear-left seat (the fold state's host), the clutter part with its four models
function newCRV(id)
    local v = newVehicle(id, { "TruckBed", "CRVPicnicTable", "SeatRearLeft", "SeatRearRight", "CRVClutterCargo" })
    v.parts.TruckBed.item = newItem("Base.NormalTrunk")
    v.parts.TruckBed.cont = newContainer(55, 0)
    v.parts.CRVPicnicTable.item = newItem("Base.CRVGen1_PicnicTable")
    v.parts.SeatRearLeft.item = newItem("Base.NormalCarSeat")
    v.parts.CRVClutterCargo.models = { "InteriorClutter1", "InteriorClutter2", "InteriorClutter3", "InteriorClutterWell" }
    return v
end
function SHOWN(v)
    local p = v.parts.CRVClutterCargo
    local t = {}
    for _, m in ipairs(p.models) do t[#t + 1] = p.visible[m] and "1" or "0" end
    return table.concat(t)
end
-- the full part (2026-10-24): the folded load floor's pieces and the function feature's two containers (no item):
-- the folded load floor (CRVFunctionCargo, 60) and the under-floor storage (CRVFunctionUnderfloor, 10). SHOWN reads
-- "trunk 1-3 | fold 1-3 | well"
function newCRV2(id)
    local v = newCRV(id)
    v:addPart("CRVFunctionCargo").cont = newContainer(60, 0)
    v:addPart("CRVFunctionUnderfloor").cont = newContainer(10, 0)
    v.parts.CRVClutterCargo.models = { "InteriorClutter1", "InteriorClutter2", "InteriorClutter3", "InteriorClutterFold1",
                                       "InteriorClutterFold2", "InteriorClutterFold3", "InteriorClutterWell" }
    return v
end
'''

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


def side(role, net=None, player=None, seed=7):
    s = Side(role, net, player=player, seed=seed)
    s.run(GAME)
    s.load(*STATE)
    s.load(*FILES)
    return s


def single_player():
    sp = side("sp", player="tester")
    C = "HondaCRVGen1.Clutter"
    sp.run("v = newCRV(1); %s.Init(v, v.parts.CRVClutterCargo)" % C)
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 0, "an empty trunk is state 0")
    check(sp.eval("SHOWN(v)") == "0000", "nothing shows on an empty trunk (%s)" % sp.eval("SHOWN(v)"))
    for kg, state, shown in ((5.0, 0, "0000"), (6.0, 1, "1000"), (21.9, 1, "1000"), (22.1, 2, "1100"),
                             (41.0, 2, "1100"), (41.3, 3, "1110"), (55.0, 3, "1110")):
        sp.run("v.parts.TruckBed.cont.weight = %r; TICK(15)" % kg)
        check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == state and sp.eval("SHOWN(v)") == shown,
              "%.1f kg of 55: state %d, models %s (got %s %s)" % (kg, state, shown,
                                                                  sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')"), sp.eval("SHOWN(v)")))
    check(sp.eval("v.parts.CRVClutterCargo.md.crv_clutter_load") == 3, "the state lives in the part's mod data (saved with the car)")
    # hysteresis: from 3, 40.4 kg (73.5 %) stays 3, 39.5 kg (71.8 %, under 75 - 2) goes to 2
    sp.run("v.parts.TruckBed.cont.weight = 40.4; TICK(15)")
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 3, "73.5 % stays at 3 (hysteresis)")
    sp.run("v.parts.TruckBed.cont.weight = 39.5; TICK(15)")
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 2, "71.8 % drops to 2")
    sp.run("v.parts.TruckBed.cont.weight = 45; TICK(15)")
    # idle ticks: nothing redrawn
    sp.run("calls0 = v.parts.CRVClutterCargo.calls; TICK(300)")
    check(sp.eval("v.parts.CRVClutterCargo.calls - calls0") == 0, "idle ticks make no setModelVisible calls")
    # only every 15th tick looks
    sp.run("v.parts.TruckBed.cont.weight = 0; TICK(1)")
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 3, "the fill is checked on a 15-tick tick, not every tick")
    sp.run("TICK(15)")
    check(sp.eval("SHOWN(v)") == "0000", "emptied: nothing shows")
    sp.run("v.parts.TruckBed.cont.weight = 45; TICK(15)")
    # the table out: the State poll (30 ticks) sees its item change; the well blanket shows with the load
    sp.run("v.parts.CRVPicnicTable:setInventoryItem(nil); TICK(30)")
    check(sp.eval("SHOWN(v)") == "1111", "table out: the well blanket shows under the load (%s)" % sp.eval("SHOWN(v)"))
    sp.run("v.parts.TruckBed.cont.weight = 0; TICK(15)")
    check(sp.eval("SHOWN(v)") == "0000", "table out, empty trunk: nothing, not even the blanket")
    sp.run("v.parts.TruckBed.cont.weight = 7; TICK(15)")
    check(sp.eval("SHOWN(v)") == "1001", "table out, state 1: load 1 and the blanket")
    sp.run("v.parts.CRVPicnicTable:setInventoryItem(newItem('Base.CRVGen1_PicnicTable')); TICK(30)")
    check(sp.eval("SHOWN(v)") == "1000", "table back: the blanket goes")
    # folded seats: nothing, whatever the load; unfolded: back
    sp.run("v.parts.TruckBed.cont.weight = 50; TICK(15)")
    sp.run("HondaCRVGen1.Shared.setBed(v, true)")
    check(sp.eval("SHOWN(v)") == "0000", "seats folded: no clutter (the bed lies there)")
    sp.run("TICK(60)")
    check(sp.eval("SHOWN(v)") == "0000" and sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 3,
          "still hidden while folded; the state still follows the trunk")
    # fold modes (2026-10-22): as a bare load floor the trunk's load shows; made up as a bed it hides again
    sp.run("HondaCRVGen1.Shared.setFold(v, true, 'cargo')")
    check(sp.eval("SHOWN(v)") == "1110", "folded as a load floor: the load shows (%s)" % sp.eval("SHOWN(v)"))
    sp.run("HondaCRVGen1.Shared.setFold(v, true, 'bed')")
    check(sp.eval("SHOWN(v)") == "0000", "the bed made up: hidden again")
    sp.run("HondaCRVGen1.Shared.setBed(v, false)")
    check(sp.eval("SHOWN(v)") == "1110", "unfolded: the load shows again")
    # a load saved with the car shows on load (init on a fresh part)
    sp.run("w = newCRV(2); w.parts.CRVClutterCargo.md.crv_clutter_load = 2; w.parts.TruckBed.cont.weight = 25; "
           "%s.Init(w, w.parts.CRVClutterCargo)" % C)
    check(sp.eval("SHOWN(w)") == "1100", "a saved state 2 shows at init (%s)" % sp.eval("SHOWN(w)"))
    # a spawned car whose trunk the loot filled after its parts' init: the tick catches it
    sp.run("s = newCRV(3); %s.Init(s, s.parts.CRVClutterCargo); s.parts.TruckBed.cont.weight = 30; TICK(15)" % C)
    check(sp.eval("SHOWN(s)") == "1100", "trunk loot after init shows on the next fill check")
    # no trunk item: empty
    sp.run("s.parts.TruckBed.item = nil; TICK(15)")
    check(sp.eval("SHOWN(s)") == "0000", "the trunk part removed: nothing")
    # a car removed from the world leaves the followed list
    sp.run("s.removed = true; TICK(15)")
    check(sp.eval("%s.cars[3]" % C) is None, "a removed car is dropped from the fill tick")
    # other parts' init does nothing; a non-CR-V is ignored
    sp.run("calls1 = v.parts.CRVClutterCargo.calls; %s.Init(v, v.parts.TruckBed)" % C)
    check(sp.eval("v.parts.CRVClutterCargo.calls - calls1") == 0, "Init of another part is a no-op")
    sp.run("o = newVehicle(9, {'CRVClutterCargo'}, 'Base.SUV'); %s.apply(o)" % C)
    check(sp.eval("o.parts.CRVClutterCargo.calls") == 0, "a vanilla car is never touched")
    print("SP: states 0-3 at 10/40/75 %, hysteresis, incremental models, the well blanket with the table out, "
          "hidden while folded, saved / spawned / removed cars")


def multiplayer():
    net = Net()
    server = side("server", net, seed=11)
    a = side("client", net, player="alice", seed=12)
    b = side("client", net, player="bob", seed=13)
    C = "HondaCRVGen1.Clutter"
    for s in (server, a, b):
        s.run("v = newCRV(1); %s.Init(v, v.parts.CRVClutterCargo)" % C)
    check(a.eval("EVENTS.OnTick ~= nil and #EVENTS.OnTick") == 1, "a client registers only the State poll, no fill tick")
    server.run("v.parts.TruckBed.cont.weight = 30; TICK(15)")
    check(server.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 2, "server: state 2")
    check(server.eval("v.parts.CRVClutterCargo.calls") == 0, "the dedicated server draws nothing")
    check(a.eval("SHOWN(v)") == "0000", "nothing on the clients before the network")
    net.pump()
    for c in (a, b):
        check(c.eval("SHOWN(v)") == "1100", "%s shows state 2 (%s)" % (c.player, c.eval("SHOWN(v)")))
    # clients never derive the state from their own copy of the container
    a.run("v.parts.TruckBed.cont.weight = 0; TICK(60)")
    check(a.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 2 and a.eval("SHOWN(v)") == "1100",
          "a client's own container copy changes nothing")
    check(a.eval("HondaCRVGen1.State.set(v, 'clutter_load', 0)")[0] is False, "a client cannot set it")
    check(a.eval("HondaCRVGen1.State.request(PLAYER, v, 'clutter_load', 0)")[0] is False, "nor request it (server-only)")
    # the mod data packet alone (command lost): the clients' poll
    net.drop_commands = True
    server.run("v.parts.TruckBed.cont.weight = 50; TICK(15)")
    net.pump()
    for c in (a, b):
        c.run("TICK(30)")
        check(c.eval("SHOWN(v)") == "1110", "%s: the packet alone reaches state 3 through the poll" % c.player)
    net.drop_commands = False
    # the table taken out on the server: the item sync, then each client's poll
    server.run("v.parts.CRVPicnicTable:setInventoryItem(nil)")
    net.sync_item(1, "CRVPicnicTable")
    for c in (a, b):
        c.run("TICK(30)")
        check(c.eval("SHOWN(v)") == "1111", "%s: table out, the well blanket shows (%s)" % (c.player, c.eval("SHOWN(v)")))
    server.run("v.parts.CRVPicnicTable:setInventoryItem(newItem('Base.CRVGen1_PicnicTable'))")
    net.sync_item(1, "CRVPicnicTable")
    for c in (a, b):
        c.run("TICK(30)")
        check(c.eval("SHOWN(v)") == "1110", "%s: table back in" % c.player)
    # the fold, set on the server, hides the load on both clients
    server.run("HondaCRVGen1.Shared.setBed(v, true)")
    net.pump()
    for c in (a, b):
        check(c.eval("SHOWN(v)") == "0000", "%s: folded seats hide the load" % c.player)
    # the bed cleared for cargo on the server: the load shows on both clients (command, or the poll alone)
    server.run("HondaCRVGen1.Shared.setFold(v, true, 'cargo')")
    net.pump()
    for c in (a, b):
        check(c.eval("SHOWN(v)") == "1110", "%s: folded as a load floor, the load shows" % c.player)
    net.drop_commands = True
    server.run("HondaCRVGen1.Shared.setFold(v, true, 'bed')")
    net.pump()
    for c in (a, b):
        c.run("TICK(60)")
        check(c.eval("SHOWN(v)") == "0000", "%s: the bed made up (packet alone): hidden" % c.player)
    net.drop_commands = False
    server.run("HondaCRVGen1.Shared.setBed(v, false)")
    net.pump()
    for c in (a, b):
        check(c.eval("SHOWN(v)") == "1110", "%s: unfolded, the load is back" % c.player)
    # a third car streamed in on bob's client later: the full update carries the mod data, its init shows it
    server.run("w = newCRV(2); %s.Init(w, w.parts.CRVClutterCargo); w.parts.TruckBed.cont.weight = 8; TICK(15)" % C)
    net.pump()
    md = server.eval("w.parts.CRVClutterCargo.md.crv_clutter_load")
    b.run("w = newCRV(2); w.parts.CRVClutterCargo.md.crv_clutter_load = %d; %s.Init(w, w.parts.CRVClutterCargo)" % (md, C))
    check(b.eval("SHOWN(w)") == "1000", "a car streamed in later shows its state at init (%s)" % b.eval("SHOWN(w)"))
    # the server's State.set sent one command and one mod data packet per change, none while idle
    server.run("sent0 = SENT.transmitModData; TICK(300)")
    check(server.eval("SENT.transmitModData - sent0") == 0, "an idle server sends nothing")
    print("MP: the server derives and syncs (command or packet alone), never draws; clients never derive; "
          "table and fold follow on both clients; a streamed-in car shows at init")


def well_follows_storage():
    """H-FEATURES-8 (2026-10-24): the well blanket followed the TRUNK's fill: a well holding the under-floor storage's
    things showed nothing with an empty trunk. It now shows while the table is out and the storage holds something
    (State key clutter_well, derived on the authoritative side), or the trunk is loaded (its pieces stand partly over
    the open well); single player and a server with a client."""
    sp = side("sp", player="tester")
    C = "HondaCRVGen1.Clutter"
    sp.run("v = newCRV2(1); %s.Init(v, v.parts.CRVClutterCargo); v.parts.CRVPicnicTable:setInventoryItem(nil); TICK(30)" % C)
    check(sp.eval("SHOWN(v)") == "0000000", "table out, empty well and trunk: nothing (%s)" % sp.eval("SHOWN(v)"))
    sp.run("v.parts.CRVFunctionUnderfloor.cont.items = 2; v.parts.CRVFunctionUnderfloor.cont.weight = 1.5; TICK(15)")
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_well')") is True, "the storage holds something: clutter_well")
    check(sp.eval("SHOWN(v)") == "0000001", "table out, things in the well, empty trunk: the blanket (%s)" % sp.eval("SHOWN(v)"))
    sp.run("v.parts.CRVPicnicTable:setInventoryItem(newItem('Base.CRVGen1_PicnicTable')); TICK(30)")
    check(sp.eval("SHOWN(v)") == "0000000", "table back over the well: hidden")
    sp.run("v.parts.CRVPicnicTable:setInventoryItem(nil); TICK(30); v.parts.CRVFunctionUnderfloor.cont.items = 0; TICK(15)")
    check(sp.eval("SHOWN(v)") == "0000000" and sp.eval("v.parts.CRVClutterCargo.md.crv_clutter_well") is None,
          "the well emptied: hidden, the key back to its default")
    sp.run("v.parts.TruckBed.cont.weight = 30; TICK(15)")
    check(sp.eval("SHOWN(v)") == "1100001", "empty well, loaded trunk: the blanket under the load (nothing floats)")
    sp.run("v.parts.TruckBed.cont.weight = 0; v.parts.CRVFunctionUnderfloor.cont.items = 1; HondaCRVGen1.Shared.setBed(v, true); TICK(15)")
    check(sp.eval("SHOWN(v)") == "0000000", "the bed made up over it: nothing")
    sp.run("HondaCRVGen1.Shared.setBed(v, false)")
    # multiplayer: the server derives it, the client draws it
    net = Net()
    server = side("server", net, seed=21)
    a = side("client", net, player="alice", seed=22)
    for s in (server, a):
        s.run("v = newCRV2(5); v.parts.CRVPicnicTable.item = nil; %s.Init(v, v.parts.CRVClutterCargo)" % C)
    server.run("v.parts.CRVFunctionUnderfloor.cont.items = 3; TICK(15)")
    net.pump()
    check(a.eval("SHOWN(v)") == "0000001", "alice: the server's storage with things in it shows the blanket (%s)" % a.eval("SHOWN(v)"))
    a.run("v.parts.CRVFunctionUnderfloor.cont.items = 0; TICK(60)")
    check(a.eval("SHOWN(v)") == "0000001", "alice's own container copy changes nothing")
    check(server.eval("v.parts.CRVClutterCargo.calls") == 0, "the server draws nothing")
    print("WELL: the blanket follows the under-floor storage (or the trunk's load under which it lies), SP and MP")


def fold_load():
    """I-FEATURES-4 (2026-10-24): what lies on the folded load floor (CRVFunctionCargo, 60) shows on the folded seats in
    fold mode "cargo": InteriorClutterFold1..3 at 10 / 40 / 75 %, hidden while the seats are up or made up as a bed."""
    sp = side("sp", player="tester")
    C = "HondaCRVGen1.Clutter"
    S = "HondaCRVGen1.Shared"
    sp.run("v = newCRV2(1); %s.Init(v, v.parts.CRVClutterCargo); %s.setFold(v, true, 'cargo')" % (C, S))
    check(sp.eval("SHOWN(v)") == "0000000", "folded flat, empty: nothing")
    for kg, shown in ((5.0, "0000000"), (6.5, "0001000"), (24.5, "0001100"), (45.5, "0001110"), (60.0, "0001110")):
        sp.run("v.parts.CRVFunctionCargo.cont.weight = %r; TICK(15)" % kg)
        check(sp.eval("SHOWN(v)") == shown, "%.1f kg of 60 on the load floor: %s (got %s)" % (kg, shown, sp.eval("SHOWN(v)")))
    check(sp.eval("v.parts.CRVClutterCargo.md.crv_clutter_fold") == 3, "the state lives in the part's mod data")
    sp.run("v.parts.CRVFunctionCargo.cont.weight = 44.5; TICK(15)")
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_fold')") == 3, "hysteresis on the way down (74 %% stays 3)")
    sp.run("v.parts.TruckBed.cont.weight = 30; TICK(15)")
    check(sp.eval("SHOWN(v)") == "1101110", "both loads: the trunk's and the folded floor's (%s)" % sp.eval("SHOWN(v)"))
    sp.run("%s.setFold(v, true, 'bed')" % S)
    check(sp.eval("SHOWN(v)") == "0000000", "made up as a bed: nothing")
    sp.run("%s.setFold(v, true, 'cargo')" % S)
    check(sp.eval("SHOWN(v)") == "1101110", "back to a load floor: both again")
    sp.run("%s.setBed(v, false)" % S)
    check(sp.eval("SHOWN(v)") == "1100000", "seats up: the folded floor's pieces go, the trunk's stay")
    sp.run("calls0 = v.parts.CRVClutterCargo.calls; TICK(300)")
    check(sp.eval("v.parts.CRVClutterCargo.calls - calls0") == 0, "idle ticks make no setModelVisible calls")
    net = Net()
    server = side("server", net, seed=31)
    a = side("client", net, player="alice", seed=32)
    for s in (server, a):
        s.run("v = newCRV2(5); %s.Init(v, v.parts.CRVClutterCargo)" % C)
    server.run("%s.setFold(v, true, 'cargo'); v.parts.CRVFunctionCargo.cont.weight = 30; TICK(15)" % S)
    net.pump()
    check(a.eval("SHOWN(v)") == "0001100", "alice: the server's folded floor at state 2 (%s)" % a.eval("SHOWN(v)"))
    server.run("%s.setFold(v, true, 'bed')" % S)
    net.pump()
    check(a.eval("SHOWN(v)") == "0000000", "alice: the bed made up on the server hides it")
    print("FOLD LOAD: the folded load floor's pieces at 10/40/75 %, cargo mode only, SP and MP")


def prune_shown():
    """H-LUA-3 (2026-10-24): C.shown kept every CR-V a client ever drew (only re-initialising the same id replaced an
    entry). The State poll now drops the cars that left the world (State.prunable)."""
    s = side("client", Net(), player="bob")
    C = "HondaCRVGen1.Clutter"
    s.run("for id = 1, 50 do local v = newCRV2(id); %s.Init(v, v.parts.CRVClutterCargo); v.removed = true; VEHICLES[id] = nil end" % C)
    s.run("keep = newCRV2(99); %s.Init(keep, keep.parts.CRVClutterCargo)" % C)
    n0 = s.eval("(function() local n = 0 for _ in pairs(%s.shown) do n = n + 1 end return n end)()" % C)
    s.run("TICK(HondaCRVGen1.State.POLL)")
    n1 = s.eval("(function() local n = 0 for _ in pairs(%s.shown) do n = n + 1 end return n end)()" % C)
    check(n0 == 51 and n1 == 1 and s.eval("%s.shown[99] ~= nil" % C), "50 cars left the world: dropped by the poll (%d -> %d)" % (n0, n1))
    print("PRUNE: Clutter.shown loses the cars that left the world")


def parts_reset_on_init():
    """I-DIFF-1 (mutation clutter-parts-reset): the authoritative side keeps the car's parts and their containers
    (C.cars[id].parts, perf 2026-10-24); a part init (the parts re-made, e.g. the car reloaded under the same id and
    object) must look them up again, or the fill follows the old, dead trunk container."""
    sp = side("sp", player="tester")
    C = "HondaCRVGen1.Clutter"
    sp.run("v = newCRV(1); %s.Init(v, v.parts.CRVClutterCargo); v.parts.TruckBed.cont.weight = 30; TICK(15)" % C)
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 2, "parts reset: the first trunk followed (state 2)")
    sp.run("old = v.parts.TruckBed.cont; local t = v:addPart('TruckBed'); t.item = newItem('Base.NormalTrunk'); "
           "t.cont = newContainer(55, 50); %s.Init(v, v.parts.CRVClutterCargo); old.weight = 0; TICK(30)" % C)
    check(sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')") == 3,
          "parts reset: after the part init the new trunk (50 of 55 kg) is followed, not the old container (got %s)"
          % sp.eval("HondaCRVGen1.State.get(v, 'clutter_load')"))


def main():
    single_player()
    parts_reset_on_init()
    multiplayer()
    well_follows_storage()
    fold_load()
    prune_shown()
    if FAILS:
        print("%d FAIL(s)" % len(FAILS))
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
