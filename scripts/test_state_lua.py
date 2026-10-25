"""
HondaCRVGen1.State under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1): single player, a multiplayer
server with two clients over a fake network (scripts/lua_harness.py), and the roof rack's cargo
state migrated onto it (HondaCRVGen1Accessories.lua).

    python scripts\test_state_lua.py
"""
import os
import sys

from lua_harness import Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
ACC = STATE + ("server/Vehicles/HondaCRVGen1Accessories.lua",)

# keys every test side defines: a requestable choice, a requestable flag with a custom rule, a
# server-only number. Listeners log (vehicle id, key, value, old, how) into LOG.
DEFINE = r'''
local State = HondaCRVGen1.State
State.define("test_colour", { part = "CRVTest", kind = "string", default = "none",
                              values = { "none", "blue", "black" }, request = true })
State.define("test_flag", { part = "CRVTest", kind = "boolean", default = false,
                            request = function(vehicle, player, value, old)
                                if player and player:getUsername() == "mallory" then return false, "not you" end
                                return true
                            end })
State.define("test_level", { part = "CRVOther", kind = "number", default = 0, min = 0, max = 3, integer = true })
LOG = {}
State.onChange("*", function(vehicle, key, value, old, how)
    LOG[#LOG + 1] = { id = vehicle:getId(), key = key, value = value, old = old, how = how }
end)
function lastLog() return LOG[#LOG] end
'''


def log(side):
    return [dict(e.items()) for e in side.eval("LOG").values()]


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)


def single_player():
    sp = Side("sp", player="tester")
    sp.load(*STATE)
    sp.run(DEFINE)
    sp.run("v = newVehicle(1, {'CRVTest', 'CRVOther'})")
    S = "HondaCRVGen1.State"
    check(sp.eval("%s.get(v, 'test_colour')" % S) == "none", "default")
    check(sp.eval("%s.isCRV(v)" % S) and not sp.eval("%s.isCRV(newVehicle(2, {}, 'Base.SUV'))" % S), "isCRV")
    sp.run("%s.registerVehicle('Base.HondaCRVGen1Lifted')" % S)
    check(sp.eval("%s.isCRV(newVehicle(3, {}, 'Base.HondaCRVGen1Lifted'))" % S), "a registered script is a CR-V")
    # a menu asks: nothing changes until the game's local server delivers the command (a tick later)
    ok = sp.eval("%s.request(PLAYER, v, 'test_colour', 'blue')" % S)
    check(ok is True or (isinstance(ok, tuple) and ok[0] is True), "request accepted locally")
    check(sp.eval("%s.get(v, 'test_colour')" % S) == "none" and not log(sp), "unchanged before the pump")
    check(sp.pump() == 1, "one command queued")
    check(sp.eval("%s.get(v, 'test_colour')" % S) == "blue", "set by the server half")
    check(sp.eval("v.parts.CRVTest.md.crv_test_colour") == "blue", "stored in the host part's mod data")
    check(log(sp) == [{"id": 1, "key": "test_colour", "value": "blue", "old": "none", "how": "set"}], "one 'set' event: %s" % log(sp))
    check(sp.eval("SENT.transmitModData") == 1, "transmitted once")
    # the poll does not repeat it, the same value again is no change, the default clears the slot
    sp.run("TICK(60)")
    check(len(log(sp)) == 1, "the client poll repeated a local set")
    check(sp.eval("%s.set(v, 'test_colour', 'blue')" % S)[1] == "unchanged", "same value: unchanged")
    sp.run("%s.set(v, 'test_colour', 'none')" % S)
    check(sp.eval("v.parts.CRVTest.md.crv_test_colour") is None, "the default is stored as nil")
    sp.run("%s.set(v, 'test_colour', 'black'); LOG = {}; %s.set(v, 'test_colour', nil)" % (S, S))
    check(log(sp) == [{"id": 1, "key": "test_colour", "value": "none", "old": "black", "how": "set"}]
          and sp.eval("v.parts.CRVTest.md.crv_test_colour") is None, "set(nil) is the default: %s" % log(sp))
    sp.run("LOG = {}")
    # validation: wrong type, not an allowed value, out of range, server-only, far away, custom rule
    check(sp.eval("%s.set(v, 'test_colour', 3)" % S)[0] is False, "wrong type refused")
    check(sp.eval("%s.set(v, 'test_colour', 'pink')" % S)[0] is False, "unlisted value refused")
    check(sp.eval("%s.set(v, 'test_level', 4)" % S)[0] is False, "above max refused")
    check(sp.eval("%s.set(v, 'test_level', 1.5)" % S)[0] is False, "fraction refused")
    check(sp.eval("%s.request(PLAYER, v, 'test_level', 1)" % S)[0] is False, "server-only key not requestable")
    sp.run("PLAYER.x = 200")
    sp.run("sendClientCommand(PLAYER, 'HondaCRVGen1', 'set', { vehicle = 1, key = 'test_colour', value = 'black' })")
    sp.pump()
    check(sp.eval("%s.get(v, 'test_colour')" % S) == "none", "a player out of reach was obeyed")
    sp.run("PLAYER.x = 100; PLAYER.vehicle = nil")
    sp.run("M = newPlayer('mallory'); %s.request(M, v, 'test_flag', true)" % S)
    sp.pump()
    check(sp.eval("%s.get(v, 'test_flag')" % S) is False, "the custom rule was ignored")
    sp.run("%s.request(PLAYER, v, 'test_flag', true)" % S)
    sp.pump()
    check(sp.eval("%s.get(v, 'test_flag')" % S) is True, "the custom rule refused a legal player")
    # refresh: every key's current value, how 'init'; one key alone
    sp.run("LOG = {}; %s.refresh(v)" % S)
    check(sorted((e["key"], e["how"]) for e in log(sp)) == [("test_colour", "init"), ("test_flag", "init"), ("test_level", "init")],
          "refresh fires every key: %s" % log(sp))
    sp.run("LOG = {}; %s.refresh(v, 'test_flag')" % S)
    check([e["key"] for e in log(sp)] == ["test_flag"], "refresh(vehicle, key) fires that key only")
    # a listener that throws does not stop the others
    sp.run("%s.onChange('test_level', function() error('boom') end)" % S)
    sp.run("LOG = {}; %s.set(v, 'test_level', 2)" % S)
    check(len(log(sp)) == 1 and log(sp)[0]["value"] == 2, "a failing listener blocked the next one")
    print("STATE single player: request -> next tick -> set; validation, reach, custom rule, refresh, isolated listeners ok")


def multiplayer():
    net = Net()
    server = Side("server", net)
    a = Side("client", net, player="alice")
    b = Side("client", net, player="bob")
    for side in (server, a, b):
        side.load(*STATE)
        side.run(DEFINE)
    server.run("newPlayer('alice'); newPlayer('bob'); v = newVehicle(7, {'CRVTest', 'CRVOther'})")
    a.run("v = newVehicle(7, {'CRVTest', 'CRVOther'})")                  # bob has not streamed the car in yet
    S = "HondaCRVGen1.State"
    a.run("%s.refresh(v)" % S)
    check(len(log(a)) == 3 and all(e["how"] == "init" for e in log(a)), "client init")
    a.run("LOG = {}")
    # a client cannot set
    check(a.eval("%s.set(v, 'test_colour', 'blue')" % S)[0] is False, "a client set something")
    # request -> server validates and sets -> command + mod data -> client listener 'sync'
    a.run("%s.request(PLAYER, v, 'test_colour', 'blue')" % S)
    check(len(net.to_server) == 1, "request sent")
    net.pump()
    check(server.eval("%s.get(v, 'test_colour')" % S) == "blue", "server value")
    check(log(server) == [{"id": 7, "key": "test_colour", "value": "blue", "old": "none", "how": "set"}], "server event %s" % log(server))
    check(a.eval("%s.get(v, 'test_colour')" % S) == "blue", "client value")
    check(log(a) == [{"id": 7, "key": "test_colour", "value": "blue", "old": "none", "how": "sync"}], "client event %s" % log(a))
    check(a.eval("v.parts.CRVTest.md.crv_test_colour") == "blue", "client mod data (the packet)")
    a.run("TICK(90)")
    check(len(log(a)) == 1, "the poll fired again after the command")
    # bob streams the car in later: his init reads the mod data the full update carried
    b.run("v = newVehicle(7, {'CRVTest', 'CRVOther'}); v.parts.CRVTest.md.crv_test_colour = 'blue'")
    b.run("%s.refresh(v, 'test_colour')" % S)
    check(log(b) == [{"id": 7, "key": "test_colour", "value": "blue", "how": "init"}], "late joiner init %s" % log(b))
    # the mod data packet alone (no command): the poll catches it
    net.drop_commands = True
    server.run("%s.set(v, 'test_level', 3)" % S)
    net.pump()
    net.drop_commands = False
    check(a.eval("%s.get(v, 'test_level')" % S) == 3 and not [e for e in log(a) if e["key"] == "test_level"], "before the poll")
    a.run("TICK(%d)" % a.eval("%s.POLL" % S))
    lv = [e for e in log(a) if e["key"] == "test_level"]
    check(lv == [{"id": 7, "key": "test_level", "value": 3, "old": 0, "how": "sync"}], "poll sync %s" % lv)
    # back to the default (nil travels as an absent value): the client hears the default, not nil
    a.run("LOG = {}")
    server.run("%s.set(v, 'test_colour', nil)" % S)
    net.pump()
    check(log(a) == [{"id": 7, "key": "test_colour", "value": "none", "old": "blue", "how": "sync"}]
          and a.eval("v.parts.CRVTest.md.crv_test_colour") is None, "client default after set(nil): %s" % log(a))
    # a server-only key requested anyway (a hand-made command) is refused by the server
    a.run("sendClientCommand(PLAYER, 'HondaCRVGen1', 'set', { vehicle = 7, key = 'test_level', value = 1 })")
    net.pump()
    check(server.eval("%s.get(v, 'test_level')" % S) == 3, "the server obeyed a server-only request")
    # a car the client does not have: the announcement is ignored, nothing breaks
    server.run("w = newVehicle(8, {'CRVTest'})")
    server.run("%s.set(w, 'test_colour', 'black')" % S)
    net.pump()
    check(a.eval("VEHICLES[8]") is None, "phantom car")
    # the server never tracks or polls (it draws nothing)
    check(len(list(server.eval("%s.tracked" % S).keys())) == 0, "the server tracked cars")
    print("STATE multiplayer: request -> server -> command + mod data -> clients; late joiner, packet-only poll, "
          "server-only refusal, unknown car ok")


ONLINE = r'''
function getOnlinePlayers()
    local list = {}
    for _, name in ipairs({ 'alice', 'bob', 'carol' }) do if PLAYERS[name] then list[#list + 1] = PLAYERS[name] end end
    return { size = function() return #list end, get = function(_, i) return list[i + 1] end }
end
'''


def announcements():
    """H-MP-1 / H-MP-I3 (2026-10-24). Every "changed" carries seq (rising per server run) and session (the run's id);
    a client applies a key's announcement only when it is newer than the last one it applied for that car, so a resent
    old command (ClientCommand is reliable but unordered) cannot undo a newer value. A new car object under the id, or
    another server run, starts fresh. The command goes only to the online players within State.STREAM tiles of the car
    on both axes (vanilla's relevance: at most 12 chunks = 96 tiles, UdpConnection.isRelevantTo); a player who
    streams the car in later reads the state from its mod data."""
    net = Net()
    server = Side("server", net)
    a = Side("client", net, player="alice")
    b = Side("client", net, player="bob")
    c = Side("client", net, player="carol")
    for side in (server, a, b, c):
        side.load(*STATE)
        side.run(DEFINE)
    S = "HondaCRVGen1.State"
    server.run(ONLINE)
    check(server.eval("%s.STREAM" % S) >= 96 + 16, "the stream margin covers vanilla's widest relevance (96 tiles)")
    # alice at the car, bob 100 tiles off on x (inside the widest relevance), carol 300 tiles off
    server.run("newPlayer('alice', 100, 100); newPlayer('bob', 200, 100); newPlayer('carol', 400, 100); "
               "v = newVehicle(7, {'CRVTest', 'CRVOther'})")
    for side in (a, b, c):
        side.run("v = newVehicle(7, {'CRVTest', 'CRVOther'}); %s.refresh(v); LOG = {}" % S)
    server.run("%s.set(v, 'test_colour', 'blue')" % S)
    cmds = [p for p in net.to_clients if p[1] == "changed"]
    check(sorted(p[3] for p in cmds) == ["alice", "bob"], "sent to the players in stream range only: %s" % [p[3] for p in cmds])
    net.drop_commands = False
    net.moddata.clear()                                            # carol: not even the mod data reaches her (not relevant)
    net.pump()
    check(a.eval("%s.get(v, 'test_colour')" % S) == "blue" and b.eval("%s.get(v, 'test_colour')" % S) == "blue", "alice, bob")
    check(c.eval("%s.get(v, 'test_colour')" % S) == "none" and not log(c), "carol heard nothing")
    # carol drives up: the car streams in again (a new object) with the mod data; her init reads it
    c.run("v = newVehicle(7, {'CRVTest', 'CRVOther'}); v.parts.CRVTest.md.crv_test_colour = 'blue'; %s.refresh(v, 'test_colour')" % S)
    check(c.eval("%s.get(v, 'test_colour')" % S) == "blue", "carol streams it in later: the state comes with the car")
    # numbering: two quick changes, the first resent late (after the second), and a duplicate
    server.run("%s.set(v, 'test_colour', 'black')" % S)
    c1 = net.take()
    server.run("%s.set(v, 'test_colour', 'none')" % S)
    c2 = net.take()
    seqs = [p[2]["seq"] for k, p in c1 + c2 if k == "cmd" and p[3] == "alice"]
    check(len(seqs) == 2 and seqs[0] < seqs[1], "rising numbers %s" % seqs)
    a.run("LOG = {}")
    net.deliver(c2 + c1 + c2)
    a.run("TICK(%d)" % (a.eval("%s.POLL" % S) * 4))
    check(a.eval("%s.get(v, 'test_colour')" % S) == "none", "the late older announcement is dropped: %s" % a.eval("%s.get(v, 'test_colour')" % S))
    check([e["value"] for e in log(a)] == ["none"], "one change heard, nothing undone: %s" % log(a))
    # a stale one for a key does not block another key
    server.run("%s.set(v, 'test_level', 2)" % S)
    net.pump()
    check(a.eval("%s.get(v, 'test_level')" % S) == 2, "another key's newer announcement applies")
    # a new car object under the id (streamed out and back): fresh record, an announcement with an old number applies
    old = [p for k, p in c1 if k == "cmd" and p[3] == "alice"][0]
    a.run("v = newVehicle(7, {'CRVTest', 'CRVOther'}); %s.refresh(v)" % S)
    a.trigger("OnServerCommand", old[0], old[1], a.table(old[2]))
    check(a.eval("%s.get(v, 'test_colour')" % S) == "black", "a new car object starts a fresh record")
    # the server restarts: numbers from 1 again under a new session id; the client takes them
    a.trigger("OnServerCommand", "HondaCRVGen1", "changed",
              a.table({"vehicle": 7, "key": "test_colour", "value": "blue", "seq": 1, "session": -5}))
    check(a.eval("%s.get(v, 'test_colour')" % S) == "blue", "another server run (session): its first number applies")
    a.trigger("OnServerCommand", "HondaCRVGen1", "changed",
              a.table({"vehicle": 7, "key": "test_colour", "value": "none", "seq": 1, "session": -5}))
    check(a.eval("%s.get(v, 'test_colour')" % S) == "blue", "the same number again (a duplicate) is dropped")
    # no player list (getOnlinePlayers missing): every client, as before
    server.run("getOnlinePlayers = nil; %s.set(v, 'test_level', 3)" % S)
    check([p[3] for p in net.to_clients if p[1] == "changed"] == [None], "no player list: broadcast")
    net.pump()
    check(c.eval("%s.get(v, 'test_level')" % S) == 3, "broadcast reached carol")
    print("STATE announcements: numbered (late / duplicate dropped, new car and new server run start fresh), "
          "sent only to players in stream range")


def rack_over_mp():
    """The roof rack's cargo state, set on the server from the container and drawn by a client."""
    net = Net()
    server = Side("server", net)
    client = Side("client", net, player="alice")
    rack_setup = r'''
v = newVehicle(11, {'CRVRoofRack', 'TrunkDoor'})
rack = v.parts.CRVRoofRack
rack.models = { 'CRVRoofRack', 'RackLoad1', 'RackLoad2', 'RackLoad3' }
rack.cont = newContainer(50, 0)
function shown()
    local out = {}
    for _, m in ipairs(rack.models) do if rack.visible[m] then out[#out + 1] = m end end
    return table.concat(out, '+')
end
'''
    for side in (server, client):
        side.load(*ACC)
        side.run(rack_setup)
    Acc = "HondaCRVGen1.Acc"
    # the car spawns with a rack holding 20 kg: created on the server, streamed to the client
    server.run("rack:setInventoryItem(newItem('CRVGen1_RoofRack')); rack.cont.weight = 20; %s.Init(v, rack)" % Acc)
    net.pump()
    check(server.eval("HondaCRVGen1.State.get(v, 'acc_rackLoad')") == 2, "server state for 20/50 kg")
    check(server.eval("rack.calls") == 0, "the server touched models")
    client.run("rack:setInventoryItem(newItem('CRVGen1_RoofRack'))")      # the full update, models all shown
    check(client.eval("shown()") == "CRVRoofRack+RackLoad1+RackLoad2+RackLoad3", "engine default on the client")
    client.run("%s.Init(v, rack)" % Acc)
    check(client.eval("shown()") == "CRVRoofRack+RackLoad2", "client after init: %s" % client.eval("shown()"))
    check(client.eval("HondaCRVGen1.State.get(v, 'acc_rackLoad')") == 2, "client value from the mod data packet")
    # fill changes on the server reach the client through the State module
    for kg, want in ((40, "CRVRoofRack+RackLoad3"), (1, "CRVRoofRack"), (3, "CRVRoofRack+RackLoad1")):
        server.run("rack.cont.weight = %s; TICK(%s.RACK_EVERY)" % (kg, Acc))
        net.pump()
        check(client.eval("shown()") == want, "%s kg -> %s, want %s" % (kg, client.eval("shown()"), want))
    calls = client.eval("rack.calls")
    client.run("TICK(120)")
    check(client.eval("rack.calls") == calls, "idle client ticks called setModelVisible")
    # the rack comes off and goes back on (both completed on the server); the client only sees items arrive
    server.run("rack.cont.weight = 0; rack:setInventoryItem(nil); %s.UninstallComplete(v, rack, {})" % Acc)
    net.pump()
    net.sync_item(11, "CRVRoofRack")
    check(client.eval("shown()") == "", "uninstalled: nothing drawn")
    server.run("rack:setInventoryItem(newItem('CRVGen1_RoofRack')); %s.InstallComplete(v, rack)" % Acc)
    net.pump()
    net.sync_item(11, "CRVRoofRack")
    check(client.eval("shown()") == "CRVRoofRack+RackLoad1+RackLoad2+RackLoad3", "the item reset the client's models")
    client.run("TICK(HondaCRVGen1.State.POLL)")
    check(client.eval("shown()") == "CRVRoofRack", "the client poll trimmed a reinstalled empty rack: %s" % client.eval("shown()"))
    server.run("rack.cont.weight = 20; TICK(%s.RACK_EVERY)" % Acc)
    net.pump()
    check(client.eval("shown()") == "CRVRoofRack+RackLoad2", "fill after reinstall")
    calls = client.eval("rack.calls")
    client.run("TICK(120)")
    check(client.eval("rack.calls") == calls, "idle client ticks after the reinstall called setModelVisible")
    check(server.eval("rack.calls") == 0, "the server touched models")
    print("STATE rack cargo over multiplayer: server derives, client draws; reinstall reset caught by the poll")


def caches_pruned():
    """H-LUA-3 (2026-10-24): the drawing side's per-car caches (Acc.shown, Clutter.shown, Awning.shown; Function's
    seatsShown) kept every CR-V a client ever drew. State.prunable registers a cache; the client poll (State.POLL
    ticks) drops the entries of cars that left the world by the same test it prunes State.tracked with (State.gone:
    removed from the world, or another car now under that id), and keeps the rest. The hunt's probe: 50 kitted cars
    streamed in and out on a client, then 300 ticks."""
    c = Side("client", Net(), player="bob")
    c.load(*ACC)
    c.run(DEFINE)
    S = "HondaCRVGen1.State"
    c.run("CACHE = %s.prunable({}); %s.prunable(CACHE)" % (S, S))
    check(c.eval("(function() local n = 0 for _, t in ipairs(%s.caches) do if t == CACHE then n = n + 1 end end return n end)()" % S) == 1,
          "registered once")
    c.run("for id = 1, 50 do local v = newVehicle(id, {'CRVRoofRack'}); CACHE[id] = { vehicle = v }; "
          "local rack = v.parts.CRVRoofRack; rack.item = newItem('Base.CRVGen1_RoofRack'); rack.cont = newContainer(50, 0); "
          "rack.models = { 'CRVRoofRack', 'RackLoad1', 'RackLoad2', 'RackLoad3' }; HondaCRVGen1.Acc.Init(v, rack) end")
    c.run("live = newVehicle(77, {'CRVTest'}); CACHE[77] = { vehicle = live }; CACHE[78] = { vehicle = live }")
    c.run("for id = 1, 50 do VEHICLES[id].removed = true; VEHICLES[id] = nil end; TICK(300)")
    left = c.eval("(function() local t = {} for id, _ in pairs(CACHE) do t[#t + 1] = id end table.sort(t) "
                  "return table.concat(t, ',') end)()")
    check(left == "77", "removed cars and a stale id dropped, the live car kept: %s" % left)
    n = c.eval("(function() local n = 0 for _ in pairs(HondaCRVGen1.Acc.shown) do n = n + 1 end return n end)()")
    check(n == 0, "Acc.shown: %d removed cars still referenced" % n)
    check(c.eval("%s.gone(nil, 1)" % S) and not c.eval("%s.gone(live, 77)" % S) and c.eval("%s.gone(live, 78)" % S),
          "State.gone: nil, the live car, another id")
    # the reach a timed action's complete() re-checks (State.near): in the car, or within REACH tiles
    c.run("p = newPlayer('walker', 100, 100)")
    check(c.eval("%s.near(p, live)" % S), "at the car: near")
    c.run("p.x = 100 + %s.REACH + 0.5" % S)
    check(not c.eval("%s.near(p, live)" % S), "past REACH: not near")
    c.run("p.vehicle = live")
    check(c.eval("%s.near(p, live)" % S), "inside the car: near")
    print("STATE caches: prunable caches lose the cars that left the world on the client poll; State.near")


def part_cache_reset():
    """I-DIFF-1 (mutation partof-nocache-reset): the client poll keeps each tracked car's part objects (State.partOf,
    perf 2026-10-24); State.refresh, which every part init calls, must drop that cache, or a part made after the
    first poll (cached as missing) is never read again: its synced values are lost to the poll."""
    c = Side("client", Net(), player="bob")
    c.load(*STATE)
    c.run(DEFINE)
    S = "HondaCRVGen1.State"
    c.run("v = newVehicle(9, {'CRVOther'}); %s.refresh(v); TICK(%s.POLL * 2)" % (S, S))
    check(c.eval("%s.tracked[9].parts.CRVTest" % S) is False,"the poll cached CRVTest as missing")
    c.run("p = v:addPart('CRVTest'); p.md.crv_test_colour = 'blue'; %s.refresh(v)" % S)   # the part's init
    c.run("LOG = {}; p.md.crv_test_colour = 'black'; TICK(%s.POLL * 2)" % S)              # a mod data packet alone
    got = [(e["key"], e["value"]) for e in log(c)]
    check(got == [("test_colour", "black")], "the poll reads the new part after its init: %s" % got)
    print("STATE part cache: a part init (State.refresh) drops the poll's part cache")


def smashed():
    """H-PLAY-4 (2026-10-24): crash-scene CR-Vs spawned like new: BaseVehicle.setSmashed(side) (42.21) looks up
    SmashedCarDefinitions.cars[scriptName][side:lower()] and, only when it finds a script there, replaces the car with
    a new one of it (part conditions 0.5 +- 60, engine 0, glove box gone, VehicleEngine.setSmashed); "skin" is read
    with rawgetInt (missing = -1: keep the car's skin). Every CR-V script must map every side to itself, also when
    vanilla's file (which sets cars = {}) loads after ours."""
    import glob
    import re
    import crv_paths
    from lua_harness import LUA_DIR
    vanilla = os.path.join(crv_paths.GAME_MEDIA, "lua", "shared", "Definitions", "SmashedCarDefinitions.lua")
    check(os.path.exists(vanilla), "vanilla %s" % vanilla)
    vdir = os.path.join(os.path.dirname(LUA_DIR), "scripts", "vehicles")
    scripts = sorted("Base." + n for f in glob.glob(os.path.join(vdir, "*.txt"))
                     for n in re.findall(r"^\s*vehicle\s+(\w+)", open(f, encoding="utf-8").read(), re.M))
    check(len(scripts) == 3, "3 CR-V vehicle scripts: %s" % scripts)
    for order in ("vanilla first", "ours first"):
        s = Side("server" if order == "ours first" else "sp")
        files = ("shared/HondaCRVGen1_State.lua", "shared/HondaCRVGen1_Vehicles.lua", "shared/HondaCRVGen1_Smashed.lua")
        if order == "vanilla first":
            s.load(vanilla, *files)
        else:
            s.load(*files)
            s.load(vanilla)
            check(s.eval("SmashedCarDefinitions.cars['Base.HondaCRVGen1']") is None, "vanilla's file reset the table")
            s.trigger("OnGameBoot")
        for script in scripts:
            for side in ("Front", "Rear", "Left", "Right"):
                got = s.eval("(SmashedCarDefinitions.cars[%r] or {})[string.lower(%r)]" % (script, side))
                check(got == script, "%s: setSmashed(%r) -> %r (want the same script)" % (order, side, got))
            check(s.eval("SmashedCarDefinitions.cars[%r].skin" % script) is None, "%s: no skin entry (keeps the paint)" % script)
        check(s.eval("SmashedCarDefinitions.cars['Base.CarNormal'].front") == "Base.CarNormalSmashedFront", "vanilla entries kept")
        s.run("SmashedCarDefinitions.cars['Base.HondaCRVGen1'] = { front = 'Other.Mod' }")
        s.trigger("OnInitGlobalModData")
        check(s.eval("SmashedCarDefinitions.cars['Base.HondaCRVGen1'].front") == "Other.Mod", "another mod's entry is not replaced")
    print("STATE smashed: every CR-V script maps each crash side to itself in SmashedCarDefinitions (either load order)")


def main():
    single_player()
    multiplayer()
    announcements()
    rack_over_mp()
    caches_pruned()
    part_cache_reset()
    smashed()
    print("STATE LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
