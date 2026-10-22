r"""
The lift conversion's Lua (HondaCRVGen1_Lift.lua, TimedActions/ISCRVLiftConvert.lua,
client/HondaCRVGen1_LiftMenu.lua) under Lua 5.1 (lupa; PZ's Kahlua is a Lua 5.1), on the fake game of
scripts/lua_harness.py extended here (helpers in this file only): single player, the refusals, the
reverse and the wheel swap, the spawn failures, the menu, and a multiplayer round trip (the client
builds the action, the server rebuilds it from new()'s parameter names and completes it, the client
receives the new car with its part mod data).

    python scripts\test_lift_lua.py
"""
import os
import re
import sys

from lua_harness import LUA_DIR, Net, Side

STATE = ("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
LIFT = ("shared/HondaCRVGen1_Shared.lua", "server/Vehicles/HondaCRVGen1Accessories.lua",
        "shared/HondaCRVGen1_Lift.lua", "shared/TimedActions/ISCRVLiftConvert.lua")
MENU = ("client/HondaCRVGen1_LiftMenu.lua",)

# what the game gives the lift's Lua beyond lua_harness's PRELUDE (Java methods by their 42.21 names)
FAKE = r'''
Metabolics = { HeavyWork = 4 }
Perks = { Mechanics = "Mechanics" }
IsoDirections = { N = "N" }
ItemTag = { get = function(r) return r end }
ResourceLocation = { of = function(s) return s end }
function getText(k, a) if a ~= nil then return k .. "(" .. tostring(a) .. ")" end return k end
HaloTextHelper = { addText = function() end, getColorWhite = function() return 1 end }
TAGS = { Wrench = "base:wrench", LugWrench = "base:lugwrench" }

-- items and inventories
function Item:getFullType() return "Base." .. self.type end
function Item:getContainer() return self.container end
function Item:hasTag(t) return TAGS[self.type] == t end
Inv = {}
Inv.__index = Inv
function newInv() return setmetatable({ list = {} }, Inv) end
function Inv:AddItem(t)
    local it = type(t) == "string" and newItem((t:gsub("^Base%.", ""))) or t
    it.container = self
    table.insert(self.list, it)
    return it
end
function Inv:DoRemoveItem(it)
    for i, x in ipairs(self.list) do
        if x == it then table.remove(self.list, i); it.container = nil; return end
    end
end
function Inv:getFirstTypeRecurse(t)
    t = t:gsub("^Base%.", "")
    for _, x in ipairs(self.list) do if x.type == t then return x end end
    return nil
end
function Inv:getFirstTagRecurse(tag)
    for _, x in ipairs(self.list) do if TAGS[x.type] == tag then return x end end
    return nil
end
function Inv:count() return #self.list end
function Inv:getItems()
    local list = self.list
    return { size = function() return #list end, get = function(_, i) return list[i + 1] end }
end
-- ItemContainer.getMaxWeight / getCapacity is the container's own capacity field (0 = full, nothing fits)
function Inv:getMaxWeight() return self.capacity or 0 end
function Inv:getCapacityWeight() return self.weight or 0 end
function Inv:hasRoomFor(w) return (self.weight or 0) + w <= (self.capacity or 0) end
NET_INV = { removed = 0, added = 0 }
function sendRemoveItemFromContainer(c, it) NET_INV.removed = NET_INV.removed + 1 end
function sendAddItemToContainer(c, it) NET_INV.added = NET_INV.added + 1 end
XP = {}
function addXp(chr, perk, n) XP[#XP + 1] = { who = chr.name, perk = perk, n = n } end

-- the player
function Player:getInventory() self.inv = self.inv or newInv(); return self.inv end
function Player:getPerkLevel(perk) return self.mech or 0 end
function Player:isMechanicsCheat() return false end
function Player:isTimedActionInstant() return false end
function Player:faceThisObject() end
function Player:shouldBeTurning() return false end
function Player:setMetabolicTarget() end
function Player:getPlayerNum() return 0 end
function Player:playSound() return 0 end

-- squares
SQUARES = {}
function getSquare(x, y, z)
    local k = math.floor(x) .. "," .. math.floor(y)
    SQUARES[k] = SQUARES[k] or { x = math.floor(x), y = math.floor(y), z = 0, outside = true, ground = {} }
    return setmetatable(SQUARES[k], { __index = {
        isOutside = function(s) return s.outside end, getX = function(s) return s.x end,
        getY = function(s) return s.y end, getZ = function(s) return s.z end,
        AddWorldInventoryItem = function(s, it) table.insert(s.ground, it) end } })
end
ZONES = {}
function getVehicleZoneAt(x, y, z) return ZONES[x .. "," .. y] end

-- doors, windows, containers, the parts the car's script gives it (order = getPartByIndex)
Door = {}
Door.__index = Door
function Door:isLocked() return self.locked end
function Door:setLocked(b) self.locked = b end
function Door:isOpen() return self.open end
function Door:setOpen(b) self.open = b end
function Door:isLockBroken() return self.broken end
function Door:setLockBroken(b) self.broken = b end
Win = {}
Win.__index = Win
function Win:isOpen() return self.open end
function Win:setOpen(b) self.open = b end
function Part:isContainer() return self.isCont == true end
function Part:getContainerContentAmount() return self.amount or 0 end
function Part:setContainerContentAmount(a) self.amount = a end
function Part:getDoor() return self.door end
function Part:getWindow() return self.win end
-- VehiclePart.setItemContainer (42.21): re-parents the container, never touches its capacity
function Part:setItemContainer(c) self.cont = c end
function Part:getLuaFunction(name) return self.lua and self.lua[name] end
function Part:getMechanicSkillInstaller() return self.skill or 0 end
-- VehiclePart.setContainerCapacity: writes getItemContainer().capacity, the container held NOW
function Part:setContainerCapacity(n) if self.isCont and self.cont then self.cont.capacity = n end end
-- VehiclePart.setInventoryItem(item[, skill]) -> doInventoryItemStats (42.21 bytecode): with an item, the
-- item's MaxCapacity (x condition when the container's conditionAffectsCapacity) into the held
-- container, the item's capacity as content amount, its condition, the installer's skill; with none,
-- the script's container capacity or 0, content 0. And every model shown / hidden
function Part:setInventoryItem(item, skill)
    self.item = item
    for _, m in ipairs(self.models or {}) do self.visible[m] = item and true or nil end
    if item then
        if self.isCont then
            if (item.maxCap or 0) > 0 then
                local cap = item.maxCap
                if self.condCap then cap = math.floor(cap * (item.cond or 100) / 100) end
                self:setContainerCapacity(cap)
            end
            self.amount = item.itemCap or 0
        end
        self.cond = item.cond or 100
        self.skill = skill or 0
    else
        self:setContainerCapacity(self.scriptCap or 0)
        self.skill = 0
        self.amount = 0
    end
end
MAXCAP = { BigTrunk1 = 70, GloveBox1 = 7, NormalCarSeat1 = 15, CRVGen1_RoofRack = 50 }
function capItem(t, cond) local it = newItem(t); it.maxCap = MAXCAP[t]; it.cond = cond or 100; return it end
PARTS = {
    { "TireFrontLeft", { cont = "air", item = "NormalTire1" } }, { "GasTank", { cont = "fuel", item = "NormalGasTank1" } },
    { "Engine", {} }, { "GloveBox", { inv = true, item = "GloveBox1" } }, { "SeatRearLeft", { inv = true, item = "NormalCarSeat1" } },
    { "TruckBed", { inv = true, item = "BigTrunk1", condCap = true } }, { "DoorFrontLeft", { door = true, item = "FrontCarDoor1" } },
    { "WindowFrontLeft", { win = true, item = "FrontWindow1" } }, { "CRVRoofRack", { inv = true, acc = true } },
    { "CRVBullbar", { acc = true } }, { "CRVFunctionUnderfloor", { inv = true, scriptCap = 10 } },
}
-- the vehicle scripts' engineForce (VehicleScript.getEngineForce)
FORCE = { ["Base.HondaCRVGen1"] = 4800, ["Base.HondaCRVGen1LiftAlloy"] = 4500, ["Base.HondaCRVGen1LiftSteel"] = 4500 }
function Veh:getScript()
    local name = self.script
    return { getEngineForce = function() return FORCE[name] or 4800 end }
end
INITS = {}
function newCRV(id, script, x, y)
    local v = newVehicle(id, {}, script)
    v.order = {}
    v.x, v.y, v.z = x or 100.5, y or 100.5, 0
    v.ax, v.ay, v.az = 0, 90, 0
    v.phys = { x = v.x, y = v.y }                                  -- jniTransform.origin (physics body)
    v.skin, v.hue, v.sat, v.val, v.rust = 0, 0, 0, 0, 0
    v.keyId, v.mechId, v.quality, v.loudness, v.power = 0, 0, 50, 50, 100
    v.hotwired, v.alarmed, v.entered, v.blood, v.seated, v.controller = false, false, false, {}, {}, {}
    v.ignition = newInv()                                          -- BaseVehicle.ignitionSwitch
    v.sent = 0
    for _, spec in ipairs(PARTS) do
        local pid, s = spec[1], spec[2]
        local p = v:addPart(pid)
        table.insert(v.order, pid)
        if s.cont then p.isCont = true end
        if s.inv then p.isCont = true; p.cont = newInv() end
        p.scriptCap, p.condCap = s.scriptCap, s.condCap
        if s.inv and not s.item then p:setContainerCapacity(s.scriptCap or 0) end
        if s.door then p.door = setmetatable({ locked = false, open = false, broken = false }, Door) end
        if s.win then p.win = setmetatable({ open = false }, Win) end
        if s.acc then p.lua = { init = "HondaCRVGen1.Acc.Init" } end
        p.models = { pid }
    end
    return v
end
-- zombie.core.physics.Transform (exposed) and BaseVehicle.get/setWorldTransform, setX/Y/Z
Transform = { new = function() return { x = 0, y = 0, ax = 0, ay = 0, az = 0 } end }
function Veh:getWorldTransform(t)
    t.x, t.y, t.ax, t.ay, t.az = self.phys.x, self.phys.y, self.ax, self.ay, self.az
    return t
end
function Veh:setWorldTransform(t)
    self.phys = { x = t.x, y = t.y }
    self.ax, self.ay, self.az = t.ax, t.ay, t.az
end
function Veh:setX(x) self.x = x end
function Veh:setY(y) self.y = y end
function Veh:setZ(z) self.z = z end
function Veh:getCurrentKey() return self.ignition.list[1] end
-- players: who else is at the car (getOnlinePlayers is empty in single player; the split-screen players)
function Player:getOnlineID() return self.oid or -1 end
function Player:isDead() return false end
function getOnlinePlayers()
    local list = {}
    if ROLE ~= "sp" then for _, p in pairs(PLAYERS) do list[#list + 1] = p end end
    return { size = function() return #list end, get = function(_, i) return list[i + 1] end }
end
LOCAL = { PLAYER }
function getNumActivePlayers() if ROLE == "server" then return 0 end return #LOCAL end
function getSpecificPlayer(i) return LOCAL[i + 1] end
function getPlayer() return PLAYER end
function getPlayerByOnlineID(id) for _, p in pairs(PLAYERS) do if p.oid == id then return p end end return nil end
HALOS = {}
HaloTextHelper = { addText = function(chr, text) HALOS[#HALOS + 1] = { who = chr.name, text = text, colour = "white" } end,
                   addBadText = function(chr, text) HALOS[#HALOS + 1] = { who = chr.name, text = text, colour = "bad" } end,
                   getColorWhite = function() return "white" end, getColorRed = function() return "red" end }
GAME_MS = 0
function getGameTime() return { getCalender = function() return { getTimeInMillis = function() return GAME_MS end } end } end
-- a server command to ONE player's client (sendServerCommand(player, module, command, args))
TO_PLAYER = {}
local serverCommand = sendServerCommand
function sendServerCommand(a, b, c, d)
    if type(a) == "table" and getmetatable(a) == Player then
        if ROLE == "server" then TO_PLAYER[#TO_PLAYER + 1] = { player = a.name, module = b, command = c, args = d } end
        return
    end
    return serverCommand(a, b, c)
end
function Veh:getPartCount() return #self.order end
function Veh:getPartByIndex(i) return self.parts[self.order[i + 1]] end
function Veh:getZ() return self.z end
function Veh:getSquare() return getSquare(self.x, self.y, self.z) end
function Veh:getAngleX() return self.ax end
function Veh:getAngleY() return self.ay end
function Veh:getAngleZ() return self.az end
function Veh:setAngles(x, y, z) self.ax, self.ay, self.az = x, y, z end
function Veh:getSkinIndex() return self.skin end
function Veh:setSkinIndex(k) self.skin = k end
function Veh:getColorHue() return self.hue end
function Veh:getColorSaturation() return self.sat end
function Veh:getColorValue() return self.val end
function Veh:setColorHSV(h, s, v) self.hue, self.sat, self.val = h, s, v end
function Veh:getRust() return self.rust end
function Veh:setRust(r) self.rust = r end
function Veh:getKeyId() return self.keyId end
function Veh:setKeyId(k) self.keyId = k end
function Veh:getMechanicalID() return self.mechId end
function Veh:setMechanicalID(k) self.mechId = k end
function Veh:getEngineQuality() return self.quality end
function Veh:getEngineLoudness() return self.loudness end
function Veh:getEnginePower() return self.power end
function Veh:setEngineFeature(q, l, p) self.quality, self.loudness, self.power = q, l, p end
function Veh:isHotwired() return self.hotwired end
function Veh:setHotwired(b) self.hotwired = b end
function Veh:isAlarmed() return self.alarmed end
function Veh:setAlarmed(b) self.alarmed = b end
function Veh:isPreviouslyEntered() return self.entered end
function Veh:setPreviouslyEntered(b) self.entered = b end
function Veh:getBloodIntensity(id) return self.blood[id] or 0 end
function Veh:setBloodIntensity(id, v) self.blood[id] = v end
function Veh:getMaxPassengers() return 4 end
function Veh:getCharacter(seat) return self.seated[seat] end
function Veh:getVehicleTowing() return self.towing end
function Veh:getVehicleTowedBy() return self.towedBy end
function Veh:isKeysInIgnition() return self.keyIn == true or #self.ignition.list > 0 end
function Veh:isKeyIsOnDoor() return self.keyDoor == true end
function Veh:isEngineRunning() return self.running == true end
function Veh:getController() return self.controller end
function Veh:permanentlyRemove() self.removed = true; VEHICLES[self.id] = nil end
function Veh:transmitPartDoor() self.sent = self.sent + 1 end
function Veh:transmitPartWindow() self.sent = self.sent + 1 end
function Veh:transmitEngine() self.sent = self.sent + 1 end
function Veh:transmitRust() self.sent = self.sent + 1 end
function Veh:transmitColorHSV() self.sent = self.sent + 1 end
function Veh:transmitSkinIndex() self.sent = self.sent + 1 end

-- addVehicleDebug (GlobalObject 42.21): a new car of `script` at the square's INTEGER corner (setX(sq.x)),
-- physics seeded there, yaw jittered, the create hooks' random parts (their items' capacities written into
-- the fresh containers) and loot; addToWorld's trySpawnKey puts a key in the ignition when SPAWN_KEY > 0
-- (counted down per spawn). SPAWN_FAIL[script] = true makes it fail the way the engine does (the object
-- comes back, never added: no physics)
NEXT_ID = 50
SPAWN_FAIL = {}
SPAWNED = {}
SPAWN_KEY = 0
function addVehicleDebug(script, dir, skin, sq)
    NEXT_ID = NEXT_ID + 1
    local v = newCRV(NEXT_ID, script, sq:getX(), sq:getY())
    v.skin = skin or 0
    v.ax, v.ay, v.az = 0, 7, 0                                     -- the engine's yaw jitter
    v.keyId = 999                                                  -- a fresh random key id
    v.parts.CRVBullbar.item = newItem("CRVGen1_Bullbar")           -- create hooks: a random accessory,
    v.parts.GloveBox:setInventoryItem(capItem("GloveBox1"))         -- random loot, new tyres, the trunk,
    v.parts.GloveBox.cont:AddItem("Base.Cigarettes")               -- seats and glove box
    v.parts.TruckBed:setInventoryItem(capItem("BigTrunk1", 80))
    v.parts.SeatRearLeft:setInventoryItem(capItem("NormalCarSeat1"))
    v.parts.TireFrontLeft.item = newItem("ModernTire1")
    v.parts.SeatRearLeft.md.junk = true
    if SPAWN_KEY > 0 then
        SPAWN_KEY = SPAWN_KEY - 1
        v.ignition:AddItem("Base.CarKey").keyId = 999
    end
    if SPAWN_FAIL[script] then
        v.controller = nil
        VEHICLES[v.id] = nil
    end
    table.insert(SPAWNED, v)
    return v
end
VehicleUtils = { callLua = function(name, a, b, c, d)
    INITS[#INITS + 1] = name .. ":" .. b:getId()
    local t = _G
    for seg in string.gmatch(name, "[^%.]+") do t = t[seg] end
    return t(a, b, c, d)
end }

-- B42 timed actions (ISBaseTimedAction, enough of it)
ISBaseTimedAction = {}
ISBaseTimedAction.__index = ISBaseTimedAction
function ISBaseTimedAction:derive(name) local c = setmetatable({ Type = name }, self); c.__index = c; return c end
function ISBaseTimedAction.new(self, character) return setmetatable({ character = character }, self) end
function ISBaseTimedAction:perform() self.performed = true end
function ISBaseTimedAction:stop() self.stopped = true end
function ISBaseTimedAction:setActionAnim(a) self.anim = a end

-- a stock car with everything worth keeping
function scenario(id)
    local v = newCRV(id or 1, "Base.HondaCRVGen1", 100.73, 100.41)   -- parked off the square's corner
    v.skin, v.hue, v.sat, v.val, v.rust = 3, 0.6, 0.4, 0.7, 0.25
    v.keyId, v.mechId, v.quality, v.loudness, v.power = 1234, 77, 80, 60, 4320
    v.ax, v.ay, v.az = 1.5, 213.0, -0.5
    v.entered, v.blood.Front = true, 0.4
    v.md.crvGen1Guards = false
    local P = v.parts
    P.TireFrontLeft.item = newItem("NormalTire1"); P.TireFrontLeft.amount = 31; P.TireFrontLeft.cond = 64
    P.GasTank.item = newItem("NormalGasTank1"); P.GasTank.amount = 37.5
    P.Engine.cond = 71
    -- the containers' capacities come from their items, as the game sets them (setInventoryItem)
    P.GloveBox:setInventoryItem(capItem("GloveBox1"), 2); P.GloveBox.cont:AddItem("Base.Map")
    P.SeatRearLeft:setInventoryItem(capItem("NormalCarSeat1"), 3); P.SeatRearLeft.md.crvBed = true
    P.TruckBed:setInventoryItem(capItem("BigTrunk1", 90), 4)         -- conditionAffectsCapacity: 70 x 90 % = 63
    P.TruckBed.cont:AddItem("Base.WaterBottle").fluid = 0.8
    P.CRVFunctionUnderfloor.cont:AddItem("Base.Pistol")             -- no item: the script's capacity (10)
    P.DoorFrontLeft.item = newItem("FrontCarDoor1"); P.DoorFrontLeft.door.locked = true; P.DoorFrontLeft.cond = 55
    P.WindowFrontLeft.item = newItem("FrontWindow1"); P.WindowFrontLeft.win.open = true
    P.CRVRoofRack:setInventoryItem(capItem("CRVGen1_RoofRack"))
    P.CRVRoofRack.cont.weight = 20; P.CRVRoofRack.md.crv_acc_rackLoad = 2
    -- nothing in the bull bar slot: the create hook's random bar must not survive
    return v
end

-- what the game would answer for a car's containers: capacity, item count, room for a 1 kg item
function capacities(v)
    local out = {}
    for _, pid in ipairs({ "GloveBox", "SeatRearLeft", "TruckBed", "CRVRoofRack", "CRVFunctionUnderfloor" }) do
        local c = v.parts[pid].cont
        out[pid] = { cap = c.capacity or 0, n = c:count(), room = c:hasRoomFor(1) }
    end
    return out
end

function kitUp(player, withKit)
    local inv = player:getInventory()
    if withKit then inv:AddItem("Base.CRVGen1_LiftKit") end
    inv:AddItem("Base.Wrench"); inv:AddItem("Base.LugWrench"); inv:AddItem("Base.Jack")
    player.mech = 5
    player.x, player.y = 101, 101
end
'''


def check(cond, msg):
    if not cond:
        raise SystemExit("FAIL " + msg)


def _lift_files():
    """The lift Lua to test: the mod's, or CRV_LIFT_LUA=<dir> holding an older copy (shared/... paths) to
    show what the tests catch in it."""
    alt = os.environ.get("CRV_LIFT_LUA")
    if not alt:
        return LIFT
    return tuple(os.path.join(alt, *p.split("/")) if os.path.exists(os.path.join(alt, *p.split("/"))) else p for p in LIFT)


def side(role, net=None, player="tester", menu=False):
    s = Side(role, net, player=player)
    s.run(FAKE)
    s.load(*STATE)
    s.load(*_lift_files())
    if menu:
        s.run(MENU_FAKE)
        s.load(*MENU)
    return s


MENU_FAKE = r'''
ISVehicleMenu = { FillMenuOutsideVehicle = function() return "vanilla" end,
                  showRadialMenuOutside = VANILLA_RADIAL_OUTSIDE,
                  getVehicleToInteractWith = function(playerObj) return playerObj:getVehicle() or RADIAL_TARGET end }
RADIAL = newRadial()
function getPlayerRadialMenu(n) return RADIAL end
function getTexture(path) return path end
Ctx = {}
Ctx.__index = Ctx
function newCtx() return setmetatable({ options = {}, subs = {} }, Ctx) end
function Ctx:addOption(text, a, fn, b, c)
    local o = { text = text, fn = fn, args = { a, b, c } }
    table.insert(self.options, o)
    return o
end
function Ctx:addSubMenu(o, sub) o.sub = sub end
ISContextMenu = { getNew = function(self, parent) return newCtx() end }
ISWorldObjectContextMenu = { addToolTip = function() return {} end }
function getSpecificPlayer(n) return PLAYER end
QUEUE = {}
ISTimedActionQueue = { add = function(a) table.insert(QUEUE, a) end }
ISPathFindAction = { pathToVehicleArea = function(self, p, v, area) return { path = area } end }
'''


def new_param_names():
    src = open(os.path.join(LUA_DIR, "shared", "TimedActions", "ISCRVLiftConvert.lua"), encoding="utf-8").read()
    m = re.search(r"function ISCRVLiftConvert:new\(([^)]*)\)", src)
    return [n.strip() for n in m.group(1).split(",")]


def single_player():
    sp = side("sp")
    sp.run("v = scenario(1); kitUp(PLAYER, true)")
    L = "HondaCRVGen1.Lift"
    check(sp.eval("%s.kindOf(v)" % L) == "stock", "kindOf stock")
    check(sp.eval("HondaCRVGen1.State.isCRV(newCRV(2, 'Base.HondaCRVGen1LiftSteel'))"), "lifted scripts registered as CR-Vs")
    sp.run("VEHICLES[2] = nil")
    ok = sp.eval("(%s.canConvert(PLAYER, v, 'alloy'))" % L)
    check(ok is True, "a stock car with kit, tools and skill can be lifted")
    sp.run("before = {}; for _, pid in ipairs(v.order) do before[pid] = { item = v.parts[pid].item, cont = v.parts[pid].cont } end")
    sp.run("a = ISCRVLiftConvert:new(PLAYER, v, 'alloy')")
    check(sp.eval("a:isValid()") is True and sp.eval("a.maxTime") == sp.eval("%s.TIME" % L), "action valid, long")
    sp.run("a:start(); a:perform(); done = a:complete()")
    check(sp.eval("done") is True, "complete returned true")
    check(sp.eval("v.removed") is True and sp.eval("VEHICLES[1]") is None, "old car removed")
    sp.run("n = SPAWNED[#SPAWNED]")
    check(sp.eval("n:getScriptName()") == "Base.HondaCRVGen1LiftAlloy", "new car is the lifted alloy script")
    # every part item is the SAME object, conditions, containers (objects), amounts, mod data, doors, windows
    for pid in ("TireFrontLeft", "GasTank", "SeatRearLeft", "DoorFrontLeft", "WindowFrontLeft", "CRVRoofRack"):
        check(sp.eval("n.parts.%s.item ~= nil and rawequal(n.parts.%s.item, before.%s.item)" % (pid, pid, pid)) is True,
              "%s: the very same item object" % pid)
    for pid in ("GloveBox", "TruckBed", "CRVRoofRack", "SeatRearLeft"):
        check(sp.eval("rawequal(n.parts.%s.cont, before.%s.cont)" % (pid, pid)) is True, "%s: the very same container" % pid)
    check(sp.eval("v.parts.GasTank.item") is None, "items detached from the old car before its removal")
    check(sp.eval("n.parts.TireFrontLeft.item.type") == "NormalTire1", "the tyre item is the old one, not the create hook's")
    check(sp.eval("n.parts.TireFrontLeft.amount") == 31 and sp.eval("n.parts.TireFrontLeft.cond") == 64, "tyre pressure, condition")
    check(sp.eval("n.parts.GasTank.amount") == 37.5, "fuel")
    check(sp.eval("n.parts.Engine.cond") == 71, "engine condition")
    check(sp.eval("n.parts.CRVBullbar.item") is None, "the create hook's random bull bar is gone")
    check(sp.eval("n.parts.GloveBox.cont:count()") == 1 and sp.eval("n.parts.GloveBox.cont.list[1].type") == "Map",
          "glovebox: the old contents, not the new car's loot")
    check(sp.eval("n.parts.TruckBed.cont.list[1].fluid") == 0.8, "a container moved with its items and their fluids")
    check(sp.eval("n.parts.SeatRearLeft.md.crvBed") is True and sp.eval("n.parts.SeatRearLeft.md.junk") is None, "part mod data replaced")
    check(sp.eval("n.parts.DoorFrontLeft.door.locked") is True and sp.eval("n.parts.DoorFrontLeft.cond") == 55, "door")
    check(sp.eval("n.parts.WindowFrontLeft.win.open") is True, "window")
    for k, want in (("keyId", 1234), ("mechId", 77), ("skin", 3), ("quality", 80), ("loudness", 60),
                    ("rust", 0.25), ("hue", 0.6), ("sat", 0.4), ("val", 0.7), ("ax", 1.5), ("ay", 213.0), ("az", -0.5),
                    ("entered", True)):
        check(sp.eval("n.%s" % k) == want, "vehicle %s kept (%r)" % (k, sp.eval("n.%s" % k)))
    # the engine power follows the scripts' engineForce (4320 = 4800 x 0.9 -> 4500 x 0.9)
    check(sp.eval("n.power") == 4050, "engine power scaled to the lifted script's force (%r)" % sp.eval("n.power"))
    # where the old car stood, not on the square's corner (addVehicleDebug's setX(sq.x))
    check(abs(sp.eval("n.x") - 100.73) < 1e-9 and abs(sp.eval("n.y") - 100.41) < 1e-9 and sp.eval("n.z") == 0,
          "position kept exactly (%r, %r)" % (sp.eval("n.x"), sp.eval("n.y")))
    check(abs(sp.eval("n.phys.x") - 100.73) < 1e-9 and abs(sp.eval("n.phys.y") - 100.41) < 1e-9, "physics body moved there too")
    # every container keeps its item's capacity (or the script's), its contents and room to put more in
    caps = sp.eval("capacities(n)")
    for pid, cap, cnt in (("GloveBox", 7, 1), ("SeatRearLeft", 15, 0), ("TruckBed", 63, 1), ("CRVRoofRack", 50, 0),
                          ("CRVFunctionUnderfloor", 10, 1)):
        c = caps[pid]
        check(c["cap"] == cap and c["n"] == cnt and c["room"] is True,
              "%s capacity %r (want %d), %r items, room %r" % (pid, c["cap"], cap, c["n"], c["room"]))
    check(sp.eval("n.parts.TruckBed.skill") == 4 and sp.eval("n.parts.GloveBox.skill") == 2, "installer skill kept")
    check(sp.eval("HondaCRVGen1.State.get(n, 'acc_rackLoad')") == 2, "State values carried (rack cargo)")
    check(sp.eval("n.blood.Front") == 0.4 and sp.eval("n.md.crvGen1Guards") is False, "blood, vehicle mod data")
    check(sp.eval("PLAYER:getInventory():getFirstTypeRecurse('Base.CRVGen1_LiftKit')") is None and sp.eval("NET_INV.removed") == 1,
          "kit consumed (and the removal sent)")
    check(sp.eval("XP[1].n") == sp.eval("%s.XP" % L), "Mechanics XP")
    check(sp.eval("HALOS[#HALOS].text") == "IGUI_CRV_Lift_Lifted" and sp.eval("HALOS[#HALOS].colour") == "white",
          "single player: the outcome is shown by complete()")
    check("HondaCRVGen1.Acc.Init:CRVRoofRack" in sp.eval("table.concat(INITS, ' ')"), "part init hooks re-run (rack watcher)")
    check(sp.eval("HondaCRVGen1.Acc.racks[n:getId()] ~= nil"), "the rack's fill is followed on the new car")
    print("LIFT single player: stock -> lifted alloy, every part, container, fluid, mod data and vehicle value kept")

    # wheel swap: no kit, lower skill, shorter; then back to stock gives the kit back
    sp.run("PLAYER.mech = 3; b = ISCRVLiftConvert:new(PLAYER, n, 'steel')")
    check(sp.eval("b.maxTime") == sp.eval("%s.TIME_SWAP" % L) and sp.eval("b:isValid()") is True, "swap valid without a kit at level 3")
    sp.run("b:perform(); b:complete(); n2 = SPAWNED[#SPAWNED]")
    check(sp.eval("n2:getScriptName()") == "Base.HondaCRVGen1LiftSteel" and sp.eval("n2.keyId") == 1234, "swapped to steel")
    check(sp.eval("PLAYER:getInventory():getFirstTypeRecurse('Base.CRVGen1_LiftKit')") is None, "a swap gives no kit")
    sp.run("c = ISCRVLiftConvert:new(PLAYER, n2, 'stock')")
    check(sp.eval("c:isValid()") is False, "removing the kit needs level 5")
    sp.run("PLAYER.mech = 5; c = ISCRVLiftConvert:new(PLAYER, n2, 'stock'); c:perform(); c:complete(); n3 = SPAWNED[#SPAWNED]")
    check(sp.eval("n3:getScriptName()") == "Base.HondaCRVGen1", "back to stock")
    check(sp.eval("PLAYER:getInventory():getFirstTypeRecurse('Base.CRVGen1_LiftKit')") is not None and sp.eval("NET_INV.added") == 1,
          "the kit comes back")
    check(sp.eval("n3.parts.GasTank.amount") == 37.5 and sp.eval("HondaCRVGen1.State.get(n3, 'acc_rackLoad')") == 2, "kept through three conversions")
    caps = sp.eval("capacities(n3)")
    check(all(caps[p]["room"] for p in caps) and caps["TruckBed"]["cap"] == 63 and caps["CRVRoofRack"]["cap"] == 50,
          "capacities kept through three conversions (%r)" % {p: caps[p]["cap"] for p in caps})
    check(sp.eval("n3.power") == 4320 and abs(sp.eval("n3.x") - 100.73) < 1e-9, "power and position back where they were")
    print("LIFT single player: wheel swap without the kit, removal gives the kit back")
    return sp


def xp_farming():
    """Repeating swaps (or fit / remove) on one car pays once per kind of work per in-game day."""
    sp = side("sp")
    L = "HondaCRVGen1.Lift"
    sp.run("v = scenario(1); kitUp(PLAYER, true)")
    sp.run("n = %s.convert(PLAYER, v, 'alloy')" % L)
    for i in range(6):
        sp.run("n = %s.convert(PLAYER, n, '%s')" % (L, "steel" if i % 2 == 0 else "alloy"))
    sp.run("n = %s.convert(PLAYER, n, 'stock'); n = %s.convert(PLAYER, n, 'alloy'); n = %s.convert(PLAYER, n, 'stock')" % (L, L, L))
    xp = sp.eval("(function() local t = {} for _, x in ipairs(XP) do t[#t + 1] = x.n end return table.concat(t, ',') end)()")
    check(sp.eval("n:getScriptName()") == "Base.HondaCRVGen1", "ten conversions done")
    check(xp == "25,8,25", "one fit, one swap and one removal paid, the repeats nothing (%s)" % xp)
    # another player converting the same car is paid for their own work; a day later it pays again
    sp.run("bob = newPlayer('bob', 101, 101); bob.inv = nil; kitUp(bob, true)")
    sp.run("PLAYER.x = 120; n = %s.convert(bob, n, 'steel'); PLAYER.x = 101" % L)       # the tester stands back
    check(sp.eval("#XP") == 4 and sp.eval("XP[4].who") == "bob", "another player's own fit pays")
    sp.run("GAME_MS = 86400000 + 1; n = %s.convert(PLAYER, n, 'alloy')" % L)
    check(sp.eval("#XP") == 5 and sp.eval("XP[5].n") == 8, "a day later the swap pays again")
    print("LIFT XP: once per car, kind of work and player per in-game day (no farming by swapping)")


def spawn_key():
    """trySpawnKey can put a fresh key in the new car's ignition: it must come out."""
    sp = side("sp")
    L = "HondaCRVGen1.Lift"
    sp.run("v = scenario(1); kitUp(PLAYER, true); SPAWN_KEY = 1")
    sp.run("n = %s.convert(PLAYER, v, 'alloy')" % L)
    check(sp.eval("n ~= nil") and sp.eval("n:getScriptName()") == "Base.HondaCRVGen1LiftAlloy", "converted")
    check(sp.eval("n:isKeysInIgnition()") is False and sp.eval("n:getCurrentKey()") is None,
          "no key in the converted car's ignition")
    check(sp.eval("n.keyId") == 1234, "the car keeps its own key id")
    print("LIFT spawn key: the key trySpawnKey put in the new car's ignition is taken out")


def busy():
    """Another player at the car: no conversion (their action would land on the removed car)."""
    net = Net()
    server = side("server", net, player="tester")
    client = side("client", net, player="tester")
    for s in (server, client):
        s.run("v = scenario(1); kitUp(PLAYER, true); PLAYER.oid = 1; bob = newPlayer('bob', 102, 101); bob.oid = 2")
    ok, why = client.eval("HondaCRVGen1.Lift.canConvert(PLAYER, v, 'alloy')")
    check(ok is False and "Tooltip_CRV_Lift_Busy" in list(why.values()), "the menu refuses with bob at the car (%s)" % list(why.values()))
    server.run("sa = ISCRVLiftConvert:new(PLAYERS['tester'], getVehicleById(1), 'alloy'); done = sa:complete()")
    check(server.eval("done") is False and server.eval("v.removed") is False and server.eval("#SPAWNED") == 0,
          "the server refuses too and touches nothing")
    check(server.eval("TO_PLAYER[1].player") == "tester" and server.eval("TO_PLAYER[1].args.key") == "Tooltip_CRV_Lift_Busy"
          and server.eval("TO_PLAYER[1].args.ok") is False, "the acting player is told why")
    for s in (server, client):
        s.run("bob.x, bob.y = 106, 101")
    check(client.eval("(HondaCRVGen1.Lift.canConvert(PLAYER, v, 'alloy'))") is True, "bob stepped back: allowed")
    server.run("bob.x, bob.y, bob.vehicle = 101, 101, newCRV(7, 'Base.SUV')")
    check(server.eval("(HondaCRVGen1.Lift.canConvert(PLAYER, v, 'alloy'))") is True, "a player sitting in another car does not count")
    sp = side("sp")
    sp.run("v = scenario(1); kitUp(PLAYER, true); p2 = newPlayer('p2', 101, 100); LOCAL[2] = p2")
    check(sp.eval("(HondaCRVGen1.Lift.canConvert(PLAYER, v, 'alloy'))") is False, "split screen: the second player counts")
    print("LIFT busy: refused while another player is at the car (menu, server), told to the player")


def refusals():
    sp = side("sp")
    L = "HondaCRVGen1.Lift"
    cases = [
        ("v.seated[1] = newPlayer('bob')", "Tooltip_CRV_Lift_Passengers"),
        ("v.towing = newCRV(3, 'Base.SUV')", "Tooltip_CRV_Lift_Trailer"),
        ("v.keyIn = true", "Tooltip_CRV_Lift_Key"),
        ("v.keyDoor = true", "Tooltip_CRV_Lift_Key"),
        ("v.running = true", "Tooltip_CRV_Lift_Engine"),
        ("getSquare(100, 100).outside = false", "Tooltip_CRV_Lift_Ground"),
        ("PLAYER:getInventory():DoRemoveItem(PLAYER:getInventory():getFirstTypeRecurse('Jack'))", "Tooltip_CRV_Lift_NeedJack"),
        ("PLAYER:getInventory():DoRemoveItem(PLAYER:getInventory():getFirstTypeRecurse('LugWrench'))", "Tooltip_CRV_Lift_NeedLugWrench"),
        ("PLAYER.mech = 4", "Tooltip_CRV_Lift_NeedSkill"),
        ("PLAYER:getInventory():DoRemoveItem(PLAYER:getInventory():getFirstTypeRecurse('CRVGen1_LiftKit'))", "Tooltip_CRV_Lift_NeedKit"),
    ]
    for setup, reason in cases:
        sp.run("SQUARES = {}; VEHICLES = {}; PLAYER.inv = nil; v = scenario(1); kitUp(PLAYER, true); n0 = #SPAWNED")
        sp.run(setup)
        ok, why = sp.eval("%s.canConvert(PLAYER, v, 'alloy')" % L)
        check(ok is False and reason in list(why.values()), "refused for %s (%s)" % (reason, list(why.values())))
        sp.run("res, r2 = %s.convert(PLAYER, v, 'alloy')" % L)
        check(sp.eval("res") is None and sp.eval("v.removed") is False and sp.eval("#SPAWNED") == sp.eval("n0"),
              "complete() refuses too and touches nothing (%s)" % reason)
    # indoors but in a vehicle zone (a garage): allowed
    sp.run("SQUARES = {}; VEHICLES = {}; PLAYER.inv = nil; v = scenario(1); kitUp(PLAYER, true); getSquare(100, 100).outside = false; ZONES['100,100'] = 'parking'")
    check(sp.eval("(%s.canConvert(PLAYER, v, 'alloy'))" % L) is True, "a garage's vehicle zone is fine")
    # the same script, a non-CR-V, a client
    check(sp.eval("(%s.canConvert(PLAYER, v, 'stock'))" % L) is False, "stock -> stock refused")
    check(sp.eval("(%s.canConvert(PLAYER, newCRV(4, 'Base.SUV'), 'alloy'))" % L) is False, "not a CR-V")
    print("LIFT refusals: passengers, trailer, key, engine, ground, tools, skill, kit; garage zone allowed")


def spawn_failures():
    sp = side("sp")
    L = "HondaCRVGen1.Lift"
    sp.run("v = scenario(1); kitUp(PLAYER, true); SPAWN_FAIL['Base.HondaCRVGen1LiftAlloy'] = true")
    sp.run("res, why = %s.convert(PLAYER, v, 'alloy'); back = SPAWNED[#SPAWNED]" % L)
    check(sp.eval("res") is None and sp.eval("why") == "IGUI_CRV_Lift_Failed", "a failed spawn reports failure")
    check(sp.eval("back:getScriptName()") == "Base.HondaCRVGen1" and sp.eval("back.parts.GasTank.amount") == 37.5
          and sp.eval("back.parts.GloveBox.cont.list[1].type") == "Map", "the stock car is put back whole")
    check(sp.eval("PLAYER:getInventory():getFirstTypeRecurse('Base.CRVGen1_LiftKit')") is not None and sp.eval("#XP") == 0,
          "kit kept, no XP")
    sp.run("SPAWN_FAIL['Base.HondaCRVGen1'] = true; v = back; res, why = %s.convert(PLAYER, v, 'alloy')" % L)
    sq = "getSquare(v.x, v.y, 0).ground"
    types = sorted(sp.eval("(function() local t = {} for _, it in ipairs(%s) do t[#t + 1] = it.type end return table.concat(t, ',') end)()" % sq).split(","))
    check(sp.eval("res") is None and "Map" in types and "NormalGasTank1" in types and "WaterBottle" in types and "CRVGen1_RoofRack" in types,
          "nothing could be spawned: parts and contents on the ground (%s)" % types)
    print("LIFT spawn failures: the old script comes back; if that fails too, everything lands on the square")


def menu():
    sp = side("sp", menu=True)
    sp.run("v = scenario(1); kitUp(PLAYER, false); ctx = newCtx(); r = ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false)")
    check(sp.eval("r") == "vanilla" and sp.eval("ctx.options[1].text") == "ContextMenu_CRV_Lift_Menu", "submenu added after vanilla's")
    sub = "ctx.options[1].sub.options"
    check(sp.eval("#%s" % sub) == 2 and sp.eval("%s[1].text" % sub) == "ContextMenu_CRV_Lift_Alloy", "stock: alloy and steel")
    check(sp.eval("%s[1].notAvailable" % sub) is True and "Tooltip_CRV_Lift_NeedKit" in sp.eval("%s[1].toolTip.description" % sub),
          "no kit: greyed, the tooltip says why")
    # the outside radial (Project Viewpoint's harvest): without a kit the stock car offers no fitting at all
    radial = "viewpointRadial(PLAYER, %s):texts()"
    check(sp.eval(radial % "v") == "VANILLA_MECHANICS", "radial, no kit: no lift slices (%s)" % sp.eval(radial % "v"))
    sp.run("PLAYER:getInventory():AddItem('Base.CRVGen1_LiftKit'); ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false)")
    check(sp.eval("%s[2].notAvailable" % sub) is None, "with the kit: available")
    want = ",".join(["VANILLA_MECHANICS"] + [sp.eval("%s[%d].text" % (sub, i)) + ("" if sp.eval("%s[%d].notAvailable" % (sub, i)) is None
                                                                               else " [...]!") for i in (1, 2)])
    got = sp.eval(radial % "v")
    check(re.sub(r" \[[^\]]*\]!", " [...]!", got) == want, "radial with the kit: the submenu's options, in order (%s)" % got)
    check(sp.eval("viewpointRadial(PLAYER, v):find('ContextMenu_CRV_Lift_Steel').texture") == "media/textures/Item_CRVGen1_LiftKit.png",
          "the kit's icon")
    # the slice runs the option's handler with the option's arguments: the same walk and conversion
    sp.run("QUEUE = {}; m = viewpointRadial(PLAYER, v); s = m:find('ContextMenu_CRV_Lift_Steel')")
    check(sp.eval("s.fn == %s[2].fn and s.args[1] == %s[2].args[1] and s.args[2] == %s[2].args[2] and s.args[3] == %s[2].args[3]"
                  % (sub, sub, sub, sub)) is True, "the steel slice is the steel option (handler and arguments)")
    sp.run("m:pick(s)")
    check(sp.eval("QUEUE[2].target") == "steel" and sp.eval("QUEUE[1].path") == "TireFrontLeft", "radial: walk to the car, then the action")
    sp.run("QUEUE = {}")
    sp.run("o = %s[2]; o.fn(o.args[1], o.args[2], o.args[3])" % sub)
    check(sp.eval("QUEUE[2].target") == "steel" and sp.eval("QUEUE[1].path") == "TireFrontLeft", "walk to the car, then the action")
    sp.run("n = newCRV(5, 'Base.HondaCRVGen1LiftSteel'); ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, n, false)")
    check(sp.eval("%s[1].text" % sub) == "ContextMenu_CRV_Lift_Remove" and sp.eval("%s[2].text" % sub) == "ContextMenu_CRV_Lift_ToAlloy",
          "lifted: remove, swap")
    got = sp.eval(radial % "n")
    check(re.match(r"VANILLA_MECHANICS,ContextMenu_CRV_Lift_Remove( \[[^\]]+\]!)?,ContextMenu_CRV_Lift_ToAlloy( \[[^\]]+\]!)?$", got)
          is not None, "radial, lifted: remove, swap (%s)" % got)
    # a blocked slice has no command and says what is missing, in one line
    sp.run("n.running = true")
    got = sp.eval(radial % "n")
    check("ContextMenu_CRV_Lift_Remove [" in got and "Tooltip_CRV_Lift_Engine" in got and "<LINE>" not in got
          and sp.eval("viewpointRadial(PLAYER, n):find('ContextMenu_CRV_Lift_Remove').fn") is None,
          "radial, engine running: blocked, the reason in the label (%s)" % got)
    sp.run("n.running = false")
    sp.run("ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, newVehicle(6, {}, 'Base.SUV'), false)")
    check(sp.eval("#ctx.options") == 0, "no menu on other cars")
    check(sp.eval(radial % "newVehicle(7, {}, 'Base.SUV')") == "VANILLA_MECHANICS", "no slices on other cars")
    sp.run("RADIAL = newRadial(); RADIAL_TARGET = v; ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(sp.eval("RADIAL:texts()") == sp.eval(radial % "v") and sp.eval("RADIAL.shown") is True, "the game's V: the same slices")
    print("LIFT menu: submenu, greyed options with reasons, walk then act; the radial: the same, no fitting without a kit")


def multiplayer():
    net = Net()
    server = side("server", net, player="tester")
    client = side("client", net, player="tester", menu=True)
    other = side("client", net, player="bob")
    for s in (server, client, other):
        s.run("v = scenario(1); kitUp(PLAYER, true)")
    other.run("PLAYER.x, PLAYER.y = 110, 110")                    # bob watches from a distance
    # the client asks: the action's parameters are stored under their own names (NetTimedAction)
    client.run("a = ISCRVLiftConvert:new(PLAYER, v, 'steel')")
    names = new_param_names()
    check(names == ["character", "vehicle", "target"], "new() parameters %s" % names)
    for n in names:
        check(client.eval("a.%s ~= nil" % n), "action field %s stored under its parameter name" % n)
    check(client.eval("a:isValid()") is True, "valid on the client")
    client.run("res, why = HondaCRVGen1.Lift.convert(PLAYER, v, 'steel')")
    check(client.eval("res") is None and client.eval("why") == "client" and client.eval("v.removed") is False,
          "a client never converts by itself")
    # the server rebuilds the action from those fields (its own player and car objects) and completes it
    server.run("SPAWN_KEY = 1")
    server.run("sa = ISCRVLiftConvert:new(PLAYERS['%s'], getVehicleById(1), '%s')" % (client.eval("a.character.name"), client.eval("a.target")))
    check(server.eval("sa:isValid()") is True and server.eval("sa:complete()") is True, "server completes")
    server.run("n = SPAWNED[#SPAWNED]")
    check(server.eval("n:getScriptName()") == "Base.HondaCRVGen1LiftSteel" and server.eval("v.removed"), "server swapped the car")
    check(server.eval("n.sent") > 0 and server.eval("SENT.transmitModData") >= 10, "server transmitted the new car's parts")
    check(server.eval("NET_INV.removed") == 1, "kit removal sent to the client")
    check(server.eval("n:isKeysInIgnition()") is False, "server: no spawn key in the new car's ignition")
    caps = server.eval("capacities(n)")
    check(all(caps[p]["room"] for p in caps) and caps["TruckBed"]["cap"] == 63 and caps["GloveBox"]["n"] == 1,
          "server: every container keeps its capacity and contents (%r)" % {p: caps[p]["cap"] for p in caps})
    check(server.eval("n.parts.GasTank.amount") == 37.5 and server.eval("n.parts.TruckBed.cont.list[1].fluid") == 0.8,
          "server: fuel and the bottle's water kept")
    check(abs(server.eval("n.x") - 100.73) < 1e-9 and abs(server.eval("n.y") - 100.41) < 1e-9, "server: position kept (x / y saved and sent)")
    # the server's packets reach the client BEFORE its Done: the old car is removed there, the kit gone.
    # isValid must hold so the client waits for Done (perform) instead of stopping (stop drops the queue)
    client.run("v.removed = true; PLAYER:getInventory():DoRemoveItem(PLAYER:getInventory():getFirstTypeRecurse('Base.CRVGen1_LiftKit'))")
    check(client.eval("a:isValid()") is True, "client: the server's answer does not cancel the action")
    client.run("a.vehicle = newCRV(9, 'Base.HondaCRVGen1'); a.from = 'stock'; a.action = { getJobDelta = function() return 0.95 end }")
    client.run("a.vehicle.running = true")
    check(client.eval("a:isValid()") is True, "client: at the end of the bar the server decides")
    client.run("a.action = nil")
    check(client.eval("a:isValid()") is False, "client: before that a failed check still stops it")
    client.run("a.vehicle = v; HALOS = {}; a:perform()")
    check(client.eval("a.performed") is True and client.eval("#HALOS") == 0, "client perform: no outcome text of its own")
    msg = server.eval("TO_PLAYER[#TO_PLAYER]")
    check(msg["player"] == "tester" and msg["module"] == "HondaCRVGen1Lift" and msg["args"]["key"] == "IGUI_CRV_Lift_Lifted"
          and msg["args"]["ok"] is True, "server tells the acting player (%r)" % msg["args"]["key"])
    client.trigger("OnServerCommand", msg["module"], msg["command"], client.table({k: msg["args"][k] for k in ("ok", "key")}))
    check(client.eval("HALOS[1].text") == "IGUI_CRV_Lift_Lifted" and client.eval("HALOS[1].who") == "tester",
          "client shows the server's outcome")
    net.pump()
    # the engine streams the new car to every client (VehicleFullUpdatePacket: script, items, part mod data)
    nid = server.eval("n:getId()")
    for c in (client, other):
        c.run("v:permanentlyRemove(); cn = newCRV(%d, 'Base.HondaCRVGen1LiftSteel')" % nid)
        for pid in ("CRVRoofRack", "SeatRearLeft", "GasTank"):
            md = server.eval("n.parts.%s.md" % pid)
            c.run("cn.parts.%s.md = {}" % pid)
            for k, val in md.items():
                c.run("cn.parts.%s.md[%r] = %s" % (pid, k, repr(val).lower() if isinstance(val, bool) else repr(val)))
        c.run("cn.parts.CRVRoofRack.item = newItem('CRVGen1_RoofRack'); HondaCRVGen1.State.refresh(cn)")
        check(c.eval("HondaCRVGen1.State.get(cn, 'acc_rackLoad')") == 2 and c.eval("HondaCRVGen1.Shared.isBed(cn)") is True,
              "a client sees the carried state on the new car")
        check(c.eval("HondaCRVGen1.Lift.kindOf(cn)") == "steel" and c.eval("HondaCRVGen1.State.isCRV(cn)"), "client knows the lifted car")
    check(client.eval("XP[1]") is None and server.eval("XP[1].who") == "tester", "XP given on the server")
    print("LIFT multiplayer: client action rebuilt by name on the server, converted there, state reaches both clients")


def main():
    single_player()
    refusals()
    spawn_failures()
    xp_farming()
    spawn_key()
    busy()
    menu()
    multiplayer()
    print("LIFT LUA TESTS OK")


if __name__ == "__main__":
    sys.exit(main())
