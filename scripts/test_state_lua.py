"""
HondaCRVGen1.State under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1): single player, a multiplayer
server with two clients over a fake network (scripts/lua_harness.py), and the roof rack's cargo
state migrated onto it (HondaCRVGen1Accessories.lua).

    python scripts\test_state_lua.py
"""
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


def main():
    single_player()
    multiplayer()
    rack_over_mp()
    print("STATE LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
