r"""
The function feature's Lua under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1), single player and a
multiplayer server with two clients (scripts/lua_harness.py):

  * fold-flat seats: the timed action changes the state in complete() only (the old perform() bug),
    the state rides HondaCRVGen1.State to every client, rear seats refuse items, the folded load floor
    (CRVFunctionCargo) opens only while folded and must be empty to unfold, old saves' crvBed migrates;
  * the hidden under-floor storage: invisible until "Lift the cargo floor" completes (gate open), then
    open at the tailgate on every client;
  * NetTimedAction: every new() parameter of our actions is stored under its own name;
  * sandbox: FunctionSpawnRate scales the zone weights at OnLoadedMapZones, FunctionAccessoryChance the
    accessory rolls (Acc.Create), FunctionLootRarity the generated loot (weight x headroom, thinned at
    OnFillContainer) and the glove-box manual;
  * the owner's manual's Mechanics XP bonus on a CR-V (wrapped vanilla actions, authoritative side).

    python scripts\test_function_lua.py
"""
import os
import re
import sys

from lua_harness import LUA_DIR, Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
FUNC = ("shared/HondaCRVGen1_Shared.lua", "server/Vehicles/HondaCRVGen1Accessories.lua", "shared/HondaCRVGen1_Function.lua",
        "shared/TimedActions/ISCRVFoldSeats.lua", "shared/TimedActions/ISCRVFunctionLiftFloor.lua",
        "server/HondaCRVGen1_FunctionServer.lua")
LOOT = os.path.join(LUA_DIR, "server", "Items", "HondaCRVGen1_Loot.lua")

# what the game gives the mod's Lua beyond lua_harness's PRELUDE: timed actions, vanilla vehicle actions
# (their complete() reduced to the part change), doors, items with ids, XP, the zone and loot tables
GAME = r'''
ISBaseTimedAction = {}
ISBaseTimedAction.__index = ISBaseTimedAction
function ISBaseTimedAction:derive(t) local o = {}; setmetatable(o, self); self.__index = self; o.Type = t; return o end
function ISBaseTimedAction.new(self, character)
    local o = {}; setmetatable(o, self); self.__index = self; o.character = character; return o
end
function ISBaseTimedAction:perform() self.performed = true end
function ISBaseTimedAction:stop() end
function ISBaseTimedAction:setActionAnim() end
HALO = {}
HaloTextHelper = { addText = function(c, t) HALO[#HALO + 1] = t end, addBadText = function(c, t) HALO[#HALO + 1] = t end,
                   getColorWhite = function() return 1 end }
XP = {}
Perks = { Mechanics = "Mechanics" }
function addXp(c, perk, amount) XP[#XP + 1] = { c = c:getUsername(), perk = perk, amount = amount } end
function ZombRandFloat(a, b) return a + math.random() * (b - a) end

ISInstallVehiclePart = { complete = function(self)
    if self.fail then return true end
    self.part:setInventoryItem(self.item); return true end }
ISUninstallVehiclePart = { complete = function(self) self.part:setInventoryItem(nil); return true end }
ISRepairEngine = { complete = function(self) self.part:setCondition(self.part:getCondition() + 10); return true end }

Item.nextId = 100
local newItem0 = newItem
function newItem(t) local it = newItem0(t); Item.nextId = Item.nextId + 1; it.id = Item.nextId; return it end
function Item:getID() return self.id end
function Item:getFullType() return self.type end

Door = {}
Door.__index = Door
function Part:getDoor() return self.door end
function Door:isOpen() return self.open end
function Cont:AddItem(t) self.items = self.items + 1; self.added = self.added or {}; self.added[#self.added + 1] = t end

function Veh:getMechanicalID() return 4242 end
function Veh:getIdent() return self.id end

function Player:faceThisObject() end
function Player:shouldBeTurning() return false end
function Player:isTimedActionInstant() return false end
function Player:SetVariable() end
function Player:isRecipeActuallyKnown(name) return self.known ~= nil and self.known[name] == true end
function Player:getMechanicsItem(key) return self.mech and self.mech[key] end

-- a CR-V with what the feature touches
function newCRV(id)
    local v = newVehicle(id, { "SeatRearLeft", "SeatRearRight", "CRVFunctionCargo", "CRVFunctionUnderfloor",
                               "CRVFunctionSeats", "TrunkDoor", "DoorRearLeft", "DoorRearRight", "GloveBox", "TruckBed",
                               "Engine" })
    for _, p in ipairs({ "SeatRearLeft", "SeatRearRight", "TrunkDoor", "DoorRearLeft", "DoorRearRight", "TruckBed" }) do
        v.parts[p].item = newItem(p)
    end
    for _, p in ipairs({ "SeatRearLeft", "SeatRearRight", "CRVFunctionCargo", "CRVFunctionUnderfloor", "GloveBox", "TruckBed" }) do
        v.parts[p].cont = newContainer(50, 0)
    end
    for _, p in ipairs({ "TrunkDoor", "DoorRearLeft", "DoorRearRight" }) do
        v.parts[p].door = setmetatable({ open = false }, Door)
    end
    return v
end
'''


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)
    return True


def side(role, net=None, player=None, seed=7):
    s = Side(role, net, player=player, seed=seed)
    s.run(GAME)
    s.load(*STATE)
    s.load(*FUNC)
    return s


def net_action_fields():
    """NetTimedAction rebuilds an action on the server from new()'s parameter NAMES (action[name]): every
    parameter must be stored as o.<name> = <name>."""
    for rel, cls in (("shared/TimedActions/ISCRVFoldSeats.lua", "ISCRVFoldSeats"),
                     ("shared/TimedActions/ISCRVFunctionLiftFloor.lua", "ISCRVFunctionLiftFloor")):
        src = open(os.path.join(LUA_DIR, *rel.split("/")), encoding="utf-8").read()
        m = re.search(r"function %s:new\(([^)]*)\)(.*?)\nend" % cls, src, re.S)
        check(m, "%s:new found" % cls)
        params = [p.strip() for p in m.group(1).split(",") if p.strip()]
        for p in params:
            check(re.search(r"\bo\.%s\s*=\s*%s\b" % (p, p), m.group(2)), "%s:new stores %s as o.%s" % (cls, p, p))
        check("function %s:complete()" % cls in src, "%s has a complete()" % cls)
        perform = re.search(r"function %s:perform\(\)(.*?)\nend" % cls, src, re.S).group(1)
        check("State.set" not in perform and "setBed" not in perform and "setFloorFound" not in perform,
              "%s:perform changes no state" % cls)
    print("NET ACTIONS: ISCRVFoldSeats(character, vehicle, on, mode), ISCRVFunctionLiftFloor(character, vehicle): fields named like "
          "new()'s parameters, state only in complete()")


def single_player():
    sp = side("sp", player="tester")
    sp.run("v = newCRV(1); PLAYER.area = 'TruckBed'")
    F, S = "HondaCRVGen1.Function", "HondaCRVGen1.Shared"
    check(not sp.eval("%s.isBed(v)" % S), "starts unfolded")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "cargo closed while the seats are up")
    # fold as a load floor: isValid, complete (the state), perform (feedback only)
    sp.run("a = ISCRVFoldSeats:new(PLAYER, v, true, 'cargo')")
    check(sp.eval("a:isValid()"), "fold valid")
    sp.run("a:perform()")
    check(not sp.eval("%s.isFolded(v)" % S), "perform() alone changes nothing")
    check(sp.eval("a:complete()") is True and sp.eval("%s.isCargo(v)" % S) and not sp.eval("%s.isBed(v)" % S),
          "complete() folds, as a load floor")
    check(sp.eval("v.parts.SeatRearLeft.md.crv_function_folded") is True, "stored as the State key in the seat's mod data")
    check(sp.eval("v.parts.SeatRearLeft.md.crv_function_foldMode") == "cargo", "the mode beside it")
    check(sp.eval("HondaCRVGen1.Acc.RearSeatAccess(v, v.parts.SeatRearLeft, PLAYER)") is False, "rear seats refuse items folded")
    # folded load floor access: gate closed / open, rear door, inside the car, another car
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "gate closed: no access")
    sp.run("v.parts.TrunkDoor.door.open = true")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "gate open: access")
    sp.run("v.parts.TrunkDoor.door.open = false; PLAYER.area = 'SeatRearRight'")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "rear door shut: no access")
    sp.run("v.parts.DoorRearRight.door.open = true")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "rear door open: access")
    sp.run("PLAYER.area = nil; PLAYER.vehicle = v")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "from inside the car")
    sp.run("PLAYER.vehicle = newCRV(2)")
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "not from inside another car")
    sp.run("PLAYER.vehicle = nil; PLAYER.area = 'TruckBed'")
    # unfold: blocked while the load floor holds something
    sp.run("v.parts.CRVFunctionCargo.cont.items = 3; b = ISCRVFoldSeats:new(PLAYER, v, false)")
    check(not sp.eval("b:isValid()") and sp.eval("b:complete()") is False and sp.eval("%s.isCargo(v)" % S), "loaded floor blocks unfolding")
    check(sp.eval("select(2, %s.canUnfold(v))" % S) == "IGUI_CRV_Function_CargoNotEmpty", "the reason")
    sp.run("v.parts.CRVFunctionCargo.cont.items = 0")
    check(sp.eval("b:isValid()") and sp.eval("b:complete()") is True and not sp.eval("%s.isFolded(v)" % S), "empty floor: unfolds")
    check(sp.eval("v.parts.SeatRearLeft.md.crv_function_folded") is None, "unfolded = the default, stored as nil")
    check(sp.eval("v.parts.SeatRearLeft.md.crv_function_foldMode") is None, "the mode back to its default, stored as nil")
    # folding is refused with a loaded or occupied rear seat (the existing rules)
    sp.run("v.parts.SeatRearRight.cont.items = 1")
    check(not sp.eval("ISCRVFoldSeats:new(PLAYER, v, true):isValid()"), "loaded rear seat blocks folding")
    sp.run("v.parts.SeatRearRight.cont.items = 0; v.occupied[3] = true")
    check(not sp.eval("ISCRVFoldSeats:new(PLAYER, v, true):isValid()"), "occupied rear seat blocks folding")
    sp.run("v.occupied[3] = nil")
    # old save: crvBed = true in the seat's mod data
    sp.run("w = newCRV(3); w.parts.SeatRearLeft.md.crvBed = true")
    check(sp.eval("%s.isBed(w)" % S), "a legacy bed reads as folded into a bed before migration")
    sp.run("SENT.transmitModData = 0; %s.Init(w, w.parts.CRVFunctionCargo)" % F)
    check(sp.eval("w.parts.SeatRearLeft.md.crvBed") is None and sp.eval("w.parts.SeatRearLeft.md.crv_function_folded") is True
          and sp.eval("SENT.transmitModData") == 1, "Init migrates crvBed onto the State key and transmits")
    check(sp.eval("%s.isBed(w)" % S) and sp.eval("%s.foldMode(w)" % S) == "bed", "a migrated legacy bed is a bed")
    print("SP FOLD: complete() folds, perform() does not; rear seats refuse items; load floor at gate / rear door / inside; "
          "unfold needs it empty; crvBed migrates")

    # hidden storage
    check(sp.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is False, "hidden at first")
    sp.run("c = ISCRVFunctionLiftFloor:new(PLAYER, v)")
    check(not sp.eval("c:isValid()") and sp.eval("c:complete()") is False, "gate closed: cannot lift the floor")
    check(sp.eval("select(2, %s.canLiftFloor(v, PLAYER))" % F) == "Tooltip_CRV_GateClosed", "the reason")
    sp.run("v.parts.TrunkDoor.door.open = true")
    check(sp.eval("c:isValid()"), "gate open: can lift")
    sp.run("c:perform()")
    check(not sp.eval("%s.isFloorFound(v)" % F), "perform() changes nothing")
    check(sp.eval("c:complete()") is True and sp.eval("%s.isFloorFound(v)" % F), "complete() finds it")
    check(sp.eval("v.parts.CRVFunctionUnderfloor.md.crv_function_floorFound") is True, "stored in the part's mod data")
    check(sp.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is True, "open at the gate once found")
    sp.run("v.parts.TrunkDoor.door.open = false")
    check(sp.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is False, "gate closed: shut")
    sp.run("v.parts.TrunkDoor.door.open = true; PLAYER.vehicle = v")
    check(sp.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is False, "not from inside")
    sp.run("PLAYER.vehicle = nil")
    check(not sp.eval("ISCRVFunctionLiftFloor:new(PLAYER, v):isValid()"), "nothing to lift twice")
    print("SP STORAGE: hidden until the floor is lifted (gate open), then open at the tailgate only")

    # the owner's manual: XP on a CR-V for a reader, once per item and car, nothing for others
    sp.run(r'''
XP = {}
local seat = v.parts.SeatRearLeft
local it = newItem("Base.NormalCarSeat1")
local a = { character = PLAYER, vehicle = v, part = seat, item = it }
seat.item = nil
ISInstallVehiclePart.complete(a)                                 -- not a reader: nothing
PLAYER.known = { HondaCRVKnowHow = true }
seat.item = nil
ISInstallVehiclePart.complete(a)                                 -- reader, first time: install bonus
PLAYER.mech = { [it:getID() .. "4242" .. "1"] = true }
seat.item = nil
ISInstallVehiclePart.complete(a)                                 -- already done once: nothing
a.fail = true; seat.item = nil
ISInstallVehiclePart.complete(a)                                 -- a failure: the failure bonus
ISUninstallVehiclePart.complete({ character = PLAYER, vehicle = v, part = v.parts.SeatRearRight })   -- first uninstall
ISRepairEngine.complete({ character = PLAYER, vehicle = v, part = v.parts.Engine })                  -- first repair
local suv = newVehicle(9, { "SeatRearLeft" }, "Base.SUV")
ISUninstallVehiclePart.complete({ character = PLAYER, vehicle = suv, part = suv.parts.SeatRearLeft })
''')
    xp = [e["amount"] for e in (dict(x.items()) for x in sp.eval("XP").values())]
    check(xp == [3, 1, 2, 2], "manual XP bonuses %s" % xp)
    print("SP MANUAL XP: reader on a CR-V: install +3 (first time only), failure +1, uninstall +2, repair +2; "
          "non-readers and other cars nothing")
    return sp


def sandbox_and_loot():
    # spawn rate at OnLoadedMapZones (SandboxVars are stale when the file loads)
    s = Side("server")
    s.run(GAME)
    s.run(r'''
VehicleZoneDistribution = {}
for _, z in ipairs({ "parkingstall", "medium", "good", "middleClass", "professional", "bad", "evacuee", "trailerpark",
                     "farm", "junkyard" }) do VehicleZoneDistribution[z] = { vehicles = {} } end
local jam = {}
for _, z in ipairs({ "trafficjamn", "trafficjams", "trafficjame", "trafficjamw" }) do VehicleZoneDistribution[z] = { vehicles = jam } end
SandboxVars = { HondaCRVGen1 = { FunctionSpawnRate = 250 } }       -- the server's value: not yet loaded at file load
''')
    s.load("shared/HondaCRVGen1SpawnList.lua")
    car = "VehicleZoneDistribution.%s.vehicles['Base.HondaCRVGen1']"
    check(s.eval(car % "good" + ".spawnChance") == 10 and s.eval(car % "farm" + ".spawnChance") == 3, "file load: the stock weights")
    for z in ("parkingstall", "medium", "good", "middleClass", "farm", "trailerpark", "trafficjamn", "trafficjamw", "junkyard"):
        check(s.eval(car % z) is not None, "zone %s has the CR-V" % z)
    check(s.trigger("OnLoadedMapZones") == 1, "OnLoadedMapZones registered")
    check(s.eval(car % "good" + ".spawnChance") == 25 and s.eval(car % "trafficjams" + ".spawnChance") == 10, "250 %% scaled")
    s.run("SandboxVars.HondaCRVGen1.FunctionSpawnRate = 0")
    s.trigger("OnLoadedMapZones")
    check(s.eval(car % "good") is None and s.eval(car % "parkingstall") is None, "0 %: no CR-V anywhere")
    s.run("SandboxVars = nil")
    s.trigger("OnLoadedMapZones")
    check(s.eval(car % "medium" + ".spawnChance") == 6, "no sandbox: the stock weights")
    print("SANDBOX SPAWN: suburbs / driveways, farms, parking lots, traffic jams, junkyards; scaled at OnLoadedMapZones (250 %, 0 %, unset)")

    # accessory chance (Acc.Create runs at the part's create, on the server)
    s.run("VehicleUtils = { createPartInventoryItem = function(part) part.item = newItem(part.id) end }")
    s.load(*STATE)
    s.load(*FUNC)

    def fitted(pct, part, n=400):
        s.run("SandboxVars = { HondaCRVGen1 = { FunctionAccessoryChance = %s } }" % pct)
        return s.eval(r'''(function()
            local n = 0
            for i = 1, %d do
                local v = newVehicle(5000 + i, { "%s", "TrunkDoor", "Windshield", "CRVGuardWindshield" })
                v.parts.TrunkDoor.item = newItem("TrunkDoor"); v.parts.Windshield.item = newItem("Windshield")
                HondaCRVGen1.Acc.Create(v, v.parts["%s"])
                if v.parts["%s"].item then n = n + 1 end
            end
            return n end)()''' % (n, part, part, part))
    bar0, bar1, bar3 = fitted(0, "CRVBullbar"), fitted(100, "CRVBullbar"), fitted(300, "CRVBullbar")
    table0 = fitted(0, "CRVPicnicTable")
    guard0, guard5 = fitted(0, "CRVGuardWindshield"), fitted(500, "CRVGuardWindshield")
    check(bar0 == 0 and 40 <= bar1 <= 110 and 170 <= bar3 <= 260, "bull bar 0/100/300 %%: %d %d %d of 400" % (bar0, bar1, bar3))
    check(table0 > 330, "the picnic table is stock: %d of 400 at 0 %%" % table0)
    check(guard0 == 0 and 80 <= guard5 <= 160, "window guard set 0 / 500 %%: %d %d" % (guard0, guard5))
    print("SANDBOX ACCESSORIES: bull bar at 0/100/300 %%: %d/%d/%d of 400; table stays (%d); guard set 0/500 %%: %d/%d"
          % (bar0, bar1, bar3, table0, guard0, guard5))

    # loot rarity: the generated loot Lua (gen_scripts.loot_lua with FunctionLootRarity declared)
    loot = open(LOOT, encoding="utf-8").read()
    check("Events.OnFillContainer.Add" in loot, "the loot Lua thins at OnFillContainer (regenerate with gen_scripts)")
    s.run(r'''
ProceduralDistributions = { list = { CarDealerDesk = { items = { "Paperwork", 10 } }, CarSupplyLiterature = { items = {} },
    CarSupplyMagazines = { items = {} }, BookstoreAutomotive = { items = {} }, MechanicShelfBooks = { items = {} },
    GarageMechanics = { items = {} } } }
SandboxVars = { HondaCRVGen1 = {} }
-- a filled container: a Java ArrayList of items
List = {}
List.__index = List
function List:size() return #self.t end
function List:get(i) return self.t[i + 1] end
LootCont = {}
LootCont.__index = LootCont
function newLootCont(types)
    local c = setmetatable({ list = setmetatable({ t = {} }, List) }, LootCont)
    for _, t in ipairs(types) do table.insert(c.list.t, newItem(t)) end
    return c
end
function LootCont:getItems() return self.list end
function LootCont:Remove(it)
    for i, x in ipairs(self.list.t) do if x == it then table.remove(self.list.t, i) return end end
end
''')
    s.L.execute(loot)
    s.trigger("OnPreDistributionMerge")
    dealer = list(s.eval("ProceduralDistributions.list.CarDealerDesk.items").values())
    check(dealer == ["Paperwork", 10, "Base.CRVGen1_OwnersManual", 8.0], "inserted at weight x headroom: %s" % dealer)

    def kept(rarity, n=2000):
        s.run("SandboxVars.HondaCRVGen1.FunctionLootRarity = %s" % ("nil" if rarity is None else rarity))
        return s.eval(r'''(function()
            local k = 0
            for i = 1, %d do
                local c = newLootCont({ "Base.CRVGen1_OwnersManual", "Base.Paperwork" })
                triggerEvent("OnFillContainer", "office", "desk", c)
                for _, it in ipairs(c.list.t) do if it.type == "Base.CRVGen1_OwnersManual" then k = k + 1 end end
                assert(c.list.t[#c.list.t].type == "Base.Paperwork", "vanilla items are never touched")
            end
            return k end)()''' % n)
    k_def, k1, k0, k4, k2 = kept(None), kept(1.0), kept(0.0), kept(4.0), kept(2.0)
    check(400 <= k_def <= 600 and 400 <= k1 <= 600, "rarity 1 keeps a quarter: %d %d of 2000" % (k_def, k1))
    check(k0 == 0 and k4 == 2000 and 900 <= k2 <= 1100, "rarity 0 / 4 / 2: %d %d %d" % (k0, k4, k2))
    print("SANDBOX LOOT: inserted at x4, kept at OnFillContainer: rarity unset/1/0/2/4 -> %d/%d/%d/%d/%d of 2000 "
          "(expected count = weight x rarity)" % (k_def, k1, k0, k2, k4))

    # the glove-box manual: every CR-V gets one, once per car, whatever the loot slider says
    def manuals(rarity, n=200):
        s.run("SandboxVars.HondaCRVGen1.FunctionLootRarity = %s" % rarity)
        return s.eval(r'''(function()
            local k = 0
            for i = 1, %d do
                local v = newCRV(7000 + i)
                triggerEvent("OnSpawnVehicleEnd", v)
                triggerEvent("OnSpawnVehicleEnd", v)            -- createPhysics again (a reload): no second copy
                k = k + v.parts.GloveBox.cont.items
            end
            return k end)()''' % n)
    m1, m0, m4 = manuals(1.0), manuals(0.0), manuals(4.0)
    check(m1 == 200 and m0 == 200 and m4 == 200, "every CR-V gets one glove-box manual at rarity 1/0/4: %d %d %d of 200" % (m1, m0, m4))
    s.run("SandboxVars.HondaCRVGen1.FunctionLootRarity = 4; o = newVehicle(8000, { 'GloveBox' }, 'Base.SUV'); "
          "o.parts.GloveBox.cont = newContainer(5, 0); triggerEvent('OnSpawnVehicleEnd', o)")
    check(s.eval("o.parts.GloveBox.cont.items") == 0, "other cars get no manual")
    print("SANDBOX MANUAL: glove-box manual in %d/%d/%d of 200 CR-Vs at rarity 1/0/4, one per car" % (m1, m0, m4))


def multiplayer():
    net = Net()
    server = side("server", net, seed=11)
    a = side("client", net, player="alice", seed=12)
    b = side("client", net, player="bob", seed=13)
    server.run("newPlayer('alice'); newPlayer('bob')")
    for s in (server, a, b):
        s.run("v = newCRV(1)")
    for c in (a, b):
        c.run("HondaCRVGen1.Function.Init(v, v.parts.CRVFunctionCargo); HondaCRVGen1.Function.Init(v, v.parts.CRVFunctionUnderfloor)")
    F, S = "HondaCRVGen1.Function", "HondaCRVGen1.Shared"
    # alice folds: her client runs the action (isValid, perform), the server its complete()
    a.run("PLAYER.area = 'TruckBed'; act = ISCRVFoldSeats:new(PLAYER, v, true, 'cargo'); v.parts.SeatRearRight.cont.items = 1")
    check(not a.eval("act:isValid()"), "client: a loaded rear seat refuses the start already")
    a.run("v.parts.SeatRearRight.cont.items = 0")
    check(a.eval("act:isValid()"), "client: valid")
    a.run("act:perform()")
    check(not a.eval("%s.isFolded(v)" % S) and a.eval("SENT.transmitModData") == 0, "client perform: no state")
    # the server rebuilds the action from the fields named like new()'s parameters
    server.run("sact = ISCRVFoldSeats:new(PLAYERS.alice, getVehicleById(%d), %s, '%s')" % (
        a.eval("act.vehicle:getId()"), "true" if a.eval("act.on") else "false", a.eval("act.mode")))
    check(server.eval("sact:isValid()") and server.eval("sact:complete()") is True, "server complete")
    check(server.eval("%s.isCargo(v)" % S), "server folded, as a load floor")
    check(not a.eval("%s.isFolded(v)" % S), "nothing on the clients before the network")
    check(a.eval("act:isValid()"), "client action stays valid however the state moves")
    net.pump()
    for c in (a, b):
        check(c.eval("%s.isCargo(v)" % S), "%s sees the seats folded as a load floor" % c.player)
        check(c.eval("v.parts.SeatRearLeft.md.crv_function_folded") is True, "%s has the mod data" % c.player)
        check(c.eval("HondaCRVGen1.Acc.RearSeatAccess(v, v.parts.SeatRearLeft, PLAYER)") is False, "%s: rear seats refuse items" % c.player)
    b.run("PLAYER.vehicle = v")
    check(b.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "bob reaches the load floor from his seat")
    # a client cannot set the state itself, nor request it (server-only key)
    check(a.eval("HondaCRVGen1.State.set(v, '%s', false)" % "function_folded")[0] is False, "client State.set refused")
    check(a.eval("HondaCRVGen1.State.request(PLAYER, v, 'function_folded', false)")[0] is False, "not requestable")
    # unfolding with cargo on the floor: the server refuses, nothing changes anywhere
    server.run("v.parts.CRVFunctionCargo.cont.items = 2")
    server.run("u = ISCRVFoldSeats:new(PLAYERS.bob, v, false)")
    check(server.eval("u:complete()") is False, "server refuses to unfold over cargo")
    net.pump()
    check(all(c.eval("%s.isCargo(v)" % S) for c in (a, b)), "still folded everywhere")
    server.run("v.parts.CRVFunctionCargo.cont.items = 0")
    check(server.eval("u:complete()") is True, "empty: unfolds")
    net.pump()
    check(not any(c.eval("%s.isFolded(v)" % S) for c in (a, b)), "unfolded on both clients")
    # the mod data packet alone (command lost) reaches the clients through the poll
    net.drop_commands = True
    server.run("HondaCRVGen1.Shared.setBed(v, true)")
    net.pump()
    b.run("TICK(60)")
    check(b.eval("%s.isBed(v)" % S), "bob's poll picked up the packet alone")
    net.drop_commands = False
    server.run("HondaCRVGen1.Shared.setBed(v, false)")
    net.pump()
    print("MP FOLD: alice's client performs, the server completes; both clients fold (command or packet alone); "
          "server refuses to unfold over cargo; clients cannot set or request it")

    # hidden storage, found by bob with the gate open
    server.run("v.parts.TrunkDoor.door.open = true; PLAYERS.bob.area = 'TruckBed'")
    for c in (a, b):
        c.run("v.parts.TrunkDoor.door.open = true; PLAYER.area = 'TruckBed'; PLAYER.vehicle = nil")
        check(c.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is False, "hidden on %s" % c.player)
    b.run("lift = ISCRVFunctionLiftFloor:new(PLAYER, v); v.parts.TrunkDoor.door.open = false")
    check(not b.eval("lift:isValid()"), "bob's client: gate shut, refused at the start")
    b.run("v.parts.TrunkDoor.door.open = true")
    check(b.eval("lift:isValid()"), "bob's client: valid")
    b.run("lift:perform()")
    server.run("slift = ISCRVFunctionLiftFloor:new(PLAYERS.bob, v)")
    check(server.eval("slift:isValid()") and server.eval("slift:complete()") is True, "server finds it")
    net.pump()
    check(b.eval("lift:isValid()"), "bob's action survives the server's answer")
    for c in (a, b):
        check(c.eval("%s.UnderfloorAccess(v, v.parts.CRVFunctionUnderfloor, PLAYER)" % F) is True, "open for %s" % c.player)
    print("MP STORAGE: bob lifts the floor, the server completes, both clients see the under-floor storage")

    # an old single-player save loaded on a server: the server migrates, the clients follow
    server.run("w = newCRV(2); w.parts.SeatRearLeft.md.crvBed = true")
    for c in (a, b):
        c.run("w = newCRV(2)")
    server.run("HondaCRVGen1.Function.Init(w, w.parts.CRVFunctionCargo)")
    net.pump()
    check(server.eval("w.parts.SeatRearLeft.md.crvBed") is None, "server cleared crvBed")
    for c in (a, b):
        c.run("HondaCRVGen1.Function.Init(w, w.parts.CRVFunctionCargo)")
        check(c.eval("%s.isBed(w)" % S) and c.eval("w.parts.SeatRearLeft.md.crvBed") is None, "%s: migrated bed" % c.player)
    print("MP MIGRATION: crvBed moved onto the State key on the server, both clients folded")

    # the manual's XP bonus never runs on a client (complete() is the server's)
    a.run("PLAYER.known = { HondaCRVKnowHow = true }; XP = {}; v.parts.SeatRearLeft.item = nil")
    a.run("ISInstallVehiclePart.complete({ character = PLAYER, vehicle = v, part = v.parts.SeatRearLeft, item = newItem('Seat') })")
    check(len(list(a.eval("XP").values())) == 0, "no XP on a client")
    server.run("PLAYERS.alice.known = { HondaCRVKnowHow = true }; XP = {}; v.parts.SeatRearLeft.item = nil")
    server.run("ISInstallVehiclePart.complete({ character = PLAYERS.alice, vehicle = v, part = v.parts.SeatRearLeft, item = newItem('Seat') })")
    check([dict(e.items())["amount"] for e in server.eval("XP").values()] == [3], "XP on the server")
    print("MP MANUAL XP: on the server only")


def shown(s, var="v"):
    """(upright bench drawn, folded bench drawn, bedding drawn) on side s for the car in Lua variable `var`."""
    p = "%s.parts.CRVFunctionSeats.visible" % var
    return (s.eval("%s.InteriorSeatsUp == true" % p), s.eval("%s.InteriorSeatsFolded == true" % p),
            s.eval("%s.InteriorBedding == true" % p))


def seats_look():
    """Folded rear seats LOOK folded (2026-10-14): the bench is part CRVFunctionSeats' two models and exactly
    one is shown, from the synced fold state, wherever the car is drawn (single player, every client);
    never on the dedicated server. Before this the bench was baked into the static cabin: upright always."""
    sp = side("sp", player="tester")
    sp.run("v = newCRV(1); PLAYER.area = 'TruckBed'")
    check(shown(sp) == (False, False, False), "nothing drawn before the part's init (no item, setAllModelsVisible = false)")
    sp.run("HondaCRVGen1.Function.Init(v, v.parts.CRVFunctionSeats)")
    check(shown(sp) == (True, False, False), "SP: upright after init, got %s" % (shown(sp),))
    sp.run("a = ISCRVFoldSeats:new(PLAYER, v, true); a:perform()")
    check(shown(sp) == (True, False, False), "SP: perform() alone changes nothing")
    sp.run("a:complete()")
    check(shown(sp) == (False, True, True), "SP: folded once complete() ran, got %s" % (shown(sp),))
    calls = sp.eval("v.parts.CRVFunctionSeats.calls")
    sp.run("HondaCRVGen1.State.refresh(v, 'function_folded'); TICK(120)")
    check(sp.eval("v.parts.CRVFunctionSeats.calls") == calls and shown(sp) == (False, True, True), "SP: idle refreshes touch nothing")
    sp.run("b = ISCRVFoldSeats:new(PLAYER, v, false); b:complete()")
    check(shown(sp) == (True, False, False), "SP: upright again")
    # an old save's crvBed is drawn folded at load, whichever part inits first
    sp.run("w = newCRV(3); w.parts.SeatRearLeft.md.crvBed = true; HondaCRVGen1.Function.Init(w, w.parts.CRVFunctionSeats)")
    check(shown(sp, "w") == (False, True, True), "SP: a legacy bed is drawn folded")
    sp.run("HondaCRVGen1.Function.Init(w, w.parts.CRVFunctionCargo)")
    check(shown(sp, "w") == (False, True, True) and sp.eval("w.parts.SeatRearLeft.md.crv_function_folded") is True,
          "SP: still folded after the migration")
    # a re-created car (a fresh part shows nothing) gets its look back from init
    sp.run("a2 = ISCRVFoldSeats:new(PLAYER, v, true); a2:complete()")
    sp.run("v.parts.CRVFunctionSeats.visible = {}; HondaCRVGen1.Function.Init(v, v.parts.CRVFunctionSeats)")
    check(shown(sp) == (False, True, True), "SP: a fresh part is drawn folded at init")
    print("SP SEATS: upright at init, folded by complete() only, upright again; a legacy bed and a reloaded car "
          "drawn folded; idle refreshes call nothing")

    net = Net()
    server = side("server", net, seed=21)
    a = side("client", net, player="alice", seed=22)
    b = side("client", net, player="bob", seed=23)
    server.run("newPlayer('alice'); newPlayer('bob')")
    init = ("for _, p in ipairs({ 'CRVFunctionCargo', 'CRVFunctionUnderfloor', 'CRVFunctionSeats' }) do "
            "HondaCRVGen1.Function.Init(%s, %s.parts[p]) end")
    for s in (server, a, b):
        s.run("v = newCRV(1); " + init % ("v", "v"))
    for c in (a, b):
        check(shown(c) == (True, False, False), "%s: upright at init" % c.player)
    check(server.eval("v.parts.CRVFunctionSeats.calls") == 0, "the dedicated server draws nothing")
    # alice folds: her client performs, the server completes, the state rides to both clients
    a.run("PLAYER.area = 'TruckBed'; act = ISCRVFoldSeats:new(PLAYER, v, true); act:perform()")
    for c in (a, b):
        check(shown(c) == (True, False, False), "%s: perform() on alice's client changes no look" % c.player)
    server.run("sact = ISCRVFoldSeats:new(PLAYERS.alice, v, true)")
    check(server.eval("sact:complete()") is True, "server completes the fold")
    for c in (a, b):
        check(shown(c) == (True, False, False), "%s: nothing before the network" % c.player)
    net.pump()
    for c in (a, b):
        check(shown(c) == (False, True, True), "%s: folded, got %s" % (c.player, shown(c)))
    # bob puts them back up; the command is lost and the mod data packet alone arrives: the poll redraws
    net.drop_commands = True
    server.run("u = ISCRVFoldSeats:new(PLAYERS.bob, v, false)")
    check(server.eval("u:complete()") is True, "server completes the unfold")
    net.pump()
    for c in (a, b):
        c.run("TICK(60)")
        check(shown(c) == (True, False, False), "%s: upright again through the poll alone" % c.player)
    net.drop_commands = False
    # a car that streams in after the fold is drawn from its synced mod data at init
    server.run("HondaCRVGen1.Shared.setBed(v, true)")
    net.pump()
    b.run("v2 = newCRV(1); VEHICLES[1] = v2; v2.parts.SeatRearLeft.md = { crv_function_folded = true }; " + init % ("v2", "v2"))
    check(shown(b, "v2") == (False, True, True), "bob: a car streamed in folded is drawn folded")
    check(server.eval("v.parts.CRVFunctionSeats.calls") == 0, "still nothing drawn on the server")
    print("MP SEATS: the server completes, both clients redraw (by command, or by the mod data packet alone), a car "
          "streamed in later is drawn as stored; the server never draws")


UI = r'''
ISVehicleMenu = { FillMenuOutsideVehicle = function(player, context, vehicle, test) return "vanilla" end,
                  onEnter = function(playerObj, vehicle, seat) ENTERED = seat end,
                  showRadialMenuOutside = VANILLA_RADIAL_OUTSIDE,
                  getVehicleToInteractWith = function(playerObj) return playerObj:getVehicle() or RADIAL_TARGET end }
RADIAL = newRadial()
function getPlayerRadialMenu(n) return RADIAL end
function getTexture(path) return path end
function Player:getPlayerNum() return 0 end
ISWorldObjectContextMenu = { addToolTip = function() return {} end, getBedQuality = function() return "badBed" end }
ISEnterVehicle = { isValid = function(self) return true end }
ISSwitchVehicleSeat = { isValid = function(self) return true end }
ISInstallVehiclePart.new = function(self, ...) return {} end
ISUninstallVehiclePart.new = function(self, ...) return {} end
QUEUE = {}
ISTimedActionQueue = { add = function(a) QUEUE[#QUEUE + 1] = a end }
ISPathFindAction = { pathToVehicleArea = function(self, p, v, area) return { path = area } end }
function getSpecificPlayer(n) return PLAYER end
function Player:getInventory() return { getFirstTypeRecurse = function() return nil end } end
function instanceof(o, cls) return getmetatable(o) == Item end
ISModalRichText = {}
function ISModalRichText:new(x, y, w, h, text) local o = setmetatable({ text = text }, { __index = self }); MODAL = o; return o end
function ISModalRichText:initialise() end
function ISModalRichText:addToUIManager() self.shown = true end
function ISModalRichText:removeFromUIManager() self.shown = false end
function getCore() return { getScreenWidth = function() return 1920 end, getScreenHeight = function() return 1080 end } end
function newContext()
    local c = { options = {} }
    function c:addOption(name, target, fn, a1, a2) local o = { name = name, target = target, fn = fn, a1 = a1, a2 = a2 }
        self.options[#self.options + 1] = o; return o end
    return c
end
function optionNames(c) local t = {} for _, o in ipairs(c.options) do t[#t + 1] = o.name .. (o.notAvailable and "!" or "") end
    return table.concat(t, ",") end
'''


def client_menus():
    """The right-click menus run (a smoke test of the client files with the game's UI stubbed)."""
    c = side("sp", player="tester")
    c.run(UI)
    c.load("client/HondaCRVGen1_Menu.lua", "client/HondaCRVGen1_FunctionMenu.lua")
    c.run("v = newCRV(1); PLAYER.area = 'TruckBed'")
    menu = "(function() local ctx = newContext(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false); return optionNames(ctx) end)()"
    check(c.eval(menu) == "ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed,ContextMenu_CRV_Function_LiftFloor!", "closed gate: %s" % c.eval(menu))
    # the outside radial, as Project Viewpoint harvests it: the same options after the game's slices, a blocked
    # one without a command and with its reason
    radial = "viewpointRadial(PLAYER, v):texts()"
    want = "VANILLA_MECHANICS,ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed,ContextMenu_CRV_Function_LiftFloor [Tooltip_CRV_GateClosed]!"
    check(c.eval(radial) == want, "radial, closed gate: %s" % c.eval(radial))
    c.run("RADIAL = newRadial(); RADIAL_TARGET = v; ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(c.eval("RADIAL:texts()") == want and c.eval("RADIAL.shown") is True, "the game's V: the same slices, shown")
    c.run("ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(c.eval("RADIAL:texts()") == want and c.eval("RADIAL.shown") is False, "V again closes it, nothing added")
    check(c.eval("viewpointRadial(PLAYER, newVehicle(9, {}, 'Base.SUV')):texts()") == "VANILLA_MECHANICS",
          "radial on another car: the game's slices only")
    c.run("v.parts.TrunkDoor.door.open = true")
    check(c.eval(menu) == "ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed,ContextMenu_CRV_Function_LiftFloor", "open gate: %s" % c.eval(menu))
    check(c.eval(radial) == "VANILLA_MECHANICS,ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed,ContextMenu_CRV_Function_LiftFloor",
          "radial, open gate: %s" % c.eval(radial))
    # picking the slice queues what the option does: the walk to the cargo area, then the lift
    c.run("QUEUE = {}; local m = viewpointRadial(PLAYER, v); m:pick(m:find('ContextMenu_CRV_Function_LiftFloor')); BY_SLICE = QUEUE")
    c.run("QUEUE = {}; local ctx = newContext(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false); "
          "for _, o in ipairs(ctx.options) do if o.name == 'ContextMenu_CRV_Function_LiftFloor' then o.fn(o.target, o.a1, o.a2) end end; "
          "BY_OPTION = QUEUE")
    same = ("#BY_SLICE == 2 and #BY_OPTION == 2 and BY_SLICE[1].path == 'TruckBed' and BY_OPTION[1].path == 'TruckBed' "
            "and getmetatable(BY_SLICE[2]) == ISCRVFunctionLiftFloor and getmetatable(BY_OPTION[2]) == ISCRVFunctionLiftFloor "
            "and BY_SLICE[2].vehicle == v and BY_OPTION[2].vehicle == v "
            "and BY_SLICE[2].character == PLAYER and BY_OPTION[2].character == PLAYER")
    check(c.eval(same) is True, "the cargo floor slice queues the option's walk and ISCRVFunctionLiftFloor")
    c.run("QUEUE = {}")
    c.run("HondaCRVGen1.Shared.setBed(v, true); v.parts.CRVFunctionCargo.cont.items = 1")
    check(c.eval(menu) == "ContextMenu_CRV_ClearBed,ContextMenu_CRV_UnfoldBed!,ContextMenu_CRV_Function_LiftFloor", "folded, loaded: %s" % c.eval(menu))
    check(c.eval(radial) == "VANILLA_MECHANICS,ContextMenu_CRV_ClearBed,ContextMenu_CRV_UnfoldBed [IGUI_CRV_Function_CargoNotEmpty]!,"
          "ContextMenu_CRV_Function_LiftFloor", "radial, folded, loaded: %s" % c.eval(radial))
    c.run("PLAYER.vehicle = v")
    check(c.eval(radial) == "", "no outside radial from inside the car")
    c.run("PLAYER.vehicle = nil")
    c.run("ENTERED = nil; HALO = {}; ISVehicleMenu.onEnter(PLAYER, v, 2)")
    check(c.eval("ENTERED") is None and c.eval("HALO[1]") == "IGUI_CRV_Function_SeatsAreFolded", "rear seat refused with a reason")
    c.run("ISVehicleMenu.onEnter(PLAYER, v, 1)")
    check(c.eval("ENTERED") == 1, "front seat as usual")
    c.run("HondaCRVGen1.Function.setFloorFound(v)")
    check("LiftFloor" not in c.eval(menu), "no lift option once found")
    check("LiftFloor" not in c.eval(radial), "no lift slice once found")
    c.run("ctx = newContext(); HondaCRVGen1.Function.Menu.OnFillInventoryObjectContextMenu(0, ctx, { { items = { newItem('Base.CRVGen1_OwnersManual') } } })")
    check(c.eval("optionNames(ctx)") == "ContextMenu_CRV_Function_BrowseManual", "manual menu")
    c.run("ctx.options[1].fn(ctx.options[1].target)")
    text = c.eval("MODAL.text")
    check(c.eval("MODAL.shown") and "IGUI_CRV_Function_Manual_Page6" in text and "Page7" not in text, "manual window: all pages")
    # with vanilla's print media window (PZAPI.UI.PrintMedia, stubbed) the browse option opens the designed page
    c.run("""
        PM = nil
        PZAPI = { UI = { PrintMedia = function(args)
            local w = { args = args, children = { bar = { children = { name = {} } } } }
            function w:instantiate() self.inst = true end
            w.javaObj = { setAlwaysOnTop = function(_, v) w.top = v end }
            function w:centerOnScreen(p) self.centered = p end
            PM = w
            return w
        end } }
        ctx = newContext()
        HondaCRVGen1.Function.Menu.OnFillInventoryObjectContextMenu(0, ctx, { { items = { newItem('Base.CRVGen1_OwnersManual') } } })
        MODAL = nil
        ctx.options[1].fn(ctx.options[1].target)
    """)
    check(c.eval("PM ~= nil and PM.inst == true and PM.centered == 0 and PM.top == false"), "the print media window opened and placed")
    check(c.eval("PM.data") == "Print_Media_CRVGen1_Manual_info" and c.eval("PM.textData") == "Print_Text_CRVGen1_Manual_info"
          and c.eval("PM.children.bar.children.name.text") == "Print_Media_CRVGen1_Manual_title",
          "the window shows the manual's layout, text and title")
    check(c.eval("MODAL == nil"), "the text-only fallback stays closed when the print media window exists")
    # the manual's three spreads: vanilla's template system (calling a template merges `children` down the tree,
    # UI._mergeTables), the page buttons on the bottom bar, and turning pages where the window stands
    c.run("""
        HondaCRVGen1.Function.Menu.template = nil
        REMOVED = 0
        UIManager = { RemoveElement = function(j) REMOVED = REMOVED + 1 end }
        local function merge(a, b)
            local o = {}
            for k, v in pairs(a) do o[k] = v end
            for k, v in pairs(b or {}) do
                if k == "children" and type(o.children) == "table" then o.children = merge(o.children, v) else o[k] = v end
            end
            return o
        end
        local mt = {}
        local function T(t) return setmetatable(t, mt) end
        mt.__call = function(self, args)
            local o = merge(self, args)
            if o.children then
                local c = {}
                for k, v in pairs(o.children) do c[k] = (getmetatable(v) == mt) and v{} or v end
                o.children = c
            end
            return T(o)
        end
        local function link(n)
            for _, ch in pairs(n.children or {}) do ch.parent = n; link(ch) end
        end
        local Node = T{ setVisible = function(self, v) self.shown = v end, setEnabled = function(self, v) self.on = v end }
        PZAPI = { UI = {} }
        PZAPI.UI.Panel = Node{}
        PZAPI.UI.ImageButton = Node{}
        PZAPI.UI.Text = Node{}
        PZAPI.UI.PrintMedia = Node{
            children = {
                bar = Node{ children = { name = PZAPI.UI.Text{} } },
                bottomButtons = PZAPI.UI.Panel{ children = { readNewspaper = PZAPI.UI.Panel{ width = 32, height = 32, y = 4 } } },
            },
            instantiate = function(self)
                link(self)
                local w = self
                self.javaObj = { setAlwaysOnTop = function(_, v) w.top = v end,
                                 getX = function() return w.px or 100 end, getY = function() return w.py or 50 end }
                PM = self
            end,
            centerOnScreen = function(self, p) self.centered = p end,
            setX = function(self, x) self.px = x end,
            setY = function(self, y) self.py = y end,
        }
        getTexture = function(path) return path end
        HondaCRVGen1.Function.Menu.openPrintMedia(0, 1)
        P1 = PM
    """)
    check(c.eval("HondaCRVGen1.Function.Menu.template ~= false and HondaCRVGen1.Function.Menu.template ~= nil"),
          "the manual's window template derives from vanilla's")
    check(c.eval("P1.media_id") == "CRVGen1_Manual" and c.eval("P1.data") == "Print_Media_CRVGen1_Manual_info"
          and c.eval("P1.children.bottomButtons.children.readNewspaper ~= nil"),
          "spread 1 opens, vanilla's text button kept")
    check(c.eval("P1.children.bottomButtons.children.crvPrev.shown == false and P1.children.bottomButtons.children.crvNext.shown == true"),
          "spread 1: previous hidden, next shown")
    check(c.eval("P1.children.bottomButtons.children.crvNext.children.icon.texture") == "media/textures/CRVGen1_ManualNext.png",
          "the next button's icon")
    c.run("P1.px, P1.py = 321, 123; P1.children.bottomButtons.children.crvNext.children.icon:onLeftClick(); P2 = PM")
    check(c.eval("P2 ~= P1 and P2.media_id") == "CRVGen1_Manual2" and c.eval("P2.data") == "Print_Media_CRVGen1_Manual2_info"
          and c.eval("P2.textData") == "Print_Text_CRVGen1_Manual2_info" and c.eval("P2.px") == 321 and c.eval("P2.py") == 123
          and c.eval("REMOVED") == 1 and c.eval("P2.centered == nil"),
          "next: spread 2 opens where spread 1 stood, spread 1 closed")
    check(c.eval("P2.children.bottomButtons.children.crvPrev.shown == true and P2.children.bottomButtons.children.crvNext.shown == true"),
          "spread 2: both buttons")
    c.run("P2.children.bottomButtons.children.crvNext.children.icon:onLeftClick(); P3 = PM")
    check(c.eval("P3.media_id") == "CRVGen1_Manual3" and c.eval("P3.children.bottomButtons.children.crvNext.shown == false"),
          "spread 3: the last, next hidden")
    c.run("P3.children.bottomButtons.children.crvPrev.children.icon:onLeftClick(); P4 = PM")
    check(c.eval("P4.media_id") == "CRVGen1_Manual2", "previous: back to spread 2")
    c.run("HondaCRVGen1.Function.Menu.turnPage(P3, 1)")
    check(c.eval("PM == P4"), "no page after the last")
    c.run("HondaCRVGen1.Function.Menu.template = nil")
    # the item's OnCreate: vanilla's recipe-magazine set-up, then the print media mod data
    c.run("""
        VANILLA_ONCREATE = 0
        ItemCodeOnCreate = { onCreateRecipeMagazine = function(item) VANILLA_ONCREATE = VANILLA_ONCREATE + 1 end }
        local md = {}
        MANUAL_ITEM = { getModData = function() return md end }
        HondaCRVGen1.Function.OnCreateManual(MANUAL_ITEM)
        HondaCRVGen1.Function.OnCreateManual(MANUAL_ITEM)
    """)
    check(c.eval("VANILLA_ONCREATE") == 2 and c.eval("MANUAL_ITEM:getModData().printMedia.id") == "CRVGen1_Manual"
          and c.eval("MANUAL_ITEM:getModData().printMedia.info") == "Print_Media_CRVGen1_Manual_info"
          and c.eval("MANUAL_ITEM:getModData().printMedia.text") == "Print_Text_CRVGen1_Manual_info",
          "OnCreate: vanilla's set-up and the print media data")
    c.run("PZAPI = nil")
    c.run("ctx = newContext(); HondaCRVGen1.Function.Menu.OnFillInventoryObjectContextMenu(0, ctx, { newItem('Base.Book') })")
    check(c.eval("#ctx.options") == 0, "other items: nothing")
    print("CLIENT MENUS: fold / unfold (blocked over cargo) / lift the floor (gate) options, rear seat entry refused with a "
          "reason, manual window with every page, the manual's three spreads with page buttons")


BED = r'''
ItemTag = { PILLOW = "base:pillow" }
function Item:hasTag(t) return self.tags ~= nil and self.tags[t] == true end
function newPillow() local i = newItem("Base.Pillow"); i.tags = { ["base:pillow"] = true }; return i end
function Cont:containsTag(t)
    for _, i in ipairs(self.list or {}) do if i:hasTag(t) then return true end end
    return false
end
function putIn(cont, item) cont.list = cont.list or {}; table.insert(cont.list, item); cont.items = cont.items + 1 end
function Player:getPrimaryHandItem() return self.primary end
function Player:getSecondaryHandItem() return self.secondary end
SEAT_OF = {}
function Veh:getSeat(chr) return SEAT_OF[chr] or -1 end
-- BaseVehicle.getPartForSeatContainer: the seat part that holds that seat's container (nil for none)
function Veh:getPartForSeatContainer(seat)
    local ids = { [0] = "SeatFrontLeft", [1] = "SeatFrontRight", [2] = "SeatRearLeft", [3] = "SeatRearRight" }
    return ids[seat] and self.parts[ids[seat]] or nil
end
'''


def bed_quality():
    """Sleeping in a folded CR-V: a good bed; a pillow counts in hand, in the sleeper's seat container (as vanilla's
    vehicle branch does), on the folded bed floor (CRVFunctionCargo) or the cargo deck (TruckBed); upright seats and
    other cars keep the game's answer. The client file runs the same on a multiplayer client (it reads only synced
    state: the fold flag and the containers the game syncs)."""
    for role in ("sp", "client"):
        c = side(role, Net() if role == "client" else None, player="sleeper")
        c.run(UI)
        c.run(BED)
        c.load("client/HondaCRVGen1_Menu.lua")
        c.run("v = newCRV(1); v:addPart('SeatFrontLeft').cont = newContainer(50, 0); "
              "v:addPart('SeatFrontRight').cont = newContainer(50, 0); PLAYER.vehicle = v; SEAT_OF[PLAYER] = 0")
        q = "ISWorldObjectContextMenu.getBedQuality(PLAYER, nil)"
        check(c.eval(q) == "badBed", "%s: seats up, the game's bad bed (%s)" % (role, c.eval(q)))
        c.run("HondaCRVGen1.Shared.setBed(v, true)" if role == "sp" else
              "v.parts.SeatRearLeft.md.crv_function_folded = true")
        check(c.eval("HondaCRVGen1.Shared.isBed(v)") is True, "%s: folded" % role)
        check(c.eval(q) == "goodBed", "%s: folded, no pillow: goodBed (%s)" % (role, c.eval(q)))
        c.run("PLAYER.secondary = newPillow()")
        check(c.eval(q) == "goodBedPillow", "%s: pillow in hand" % role)
        c.run("PLAYER.secondary = nil; PLAYER.primary = newItem('Base.Axe')")
        check(c.eval(q) == "goodBed", "%s: an axe is no pillow" % role)
        c.run("putIn(v.parts.SeatFrontLeft.cont, newPillow())")
        check(c.eval(q) == "goodBedPillow", "%s: pillow in the sleeper's seat container" % role)
        c.run("SEAT_OF[PLAYER] = 1")
        check(c.eval(q) == "goodBed", "%s: a pillow in another seat's container does not count" % role)
        c.run("putIn(v.parts.CRVFunctionCargo.cont, newPillow())")
        check(c.eval(q) == "goodBedPillow", "%s: pillow on the folded bed floor" % role)
        c.run("v.parts.CRVFunctionCargo.cont.list = {}; putIn(v.parts.TruckBed.cont, newPillow())")
        check(c.eval(q) == "goodBedPillow", "%s: pillow on the cargo deck" % role)
        c.run("v.parts.TruckBed.cont.list = {}; v.parts.CRVFunctionCargo = nil; v.parts.TruckBed = nil; SEAT_OF[PLAYER] = nil")
        check(c.eval(q) == "goodBed", "%s: no seat (-1), no bed containers: goodBed, nothing raises" % role)
        c.run("PLAYER.vehicle = newVehicle(9, {}, 'Base.SUV')")
        check(c.eval(q) == "badBed", "%s: another car: the game's answer" % role)
    print("BED QUALITY: folded = goodBed, pillow in hand / own seat container / bed floor / cargo deck = goodBedPillow, "
          "upright seats and other cars unchanged (single player and a multiplayer client)")


def fold_modes():
    """Load floor or bed (2026-10-22, the owner: "if the seats are folded, I want to have more trunk space or a bed,
    should be able to choose"): State key function_foldMode ("cargo" | "bed", default "bed") beside function_folded,
    set only by ISCRVFoldSeats:complete on the authoritative side. Cargo: the load floor open, no bedding, no bed.
    Bed: the bedding drawn, a good bed, the load floor shut. Switching (the short action): to a bed needs the load
    floor empty, to cargo always works. Old saves (folded, no mode) are beds."""
    F, S = "HondaCRVGen1.Function", "HondaCRVGen1.Shared"
    sp = side("sp", player="tester")
    sp.run(UI)
    sp.run(BED)
    sp.load("client/HondaCRVGen1_Menu.lua", "client/HondaCRVGen1_FunctionMenu.lua")
    sp.run("v = newCRV(1); PLAYER.area = 'TruckBed'; v.parts.TrunkDoor.door.open = true; "
           "HondaCRVGen1.Function.Init(v, v.parts.CRVFunctionSeats); HondaCRVGen1.Function.setFloorFound(v)")
    menu = "(function() local ctx = newContext(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false); return optionNames(ctx) end)()"
    radial = "viewpointRadial(PLAYER, v):texts()"
    check(sp.eval(menu) == "ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed", "seats up: two folds (%s)" % sp.eval(menu))
    check(sp.eval(radial) == "VANILLA_MECHANICS,ContextMenu_CRV_FoldFlat,ContextMenu_CRV_FoldBed", "radial: %s" % sp.eval(radial))
    # the menu's two folds queue the same action with a mode
    sp.run("QUEUE = {}; local m = viewpointRadial(PLAYER, v); m:pick(m:find('ContextMenu_CRV_FoldFlat')); FLAT = QUEUE[2]; "
           "QUEUE = {}; local m2 = viewpointRadial(PLAYER, v); m2:pick(m2:find('ContextMenu_CRV_FoldBed')); BEDA = QUEUE[2]; QUEUE = {}")
    check(sp.eval("getmetatable(FLAT) == ISCRVFoldSeats and FLAT.on == true and FLAT.mode == 'cargo' and FLAT.maxTime == 150"),
          "fold flat: ISCRVFoldSeats on, mode cargo, the full time")
    check(sp.eval("getmetatable(BEDA) == ISCRVFoldSeats and BEDA.on == true and BEDA.mode == 'bed'"), "fold into a bed: mode bed")
    # fold as a load floor
    check(sp.eval("FLAT:isValid()") and sp.eval("FLAT:complete()") is True, "fold flat completes")
    check(sp.eval("%s.foldMode(v)" % S) == "cargo" and sp.eval("%s.isFolded(v)" % S) and not sp.eval("%s.isBed(v)" % S),
          "folded as a load floor")
    check(shown(sp) == (False, True, False), "cargo: the folded bench, no bedding (%s)" % (shown(sp),))
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "cargo: the load floor opens at the gate")
    check(sp.eval("HondaCRVGen1.Acc.RearSeatAccess(v, v.parts.SeatRearLeft, PLAYER)") is False, "cargo: rear seats refuse items")
    check(sp.eval("ISEnterVehicle.isValid({ seat = 2, vehicle = v })") is False, "cargo: nobody sits in the back")
    sp.run("HALO = {}; FLAT:perform()")
    check(sp.eval("HALO[1]") == "IGUI_CRV_SeatsFoldedFlat", "the fold-flat halo")
    check(sp.eval(menu) == "ContextMenu_CRV_MakeBed,ContextMenu_CRV_UnfoldBed", "cargo menu: %s" % sp.eval(menu))
    # sleeping on the load floor: no bed, vanilla's answer (the stub's badBed)
    sp.run("v:addPart('SeatFrontLeft').cont = newContainer(50, 0); PLAYER.vehicle = v; SEAT_OF[PLAYER] = 0")
    q = "ISWorldObjectContextMenu.getBedQuality(PLAYER, nil)"
    check(sp.eval(q) == "badBed", "cargo: the game's bad bed (%s)" % sp.eval(q))
    sp.run("PLAYER.vehicle = nil")
    # the same mode again: refused
    check(not sp.eval("ISCRVFoldSeats:new(PLAYER, v, true, 'cargo'):isValid()"), "already a load floor: nothing to do")
    # making up the bed over a loaded floor: refused, with the unfold rule's reason
    sp.run("v.parts.CRVFunctionCargo.cont.items = 2; mk = ISCRVFoldSeats:new(PLAYER, v, true, 'bed')")
    check(sp.eval("mk.switching") is True and sp.eval("mk.maxTime") == 80, "switching: the short action")
    check(not sp.eval("mk:isValid()") and sp.eval("mk:complete()") is False and sp.eval("%s.isCargo(v)" % S),
          "a loaded load floor blocks making up the bed")
    check(sp.eval(menu) == "ContextMenu_CRV_MakeBed!,ContextMenu_CRV_UnfoldBed!", "loaded: both blocked (%s)" % sp.eval(menu))
    check(sp.eval(radial) == "VANILLA_MECHANICS,ContextMenu_CRV_MakeBed [IGUI_CRV_Function_CargoNotEmpty]!,"
          "ContextMenu_CRV_UnfoldBed [IGUI_CRV_Function_CargoNotEmpty]!", "radial, loaded: %s" % sp.eval(radial))
    sp.run("v.parts.CRVFunctionCargo.cont.items = 0")
    check(sp.eval("mk:isValid()") and sp.eval("mk:complete()") is True and sp.eval("%s.isBed(v)" % S), "empty: the bed made up")
    sp.run("HALO = {}; mk:perform()")
    check(sp.eval("HALO[1]") == "IGUI_CRV_BedMade", "the make-up halo")
    check(shown(sp) == (False, True, True), "bed: the folded bench and the bedding (%s)" % (shown(sp),))
    check(sp.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "bed: the load floor is shut")
    check(sp.eval(menu) == "ContextMenu_CRV_ClearBed,ContextMenu_CRV_UnfoldBed", "bed menu: %s" % sp.eval(menu))
    sp.run("PLAYER.vehicle = v")
    check(sp.eval(q) == "goodBed", "bed: a good bed")
    sp.run("PLAYER.secondary = newPillow()")
    check(sp.eval(q) == "goodBedPillow", "bed: better with a pillow")
    sp.run("PLAYER.secondary = nil; PLAYER.vehicle = nil")
    # clearing the bed: always (the bed holds nothing)
    sp.run("cl = ISCRVFoldSeats:new(PLAYER, v, true, 'cargo')")
    check(sp.eval("cl.maxTime") == 80 and sp.eval("cl:isValid()") and sp.eval("cl:complete()") is True and sp.eval("%s.isCargo(v)" % S),
          "the bed cleared for cargo")
    sp.run("HALO = {}; cl:perform()")
    check(sp.eval("HALO[1]") == "IGUI_CRV_BedCleared", "the clear halo")
    check(shown(sp) == (False, True, False), "cleared: the bedding gone")
    # back up from cargo: the mode back to the default; the next plain fold is a bed
    sp.run("up = ISCRVFoldSeats:new(PLAYER, v, false, 'cargo')")
    check(sp.eval("up:isValid()") and sp.eval("up:complete()") is True and sp.eval("%s.foldMode(v)" % S) is None, "seats up")
    check(sp.eval("v.parts.SeatRearLeft.md.crv_function_foldMode") is None, "mode stored as nil once up")
    check(shown(sp) == (True, False, False), "up: the upright bench only")
    check(not sp.eval("ISCRVFoldSeats:new(PLAYER, v, false, 'bed'):isValid()"), "nothing to put back")
    sp.run("ISCRVFoldSeats:new(PLAYER, v, true):complete()")
    check(sp.eval("%s.isBed(v)" % S), "a fold without a mode is a bed (the old action)")
    # old saves: folded before the choice existed (no mode stored), or the older crvBed flag: beds, bedding drawn
    sp.run("w = newCRV(3); w.parts.SeatRearLeft.md.crv_function_folded = true; HondaCRVGen1.Function.Init(w, w.parts.CRVFunctionSeats)")
    check(sp.eval("%s.foldMode(w)" % S) == "bed" and shown(sp, "w") == (False, True, True), "an old fold is a bed, drawn made up")
    check(sp.eval("%s.CargoAccess(w, w.parts.CRVFunctionCargo, PLAYER)" % F) is False, "old fold: the load floor shut (a bed)")
    sp.run("x = newCRV(4); x.parts.SeatRearLeft.md.crvBed = true; HondaCRVGen1.Function.Init(x, x.parts.CRVFunctionSeats)")
    check(sp.eval("%s.foldMode(x)" % S) == "bed" and shown(sp, "x") == (False, True, True), "a crvBed save: a bed")
    # what an old save may have left on the load floor stays reachable: clearing the bed is always allowed
    sp.run("w.parts.CRVFunctionCargo.cont.items = 4")
    check(sp.eval("ISCRVFoldSeats:new(PLAYER, w, true, 'cargo'):isValid()"), "old fold with things on the floor: the bed can be cleared")
    # a mode value nobody writes reads as a bed; State refuses to store one
    sp.run("w.parts.SeatRearLeft.md.crv_function_foldMode = 'junk'")
    check(sp.eval("%s.foldMode(w)" % S) == "bed", "an unknown stored mode reads as a bed")
    check(sp.eval("HondaCRVGen1.State.set(w, 'function_foldMode', 'junk')")[0] is False, "State refuses an unknown mode")
    print("SP FOLD MODES: fold flat or into a bed from the menus (same action, a mode); cargo opens the load floor, no "
          "bedding, vanilla sleep; bed draws the bedding, good bed (+ pillow), floor shut; making up the bed needs the "
          "floor empty, clearing it always works (short action); old folds are beds")

    # multiplayer: alice folds flat, the server completes, both clients see it; bob makes up the bed
    net = Net()
    server = side("server", net, seed=31)
    a = side("client", net, player="alice", seed=32)
    b = side("client", net, player="bob", seed=33)
    server.run("newPlayer('alice'); newPlayer('bob')")
    init = ("for _, p in ipairs({ 'CRVFunctionCargo', 'CRVFunctionUnderfloor', 'CRVFunctionSeats' }) do "
            "HondaCRVGen1.Function.Init(v, v.parts[p]) end")
    for s in (server, a, b):
        s.run("v = newCRV(1); v.parts.TrunkDoor.door.open = true; " + init)
    a.run("PLAYER.area = 'TruckBed'; act = ISCRVFoldSeats:new(PLAYER, v, true, 'cargo'); act:perform()")
    server.run("sact = ISCRVFoldSeats:new(PLAYERS.alice, v, %s, '%s')" % ("true" if a.eval("act.on") else "false", a.eval("act.mode")))
    check(server.eval("sact:complete()") is True and server.eval("%s.isCargo(v)" % S), "server: folded flat")
    net.pump()
    for c in (a, b):
        check(c.eval("%s.isCargo(v)" % S) and shown(c) == (False, True, False), "%s: a load floor, no bedding" % c.player)
        check(c.eval("v.parts.SeatRearLeft.md.crv_function_foldMode") == "cargo", "%s has the mode" % c.player)
    b.run("PLAYER.vehicle = v")
    check(b.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is True, "bob reaches the load floor")
    check(a.eval("HondaCRVGen1.State.set(v, 'function_foldMode', 'bed')")[0] is False, "client State.set of the mode refused")
    check(a.eval("HondaCRVGen1.State.request(PLAYER, v, 'function_foldMode', 'bed')")[0] is False, "the mode is not requestable")
    # bob makes up the bed over a loaded floor: his client already refuses, so does the server
    server.run("v.parts.CRVFunctionCargo.cont.items = 1")
    b.run("v.parts.CRVFunctionCargo.cont.items = 1; mk = ISCRVFoldSeats:new(PLAYER, v, true, 'bed')")
    check(not b.eval("mk:isValid()"), "bob's client: loaded floor, refused")
    server.run("smk = ISCRVFoldSeats:new(PLAYERS.bob, v, true, 'bed')")
    check(server.eval("smk:complete()") is False, "server refuses the bed over cargo")
    net.pump()
    check(all(c.eval("%s.isCargo(v)" % S) for c in (a, b)), "still a load floor everywhere")
    server.run("v.parts.CRVFunctionCargo.cont.items = 0")
    b.run("v.parts.CRVFunctionCargo.cont.items = 0")
    check(b.eval("mk:isValid()") and b.eval("mk.switching") is True, "bob's client: valid, the short action")
    check(server.eval("smk:complete()") is True, "server makes up the bed")
    net.pump()
    check(b.eval("mk:isValid()"), "bob's action survives the server's answer")
    for c in (a, b):
        check(c.eval("%s.isBed(v)" % S) and shown(c) == (False, True, True), "%s: the bed made up, bedding drawn" % c.player)
        check(c.eval("%s.CargoAccess(v, v.parts.CRVFunctionCargo, PLAYER)" % F) is False, "%s: the load floor shut" % c.player)
    # the bed cleared, the command lost: the mod data packet alone reaches the clients through the poll
    net.drop_commands = True
    server.run("ISCRVFoldSeats:new(PLAYERS.alice, v, true, 'cargo'):complete()")
    net.pump()
    for c in (a, b):
        c.run("TICK(60)")
        check(c.eval("%s.isCargo(v)" % S) and shown(c) == (False, True, False), "%s: cleared through the poll alone" % c.player)
    net.drop_commands = False
    check(server.eval("v.parts.CRVFunctionSeats.calls") == 0, "the dedicated server draws nothing")
    print("MP FOLD MODES: alice folds flat (server completes, both clients see a load floor), bob's bed over cargo refused "
          "by his client and the server, made up once empty (bedding on both clients, floor shut), cleared by the poll "
          "alone; the mode is server-only")


def main():
    net_action_fields()
    single_player()
    sandbox_and_loot()
    multiplayer()
    seats_look()
    client_menus()
    bed_quality()
    fold_modes()
    print("FUNCTION LUA TESTS OK")


if __name__ == "__main__":
    main()
