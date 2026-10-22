r"""
Every mod Lua file at once, in the game's own load order, with vanilla stand-ins for each global the
mod wraps: the cross-feature test the per-feature tests cannot be (each loads only its own files).

    python scripts\test_all_lua.py [--lua DIR]       # DIR: another 42/media/lua tree (default: this checkout's)

Load order (42.21 LuaManager.LoadDirBase, read from the bytecode by the 2026-10-13 reviews):
  * per folder (shared, client, server): every vanilla file first, then each mod's files, their
    lower-cased relative paths sorted with String.CASE_INSENSITIVE_ORDER ("_" sorts before letters,
    sub-folders sort in with the files: shared/HondaCRVGen1_Armour.lua before shared/TimedActions/...);
  * RunLuaInternal skips a file already loaded (a require()d file does not run twice);
  * require(name) searches the folders in LuaManager.paths order (shared, client, server), only those
    whose LoadDirBase has started;
  * single player and MP clients: shared, client, OnGameBoot, server (GameLoadingState, every side),
    the distribution / map-zone events, OnGameStart (IngameState.enter);
  * dedicated server: shared, client collected but NOT run, server, OnGameBoot, the world events,
    OnServerStarted.
Kahlua does proper tail calls (OP_TAILCALL reuses the frame), so a cycle of wrappers that end in
`return f(...)` hangs the game without a stack overflow. Lua 5.1 does the same; every call from Python
into Lua here runs under an instruction budget (BUDGET) and a call over it is a FAIL ("HANG").

What runs, single player and a dedicated server with two clients (scripts/lua_harness.py runtimes):
  * the start-up itself: no Lua error in any file, no stray globals;
  * every install / uninstall test of every part of the CR-V, a lifted CR-V and a vanilla SUV, after
    the start events (the 2026-10-13 armour/offroad wrap of Vehicles.UninstallTest.Default looped here);
  * the outside-vehicle menu on a CR-V (every feature's options, vanilla once) and on a vanilla car;
  * every ISCRV* timed action stores its new() parameters under the same names (the server rebuilds
    the action from them in 42.21 multiplayer);
  * armour door plate + window mesh, roof rack + cargo + roof jerry can, snorkel, folded
    seats, cargo floor, the interlocks (rack under the roof can, plated door), then a lift conversion
    that must carry all of it; in multiplayer the same through the server, the clients drawing it.
Exit status 1 on any FAIL.
"""
import os
import re
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lupa import lua51  # noqa: E402

import lua_harness  # noqa: E402
from lua_harness import Net, Side  # noqa: E402

LUA_DIR = lua_harness.LUA_DIR
SCRIPTS_DIR = os.path.join(lua_harness.ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "scripts", "vehicles")
BUDGET = 5000000              # Lua instructions per call from the game (the whole start-up of a file is ~1e4)
MOD_GLOBALS = {"HondaCRVGen1", "ISCRVLiftConvert", "ISCRVFoldSeats", "ISCRVFunctionLiftFloor", "ISCRVAwning"}

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)
    return cond


# --------------------------------------------------------------------------------- the fake world
# On top of lua_harness.PRELUDE (events, roles, commands): items, containers, players, squares, doors,
# windows, parts and vehicles with the Java methods the mod's files call, plus the hang guard.
WORLD = r'''
EVENT_ARGS = {}
function countHandlers(name) return EVENTS[name] and #EVENTS[name] or 0 end
-- a frame is ~16 ms of wall clock (getTimestampMs); isGamePaused() is PAUSED (the engine bay's holds count unpaused time)
NOW_MS, PAUSED = 1000000, false
function getTimestampMs() return NOW_MS end
function isGamePaused() return PAUSED end
function TICK(n) for i = 1, (n or 1) do NOW_MS = NOW_MS + 16; triggerEvent("OnTick", 0) end end
function ZombRand(a, b)
    if b == nil then if a <= 0 then return 0 end return math.random(0, a - 1) end
    if b <= a then return a end
    return math.random(a, b - 1)
end
function ZombRandFloat(a, b) return a + (b - a) * math.random() end
function getText(k, ...)
    local n = select("#", ...)
    if n == 0 then return k end
    local t = {}
    for i = 1, n do t[i] = tostring((select(i, ...))) end
    return k .. "(" .. table.concat(t, ",") .. ")"
end
function instanceof(o, cls) return type(o) == "table" and o.__class == cls end
PRINTS = {}
function print(...)
    local t = {}
    for i = 1, select("#", ...) do t[i] = tostring((select(i, ...))) end
    table.insert(PRINTS, table.concat(t, " "))
end
SandboxVars = { HondaCRVGen1 = { ArmourStrength = 1.0, FunctionSpawnRate = 100, FunctionAccessoryChance = 100,
                                  FunctionLootRarity = 1.0, PolishEngineVolume = 100 } }

-- the hang guard: every call from Python is armed (ARM / DISARM); guarded() re-arms around one call
HANGS = 0
HANG_BUDGET = ...
local function hang_hook()
    HANGS = HANGS + 1
    error("HANG: over " .. HANG_BUDGET .. " Lua instructions in one call (a cycle of wrappers?)")
end
function ARM() debug.sethook(hang_hook, "", HANG_BUDGET) end
function DISARM() debug.sethook() end
function guarded(fn, ...)
    local h0 = HANGS
    ARM()
    local r = { pcall(fn, ...) }
    ARM()
    if HANGS > h0 then return false, "HANG" end
    return unpack(r, 1, table.maxn(r))
end

-- java collections
JList = {}
JList.__index = JList
function newJList(t) return setmetatable({ t = t or {} }, JList) end
function JList:size() return #self.t end
function JList:get(i) return self.t[i + 1] end
function JList:add(x) table.insert(self.t, x) return true end
function JList:isEmpty() return #self.t == 0 end
function JList:contains(x) for _, y in ipairs(self.t) do if y == x then return true end end return false end
ArrayList = { new = function() return newJList() end }
JMap = {}
JMap.__index = JMap
function newJMap() return setmetatable({ t = {} }, JMap) end
function JMap:get(k) return self.t[k] end
function JMap:put(k, v) self.t[k] = v end

ItemTag = { PAINT = "base:paint", PILLOW = "base:pillow", get = function(r) return r end }
ResourceLocation = { of = function(s) return s end }
Perks = { Mechanics = "Mechanics" }
Metabolics = { HeavyWork = 4, LightWork = 2, MediumWork = 3 }
IsoDirections = { N = "N" }
CharacterActionAnims = { Paint = "Paint" }
Fluid = { Petrol = "Petrol" }
IsoObjectChange = { MECHANIC_ACTION_DONE = 1 }
HALO = {}
HaloTextHelper = {
    addText = function(chr, t) table.insert(HALO, t) end,
    addBadText = function(chr, t) table.insert(HALO, "BAD:" .. t) end,
    getColorWhite = function() return 1 end,
}
XP = {}
function addXp(chr, perk, n) table.insert(XP, { who = chr and chr.name, perk = perk, n = n }) end
NET_INV = { removed = 0, added = 0 }
function sendRemoveItemFromContainer(c, it) NET_INV.removed = NET_INV.removed + 1 end
function sendAddItemToContainer(c, it) NET_INV.added = NET_INV.added + 1 end
function playServerSound() end
function getGameTime() return { getCalender = function() return { getTimeInMillis = function() return 1 end } end } end
function getCore() return { getScreenWidth = function() return 1920 end, getScreenHeight = function() return 1080 end } end
function getPlayerData() return nil end
function getPlayerMechanicsUI() return nil end
function getSpecificPlayer(n) return PLAYER end
function getPlayer() return PLAYER end
-- awning feature: the local players, the climate (dry: the rain loop never asks for the online players here),
-- joml's Vector3f (the car's frame: BaseVehicle.getLocalPos, below)
function getNumActivePlayers() return PLAYER and 1 or 0 end
ClimateManager = { getInstance = function() return { isRaining = function() return false end,
                                                     getTemperature = function() return 15 end } end }
V3 = {}
V3.__index = V3
Vector3f = { new = function() return setmetatable({ X = 0, Y = 0, Z = 0 }, V3) end }
function V3:x() return self.X end
function V3:y() return self.Y end
function V3:z() return self.Z end
-- vanilla's player:getNearVehicle(): the nearest vehicle of the cell within a few tiles (the polish scan)
function Player:getNearVehicle() return PLAYER_NEAR_VEHICLE(self) end
function PLAYER_NEAR_VEHICLE(p)
    local best, bd = nil, 10 * 10
    for _, v in pairs(VEHICLES) do
        local dx, dy = v:getX() - p:getX(), v:getY() - p:getY()
        if dx * dx + dy * dy <= bd then best, bd = v, dx * dx + dy * dy end
    end
    return best
end
function getCell()
    return { getVehicles = function() local t = {} for _, v in pairs(VEHICLES) do t[#t + 1] = v end return newJList(t) end }
end
EMITTERS = 0
function getWorld()
    return { getFreeEmitter = function()
        EMITTERS = EMITTERS + 1
        return { playSoundLoopedImpl = function() return 1 end, setVolume = function() end, setPitch = function() end,
                 setPos = function() end, stopSound = function() end, isPlaying = function() return true end, id = EMITTERS }
    end }
end
-- the game's radial menu (lua_harness newRadial) and the car V picks (ISVehicleMenu.getVehicleToInteractWith)
RADIAL = newRadial()
RADIAL_TARGET = false                  -- (false, not nil: the global exists from the start)
function getPlayerRadialMenu() return RADIAL end
function getTexture(path) return path end
-- the radial against the context menu: each slice past the game's has an option (submenus included) of the same
-- text, handler and arguments, or (a blocked slice, no command) a greyed option whose text starts its label.
-- Returns the slices matched and the texts of those without such an option.
function radialVsMenu(radial, ctx)
    local opts = {}
    local function walk(c)
        for _, o in ipairs(c.options) do
            opts[#opts + 1] = o
            if o.subOption then walk(o.subOption) end
        end
    end
    walk(ctx)
    local matched, missing = 0, {}
    for _, s in ipairs(radial.slices) do
        if s.text ~= "VANILLA_MECHANICS" then
            local found = false
            for _, o in ipairs(opts) do
                if s.fn then
                    if o.name == s.text and o.onSelect == s.fn and o.target == s.args[1] and not o.notAvailable then
                        local p, same = { o.param1, o.param2, o.param3, o.param4 }, true
                        for i = 2, s.n do if s.args[i] ~= p[i - 1] then same = false end end
                        if same then found = true end
                    end
                elseif o.notAvailable and string.sub(s.text, 1, #o.name + 2) == o.name .. " [" then
                    found = true
                end
            end
            if found then matched = matched + 1 else missing[#missing + 1] = s.text end
        end
    end
    return matched, table.concat(missing, ",")
end
-- what the timed-action queue holds, as text: type, then the walk's area or the action's car / setting
function queued()
    local t = {}
    for _, a in ipairs(QUEUE) do
        t[#t + 1] = tostring(a.Type) .. ":" .. tostring(a.area or (a.vehicle and a.vehicle.id)) .. ":" .. tostring(a.on)
                    .. ":" .. tostring(a.target)
    end
    return table.concat(t, ",")
end

-- items
ITEMDEF = {
    ["Base.PaintBlue"] = { tags = { "base:paint" }, uses = 10 },
    ["Base.PaintWhite"] = { tags = { "base:paint" }, uses = 10 },
    ["Base.JerryCan"] = { fluid = 20 },
    ["Base.Wrench"] = { tags = { "base:wrench" } },
    ["Base.LugWrench"] = { tags = { "base:lugwrench" } },
    ["Base.Screwdriver"] = { tags = { "base:screwdriver" } },
}
NEXT_ITEM = 1000
Item = { __class = "InventoryItem" }
Item.__index = Item
function newItem(ft, weight)
    if not ft:find("%.") then ft = "Base." .. ft end
    NEXT_ITEM = NEXT_ITEM + 1
    local d = ITEMDEF[ft] or {}
    local it = setmetatable({ ft = ft, id = NEXT_ITEM, md = {}, cond = 100, weight = weight or d.weight or 1,
                              uses = d.uses, tags = d.tags or {} }, Item)
    if d.fluid then it.fluid = newFluid(d.fluid) end
    return it
end
function Item:getFullType() return self.ft end
function Item:getType() return (self.ft:gsub("^[^%.]+%.", "")) end
function Item:getID() return self.id end
function Item:getModData() return self.md end
function Item:getCondition() return self.cond end
function Item:setCondition(c) self.cond = c end
function Item:setConditionNoSound(c) self.cond = c end
function Item:getConditionMax() return 100 end
function Item:setConditionMax() end
function Item:setMaxCapacity() end
function Item:getWeight() return self.weight end
function Item:hasTag(tag) for _, t in ipairs(self.tags) do if t == tag then return true end end return false end
function Item:getCurrentUses() return self.uses or 0 end
function Item:UseAndSync()
    self.uses = (self.uses or 0) - 1
    if self.uses <= 0 and self.container then
        local c = self.container
        c:DoRemoveItem(self)
        c:AddItem("Base.PaintbucketEmpty")
    end
end
function Item:getContainer() return self.container end
function Item:getFluidContainer() return self.fluid end
function Item:getDisplayName() return self.ft end
function Item:setJobDelta() end
function Item:setJobType() end
Fluid_ = {}
Fluid_.__index = Fluid_
function newFluid(cap) return setmetatable({ cap = cap, amount = 0 }, Fluid_) end
function Fluid_:Empty() self.amount = 0 end
function Fluid_:getCapacity() return self.cap end
function Fluid_:addFluid(f, a) self.amount = math.min(self.cap, self.amount + a) end
function Fluid_:getAmount() return self.amount end

-- containers
Cont = { __class = "ItemContainer" }
Cont.__index = Cont
function newContainer(cap) return setmetatable({ list = {}, cap = cap or 50 }, Cont) end
function Cont:AddItem(t)
    local it = type(t) == "string" and newItem(t) or t
    it.container = self
    table.insert(self.list, it)
    return it
end
function Cont:DoRemoveItem(it)
    for i, x in ipairs(self.list) do if x == it then table.remove(self.list, i); it.container = nil; return true end end
    return false
end
Cont.Remove = Cont.DoRemoveItem
function Cont:getItems() local c = {} for i, x in ipairs(self.list) do c[i] = x end return newJList(c) end
function Cont:isEmpty() return #self.list == 0 end
function Cont:getMaxWeight() return self.cap end
function Cont:getCapacity() return self.cap end
function Cont:setCapacity(c) self.cap = c end
function Cont:getCapacityWeight() local w = 0 for _, x in ipairs(self.list) do w = w + x.weight end return w end
function Cont:getFirstTypeRecurse(ft)
    if not ft:find("%.") then ft = "Base." .. ft end
    for _, x in ipairs(self.list) do if x.ft == ft then return x end end
    return nil
end
function Cont:getFirstTagRecurse(tag) for _, x in ipairs(self.list) do if x:hasTag(tag) then return x end end return nil end
function Cont:getAllEvalRecurse(fn, list) for _, x in ipairs(self.list) do if fn(x) then list:add(x) end end return list end
function Cont:contains(it) for _, x in ipairs(self.list) do if x == it then return true end end return false end
function Cont:containsID(id) for _, x in ipairs(self.list) do if x.id == id then return true end end return false end
function Cont:getItemById(id) for _, x in ipairs(self.list) do if x.id == id then return x end end return nil end
function Cont:count() return #self.list end
function Cont:containsTag(t) return false end

-- players
Player = {}
Player.__index = Player
PLAYERS = {}
function newPlayer(name, x, y)
    local p = setmetatable({ name = name, x = x or 103, y = y or 100, z = 0, vehicle = nil, inv = newContainer(200),
                             perks = { Mechanics = 0 }, recipes = {}, mech = {}, area = nil }, Player)
    PLAYERS[name] = p
    return p
end
function Player:getX() return self.x end
function Player:getY() return self.y end
function Player:getZ() return self.z end
function Player:isDead() return false end
function Player:getVehicle() return self.vehicle end
function Player:getInventory() return self.inv end
function Player:getPerkLevel(p) return self.perks[p] or 0 end
function Player:isMechanicsCheat() return false end
function Player:isTimedActionInstant() return false end
function Player:faceThisObject() end
function Player:shouldBeTurning() return false end
function Player:setMetabolicTarget() end
function Player:getPlayerNum() return 0 end
function Player:playSound() return 7 end
function Player:stopOrTriggerSound() end
function Player:getEmitter() return { stopSound = function() end } end
function Player:SetVariable() end
function Player:isRecipeActuallyKnown(n) return self.recipes[n] == true end
function Player:getMechanicsItem(k) return self.mech[k] end
function Player:addMechanicsItem(k, part, t) self.mech[k] = t end
function Player:removeFromHands() end
function Player:sendObjectChange() end
function Player:getPrimaryHandItem() return nil end
function Player:getSecondaryHandItem() return nil end
function Player:getUsername() return self.name end
function Player:isLocalPlayer() return true end
function Player:getNearVehicle() return PLAYER_NEAR_VEHICLE(self) end   -- (again: Player was redefined above)
function Player:getCurrentSquare() return getSquare(self.x, self.y, 0) end
function Player:getSquare() return getSquare(self.x, self.y, 0) end

-- squares
SQUARES = {}
function getSquare(x, y, z)
    local k = math.floor(x) .. "," .. math.floor(y)
    if not SQUARES[k] then
        SQUARES[k] = setmetatable({ x = math.floor(x), y = math.floor(y), z = 0, outside = true, ground = {} }, { __index = {
            isOutside = function(s) return s.outside end, getX = function(s) return s.x end,
            getY = function(s) return s.y end, getZ = function(s) return s.z end,
            AddWorldInventoryItem = function(s, it) table.insert(s.ground, it) end } })
    end
    return SQUARES[k]
end
function getVehicleZoneAt() return nil end

-- doors / windows
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
function Win:isDestroyed() return false end
function Win:setOpenDelta() end

-- vehicle parts (spec: SCRIPT_PARTS[script][i], parsed from the vehicle scripts in Python)
Part = { __class = "VehiclePart" }
Part.__index = Part
function Part:getId() return self.id end
function Part:getVehicle() return self.vehicle end
function Part:getInventoryItem() return self.item end
function Part:setInventoryItem(item, mech)
    self.item = item
    if self.spec.allVisible ~= false then
        for _, m in ipairs(self.models) do self.visible[m] = item and true or nil end
    end
end
function Part:getModData() return self.md end
function Part:getCondition() return self.cond end
function Part:setCondition(c) self.cond = c end
function Part:getArea() return self.spec.area or self.id end
function Part:getItemContainer() return self.cont end
function Part:setItemContainer(c) self.cont = c; if c then c.part = self end end
function Part:setModelVisible(id, vis) self.calls = self.calls + 1; self.visible[id] = vis and true or nil end
function Part:getItemType() if self.spec.itemType then return newJList(self.spec.itemType) end return nil end
function Part:getTable(name) return self.spec[name] end
function Part:getLuaFunction(name) return self.spec.lua and self.spec.lua[name] end
function Part:getDoor() return self.door end
function Part:getWindow() return self.win end
function Part:isContainer() return self.spec.container ~= nil or self.spec.content ~= nil end
function Part:getContainerContentAmount() return self.amount or 0 end
function Part:setContainerContentAmount(a) self.amount = a end
function Part:getWheelIndex() return self.spec.wheel or -1 end
function Part:getContainerSeatNumber() return self.spec.seat or -1 end
function Part:getContainerCapacity() return self.cont and self.cont.cap or (self.spec.container and self.spec.container.capacity) or 0 end
function Part:setContainerCapacity(c) if self.cont then self.cont.cap = c end end
function Part:setRandomCondition(item) end
function Part:getCategory() return self.spec.category end
function Part:visibleList()
    local out = {}
    for _, m in ipairs(self.models) do if self.visible[m] then out[#out + 1] = m end end
    return table.concat(out, ",")
end

-- vehicles
VEHICLES = {}
SENT = { moddata = 0, cond = 0, item = 0, window = 0, door = 0, other = 0, transmitModData = 0 }
JAVA_ERRORS = {}
Veh = { __class = "BaseVehicle" }
Veh.__index = Veh
NEXT_VEHICLE = 1
function buildVehicle(script, id, x, y)
    local v = setmetatable({ id = id, script = script, md = {}, parts = {}, order = {}, x = x or 100.5, y = y or 100.5, z = 0,
                             ax = 0, ay = 0, az = 0, skin = 0, hue = 0.1, sat = 0.2, val = 0.3, rust = 0, keyId = 0, mechId = id * 11,
                             quality = 50, loudness = 50, power = 100, hotwired = false, alarmed = false, entered = false,
                             blood = {}, seats = {}, chosen = newJMap(), removed = false, controller = {} }, Veh)
    for _, spec in ipairs(SCRIPT_PARTS[script]) do
        local p = setmetatable({ id = spec.id, vehicle = v, spec = spec, md = {}, cond = 100, calls = 0, visible = {},
                                 models = spec.models or {} }, Part)
        if spec.container then p.cont = newContainer(spec.container.capacity or 50); p.cont.part = p end
        if spec.door then p.door = setmetatable({ locked = false, open = false, broken = false }, Door) end
        if spec.window then p.win = setmetatable({ open = false }, Win) end
        v.parts[spec.id] = p
        table.insert(v.order, spec.id)
    end
    return v
end
-- BaseVehicle creation: create hooks (a new car only), then createPhysics: init hooks, OnSpawnVehicleEnd (new car)
function createVehicle(script, x, y, fresh)
    local id = NEXT_VEHICLE
    NEXT_VEHICLE = NEXT_VEHICLE + 1
    local v = buildVehicle(script, id, x, y)
    VEHICLES[id] = v
    if fresh then
        for _, pid in ipairs(v.order) do
            local p = v.parts[pid]
            local fn = p.spec.lua and p.spec.lua.create
            if fn then VehicleUtils.callLua(fn, v, p) end
        end
    end
    createPhysics(v)
    if fresh then triggerEvent("OnSpawnVehicleEnd", v) end
    return v
end
function createPhysics(v)
    for _, pid in ipairs(v.order) do
        local p = v.parts[pid]
        local fn = p.spec.lua and p.spec.lua.init
        if fn then VehicleUtils.callLua(fn, v, p) end
    end
end
function getVehicleById(id) return VEHICLES[id] end
function addVehicleDebug(script, dir, skin, sq)
    local v = createVehicle(script, sq:getX() + 0.5, sq:getY() + 0.5, true)
    v.ay = 7
    return v
end
function Veh:getId() return self.id end
function Veh:getScriptName() return self.script end
function Veh:getScript() local s = self.script return { getName = function() return (s:gsub("^Base%.", "")) end,
                                                          getModelScale = function() return 0.9 end } end
-- the car faces north (-y), its left is west (-x) (awning feature: the footprint)
function Veh:getLocalPos(x, y, z, out) out.X = -(x - self.x); out.Y = z - self.z; out.Z = -(y - self.y); return out end
function Veh:getDriver() return self.seats[0] end
function Veh:getPartById(id) return self.parts[id] end
function Veh:getPartCount() return #self.order end
function Veh:getPartByIndex(i) return self.parts[self.order[i + 1]] end
function Veh:getModData() return self.md end
function Veh:getX() return self.x end
function Veh:getY() return self.y end
function Veh:getZ() return self.z end
function Veh:setX(x) self.x = x end
function Veh:setY(y) self.y = y end
function Veh:setZ(z) self.z = z end
function Veh:getSquare() return getSquare(self.x, self.y, self.z) end
function Veh:isRemovedFromWorld() return self.removed end
function Veh:transmitPartModData(p) SENT.moddata = SENT.moddata + 1; if ROLE == "server" then PY_PACKET("moddata", self.id, p.id) end end
function Veh:transmitPartCondition(p) SENT.cond = SENT.cond + 1; if ROLE == "server" then PY_PACKET("cond", self.id, p.id) end end
function Veh:transmitPartItem(p) SENT.item = SENT.item + 1; if ROLE == "server" then PY_PACKET("item", self.id, p.id) end end
function Veh:transmitPartWindow(p) SENT.window = SENT.window + 1; if ROLE == "server" then PY_PACKET("window", self.id, p.id) end end
function Veh:transmitPartDoor(p) SENT.door = SENT.door + 1; if ROLE == "server" then PY_PACKET("door", self.id, p.id) end end
ANIMS = {}
function Veh:playPartAnim(p, anim) table.insert(ANIMS, p.id .. ":" .. anim) end
function Veh:transmitEngine() SENT.other = SENT.other + 1 end
function Veh:transmitRust() SENT.other = SENT.other + 1 end
function Veh:transmitColorHSV() SENT.other = SENT.other + 1 end
function Veh:transmitSkinIndex() SENT.other = SENT.other + 1 end
function Veh:doDamageOverlay() end
function Veh:isInArea(area, chr) return chr.area == area end
function Veh:isSeatOccupied(seat) return self.seats[seat] ~= nil end
function Veh:getCharacter(seat) return self.seats[seat] end
function Veh:getMaxPassengers() return 4 end
function Veh:getChoosenParts() return self.chosen end
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
function Veh:setBloodIntensity(id, val) self.blood[id] = val end
function Veh:getVehicleTowing() return nil end
function Veh:getVehicleTowedBy() return nil end
function Veh:isKeysInIgnition() return false end
function Veh:isKeyIsOnDoor() return false end
function Veh:isEngineRunning() return self.running == true end
function Veh:isEngineStarted() return self.running == true end
function Veh:getController() return self.controller end
function Veh:isBurnt() return false end
function Veh:permanentlyRemove() self.removed = true; VEHICLES[self.id] = nil; if ROLE == "server" then PY_PACKET("remove", self.id, "") end end
function Veh:getAreaCenter(area) local x, y = self.x, self.y if area == "SeatRearRight" then x = x + 1 else x = x - 1 end
    return { getX = function() return x end, getY = function() return y end } end
function Veh:getEngineSpeed() return 0 end
function Veh:getCurrentSpeedKmHour() return 0 end
function Veh:getClosestWindow() return nil end
-- Java: the part's install / uninstall test, a protected Lua call (an error is logged, the answer is false)
local function javaTest(self, chr, part, which)
    local t = part:getTable(which)
    if not t or not t.test then return false end
    local ok, res = pcall(VehicleUtils.callLua, t.test, self, part, chr)
    if not ok then table.insert(JAVA_ERRORS, tostring(res)); return false end
    return res == true
end
function Veh:canUninstallPart(chr, part) return javaTest(self, chr, part, "uninstall") end
function Veh:canInstallPart(chr, part) return javaTest(self, chr, part, "install") end
'''

# Vanilla stand-ins: the shapes of the 42.21 files under ProjectZomboid\media\lua that the mod wraps or
# calls (Vehicles.UninstallTest.Default, VehicleUtils, the vehicle timed actions and menus), trimmed to
# what the mod reaches.
VANILLA = {
    "shared/TimedActions/ISBaseTimedAction.lua": r'''
ISBaseTimedAction = { Type = "ISBaseTimedAction" }
ISBaseTimedAction.__index = ISBaseTimedAction
function ISBaseTimedAction:derive(type)
    local o = {}
    setmetatable(o, self)
    self.__index = self
    o.Type = type
    return o
end
function ISBaseTimedAction:new(character)
    local o = {}
    setmetatable(o, self)
    self.__index = self
    o.character = character
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = -1
    return o
end
function ISBaseTimedAction:perform() self.performed = true end
function ISBaseTimedAction:stop() self.stopped = true end
function ISBaseTimedAction:setActionAnim(a) self.anim = a end
function ISBaseTimedAction:setOverrideHandModels() end
function ISBaseTimedAction:getJobDelta() return 0.5 end
''',
    # 42.21 ISOpenVehicleDoor: start() plays the part's Open clip at once, complete() opens the door afterwards
    "shared/Vehicles/TimedActions/ISOpenVehicleDoor.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISOpenVehicleDoor = ISBaseTimedAction:derive("ISOpenVehicleDoor")
function ISOpenVehicleDoor:isValid() return self.part ~= nil and self.part:getDoor() ~= nil end
function ISOpenVehicleDoor:start() self.vehicle:playPartAnim(self.part, "Open") end
function ISOpenVehicleDoor:complete()
    if not self.part:getDoor():isLocked() then self.part:getDoor():setOpen(true); self.vehicle:transmitPartDoor(self.part) end
    return true
end
function ISOpenVehicleDoor:new(character, vehicle, part)
    local o = ISBaseTimedAction.new(self, character)
    o.vehicle = vehicle
    o.part = part
    o.maxTime = 0
    return o
end
''',
    "shared/Vehicles/TimedActions/ISOpenCloseVehicleWindow.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISOpenCloseVehicleWindow = ISBaseTimedAction:derive("ISOpenCloseVehicleWindow")
function ISOpenCloseVehicleWindow:isValid()
    local installed = not self.part:getItemType() or (self.part:getInventoryItem() ~= nil)
    return installed and self.window and (self.window:isOpen() ~= self.open) and not self.window:isDestroyed()
end
function ISOpenCloseVehicleWindow:complete() self.window:setOpen(self.open); self.vehicle:transmitPartWindow(self.part); return true end
function ISOpenCloseVehicleWindow:new(character, part, open)
    local o = ISBaseTimedAction.new(self, character)
    o.vehicle = part:getVehicle()
    o.part = part
    o.window = part:getWindow()
    o.open = open
    o.maxTime = 50
    return o
end
''',
    "shared/Vehicles/TimedActions/ISInstallVehiclePart.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISInstallVehiclePart = ISBaseTimedAction:derive("ISInstallVehiclePart")
function ISInstallVehiclePart:isValid()
    return self.vehicle:canInstallPart(self.character, self.part) and self.character:getInventory():contains(self.item)
end
function ISInstallVehiclePart:complete()
    if self.item == nil then return false end
    self.character:getInventory():DoRemoveItem(self.item)
    sendRemoveItemFromContainer(self.character:getInventory(), self.item)
    self.part:setInventoryItem(self.item, 5)
    local tbl = self.part:getTable("install")
    if tbl and tbl.complete then VehicleUtils.callLua(tbl.complete, self.vehicle, self.part) end
    self.vehicle:transmitPartItem(self.part)
    self.character:addMechanicsItem(self.item:getID() .. self.vehicle:getMechanicalID() .. "1", self.part, 1)
    addXp(self.character, Perks.Mechanics, 1)
    return true
end
function ISInstallVehiclePart:new(character, part, item, maxTimeInit)
    local o = ISBaseTimedAction.new(self, character)
    o.part = part
    if part ~= nil then o.vehicle = part:getVehicle() end
    o.item = item
    o.maxTime = maxTimeInit
    return o
end
''',
    "shared/Vehicles/TimedActions/ISUninstallVehiclePart.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISUninstallVehiclePart = ISBaseTimedAction:derive("ISUninstallVehiclePart")
function ISUninstallVehiclePart:isValid()
    return self.part:getInventoryItem() and self.vehicle:canUninstallPart(self.character, self.part)
end
function ISUninstallVehiclePart:complete()
    local item = self.part:getInventoryItem()
    if not item then return false end
    self.part:setInventoryItem(nil)
    local tbl = self.part:getTable("uninstall")
    if tbl and tbl.complete then VehicleUtils.callLua(tbl.complete, self.vehicle, self.part, item) end
    self.vehicle:transmitPartItem(self.part)
    self.character:getInventory():AddItem(item)
    self.character:addMechanicsItem(item:getID() .. self.vehicle:getMechanicalID() .. "0", self.part, 1)
    return true
end
function ISUninstallVehiclePart:new(character, part, maxTime)
    local o = ISBaseTimedAction.new(self, character)
    o.part = part
    o.vehicle = part:getVehicle()
    o.maxTime = maxTime
    return o
end
''',
    "shared/Vehicles/TimedActions/ISRepairEngine.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISRepairEngine = ISBaseTimedAction:derive("ISRepairEngine")
function ISRepairEngine:complete() self.part:setCondition(self.part:getCondition() + 5); return true end
function ISRepairEngine:new(character, part, item, maxTime)
    local o = ISBaseTimedAction.new(self, character)
    o.part = part; o.vehicle = part:getVehicle(); o.item = item; o.maxTime = maxTime
    return o
end
''',
    "client/ISUI/ISContextMenu.lua": r'''
Ctx = {}
Ctx.__index = Ctx
function newCtx() return setmetatable({ options = {} }, Ctx) end
function Ctx:addOption(text, target, fn, a, b, c, d)
    local o = { name = text, target = target, onSelect = fn, param1 = a, param2 = b, param3 = c, param4 = d }
    table.insert(self.options, o)
    return o
end
function Ctx:addSubMenu(o, sub) o.subOption = sub end
function Ctx:removeLastOption() table.remove(self.options) end
ISContextMenu = { getNew = function(self, parent) return newCtx() end }
''',
    "client/ISUI/ISWorldObjectContextMenu.lua": r'''
ISWorldObjectContextMenu = {}
function ISWorldObjectContextMenu.addToolTip() return {} end
TRANSFERS = {}
function ISWorldObjectContextMenu.transferIfNeeded(p, item) table.insert(TRANSFERS, item) end
ISWorldObjectContextMenu.getBedQuality = function(playerObj, bed)
    if playerObj:getVehicle() then return "badBed" end
    if not bed then return "floor" end
    return "averageBed"
end
''',
    "client/ISUI/ISModalRichText.lua": r'''ISModalRichText = {}''',
    "client/TimedActions/ISTimedActionQueue.lua": r'''
QUEUE = {}
ISTimedActionQueue = { add = function(a) table.insert(QUEUE, a) return a end }
ISPathFindAction = { pathToVehicleArea = function(self, p, v, area) return { Type = "path", area = area } end }
''',
    "client/Vehicles/ISUI/ISVehicleMenu.lua": r'''
ISVehicleMenu = {}
VANILLA_OUTSIDE = 0
function ISVehicleMenu.FillMenuOutsideVehicle(player, context, vehicle, test)
    VANILLA_OUTSIDE = VANILLA_OUTSIDE + 1
    context:addOption("VANILLA_WASH", nil, nil)
end
ENTERED = {}
function ISVehicleMenu.onEnter(playerObj, vehicle, seat) table.insert(ENTERED, seat) end
function ISVehicleMenu.getVehicleToInteractWith(playerObj) return playerObj:getVehicle() or RADIAL_TARGET end
ISVehicleMenu.showRadialMenuOutside = VANILLA_RADIAL_OUTSIDE
''',
    "client/Vehicles/ISUI/ISCarMechanicsOverlay.lua": r'''
ISCarMechanicsOverlay = { CarList = {}, PartList = { EngineDoor = { img = "hood", vehicles = {} } } }
''',
    "client/Vehicles/ISUI/ISVehicleMechanics.lua": r'''
ISVehicleMechanics = {}
function ISVehicleMechanics:renderCarOverlay() end
''',
    "client/Vehicles/TimedActions/ISEnterVehicle.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISEnterVehicle = ISBaseTimedAction:derive("ISEnterVehicle")
function ISEnterVehicle:isValid() return not self.vehicle:isSeatOccupied(self.seat) end
function ISEnterVehicle:new(character, vehicle, seat)
    local o = ISBaseTimedAction.new(self, character); o.vehicle = vehicle; o.seat = seat; return o
end
''',
    "client/Vehicles/TimedActions/ISSwitchVehicleSeat.lua": r'''
require "TimedActions/ISBaseTimedAction"
ISSwitchVehicleSeat = ISBaseTimedAction:derive("ISSwitchVehicleSeat")
function ISSwitchVehicleSeat:isValid() local v = self.character:getVehicle() return v ~= nil and not v:isSeatOccupied(self.seatTo) end
function ISSwitchVehicleSeat:new(character, seatTo)
    local o = ISBaseTimedAction.new(self, character); o.seatTo = seatTo; return o
end
''',
    "server/Vehicles/Vehicles.lua": r'''
Vehicles = {}
Vehicles.CheckEngine = {}
Vehicles.CheckOperate = {}
Vehicles.ContainerAccess = {}
Vehicles.Create = {}
Vehicles.Init = {}
Vehicles.InstallComplete = {}
Vehicles.InstallTest = {}
Vehicles.UninstallComplete = {}
Vehicles.UninstallTest = {}
Vehicles.Update = {}
Vehicles.Use = {}
VANILLA_UNINSTALL_CALLS = 0
function Vehicles.ContainerAccess.Seat(vehicle, part, chr)
    if chr:getVehicle() == vehicle then return true end
    return vehicle:isInArea(part:getArea(), chr)
end
function Vehicles.ContainerAccess.TruckBed(vehicle, part, chr) return vehicle:isInArea(part:getArea(), chr) end
function Vehicles.InstallTest.Default(vehicle, part, chr)
    if part:getInventoryItem() then return false end
    local kv = part:getTable("install")
    if not kv then return false end
    if kv.requireInstalled and not (vehicle:getPartById(kv.requireInstalled) and vehicle:getPartById(kv.requireInstalled):getInventoryItem()) then return false end
    return true
end
function Vehicles.UninstallTest.Default(vehicle, part, chr)
    VANILLA_UNINSTALL_CALLS = VANILLA_UNINSTALL_CALLS + 1
    local keyvalues = part:getTable("uninstall")
    if not keyvalues then return false end
    if not part:getInventoryItem() then return false end
    if not part:getItemType() or part:getItemType():isEmpty() then return false end
    if keyvalues.requireUninstalled and (vehicle:getPartById(keyvalues.requireUninstalled) and vehicle:getPartById(keyvalues.requireUninstalled):getInventoryItem()) then
        return false
    end
    if keyvalues.requireEmpty and part:getItemContainer() and not part:getItemContainer():isEmpty() then return false end
    return true
end
function Vehicles.Create.Default(vehicle, part) VehicleUtils.createPartInventoryItem(part) end
function Vehicles.Create.Door(vehicle, part) VehicleUtils.createPartInventoryItem(part) end
function Vehicles.Init.Door(vehicle, part) end
function Vehicles.InstallComplete.Default(vehicle, part) vehicle:doDamageOverlay() end
function Vehicles.UninstallComplete.Default(vehicle, part, item) vehicle:doDamageOverlay() end
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
        part:setInventoryItem(newItem(itemType))
    end
    return part:getInventoryItem()
end
function VehicleUtils.callLua(functionName, arg1, arg2, arg3, arg4)
    if functionName:find(".", 1, true) then
        local t = _G
        local ss = {}
        for seg in string.gmatch(functionName, "[^%.]+") do ss[#ss + 1] = seg end
        for i = 1, #ss - 1 do t = t[ss[i]] end
        local func = t[ss[#ss]]
        return func(arg1, arg2, arg3, arg4)
    else
        return _G[functionName](arg1, arg2, arg3, arg4)
    end
end
''',
    "server/Vehicles/VehicleDistributions.lua": r'''
VehicleDistributions = { { SUV = { Normal = { GloveBox = { rolls = 1, items = {} } }, Specific = { { GloveBox = { rolls = 1, items = {} } } } } } }
''',
    "server/Items/ProceduralDistributions.lua": r'''
ProceduralDistributions = { list = setmetatable({}, { __index = function(t, k) local l = { items = {} }; rawset(t, k, l); return l end }) }
''',
}
VANILLA_GLOBALS = {"Ctx", "ENTERED", "ISBaseTimedAction", "ISCarMechanicsOverlay", "ISContextMenu", "ISEnterVehicle",
                   "ISInstallVehiclePart", "ISModalRichText", "ISOpenCloseVehicleWindow", "ISOpenVehicleDoor",
                   "ISPathFindAction", "ISRepairEngine",
                   "ISSwitchVehicleSeat", "ISTimedActionQueue", "ISUninstallVehiclePart", "ISVehicleMechanics", "ISVehicleMenu",
                   "ISWorldObjectContextMenu", "ProceduralDistributions", "QUEUE", "TRANSFERS", "VANILLA_OUTSIDE",
                   "VANILLA_UNINSTALL_CALLS", "VehicleDistributions", "VehicleUtils", "Vehicles", "newCtx"}


# --------------------------------------------------------------------------------- vehicle scripts
def _lines(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if line:
            yield line


def _blocks(text):
    """Nested script blocks: [('kv', k, v) | ('block', header, children)]."""
    stack, pending = [[]], None
    for line in _lines(text):
        if line == "{":
            node = ("block", pending, [])
            stack[-1].append(node)
            stack.append(node[2])
            pending = None
        elif line in ("}", "},"):
            stack.pop()
        elif "=" in line:
            k, v = line.split("=", 1)
            stack[-1].append(("kv", k.strip(), v.strip().rstrip(",").strip()))
        else:
            pending = line
    return stack[0]


def _kv(children):
    return {c[1]: c[2] for c in children if c[0] == "kv"}


# the template parts the CR-V takes from vanilla (template! = SUV and the door / window / seat templates)
VANILLA_PARTS = [
    ("Engine", {}),
    ("EngineDoor", {"item": "Base.EngineDoor1", "door": True, "area": "Engine"}),
    ("Battery", {"item": "Base.Battery"}),
    ("GasTank", {"item": "Base.NormalGasTank1", "content": True}),
    # template_glovebox: itemType = Base.GloveBox (a removable part: taking it out once hid the whole cabin)
    ("GloveBox", {"item": "Base.GloveBox1", "container": {"capacity": 5}}),
    ("TruckBed", {"item": "Base.BigTrunk1", "container": {"capacity": 70}, "area": "TruckBed"}),
    ("TrunkDoor", {"item": "Base.TrunkDoor1", "door": True, "area": "TruckBed"}),
    ("Windshield", {"item": "Base.Windshield1", "window": True}),
    ("WindshieldRear", {"item": "Base.RearWindshield1", "window": True, "parent": "TrunkDoor"}),
    ("SeatFrontLeft", {"item": "Base.NormalCarSeat1", "container": {"capacity": 20}, "seat": 0}),
    ("SeatFrontRight", {"item": "Base.NormalCarSeat1", "container": {"capacity": 20}, "seat": 1}),
    ("SeatRearLeft", {"item": "Base.NormalCarSeat1", "container": {"capacity": 20}, "seat": 2}),
    ("SeatRearRight", {"item": "Base.NormalCarSeat1", "container": {"capacity": 20}, "seat": 3}),
    ("HeadlightLeft", {"item": "Base.ModernCarLight"}),
    ("HeadlightRight", {"item": "Base.ModernCarLight"}),
    ("Muffler", {"item": "Base.NormalCarMuffler1"}),
]
for _side in ("FrontLeft", "FrontRight", "RearLeft", "RearRight"):
    VANILLA_PARTS += [
        ("Door" + _side, {"item": "Base.FrontCarDoor1" if "Front" in _side else "Base.RearCarDoor1", "door": True,
                          "area": "Seat" + _side, "uninstall_extra": {"requireUninstalled": "Window" + _side}}),
        ("Window" + _side, {"item": "Base.FrontWindow1" if "Front" in _side else "Base.RearWindow1", "window": True,
                            "parent": "Door" + _side}),
        ("Tire" + _side, {"item": "Base.NormalTire1", "content": True, "wheel": 0}),
        ("Brake" + _side, {"item": "Base.NormalBrake1"}),
        ("Suspension" + _side, {"item": "Base.NormalSuspension1"}),
    ]


def parse_vehicle(path):
    top = _blocks(open(path, encoding="utf-8").read())
    module = [c for c in top if c[0] == "block"][0]
    vehicle = [c for c in module[2] if c[0] == "block" and c[1].startswith("vehicle ")][0]
    name = "Base." + vehicle[1].split()[1]
    parts, order = {}, []
    for pid, spec in VANILLA_PARTS:
        s = {"id": pid, "models": [pid] if spec.get("item") else []}
        if spec.get("item"):
            s["itemType"] = [spec["item"]]
            s["lua"] = {"create": "Vehicles.Create.Default"}
            s["install"] = {"test": "Vehicles.InstallTest.Default"}
            s["uninstall"] = dict({"test": "Vehicles.UninstallTest.Default"}, **spec.get("uninstall_extra", {}))
        for k in ("door", "window", "area", "parent", "container", "content", "wheel", "seat"):
            if k in spec:
                s[k] = spec[k]
        parts[pid] = s
        order.append(pid)
    for c in vehicle[2]:
        if c[0] != "block" or not (c[1] or "").startswith("part "):
            continue
        pid = c[1].split()[1]
        s = parts.get(pid)
        if s is None:
            s = parts[pid] = {"id": pid, "models": []}
            order.append(pid)
        for ch in c[2]:
            if ch[0] == "kv":
                k, v = ch[1], ch[2]
                if k == "itemType":
                    s["itemType"] = v.split(";")
                elif k == "setAllModelsVisible":
                    s["allVisible"] = v.lower() != "false"
                elif k in ("parent", "area", "category"):
                    s[k] = v
                continue
            head = ch[1] or ""
            if head.startswith("model "):
                if head.split()[1] not in s["models"]:
                    s["models"].append(head.split()[1])
            elif head in ("table install", "table uninstall"):
                s.setdefault(head.split()[1], {}).update(_kv(ch[2]))
            elif head == "lua":
                s.setdefault("lua", {}).update(_kv(ch[2]))
            elif head == "container":
                kv = _kv(ch[2])
                cont = s.setdefault("container", {})
                if "test" in kv:
                    cont["test"] = kv["test"]
                if "capacity" in kv:
                    cont["capacity"] = float(kv["capacity"])
    return name, [parts[p] for p in order]


def _lua(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "{" + ", ".join(_lua(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ", ".join("[%s] = %s" % (_lua(k), _lua(x)) for k, x in v.items()) + "}"
    raise TypeError(v)


def scripts_lua():
    """SCRIPT_PARTS for every CR-V script the mod ships, plus 'Base.SUV': the same car with every
    CR-V part and hook taken out (a vanilla vehicle for the wrappers' pass-through checks)."""
    out, names = ["SCRIPT_PARTS = {}"], []
    for f in sorted(os.listdir(SCRIPTS_DIR)):
        if f.endswith(".txt"):
            name, parts = parse_vehicle(os.path.join(SCRIPTS_DIR, f))
            out.append("SCRIPT_PARTS[%s] = %s" % (_lua(name), _lua(parts)))
            names.append(name)
    other = [dict(p) for p in parse_vehicle(os.path.join(SCRIPTS_DIR, "HondaCRVGen1.txt"))[1] if not p["id"].startswith("CRV")]
    for p in other:
        if "lua" in p and any(str(x).startswith("HondaCRVGen1") for x in p["lua"].values()):
            p["lua"] = {"create": "Vehicles.Create.Default"}
        p.pop("allVisible", None)
        if "uninstall" in p:
            p["uninstall"] = {k: v for k, v in p["uninstall"].items() if not v.startswith("HondaCRVGen1")}
            p["uninstall"].setdefault("test", "Vehicles.UninstallTest.Default")
            if p["uninstall"].get("requireUninstalled", "").startswith("CRV"):
                del p["uninstall"]["requireUninstalled"]
        if "install" in p:
            p["install"] = {k: v for k, v in p["install"].items() if not v.startswith("HondaCRVGen1")}
            p["install"].setdefault("test", "Vehicles.InstallTest.Default")
        if "container" in p and str(p["container"].get("test", "")).startswith("HondaCRVGen1"):
            del p["container"]["test"]
    out.append("SCRIPT_PARTS['Base.SUV'] = %s" % _lua(other))
    return "\n".join(out), names


# --------------------------------------------------------------------------------- one game side
def mod_files(folder):
    """The mod's files of one folder as LoadDirBase lists them: lower-cased relative paths, sorted
    case-insensitively (sub-folders sort in with the files)."""
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(LUA_DIR, folder)):
        for f in files:
            if f.lower().endswith(".lua"):
                out.append(os.path.relpath(os.path.join(dirpath, f), LUA_DIR).replace("\\", "/"))
    return sorted(out, key=str.lower)


class Game(Side):
    """A lua_harness Side ('sp', 'server' or 'client') with the fake world, the game's loader and the
    hang guard on every call from Python into its Lua."""

    def __init__(self, role, net=None, name=None, seed=11):
        self._depth = 0                               # nested entries (a require from a loading file)
        super().__init__(role, net, player=None, seed=seed)
        self.name = name or role
        g = self.L.globals()
        g.PY_PACKET = self._packet
        g.PY_REQUIRE = self._require
        self.L.execute(WORLD, BUDGET)
        self.L.execute("function require(name) return PY_REQUIRE(name) end")
        self.L.execute(SCRIPTS[0])
        self.paths, self.loaded, self.order, self.errors = [], [], [], []
        self.new_globals = []

    # -- every entry from Python runs armed
    def _armed(self, fn, *args):
        g = self.L.globals()
        self._depth += 1
        g.ARM()
        try:
            return fn(*args)
        finally:
            self._depth -= 1
            if self._depth == 0:
                g.DISARM()
            else:                                     # back in the outer call: a fresh budget, still armed
                g.ARM()

    def run(self, code):
        return self._armed(self.L.execute, code)

    def eval(self, expr):
        return self._armed(self.L.eval, expr)

    def trigger(self, name, *args):
        return self._armed(self.L.globals().triggerEvent, name, *args)

    def hangs(self):
        return self.L.eval("HANGS")

    def try_eval(self, expr):
        """(True, value) or (False, error text): a Lua error or a HANG is a result, not a crash."""
        h0 = self.hangs()
        try:
            v = self.eval(expr)
        except lua51.LuaError as exc:
            return False, str(exc).splitlines()[0][:200]
        if self.hangs() > h0:
            return False, "HANG (over %d instructions; a pcall in the mod swallowed the error)" % BUDGET
        return True, v

    def try_run(self, code):
        return self.try_eval("(function() %s\nreturn true end)()" % code)

    # -- the file system and the loader
    def _source(self, rel):
        low = rel.lower()
        for k, v in VANILLA.items():
            if k.lower() == low:
                return k, v
        for r in mod_files(rel.split("/")[0]):
            if r.lower() == low:
                with open(os.path.join(LUA_DIR, *r.split("/")), encoding="utf-8") as f:
                    return r, f.read()
        return None, None

    def run_lua(self, rel):
        if rel.lower() in self.loaded:               # RunLuaInternal: loaded once
            return None
        path, src = self._source(rel)
        if src is None:
            raise FileNotFoundError(rel)
        self.loaded.append(rel.lower())
        self.order.append(path)
        try:
            self.run_chunk(src, path)
        except lua51.LuaError as exc:                 # the game logs it and goes on
            self.errors.append("%s: %s" % (path, str(exc).splitlines()[0][:200]))
        return None

    def run_chunk(self, src, path):
        h0 = self.hangs()
        self._armed(self.L.execute, "local f, err = loadstring(..., %s); if not f then error(err) end; f()" % _lua("@" + path), src)
        if self.hangs() > h0:
            self.errors.append("%s: HANG at load" % path)

    def _require(self, name):
        n = name if name.lower().endswith(".lua") else name + ".lua"
        for folder in self.paths:
            path, src = self._source(folder + "/" + n)
            if src is not None:
                return self.run_lua(path)
        self.errors.append("require failed: %s (paths %s)" % (name, self.paths))
        return None

    def load_dir(self, folder, collect_only=False):
        if folder not in self.paths:
            self.paths.append(folder)
        if collect_only:                              # the dedicated server collects client/, runs none of it
            return
        for rel in sorted([k for k in VANILLA if k.split("/")[0] == folder], key=str.lower) + mod_files(folder):
            self.run_lua(rel)

    def boot(self):
        """The game's start-up for this side: files in order, then the start events, as 42.21 fires them."""
        self.L.execute("NEW_GLOBALS = {}; setmetatable(_G, { __newindex = function(t, k, v) "
                       "table.insert(NEW_GLOBALS, tostring(k)); rawset(t, k, v) end })")
        if self.role == "server":
            self.load_dir("shared")
            self.load_dir("client", collect_only=True)
            self.load_dir("server")
            self.trigger("OnGameBoot")
        else:
            self.load_dir("shared")
            self.load_dir("client")
            self.trigger("OnGameBoot")
            self.load_dir("server")
        for ev in ("OnPreDistributionMerge", "OnDistributionMerge", "OnPostDistributionMerge", "OnInitWorld",
                   "OnLoadMapZones", "OnLoadedMapZones"):
            self.trigger(ev)
        h0 = self.hangs()
        try:
            self.trigger("OnServerStarted" if self.role == "server" else "OnGameStart")
        except lua51.LuaError as exc:
            self.errors.append("start event: %s" % str(exc).splitlines()[0][:200])
        if self.hangs() > h0:
            self.errors.append("start event: HANG")
        self.new_globals = sorted(set(self.L.eval("NEW_GLOBALS").values()))
        self.run(SETUP)
        return self

    # -- the network
    def _packet(self, kind, vid, pid):
        if self.net is not None:
            self.net.packets.append((kind, vid, pid))


def _plain(value):
    if hasattr(value, "items") and callable(getattr(value, "items")):
        return {k: _plain(v) for k, v in value.items()}
    return value


class WorldNet(Net):
    """lua_harness.Net plus the part packets of this world (item, condition, window, mod data, removal)
    and cars streaming in to clients (VehicleFullUpdatePacket, then createPhysics' init hooks)."""

    def __init__(self):
        super().__init__()
        self.packets = []

    def stream_in(self, client, vid):
        sv = self.server.eval("VEHICLES")[vid]
        client.run("NEXT_VEHICLE = math.max(NEXT_VEHICLE, %d)" % (vid + 1))
        client.run("cv = buildVehicle(%s, %d, %r, %r); VEHICLES[%d] = cv" % (_lua(sv.script), vid, sv.x, sv.y, vid))
        cv = client.eval("cv")
        for pid in list(sv.order.values()):
            sp, cp = sv.parts[pid], cv.parts[pid]
            if sp.item is not None:                       # a fresh car: every model of a fitted part shows
                client.run("cv.parts[%s].item = newItem(%s); cv.parts[%s].visible = {}" % (_lua(pid), _lua(sp.item.ft), _lua(pid)))
                if cp.spec.allVisible is not False:
                    client.run("for _, m in ipairs(cv.parts[%s].models) do cv.parts[%s].visible[m] = true end" % (_lua(pid), _lua(pid)))
            cp.cond = sp.cond
            cp.md = client.table(_plain(sp.md))
            if sp.cont is not None:
                client.run("cv.parts[%s].cont = newContainer(%r)" % (_lua(pid), sp.cont.cap))
                for it in list(sp.cont.list.values()):
                    client.run("cv.parts[%s].cont:AddItem(newItem(%s, %r))" % (_lua(pid), _lua(it.ft), it.weight))
            if sp.win is not None:
                client.run("cv.parts[%s].win.open = %s" % (_lua(pid), "true" if sp.win.open else "false"))
            if sp.door is not None:
                client.run("cv.parts[%s].door.open = %s" % (_lua(pid), "true" if sp.door.open else "false"))
        client.run("createPhysics(cv)")
        return client.eval("cv")

    def stream_all(self):
        for c in self.clients:
            for vid in list(self.server.eval("VEHICLES").keys()):
                if c.eval("VEHICLES")[vid] is None:
                    self.stream_in(c, vid)

    def sync_item(self, vid, pid):
        """transmitPartItem: every client's part gets a fresh item of the same type (or none) and, like
        VehiclePart.setInventoryItem, shows its models."""
        sp = self.server.eval("VEHICLES")[vid].parts[pid]
        for c in self.clients:
            cv = c.eval("VEHICLES")[vid]
            if cv is not None:
                new = c.eval("newItem")(sp.item.ft) if sp.item is not None else None
                cv.parts[pid].setInventoryItem(cv.parts[pid], new)

    def pump(self):
        """Deliver everything; a Lua error or a hang in a handler is a FAIL, the queues are dropped."""
        try:
            return self._pump()
        except lua51.LuaError as exc:
            check(False, "network delivery ran without a Lua error (%s)" % str(exc).splitlines()[0][:200])
            self.to_server, self.to_clients, self.moddata, self.packets = [], [], [], []
            return 0

    def _pump(self):
        n = super().pump()
        while self.packets or self.to_server or self.to_clients:
            n += super().pump()
            while self.packets:
                kind, vid, pid = self.packets.pop(0)
                sv = self.server.eval("VEHICLES")[vid]
                for c in self.clients:
                    cv = c.eval("VEHICLES")[vid]
                    if kind == "remove":
                        if cv is not None:
                            c.run("VEHICLES[%d].removed = true; VEHICLES[%d] = nil" % (vid, vid))
                        continue
                    if cv is None or sv is None:
                        continue
                    sp, cp = sv.parts[pid], cv.parts[pid]
                    if kind == "moddata":
                        cp.md = c.table(_plain(sp.md))
                    elif kind == "cond":
                        cp.cond = sp.cond
                    elif kind == "window":
                        c.run("VEHICLES[%d].parts[%s].win.open = %s" % (vid, _lua(pid), "true" if sp.win.open else "false"))
                    elif kind == "door":
                        c.run("VEHICLES[%d].parts[%s].door.open = %s" % (vid, _lua(pid), "true" if sp.door.open else "false"))
                    elif kind == "item":
                        new = c.eval("newItem")(sp.item.ft) if sp.item is not None else None
                        cp.setInventoryItem(cp, new)
                n += 1
        return n


SCRIPTS = None                 # (lua, CR-V script names), filled in main()

# helpers every flow uses (after the start-up, so their globals are not counted as the mod's)
SETUP = r'''
function bare(v)
    for _, pid in ipairs(v.order) do
        if pid:find("^CRV") and pid ~= "CRVPicnicTable" then v.parts[pid]:setInventoryItem(nil) end
    end
    if HondaCRVGen1.Acc and HondaCRVGen1.Acc.watch then HondaCRVGen1.Acc.watch[v.id] = nil end
end
function kit(p)
    local inv = p:getInventory()
    for _, t in ipairs({ "Base.Wrench", "Base.LugWrench", "Base.Jack", "Base.Screwdriver", "Base.PaintBlue",
                         "Base.CRVGen1_ArmourDoorFront", "Base.CRVGen1_ArmourMeshFront", "Base.CRVGen1_RoofRack",
                         "Base.JerryCan", "Base.CRVGen1_LiftKit", "Base.CRVGen1_OffroadSnorkel",
                         "Base.CRVGen1_Awning" }) do inv:AddItem(t) end
    p.perks.Mechanics = 6
end
function install(p, v, pid, ft)
    local item = p:getInventory():getFirstTypeRecurse(ft)
    assert(item, "no " .. ft)
    local a = ISInstallVehiclePart:new(p, v.parts[pid], item, 100)
    local ok, valid = guarded(function() return a:isValid() end)
    local done = a:complete()
    return ok and valid, done
end
function vis(v, pid) return v.parts[pid]:visibleList() end
-- every part's install and uninstall test on a car, guarded one by one: {pid = "HANG" | "ERR ..." | answer}
function allTests(v, chr)
    local out = {}
    for _, pid in ipairs(v.order) do
        local p = v.parts[pid]
        for _, which in ipairs({ "install", "uninstall" }) do
            local t = p:getTable(which)
            if t and t.test then
                local ok, res = guarded(VehicleUtils.callLua, t.test, v, p, chr)
                out[which .. ":" .. pid] = (res == "HANG" and "HANG") or (ok and tostring(res)) or ("ERR " .. tostring(res))
            end
        end
    end
    return out
end
'''


# --------------------------------------------------------------------------------- the flows
def side_clean(g):
    check(g.errors == [], "%s: every file loads and the start events run without a Lua error or a hang (%s)"
          % (g.name, "; ".join(g.errors)))
    stray = [n for n in g.new_globals if n not in MOD_GLOBALS and n not in VANILLA_GLOBALS]
    check(stray == [], "%s: no stray globals at load (%s)" % (g.name, stray))


def tests_return(g, car, chr, label):
    """Every install / uninstall test of every part returns; for the CR-V the answers are reported."""
    res = dict(g.eval("allTests(%s, %s)" % (car, chr)).items())
    hung = sorted(k for k, v in res.items() if v == "HANG")
    err = sorted("%s %s" % (k, v) for k, v in res.items() if v.startswith("ERR"))
    check(not hung, "%s: all %d part tests return (%d hang: %s)" % (label, len(res), len(hung), ", ".join(hung[:8])
                                                                     + (" ..." if len(hung) > 8 else "")))
    check(not err, "%s: no part test raises (%s)" % (label, "; ".join(err[:4])))
    return res


ACTION_ARGS = {"character": "PLAYER", "vehicle": "v", "slot": "'side'", "variant": "'retro_blue'", "target": "'alloy'",
               "on": "true"}
# globals the flows themselves set (everything else a mod file creates while playing is a stray global)
TEST_GLOBALS = {"PLAYER", "suv", "v", "tmp", "ctx", "d", "f", "lf", "oldId", "old", "lc", "n", "ACT", "cv", "vid",
                "bare", "kit", "install", "vis", "allTests", "C", "L", "CABIN_SUV"}


def action_params(g):
    """Each ISCRV* action keeps every new() parameter in a field of the same name: in 42.21 multiplayer
    the server rebuilds the action from the client's object by those names before complete()."""
    for dirpath, _d, files in os.walk(os.path.join(LUA_DIR, "shared", "TimedActions")):
        for f in sorted(files):
            if not f.startswith("ISCRV") or not f.endswith(".lua"):
                continue
            src = open(os.path.join(dirpath, f), encoding="utf-8").read()
            m = re.search(r"function\s+(ISCRV\w+):new\(([^)]*)\)", src)
            if not m:
                check(False, "%s: a :new( constructor" % f)
                continue
            cls, params = m.group(1), [p.strip() for p in m.group(2).split(",") if p.strip()]
            args = [ACTION_ARGS.get(p, _lua("sentinel_" + p)) for p in params]
            ok, r = g.try_run("ACT = %s:new(%s)" % (cls, ", ".join(args)))
            if not check(ok, "%s:new(%s) runs (%s)" % (cls, ", ".join(params), "" if ok else r)):
                continue
            missing = [p for p, a in zip(params, args) if not g.eval("ACT[%s] == %s" % (_lua(p), a))]
            check(not missing, "%s keeps its new() parameters as fields of the same names (missing: %s)" % (cls, missing))
            g.run("ACT = nil")


def radial_menus(g):
    """The outside radial menu (V) and Project Viewpoint's quick-interact list, which harvests it through a stand-in
    menu: every wrapper of every feature chained over vanilla's showRadialMenuOutside; on the CR-V each slice is
    a context-menu option (same text, handler, arguments; blocked = greyed), picking one queues the same action."""
    g.run("RADIAL = newRadial(); RADIAL_TARGET = suv")
    ok, r = g.try_run("ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(ok and g.eval("RADIAL:texts()") == "VANILLA_MECHANICS" and g.eval("RADIAL.shown") is True,
          "radial on a vanilla car: the game's slices only, shown (%s, %s)" % (r, g.eval("RADIAL:texts()")))
    g.run("RADIAL = newRadial(); RADIAL_TARGET = v")
    ok, r = g.try_run("ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    texts = g.eval("RADIAL:texts()") if ok else ""
    print("     CR-V radial:", texts)
    slices = texts.split(",")
    check(ok and slices[:1] == ["VANILLA_MECHANICS"] and slices.count("VANILLA_MECHANICS") == 1,
          "radial on the CR-V: the game's slices first, once (%s)" % r)
    check(any(s.startswith("ContextMenu_CRV_FoldBed") for s in slices)
          and any(s.startswith("ContextMenu_CRV_Function_LiftFloor") for s in slices)
          and any(s.startswith("ContextMenu_CRV_TakeTable") for s in slices),
          "the fold-bed, cargo floor and picnic table slices are all on the CR-V's radial")
    check(g.eval("(function() for _, s in ipairs(RADIAL.slices) do if not s.texture then return false end end return true end)()"),
          "every slice has an icon")
    g.run("ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false)")
    matched, missing = g.eval("radialVsMenu(RADIAL, ctx)")
    check(missing == "" and matched == len(slices) - 1,
          "each CR-V slice is its context-menu option: text, handler, arguments, availability (%d matched; without: %s)"
          % (matched, missing))
    n = g.eval("#RADIAL.slices")
    ok, r = g.try_run("ISVehicleMenu.showRadialMenuOutside(PLAYER)")
    check(ok and g.eval("RADIAL.shown") is False and g.eval("#RADIAL.slices") == n, "V again closes the menu, adds nothing (%s)" % r)
    g.run("RADIAL_TARGET = false")
    # Project Viewpoint: the same slices through its stand-in, and picking one queues what the context option queues
    ok, r = g.try_eval("viewpointRadial(PLAYER, v):texts()")
    check(ok and r == texts, "Project Viewpoint's harvest sees the same slices (%s)" % r)
    ok, r = g.try_eval("viewpointRadial(PLAYER, suv):texts()")
    check(ok and r == "VANILLA_MECHANICS", "Project Viewpoint on a vanilla car: the game's slices only (%s)" % r)
    g.run("QUEUE = {}")
    ok, r = g.try_run("local m = viewpointRadial(PLAYER, v); m:pick(m:find('ContextMenu_CRV_FoldBed'))")
    by_slice = g.eval("queued()")
    g.run("QUEUE = {}")
    g.run("for _, o in ipairs(ctx.options) do if o.name == 'ContextMenu_CRV_FoldBed' then "
          "o.onSelect(o.target, o.param1, o.param2, o.param3, o.param4) end end")
    by_option = g.eval("queued()")
    check(ok and by_slice != "" and by_slice == by_option and "ISCRVFoldSeats" in by_slice,
          "the fold-bed slice queues what the option does (%s; option: %s; %s)" % (by_slice, by_option, r))
    g.run("QUEUE = {}; PLAYER.vehicle = v")
    ok, r = g.try_eval("viewpointRadial(PLAYER, v):texts()")
    check(ok and r == "", "from inside the car: no outside radial (%s)" % r)
    g.run("PLAYER.vehicle = nil")


BAY_TICKS = {"grace": 4000 // 16 + 2, "hold": 3000 // 16 + 2}     # HondaCRVGen1.Bay.OPEN_GRACE / CLOSE_HOLD in frames


def engine_bay_sp(g):
    """The engine bay (HondaCRVGen1_EngineBay.lua) in the game's load order, single player: the stand-in on a shut
    hood, the bay from the moment the open action starts, held while the hood swings shut, shown with the hood off."""
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "engine bay: a new CR-V with the hood shut shows the "
          "stand-in (%s)" % g.eval("vis(v, 'CRVEngineBay')"))
    check(g.eval("rawget(ISOpenVehicleDoor, 'HondaCRVGen1BayWrapped')") is True, "engine bay: ISOpenVehicleDoor:start wrapped once")
    g.run("ANIMS = {}; ACT = ISOpenVehicleDoor:new(PLAYER, v, v.parts.EngineDoor)")
    ok, r = g.try_run("ACT:start()")
    check(ok and g.eval("ANIMS[1]") == "EngineDoor:Open", "engine bay: the wrapped start still plays the Open clip (%s)" % r)
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "engine bay: shown as the hood starts opening, before complete()")
    g.try_run("TICK(%d)" % BAY_TICKS["grace"])
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "engine bay: an open that never completed falls back to the stand-in")
    ok, r = g.try_run("ACT:start(); TICK(5); ACT:complete(); TICK(%d)" % BAY_TICKS["grace"])
    check(ok and g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "engine bay: shown while the hood is open (%s)" % r)
    g.try_run("v.parts.EngineDoor.door.open = false; TICK(10)")
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "engine bay: still shown while the hood swings shut")
    g.try_run("PAUSED = true; TICK(%d)" % (2 * BAY_TICKS["hold"]))
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "engine bay: the hold does not run out while the game is paused")
    g.try_run("PAUSED = false; TICK(%d)" % BAY_TICKS["hold"])
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "engine bay: the stand-in once the hood is down")
    g.try_run("v.parts.EngineDoor:setInventoryItem(nil); TICK(1)")
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "engine bay: shown with the hood removed")
    g.try_run("v.parts.EngineDoor:setInventoryItem(newItem('Base.EngineDoor1')); TICK(%d)" % BAY_TICKS["hold"])
    check(g.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "engine bay: the stand-in again with a shut hood refitted")
    calls = g.eval("v.parts.CRVEngineBay.calls")
    g.try_run("TICK(50)")
    check(g.eval("v.parts.CRVEngineBay.calls") == calls, "engine bay: idle ticks call no setModelVisible")
    g.run("ANIMS = {}")
    ok, r = g.try_run("ACT = ISOpenVehicleDoor:new(PLAYER, suv, suv.parts.EngineDoor); ACT:start(); ACT:complete(); TICK(2)")
    check(ok and g.eval("ANIMS[1]") == "EngineDoor:Open" and g.eval("suv.parts.EngineDoor.door.open") is True,
          "engine bay: a vanilla car's hood opens as before (%s)" % r)
    g.run("suv.parts.EngineDoor.door.open = false; ACT = nil")


CABIN_SHOWN = "Interior,InteriorCabin"


def _cabin_owner(g, var):
    """Every part of the car whose models include the cabin's two (the script must put them on CRVCabin alone)."""
    return g.eval("(function() local t = {} for _, pid in ipairs(%s.order) do for _, m in ipairs(%s.parts[pid].models) do "
                  "if m == 'Interior' or m == 'InteriorCabin' then t[#t + 1] = pid .. '.' .. m end end end "
                  "return table.concat(t, ',') end)()" % (var, var))


def cabin_sp(g):
    """The cabin (HondaCRVGen1_Cabin.lua; round 5 bug: taking the glove box out hid the interior). The interior and
    the cabin furniture are drawn on every CR-V from its init, whatever is installed or removed: the glove box
    taken out by the vanilla uninstall action (and put back), every removable part off at once (bare)."""
    check(_cabin_owner(g, "v") == "CRVCabin.Interior,CRVCabin.InteriorCabin",
          "cabin: the interior models sit on part CRVCabin alone (%s)" % _cabin_owner(g, "v"))
    check(g.eval("v.parts.CRVCabin.spec.itemType") is None and g.eval("v.parts.CRVCabin.spec.allVisible") is False,
          "cabin: CRVCabin has no item and setAllModelsVisible = false")
    check(g.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN, "cabin: a new CR-V draws the interior and the cabin (%s)"
          % g.eval("vis(v, 'CRVCabin')"))
    ok, r = g.try_eval("(function() local a = ISUninstallVehiclePart:new(PLAYER, v.parts.GloveBox, 100) "
                       "return a:complete() end)()")
    check(ok and g.eval("v.parts.GloveBox:getInventoryItem()") is None,
          "cabin: the glove box comes out by the uninstall action (%s)" % r)
    check(g.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN, "cabin: still drawn with the glove box out (%s)"
          % g.eval("vis(v, 'CRVCabin')"))
    g.run("createPhysics(v)")
    check(g.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN, "cabin: drawn when the car is reloaded without its glove box")
    ok, r = g.try_eval("{install(PLAYER, v, 'GloveBox', 'Base.GloveBox1')}")
    check(ok and g.eval("v.parts.GloveBox:getInventoryItem()") is not None and g.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN,
          "cabin: the glove box goes back in, the cabin unchanged (%s)" % (dict(r) if ok else r))
    g.run("C = createVehicle('Base.HondaCRVGen1', 30.5, 30.5, true); for _, pid in ipairs(C.order) do "
          "if C.parts[pid]:getInventoryItem() then C.parts[pid]:setInventoryItem(nil) end end; createPhysics(C)")
    check(g.eval("vis(C, 'CRVCabin')") == CABIN_SHOWN, "cabin: drawn on a car with every removable part gone (%s)"
          % g.eval("vis(C, 'CRVCabin')"))
    for name in SCRIPTS[1]:
        ok, r = g.try_run("L = createVehicle('%s', 32.5, 32.5, true)" % name)
        check(ok and g.eval("vis(L, 'CRVCabin')") == CABIN_SHOWN, "cabin: %s draws it (%s)" % (name, r))
    ok, r = g.try_run("CABIN_SUV = createVehicle('Base.SUV', 34.5, 34.5, true); HondaCRVGen1.Cabin.Init(CABIN_SUV, nil)")
    check(ok, "cabin: Init on a car without the part does nothing (%s)" % r)
    g.run("C = nil; L = nil; CABIN_SUV = nil")


def cabin_mp(net, S, A, B):
    """The cabin in multiplayer: the dedicated server draws nothing; every client draws it on the streamed-in car
    and keeps it when the server completes a glove box removal and syncs the item."""
    check(S.eval("v.parts.CRVCabin.calls") == 0, "server: cabin: the dedicated server draws nothing")
    for c in (A, B):
        check(c.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN, "%s: cabin: a streamed-in CR-V draws it (%s)"
              % (c.name, c.eval("vis(v, 'CRVCabin')")))
    S.run("v.parts.GloveBox:setInventoryItem(nil); v:transmitPartItem(v.parts.GloveBox)")
    net.pump()
    for c in (A, B):
        c.try_run("TICK(2)")
        check(c.eval("v.parts.GloveBox:getInventoryItem()") is None and c.eval("vis(v, 'CRVCabin')") == CABIN_SHOWN,
              "%s: cabin: still drawn after the server took the glove box out" % c.name)


def engine_bay_mp(net, S, A, B):
    """The engine bay in multiplayer: nothing drawn on the dedicated server; each client follows the synced door
    and item, and the client whose player opens the hood shows the bay at the action's start."""
    for c in (A, B):
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "%s: engine bay: a streamed-in CR-V shows the stand-in" % c.name)
    check(S.eval("v.parts.CRVEngineBay.calls") == 0, "server: engine bay: the dedicated server draws nothing")
    ok, r = A.try_run("ACT = ISOpenVehicleDoor:new(PLAYER, v, v.parts.EngineDoor); ACT:start()")
    check(ok and A.eval("vis(v, 'CRVEngineBay')") == "EngineBay" and B.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow",
          "engine bay: alice starts opening the hood: her client shows the bay at once, bob's not yet (%s)" % r)
    ok, r = S.try_run("ACT = ISOpenVehicleDoor:new(PLAYERS.alice, v, v.parts.EngineDoor); ACT:start(); ACT:complete(); ACT = nil")
    check(ok and S.eval("v.parts.CRVEngineBay.calls") == 0, "server: the open completes, still nothing drawn (%s)" % r)
    net.pump()
    for c in (A, B):
        c.try_run("TICK(1)")
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "%s: engine bay shown once the open door is synced" % c.name)
    S.run("v.parts.EngineDoor.door.open = false; v:transmitPartDoor(v.parts.EngineDoor)")
    net.pump()
    for c in (A, B):
        c.try_run("TICK(10)")
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "%s: engine bay held while the hood swings shut" % c.name)
        c.try_run("TICK(%d)" % BAY_TICKS["hold"])
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "%s: the stand-in once the hood is down" % c.name)
    S.run("v.parts.EngineDoor:setInventoryItem(nil); v:transmitPartItem(v.parts.EngineDoor)")
    net.pump()
    for c in (A, B):
        c.try_run("TICK(1)")
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBay", "%s: engine bay shown with the hood removed" % c.name)
    S.run("v.parts.EngineDoor:setInventoryItem(newItem('Base.EngineDoor1')); v:transmitPartItem(v.parts.EngineDoor)")
    net.pump()
    for c in (A, B):
        c.try_run("TICK(%d)" % BAY_TICKS["hold"])
        check(c.eval("vis(v, 'CRVEngineBay')") == "EngineBayLow", "%s: the stand-in with the hood refitted, shut" % c.name)
        c.run("ACT = nil")


def single_player():
    print("\n=== single player: every file loaded in the game's order, OnGameStart")
    g = Game("sp").boot()
    side_clean(g)
    for ev in ("OnTick", "OnServerCommand", "OnClientCommand", "OnGameStart", "OnServerStarted", "OnSpawnVehicleEnd"):
        print("     %s handlers: %d" % (ev, g.eval("countHandlers(%r)" % ev)))
    g.run("PLAYER = newPlayer('tester', 101, 100); kit(PLAYER); PLAYER.area = 'SeatFrontLeft'")
    g.run("suv = createVehicle('Base.SUV', 40.5, 40.5, true)")
    g.run("v = createVehicle('Base.HondaCRVGen1', 100.5, 100.5, true)")
    # the tests of every part, fitted (spawn roll) and bare, CR-V and vanilla car, before anything else
    tests_return(g, "suv", "PLAYER", "vanilla SUV")
    tests_return(g, "v", "PLAYER", "CR-V as spawned")
    for script in SCRIPTS[1]:
        g.run("tmp = createVehicle(%s, 60.5, 60.5, true)" % _lua(script))
        tests_return(g, "tmp", "PLAYER", "%s as spawned" % script)
        g.run("tmp:permanentlyRemove(); tmp = nil")
    g.run("bare(v)")
    tests_return(g, "v", "PLAYER", "bare CR-V")
    ok, r = g.try_eval("{guarded(Vehicles.UninstallTest.Default, suv, suv.parts.TireFrontLeft, PLAYER)}")
    check(ok and r[1] is True and r[2] is True, "vanilla SUV tyre: Vehicles.UninstallTest.Default returns true (%s)"
          % (dict(r) if ok else r))
    check(g.eval("VANILLA_UNINSTALL_CALLS") > 0, "the uninstall chain reaches vanilla's Default")
    # menus
    g.run("ctx = newCtx(); VANILLA_OUTSIDE = 0")
    ok, r = g.try_run("ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, suv, false)")
    check(ok and g.eval("VANILLA_OUTSIDE") == 1 and g.eval("#ctx.options") == 1, "outside menu on a vanilla car: vanilla only, once (%s)" % r)
    g.run("ctx = newCtx(); VANILLA_OUTSIDE = 0")
    ok, r = g.try_run("ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v, false)")
    names = [o.name for o in g.eval("ctx.options").values()] if ok else []
    print("     CR-V outside menu:", names)
    check(ok and g.eval("VANILLA_OUTSIDE") == 1, "outside menu on the CR-V: vanilla once (%s)" % r)
    check(names[:1] == ["VANILLA_WASH"] and "ContextMenu_CRV_Lift_Menu" in names
          and "ContextMenu_CRV_FoldBed" in names and "ContextMenu_CRV_Function_LiftFloor" in names,
          "the cargo floor, lift and fold-bed options are all on the CR-V's menu")
    check(g.eval("(guarded(VehicleUtils.createPartInventoryItem, suv.parts.Battery))") is True,
          "createPartInventoryItem wrapper passes a vanilla car through")
    missing = [s for s in SCRIPTS[1] if not g.eval("ISCarMechanicsOverlay.CarList[%s] ~= nil" % _lua(s))]
    check(not missing, "every CR-V script has its mechanics overlay (missing: %s)" % missing)
    # picking the fold-bed option queues its action (the menu's callbacks run, nothing raises)
    g.run("QUEUE = {}")
    ok, r = g.try_run("for _, o in ipairs(ctx.options) do if o.name == 'ContextMenu_CRV_FoldBed' and o.onSelect then "
                      "o.onSelect(o.target, o.param1, o.param2, o.param3, o.param4) end end")
    check(ok and g.eval("#QUEUE") >= 1, "the fold-bed option queues an action (%s, %s queued)" % (r, g.eval("#QUEUE")))
    g.run("QUEUE = {}")
    radial_menus(g)
    action_params(g)
    engine_bay_sp(g)
    cabin_sp(g)

    # armour plate + window mesh
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVArmourDoorFrontLeft', 'Base.CRVGen1_ArmourDoorFront')}")
    check(ok and r[1] is True and r[2] is True, "armour door plate installs (%s)" % (dict(r) if ok else r))
    check(g.eval("HondaCRVGen1.Acc.watch[v.id] ~= nil"), "the plate is watched by the protection loop")
    g.run("v.parts.WindowFrontLeft.win.open = true")
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront')}")
    check(ok and r[1] is True and r[2] is True, "window mesh installs (%s)" % (dict(r) if ok else r))
    check(g.eval("vis(v, 'CRVGuardFrontLeft')") == "ArmourMesh", "the mesh variant shows only the mesh (%s)" % g.eval("vis(v, 'CRVGuardFrontLeft')"))
    check(g.eval("v.parts.WindowFrontLeft.win.open") is False, "the window under the mesh was shut")
    ok, r = g.try_eval("ISOpenCloseVehicleWindow:new(PLAYER, v.parts.WindowFrontLeft, true):isValid()")
    check(ok and r is False, "the armoured window cannot be opened (%s)" % r)
    # rack, cargo, roof can, snorkel
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVRoofRack', 'Base.CRVGen1_RoofRack')}")
    check(ok and r[1] is True and r[2] is True, "roof rack installs (%s)" % (dict(r) if ok else r))
    g.run("v.parts.CRVRoofRack.cont:AddItem(newItem('Base.Duffel', 20))")
    g.try_run("TICK(15)")
    check(g.eval("HondaCRVGen1.State.get(v, 'acc_rackLoad')") == 2, "rack cargo state 2 for a 40 % load")
    g.run("PLAYER:getInventory():getFirstTypeRecurse('Base.JerryCan'):getFluidContainer():addFluid('Petrol', 9)")
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVOffroadCanRoof', 'Base.JerryCan')}")
    check(ok and r[1] is True and r[2] is True, "roof jerry can installs on the rack (%s)" % (dict(r) if ok else r))
    check(g.eval("vis(v, 'CRVRoofRack')") == "CRVRoofRack,RackLoad2", "the rack shows basket + load 2 (%s)" % g.eval("vis(v, 'CRVRoofRack')"))
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVOffroadSnorkel', 'Base.CRVGen1_OffroadSnorkel')}")
    check(ok and r[1] is True and r[2] is True, "snorkel installs (%s)" % (dict(r) if ok else r))
    # the interlocks, through the whole Default chain (offroad and armour wrappers)
    ok, r = g.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.CRVRoofRack, PLAYER)}")
    check(ok and r[1] is True and r[2] is False, "the rack cannot come off under the roof can (%s)" % (dict(r) if ok else r))
    ok, r = g.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.DoorFrontLeft, PLAYER)}")
    check(ok and r[1] is True and r[2] is False, "the plated door cannot come off (%s)" % (dict(r) if ok else r))
    ok, r = g.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.CRVOffroadSnorkel, PLAYER)}")
    check(ok and r[1] is True and r[2] is True, "the snorkel can come off (%s)" % (dict(r) if ok else r))
    ok, r = g.try_eval("(function() local a = ISUninstallVehiclePart:new(PLAYER, v.parts.CRVOffroadSnorkel, 100) "
                       "return a:isValid() and a:complete() end)()")
    if check(ok and r is True, "the snorkel uninstall action runs end to end (%s)" % r):
        ok, r = g.try_eval("{install(PLAYER, v, 'CRVOffroadSnorkel', 'Base.CRVGen1_OffroadSnorkel')}")
        check(ok and r[2] is True, "and goes back on (%s)" % (dict(r) if ok else r))
    # the side awning: fitted rolled up (the bag alone), rolled out by its action (canopy and poles), on the menus
    ok, r = g.try_eval("{install(PLAYER, v, 'CRVAwning', 'Base.CRVGen1_Awning')}")
    check(ok and r[1] is True and r[2] is True, "awning installs (%s)" % (dict(r) if ok else r))
    check(g.eval("vis(v, 'CRVAwning')") == "CRVAwning", "the awning fitted: the bag alone (%s)" % g.eval("vis(v, 'CRVAwning')"))
    g.run("ctx = newCtx(); ISVehicleMenu.FillMenuOutsideVehicle(0, ctx, v)")
    check(any(o == "ContextMenu_CRV_Awning_Deploy" for o in g.eval("(function() local t = {} for i, o in ipairs(ctx.options) do "
                                                                   "t[i] = o.name end return t end)()").values()),
          "the outside menu offers rolling it out")
    g.run("ACT = ISCRVAwning:new(PLAYER, v, true)")
    ok, r = g.try_eval("ACT:isValid() and ACT:complete() and HondaCRVGen1.Awning.isDeployed(v)")
    check(ok and r is True, "awning rolled out (%s)" % r)
    check(g.eval("vis(v, 'CRVAwning')") == "CRVAwning,AwningCanopy,AwningPoles", "rolled out: bag, canopy, poles (%s)"
          % g.eval("vis(v, 'CRVAwning')"))
    g.run("ACT = nil")
    # fold seats, cargo, floor
    g.run("f = ISCRVFoldSeats:new(PLAYER, v, true)")
    ok, r = g.try_eval("f:isValid() and f:complete() and HondaCRVGen1.Shared.isBed(v)")
    check(ok and r is True, "rear seats folded (%s)" % r)
    g.run("v.parts.CRVFunctionCargo.cont:AddItem(newItem('Base.Tent', 8))")
    g.run("v.parts.TrunkDoor.door.open = true; lf = ISCRVFunctionLiftFloor:new(PLAYER, v)")
    ok, r = g.try_eval("lf:isValid() and lf:complete()")
    check(ok and r is True, "cargo floor lifted (%s)" % r)
    g.run("v.parts.CRVFunctionUnderfloor.cont:AddItem(newItem('Base.FirstAidKit', 1)); v.parts.TrunkDoor.door.open = false")
    ok, r = g.try_eval("ISEnterVehicle:new(PLAYER, v, 2):isValid()")
    check(ok and r is False, "nobody sits on the folded bench (%s)" % r)
    # a lift conversion that carries everything
    g.run("oldId = v.id; old = v; lc = ISCRVLiftConvert:new(PLAYER, v, 'alloy')")
    ok, r = g.try_eval("lc:isValid()")
    check(ok and r is True, "lift conversion is valid (%s)" % r)
    ok, r = g.try_eval("(function() local ok = lc:complete(); n = nil; for id, x in pairs(VEHICLES) do "
                       "if x.script == 'Base.HondaCRVGen1LiftAlloy' then n = x end end; return ok end)()")
    check(ok and r is True and g.eval("n ~= nil") and g.eval("old.removed") is True, "converted to the lifted alloy car (%s)" % r)
    if not g.eval("n ~= nil"):
        return g
    for pid, ft in (("CRVArmourDoorFrontLeft", "Base.CRVGen1_ArmourDoorFront"), ("CRVGuardFrontLeft", "Base.CRVGen1_ArmourMeshFront"),
                    ("CRVRoofRack", "Base.CRVGen1_RoofRack"), ("CRVOffroadCanRoof", "Base.JerryCan"),
                    ("CRVOffroadSnorkel", "Base.CRVGen1_OffroadSnorkel"), ("CRVAwning", "Base.CRVGen1_Awning")):
        check(g.eval("n.parts.%s.item and n.parts.%s.item.ft" % (pid, pid)) == ft, "lifted car: %s carried" % pid)
    check(g.eval("vis(n, 'CRVAwning')") == "CRVAwning,AwningCanopy,AwningPoles", "lifted car: the awning still out (%s)"
          % g.eval("vis(n, 'CRVAwning')"))
    check(g.eval("n.parts.CRVOffroadCanRoof.item:getFluidContainer():getAmount()") == 9, "lifted car: the roof can keeps its petrol")
    check(g.eval("vis(n, 'CRVGuardFrontLeft')") == "ArmourMesh", "lifted car: mesh only (%s)" % g.eval("vis(n, 'CRVGuardFrontLeft')"))
    check(g.eval("vis(n, 'CRVRoofRack')") == "CRVRoofRack,RackLoad2", "lifted car: rack load 2 (%s)" % g.eval("vis(n, 'CRVRoofRack')"))
    check(g.eval("vis(n, 'CRVEngineBay')") == "EngineBayLow", "lifted car: the engine bay's stand-in (%s)" % g.eval("vis(n, 'CRVEngineBay')"))
    check(g.eval("HondaCRVGen1.Shared.isBed(n)") is True and g.eval("n.parts.CRVFunctionCargo.cont:count()") == 1,
          "lifted car: folded, the load floor's cargo kept")
    check(g.eval("HondaCRVGen1.Function.isFloorFound(n)") is True and g.eval("n.parts.CRVFunctionUnderfloor.cont:count()") == 1,
          "lifted car: floor found, the under-floor contents kept")
    tests_return(g, "n", "PLAYER", "lifted car")
    g.try_run("TICK(3); n.parts.DoorFrontLeft.cond = 60; TICK(3)")
    check(g.eval("n.parts.DoorFrontLeft.cond") == 100, "lifted car: the plate still takes the door's damage")
    g.try_run("TICK(30)")
    # the cleanups run every few ticks (Acc.OnTickRack, State.poll); run their passes here rather than
    # depend on where the tick counters fall
    g.try_run("for i = 1, 300 do HondaCRVGen1.Acc.OnTickRack() end; HondaCRVGen1.State.poll()")
    check(g.eval("HondaCRVGen1.Acc.watch[oldId]") is None and g.eval("HondaCRVGen1.Acc.racks[oldId]") is None
          and g.eval("HondaCRVGen1.State.tracked[oldId]") is None, "the old car left the watch / rack / State tables")
    end_of_flow(g)
    return g


def end_of_flow(g):
    check(g.hangs() == 0, "%s: no call ran over the instruction budget (%d did)" % (g.name, g.hangs()))
    errs = list(g.eval("JAVA_ERRORS").values())
    check(errs == [], "%s: no Lua error inside a Java-side part test (%s)" % (g.name, errs[:3]))
    made = sorted(set(g.eval("NEW_GLOBALS").values()) - set(g.new_globals) - TEST_GLOBALS)
    check(made == [], "%s: no global created while playing (%s)" % (g.name, made))


def multiplayer():
    print("\n=== dedicated server + two clients")
    net = WorldNet()
    S = Game("server", net, "server").boot()
    A = Game("client", net, "alice").boot()
    B = Game("client", net, "bob").boot()
    for side in (S, A, B):
        side_clean(side)
    S.run("PLAYER = newPlayer('alice', 101, 100); kit(PLAYER); PLAYERS.bob = newPlayer('bob', 99, 100)")
    A.run("PLAYER = newPlayer('alice', 101, 100); kit(PLAYER)")
    B.run("PLAYER = newPlayer('bob', 99, 100)")
    S.run("suv = createVehicle('Base.SUV', 40.5, 40.5, true); v = createVehicle('Base.HondaCRVGen1', 100.5, 100.5, true); vid = v.id")
    net.pump()
    net.stream_all()
    for c in (A, B):
        c.run("v = VEHICLES[%d]; suv = VEHICLES[%d]" % (S.eval("vid"), S.eval("suv.id")))
    # the mechanics window asks on the client, the action's isValid runs again on the server
    for side in (S, A, B):
        tests_return(side, "suv", "PLAYER", "%s: vanilla SUV" % side.name)
        tests_return(side, "v", "PLAYER", "%s: CR-V as spawned" % side.name)
    engine_bay_mp(net, S, A, B)
    cabin_mp(net, S, A, B)
    S.run("bare(v)")
    net.pump()
    for pid in list(S.eval("v.order").values()):
        if pid.startswith("CRV"):
            net.sync_item(S.eval("vid"), pid)
    for c in (A, B):
        c.try_run("TICK(30)")
    # what each client's action asks, the server completes (the action rebuilt from its new() fields)
    for code in ("install(PLAYER, v, 'CRVArmourDoorFrontLeft', 'Base.CRVGen1_ArmourDoorFront')",
                 "install(PLAYER, v, 'CRVGuardFrontLeft', 'Base.CRVGen1_ArmourMeshFront')",
                 "install(PLAYER, v, 'CRVRoofRack', 'Base.CRVGen1_RoofRack')",
                 "PLAYER:getInventory():getFirstTypeRecurse('Base.JerryCan'):getFluidContainer():addFluid('Petrol', 9)",
                 "install(PLAYER, v, 'CRVOffroadCanRoof', 'Base.JerryCan')",
                 "v.parts.CRVRoofRack.cont:AddItem(newItem('Base.Duffel', 20)); TICK(15)",
                 "f = ISCRVFoldSeats:new(PLAYER, v, true); f:complete()",
                 "v.parts.TrunkDoor.door.open = true; lf = ISCRVFunctionLiftFloor:new(PLAYER, v); lf:complete(); "
                 "v.parts.TrunkDoor.door.open = false",
                 "install(PLAYER, v, 'CRVAwning', 'Base.CRVGen1_Awning')",
                 "ACT = ISCRVAwning:new(PLAYER, v, true); ACT:complete(); ACT = nil"):
        ok, r = S.try_run(code)
        check(ok, "server: %s (%s)" % (code.split("(")[0] + "(...)", r))
    net.pump()
    for c in (A, B):
        c.try_run("TICK(30)")
    for c in (A, B):
        check(c.eval("vis(v, 'CRVGuardFrontLeft')") == "ArmourMesh", "%s: the mesh only, after the poll (%s)" % (c.name, c.eval("vis(v, 'CRVGuardFrontLeft')")))
        check(c.eval("vis(v, 'CRVRoofRack')") == "CRVRoofRack,RackLoad2", "%s: rack load 2 (%s)" % (c.name, c.eval("vis(v, 'CRVRoofRack')")))
        check(c.eval("HondaCRVGen1.Shared.isBed(v)") is True and c.eval("HondaCRVGen1.Function.isFloorFound(v)") is True,
              "%s: folded, floor found" % c.name)
        check(c.eval("vis(v, 'CRVAwning')") == "CRVAwning,AwningCanopy,AwningPoles", "%s: the awning drawn rolled out (%s)"
              % (c.name, c.eval("vis(v, 'CRVAwning')")))
        ok, r = c.try_eval("viewpointRadial(PLAYER, v):texts()")
        check(ok and "ContextMenu_CRV_UnfoldBed" in r and "ContextMenu_CRV_FoldBed" not in r and "LiftFloor" not in r,
              "%s: the radial follows the synced state: put the seats back, no floor to lift (%s)" % (c.name, r))
        ok, r = c.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.CRVRoofRack, PLAYER)}")
        check(ok and r[1] is True and r[2] is False, "%s: the rack is locked under the roof can (%s)" % (c.name, dict(r) if ok else r))
        ok, r = c.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.DoorFrontLeft, PLAYER)}")
        check(ok and r[1] is True and r[2] is False, "%s: the plated door is locked (%s)" % (c.name, dict(r) if ok else r))
    ok, r = S.try_eval("{guarded(Vehicles.UninstallTest.Default, v, v.parts.DoorFrontLeft, PLAYER)}")
    check(ok and r[1] is True and r[2] is False, "server: the plated door is locked (%s)" % (dict(r) if ok else r))
    # the lift on the server; the new car streams to both clients
    S.run("lc = ISCRVLiftConvert:new(PLAYER, v, 'steel')")
    ok, r = S.try_eval("lc:isValid()")
    check(ok and r is True, "server: the conversion is valid (%s)" % r)
    ok, r = S.try_eval("(function() local ok = lc:complete(); n = nil; for id, x in pairs(VEHICLES) do "
                       "if x.script == 'Base.HondaCRVGen1LiftSteel' then n = x end end; return ok end)()")
    check(ok and r is True and S.eval("n ~= nil"), "server: converted (%s)" % r)
    if S.eval("n ~= nil"):
        net.pump()
        net.stream_all()
        nid = S.eval("n.id")
        for c in (A, B):
            c.run("n = VEHICLES[%d]" % nid)
            c.try_run("TICK(30)")
            check(c.eval("VEHICLES[%d]" % S.eval("vid")) is None, "%s: the old car is gone" % c.name)
            check(c.eval("n.script") == "Base.HondaCRVGen1LiftSteel", "%s: has the lifted car" % c.name)
            check(c.eval("vis(n, 'CRVGuardFrontLeft')") == "ArmourMesh", "%s: lifted car, mesh only (%s)" % (c.name, c.eval("vis(n, 'CRVGuardFrontLeft')")))
            check(c.eval("vis(n, 'CRVRoofRack')") == "CRVRoofRack,RackLoad2", "%s: lifted car, rack load (%s)" % (c.name, c.eval("vis(n, 'CRVRoofRack')")))
            check(c.eval("vis(n, 'CRVEngineBay')") == "EngineBayLow", "%s: lifted car, the engine bay's stand-in" % c.name)
            check(c.eval("vis(n, 'CRVAwning')") == "CRVAwning,AwningCanopy,AwningPoles", "%s: lifted car, the awning out (%s)"
                  % (c.name, c.eval("vis(n, 'CRVAwning')")))
            check(c.eval("HondaCRVGen1.Shared.isBed(n)") is True and c.eval("HondaCRVGen1.Function.isFloorFound(n)") is True,
                  "%s: lifted car, folded + floor found" % c.name)
            ok, r = c.try_eval("ISOpenCloseVehicleWindow:new(PLAYER, n.parts.WindowFrontLeft, true):isValid()")
            check(ok and r is False, "%s: the armoured window stays shut (%s)" % (c.name, r))
            tests_return(c, "n", "PLAYER", "%s: lifted car" % c.name)
        check(S.eval("HondaCRVGen1.Acc.watch[n.id] ~= nil"), "server: the lifted car is protected")
        S.try_run("TICK(3); n.parts.DoorFrontLeft.cond = 50; TICK(3)")
        check(S.eval("n.parts.DoorFrontLeft.cond") == 100, "server: the plate protects the lifted car's door")
    for side in (S, A, B):
        end_of_flow(side)


def main():
    global LUA_DIR, SCRIPTS
    if "--lua" in sys.argv:
        LUA_DIR = os.path.abspath(sys.argv[sys.argv.index("--lua") + 1])
    print("Lua tree:", LUA_DIR)
    SCRIPTS = scripts_lua()
    single_player()
    multiplayer()
    print("\n%d FAIL(S)" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    if FAILS:
        return 1
    print("ALL-LUA TESTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
