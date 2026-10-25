"""
HondaCRVGen1.Trunk under Lua 5.1 (lupa, with the harness's Kahlua limits), single player and multiplayer:

  1. a new CR-V's trunk (part TruckBed, items Base.BigTrunk1;Base.NormalTrunk1) is always the BigTrunk1 (70):
     vanilla's VehicleUtils.createPartInventoryItem alone rolls either one (the stand-in below copies its pick);
  2. a car saved before 0.4.4 with the NormalTrunk1 (55) it was made with gets a BigTrunk1 in the same condition,
     once, on the authoritative side only (the server sends the item); a standard trunk fitted afterwards stays;
  3. the picnic table comes out or goes back through the mechanics screen only with the gate open or gone.

    python scripts\\test_trunk_lua.py
"""
import sys

from lua_harness import Side

TRUNK = ("shared/HondaCRVGen1_Trunk.lua",)

STUBS = r'''
-- java.util.ArrayList / HashMap stand-ins
function jlist(t)
    local l = { t = t }
    function l:size() return #self.t end
    function l:get(i) return self.t[i + 1] end
    function l:isEmpty() return #self.t == 0 end
    return l
end
function jmap()
    local m = { t = {} }
    function m:get(k) return self.t[k] end
    function m:put(k, v) self.t[k] = v end
    return m
end

ITEMS_MADE = 0
function instanceItem(full)
    ITEMS_MADE = ITEMS_MADE + 1
    local it = { full = full, cond = 100, max = 100 }
    function it:getFullType() return self.full end
    function it:getCondition() return self.cond end
    function it:setConditionNoSound(c) self.cond = c end
    function it:getConditionMax() return self.max end
    function it:setConditionMax(c) self.max = c end
    function it:setMaxCapacity(c) self.cap = c end
    return it
end

function makeTrunkPart(car, types)
    local p = { md = {}, types = jlist(types), vehicle = car }
    function p:getItemType() return self.types end
    function p:getInventoryItem() return self.item end
    function p:setInventoryItem(i) self.item = i end
    function p:getModData() return self.md end
    function p:getContainerCapacity() return 0 end
    function p:setRandomCondition(i) i.cond = 40 + (ZombRand(60)) end
    function p:getVehicle() return self.vehicle end
    return p
end

function makeCar()
    local car = { chosen = jmap(), parts = {}, sentItem = 0 }
    function car:getChoosenParts() return self.chosen end
    function car:getPartById(id) return self.parts[id] end
    function car:transmitPartItem(p) self.sentItem = self.sentItem + 1 end
    car.parts.TruckBed = makeTrunkPart(car, { "Base.BigTrunk1", "Base.NormalTrunk1" })
    return car
end

-- vanilla 42.21 VehicleUtils.createPartInventoryItem (server/Vehicles/Vehicles.lua), its item pick as written
VehicleUtils = {}
function VehicleUtils.createPartInventoryItem(part)
    if not part:getItemType() or part:getItemType():isEmpty() then return nil end
    if not part:getInventoryItem() then
        local v = part:getVehicle()
        local chosenKey = ""
        for i = 1, part:getItemType():size() do chosenKey = chosenKey .. part:getItemType():get(i - 1) .. ';' end
        local itemType = v:getChoosenParts():get(chosenKey)
        if not itemType then
            for i = 0, part:getItemType():size() - 1 do
                if ZombRand(100) > (100 - (100 / part:getItemType():size())) or i == part:getItemType():size() - 1 then
                    itemType = part:getItemType():get(i)
                    v:getChoosenParts():put(chosenKey, itemType)
                    break
                end
            end
        end
        local item = instanceItem(itemType)
        part:setRandomCondition(item)
        part:setInventoryItem(item)
    end
    return part:getInventoryItem()
end

-- the gate and vanilla's tests
function makeGate(car, item, open)
    local door = { open = open }
    function door:isOpen() return self.open end
    local g = { item = item, door = door }
    function g:getInventoryItem() return self.item end
    function g:getDoor() return self.door end
    car.parts.TrunkDoor = g
    return g
end
DEFAULT_CALLS = 0
Vehicles = { InstallTest = {}, UninstallTest = {} }
function Vehicles.InstallTest.Default(v, p, c) DEFAULT_CALLS = DEFAULT_CALLS + 1; return "install-default" end
function Vehicles.UninstallTest.Default(v, p, c) DEFAULT_CALLS = DEFAULT_CALLS + 1; return "uninstall-default" end
'''


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def spawn_counts(s, n, ours):
    s.run("BIG, OLD = 0, 0")
    fn = "HondaCRVGen1.Trunk.Create(C, C.parts.TruckBed)" if ours else "VehicleUtils.createPartInventoryItem(C.parts.TruckBed)"
    s.run("for i = 1, %d do C = makeCar(); %s; local t = C.parts.TruckBed:getInventoryItem():getFullType(); "
          "if t == 'Base.BigTrunk1' then BIG = BIG + 1 elseif t == 'Base.NormalTrunk1' then OLD = OLD + 1 end end" % (n, fn))
    return s.eval("BIG"), s.eval("OLD")


def main():
    s = Side("sp")
    s.load(*TRUNK)
    s.run(STUBS)
    # 1. vanilla's own pick alone gives about half the cars the 55; ours gives every car the 70
    big, old = spawn_counts(s, 400, ours=False)
    check(old > 100 and big > 100, "the vanilla stand-in rolls both families (%d big, %d normal)" % (big, old))
    big, old = spawn_counts(s, 400, ours=True)
    check(big == 400 and old == 0, "Trunk.Create: every new car gets BigTrunk1 (%d big, %d normal)" % (big, old))
    s.run("C = makeCar(); C.parts.TruckBed.item = instanceItem('Base.NormalTrunk1'); HondaCRVGen1.Trunk.Create(C, C.parts.TruckBed)")
    check(s.eval("C.parts.TruckBed.item.full") == "Base.NormalTrunk1", "Create keeps an item that is already there")

    # 2. the one-off upgrade (single player)
    s.run("C = makeCar(); OLDT = instanceItem('Base.NormalTrunk1'); OLDT.cond = 63; C.parts.TruckBed.item = OLDT")
    check(s.eval("HondaCRVGen1.Trunk.Init(C, C.parts.TruckBed) == nil and C.parts.TruckBed.item.full") == "Base.BigTrunk1",
          "an old car's NormalTrunk1 becomes a BigTrunk1")
    check(s.eval("C.parts.TruckBed.item.cond") == 63, "in the same condition")
    check(s.eval("C.sentItem") == 0, "single player sends nothing")
    s.run("C.parts.TruckBed.item = instanceItem('Base.NormalTrunk1')")          # the player fits a standard trunk later
    check(s.eval("HondaCRVGen1.Trunk.fix(C, C.parts.TruckBed)") is False
          and s.eval("C.parts.TruckBed.item.full") == "Base.NormalTrunk1", "a standard trunk fitted afterwards stays")
    s.run("C = makeCar(); C.parts.TruckBed.item = instanceItem('Base.BigTrunk1')")
    check(s.eval("HondaCRVGen1.Trunk.fix(C, C.parts.TruckBed)") is False and s.eval("C.parts.TruckBed.md.crv_trunk70") is True,
          "a new car is marked, untouched")
    s.run("C = makeCar(); HondaCRVGen1.Trunk.Init(C, C.parts.TruckBed); C.parts.TruckBed.item = instanceItem('Base.NormalTrunk1')")
    check(s.eval("HondaCRVGen1.Trunk.fix(C, C.parts.TruckBed)") is False, "a car with no trunk at first sight keeps what goes in")

    # multiplayer: the server upgrades and sends the item, a client never touches it
    srv = Side("server")
    srv.load(*TRUNK)
    srv.run(STUBS)
    srv.run("C = makeCar(); C.parts.TruckBed.item = instanceItem('Base.NormalTrunk1')")
    check(srv.eval("HondaCRVGen1.Trunk.fix(C, C.parts.TruckBed)") is True and srv.eval("C.sentItem") == 1,
          "the server upgrades and transmits the trunk")
    cl = Side("client")
    cl.load(*TRUNK)
    cl.run(STUBS)
    cl.run("C = makeCar(); C.parts.TruckBed.item = instanceItem('Base.NormalTrunk1')")
    check(cl.eval("HondaCRVGen1.Trunk.fix(C, C.parts.TruckBed)") is False
          and cl.eval("C.parts.TruckBed.item.full") == "Base.NormalTrunk1",
          "a client leaves the trunk to the server")

    # 3. the picnic table's mechanics tests
    T = "HondaCRVGen1.Trunk"
    for side in (s, cl):
        side.run("C = makeCar(); P = {}; G = makeGate(C, instanceItem('Base.TrunkDoor1'), false); DEFAULT_CALLS = 0")
        check(side.eval("%s.TableInstallTest(C, P, nil)" % T) is False and side.eval("%s.TableUninstallTest(C, P, nil)" % T) is False
              and side.eval("DEFAULT_CALLS") == 0, "%s: gate shut: no take-out, no put-back" % side.role)
        side.run("G.door.open = true")
        check(side.eval("%s.TableInstallTest(C, P, nil)" % T) == "install-default"
              and side.eval("%s.TableUninstallTest(C, P, nil)" % T) == "uninstall-default", "gate open: vanilla's tests decide")
        side.run("G.door.open = false; G.item = nil")
        check(side.eval("%s.TableUninstallTest(C, P, nil)" % T) == "uninstall-default", "gate removed: reachable")
        side.run("C.parts.TrunkDoor = nil")
        check(side.eval("%s.TableInstallTest(C, P, nil)" % T) == "install-default", "no gate part: reachable")
        side.run("G = makeGate(C, instanceItem('Base.TrunkDoor1'), false); ISVehicleMechanics = { cheat = true }")
        check(side.eval("%s.TableInstallTest(C, P, nil)" % T) == "install-default", "mechanics cheat: vanilla's tests decide")
        side.run("ISVehicleMechanics = nil")
    print("TRUNK LUA TESTS OK")


if __name__ == "__main__":
    main()
