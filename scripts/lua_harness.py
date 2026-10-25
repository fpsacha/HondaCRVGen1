r"""
A fake Project Zomboid for testing the mod's Lua under Lua 5.1 (lupa.lua51; the game's Kahlua is a
Lua 5.1), single player or a multiplayer server with clients, each side its own Lua runtime.

    from lua_harness import Side, Net
    sp = Side("sp")                                   # single player: isClient() and isServer() false
    sp.load("shared/HondaCRVGen1_State.lua", "server/HondaCRVGen1_StateServer.lua", "client/HondaCRVGen1_StateClient.lua")
    sp.run("v = newVehicle(1, {'CRVRoofRack'})")
    sp.pump()                                         # deliver this side's queued client commands (the game: next tick)

    net = Net()
    server, client = Side("server", net), Side("client", net, player="bob")
    ...
    net.pump()                                        # client commands -> server, server commands and mod data -> clients

What each side's Lua sees (PRELUDE below): isClient / isServer for its role; Events.<Any>.Add/Remove
and triggerEvent(name, ...); TICK(n) runs OnTick n times; ZombRand; require (a no-op: load files in
order with Side.load); getVehicleById; sendClientCommand / sendServerCommand routed as the game does
(LuaManager.GlobalObject 42.21: a client's command reaches OnClientCommand on the server, single
player's reaches its own OnClientCommand a tick later through SinglePlayerServer; sendServerCommand
does nothing outside a server); and fake objects with the Java methods the mod calls:

    newVehicle(id, partIds, script)   BaseVehicle: getId getScriptName getPartById getModData getX getY
                                      isRemovedFromWorld transmitPartModData transmitPartCondition
                                      transmitPartItem doDamageOverlay isInArea isSeatOccupied
    v.parts[id]                       VehiclePart: getId getVehicle getInventoryItem setInventoryItem
                                      (shows every model, like setAllModelsVisible) getModData
                                      getCondition setCondition getArea getItemContainer setModelVisible
                                      (.visible[model], .calls) ; .models = { modelIds } for the reset
    newContainer(max, weight)         ItemContainer: getMaxWeight getCapacityWeight isEmpty (.items)
    newPlayer(name, x, y)             IsoPlayer: getX getY getVehicle getUsername isLocalPlayer
    newRadial()                       ISRadialMenu: addSlice clear isEmpty isReallyVisible addToUIManager
                                      undisplay (.slices = { text, texture, fn, args, n }); :texts() :find(prefix)
                                      :pick(slice)
    VANILLA_RADIAL_OUTSIDE(player)    vanilla's ISVehicleMenu.showRadialMenuOutside, its shape (for the stubs)
    VANILLA_RADIAL_INSIDE(player)     vanilla's ISVehicleMenu.showRadialMenu from a seat, its shape (Sleep slice)
    sleep                             Player:isAsleep/setBedType/getBedType/getStats/getMoodles..., getServerOptions
                                      (SERVER_OPTIONS), Veh:isStopped/isSeatInstalled/getCharacter
    viewpointRadial(player, vehicle)  the radial as Project Viewpoint's quick-interact list harvests it

Mod data sync: a server's transmitPartModData(part) queues a copy of that part's mod data for every
client (VehicleUpdatePacket's VehiclePartModData); Net.pump replaces the client part's mod data with
it, as the packet does. Net.sync_item(vehicle_id, part_id) sends a part's item the same way
(transmitPartItem): the client's part gets a new item object and shows all its models.
sendServerCommand(player, ...) reaches only the client whose player has that name. Net.pump(reorder=fn)
delivers the server's packets in another order the real net allows (Net.take / Net.deliver /
Net.legal_orders: the commands are unordered, the mod data packets keep their order).
"""
import os

from lupa import lua51

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUA_DIR = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua")

PRELUDE = r'''
ROLE = ...
EVENTS = {}
Events = setmetatable({}, { __index = function(t, name)
    local e = {
        Add = function(fn) EVENTS[name] = EVENTS[name] or {}; table.insert(EVENTS[name], fn) end,
        Remove = function(fn)
            local l = EVENTS[name] or {}
            for i = #l, 1, -1 do if l[i] == fn then table.remove(l, i) end end
        end,
    }
    rawset(t, name, e)
    return e
end })
function triggerEvent(name, ...)
    local l = EVENTS[name]
    if not l then return 0 end
    for _, fn in ipairs(l) do fn(...) end
    return #l
end
function TICK(n) for i = 1, (n or 1) do triggerEvent("OnTick") end end
function isClient() return ROLE == "client" end
function isServer() return ROLE == "server" end
function require(name) end
function ZombRand(a, b) if b == nil then return math.random(0, a - 1) end return math.random(a, b - 1) end
function getText(k) return k end

VEHICLES = {}
function getVehicleById(id) return VEHICLES[id] end
SENT = { transmitModData = 0, transmitCondition = 0, transmitItem = 0 }

function sendClientCommand(player, module, command, args)
    if ROLE == "server" then error("can't call this function on the server") end
    PY_SEND_CLIENT(player, module, command, args or {})
end
function sendServerCommand(module, command, args, extra)
    if ROLE ~= "server" then return end
    local to = nil
    if type(module) ~= "string" then                      -- the game's per-player form: (player, module, command, args)
        to = module and module.name                       -- delivered to the client whose player has that name
        module, command, args = command, args, extra
    end
    PY_SEND_SERVER(module, command, args or {}, to)
end

Item = {}
Item.__index = Item
function newItem(t) return setmetatable({ type = t }, Item) end
function Item:getType() return self.type end

Cont = {}
Cont.__index = Cont
function newContainer(max, weight) return setmetatable({ max = max or 50, weight = weight or 0, items = 0 }, Cont) end
function Cont:getMaxWeight() return self.max end
function Cont:getCapacityWeight() return self.weight end
function Cont:isEmpty() return self.items == 0 end

Part = {}
Part.__index = Part
function Part:getId() return self.id end
function Part:getVehicle() return self.vehicle end
function Part:getInventoryItem() return self.item end
function Part:setInventoryItem(item)
    self.item = item
    for _, m in ipairs(self.models or {}) do self.visible[m] = item and true or nil end
end
function Part:getModData() return self.md end
function Part:getCondition() return self.cond end
function Part:setCondition(c) self.cond = c end
function Part:getArea() return self.area end
function Part:getItemContainer() return self.cont end
function Part:setModelVisible(id, vis)
    self.calls = self.calls + 1
    self.visible[id] = vis or nil
end

Veh = {}
Veh.__index = Veh
function newVehicle(id, partIds, script)
    local v = setmetatable({ id = id, script = script or "Base.HondaCRVGen1", md = {}, parts = {}, x = 100, y = 100,
                             removed = false, occupied = {} }, Veh)
    for _, pid in ipairs(partIds or {}) do v:addPart(pid) end
    VEHICLES[id] = v
    return v
end
function Veh:addPart(pid)
    local p = setmetatable({ id = pid, vehicle = self, md = {}, cond = 100, area = pid, calls = 0, visible = {} }, Part)
    self.parts[pid] = p
    return p
end
function Veh:getId() return self.id end
function Veh:getScriptName() return self.script end
function Veh:getPartById(id) return self.parts[id] end
function Veh:getModData() return self.md end
function Veh:getX() return self.x end
function Veh:getY() return self.y end
function Veh:isRemovedFromWorld() return self.removed end
function Veh:transmitPartModData(p)
    SENT.transmitModData = SENT.transmitModData + 1
    if ROLE == "server" then PY_TRANSMIT_MODDATA(self.id, p.id, p.md) end
end
function Veh:transmitPartCondition(p) SENT.transmitCondition = SENT.transmitCondition + 1 end
function Veh:transmitPartItem(p) SENT.transmitItem = SENT.transmitItem + 1 end
function Veh:doDamageOverlay() end
function Veh:isInArea(area, chr) return chr.area == area end
function Veh:isSeatOccupied(seat) return self.occupied[seat] or false end
-- .seatGone[seat] = true: that seat's part removed; .chars[seat] = the character in it; .moving = true: not stopped
function Veh:isSeatInstalled(seat) return not (self.seatGone and self.seatGone[seat]) end
function Veh:getCharacter(seat) return self.chars and self.chars[seat] or nil end
function Veh:isStopped() return not self.moving end

Player = {}
Player.__index = Player
PLAYERS = {}
function newPlayer(name, x, y)
    local p = setmetatable({ name = name, x = x or 100, y = y or 100, vehicle = nil }, Player)
    PLAYERS[name] = p
    return p
end
function Player:getX() return self.x end
function Player:getY() return self.y end
function Player:getVehicle() return self.vehicle end
function Player:getUsername() return self.name end
function Player:isLocalPlayer() return true end
-- sleep: the bed type (IsoGameCharacter, default "averageBed"), asleep, and what vanilla's sleep checks read
-- (.fatigue default 0.6: tired enough; .zombies; .moodles = { PAIN = n, PANIC = n }; .hours / .lastSlept; .tablet)
CharacterStat = { FATIGUE = "FATIGUE" }
MoodleType = { PAIN = "PAIN", PANIC = "PANIC" }
SERVER_OPTIONS = { SleepAllowed = true, SleepNeeded = true }
function getServerOptions() return { getBoolean = function(_, k) return SERVER_OPTIONS[k] == true end } end
function Player:isAsleep() return self.asleep == true end
function Player:setAsleep(b) self.asleep = b end
function Player:getBedType() return self.bedType or "averageBed" end
function Player:setBedType(t) self.bedType = t end
function Player:getStats()
    local p = self
    return { get = function(_, stat) if stat == "FATIGUE" then return p.fatigue or 0.6 end return 0 end,
             getNumVisibleZombies = function() return p.zombies or 0 end,
             getNumChasingZombies = function() return 0 end, getNumVeryCloseZombies = function() return 0 end }
end
function Player:getMoodles()
    local p = self
    return { getMoodleLevel = function(_, m) return (p.moodles or {})[m] or 0 end }
end
function Player:getHoursSurvived() return self.hours or 100 end
function Player:getLastHourSleeped() return self.lastSlept or 0 end
function Player:getSleepingTabletEffect() return self.tablet or 0 end

-- radial menus: newRadial() records every addSlice(text, texture, fn, ...) in order, shown by addToUIManager and
-- closed by undisplay (ISRadialMenu); radial:texts() is "text,text!,..." (! = no command, a blocked slice);
-- radial:find(prefix) the first slice whose text starts so; radial:pick(slice) runs its command as the game does
Radial = {}
Radial.__index = Radial
function newRadial() return setmetatable({ slices = {}, shown = false }, Radial) end
function Radial:addSlice(text, texture, fn, ...)
    table.insert(self.slices, { text = text, texture = texture, fn = fn, args = { ... }, n = select("#", ...) })
end
function Radial:clear() self.slices = {} end
function Radial:setSliceText(i, text) if self.slices[i] then self.slices[i].text = text end end
function Radial:isEmpty() return #self.slices == 0 end
function Radial:isReallyVisible() return self.shown end
function Radial:addToUIManager() self.shown = true end
function Radial:undisplay() self.shown = false end
function Radial:texts()
    local t = {}
    for _, s in ipairs(self.slices) do t[#t + 1] = s.text .. (s.fn and "" or "!") end
    return table.concat(t, ",")
end
function Radial:find(prefix)
    for _, s in ipairs(self.slices) do
        if string.sub(s.text, 1, #prefix) == prefix then return s end
    end
    return nil
end
function Radial:pick(s) if s and s.fn then return s.fn(unpack(s.args, 1, s.n)) end end

-- vanilla's ISVehicleMenu.showRadialMenuOutside (42.21), its shape: nothing from inside a car; the key closes an
-- open menu; else clear, the game's slices for the car the player can reach (one here), show
function VANILLA_MECHANICS() end
function VANILLA_RADIAL_OUTSIDE(playerObj)
    if playerObj:getVehicle() then return end
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    if menu:isReallyVisible() then menu:undisplay(); return end
    menu:clear()
    local vehicle = ISVehicleMenu.getVehicleToInteractWith(playerObj)
    if vehicle then menu:addSlice("VANILLA_MECHANICS", "media/ui/vehicles/vehicle_repair.png", VANILLA_MECHANICS, playerObj, vehicle) end
    if menu:isEmpty() then return end
    menu:addToUIManager()
end

-- vanilla's ISVehicleMenu.showRadialMenu (42.21) from a seat, its shape: outside a car it hands over to the
-- outside menu; clear, the key closes an open menu; the switch-seat slice, the Sleep slice (when sleep is offered:
-- SleepAllowed, stopped, tired), exit; show
function VANILLA_SWITCH() end
function VANILLA_SLEEP() end
function VANILLA_RADIAL_INSIDE(playerObj)
    local vehicle = playerObj:getVehicle()
    if not vehicle then return ISVehicleMenu.showRadialMenuOutside(playerObj) end
    local menu = getPlayerRadialMenu(playerObj:getPlayerNum())
    menu:clear()
    if menu:isReallyVisible() then menu:undisplay(); return end
    menu:addSlice(getText("IGUI_SwitchSeat"), "media/ui/vehicles/vehicle_changeseats.png", VANILLA_SWITCH, playerObj, vehicle)
    if vehicle:isStopped() then
        menu:addSlice(getText("ContextMenu_Sleep"), "media/ui/vehicles/vehicle_sleep.png", VANILLA_SLEEP, playerObj, vehicle)
    end
    menu:addSlice(getText("IGUI_ExitVehicle"), "media/ui/vehicles/vehicle_exit.png", VANILLA_SWITCH, playerObj)
    menu:addToUIManager()
end

-- Project Viewpoint's quick-interact list for a car (Viewpoint_Interact.lua radialEntries, mod 3809306528):
-- getPlayerRadialMenu and ISVehicleMenu.getVehicleToInteractWith swapped for a stand-in menu (reports itself
-- visible once it holds a slice) and the target car, showRadialMenuOutside(player) called, both put back
function viewpointRadial(player, vehicle)
    local standIn = newRadial()
    function standIn:isReallyVisible() return #self.slices > 0 end
    local radialOf, pick = getPlayerRadialMenu, ISVehicleMenu.getVehicleToInteractWith
    getPlayerRadialMenu = function() return standIn end
    ISVehicleMenu.getVehicleToInteractWith = function() return vehicle end
    local ok, err = pcall(ISVehicleMenu.showRadialMenuOutside, player)
    getPlayerRadialMenu, ISVehicleMenu.getVehicleToInteractWith = radialOf, pick
    if not ok then error(err) end
    return standIn
end
'''


def _plain(value):
    """A Lua table from another runtime as plain Python data (scalars and nested dicts)."""
    if hasattr(value, "items") and callable(getattr(value, "items")):
        return {k: _plain(v) for k, v in value.items()}
    return value


class Side:
    """One game side: "sp" (single player), "server" or "client", with its own Lua runtime."""

    def __init__(self, role, net=None, player=None, seed=7):
        assert role in ("sp", "server", "client")
        self.role, self.net = role, net
        self.L = lua51.LuaRuntime(unpack_returned_tuples=True)
        assert self.L.eval("_VERSION") == "Lua 5.1", self.L.eval("_VERSION")
        self.queue = []                                   # single player: client commands for the next pump
        g = self.L.globals()
        g.PY_SEND_CLIENT = self._send_client
        g.PY_SEND_SERVER = self._send_server
        g.PY_TRANSMIT_MODDATA = self._transmit
        self.L.execute(PRELUDE, role)
        self.L.execute("next = nil")                      # the game's Kahlua has no global next (0.4.0 shipped one)
        self.L.execute("math.randomseed(%d)" % seed)
        self.player = player
        if player:
            self.run("PLAYER = newPlayer(%r)" % player)
        if net is not None:
            net.add(self)

    # -- Lua
    def run(self, code):
        return self.L.execute(code)

    def eval(self, expr):
        return self.L.eval(expr)

    def load(self, *relpaths):
        """Execute mod Lua files (paths relative to 42/media/lua, or absolute) in this order."""
        for rel in relpaths:
            path = rel if os.path.isabs(rel) else os.path.join(LUA_DIR, *rel.replace("\\", "/").split("/"))
            with open(path, encoding="utf-8") as f:
                self.L.execute(f.read())

    def trigger(self, name, *args):
        return self.L.globals().triggerEvent(name, *args)

    def table(self, data):
        if isinstance(data, dict):
            return self.L.table_from({k: self.table(v) for k, v in data.items()})
        return data

    # -- network hooks (called from Lua)
    def _send_client(self, player, module, command, args):
        if self.role == "sp":
            self.queue.append((player, module, command, args))
        else:
            self.net.to_server.append((player.name if player is not None else None, module, command, _plain(args)))

    def _send_server(self, module, command, args, to=None):
        self.net.to_clients.append((module, command, _plain(args), to))

    def _transmit(self, vehicle_id, part_id, md):
        self.net.moddata.append((vehicle_id, part_id, _plain(md)))

    def pump(self):
        """Single player: deliver the queued client commands to this side's OnClientCommand."""
        n = 0
        while self.queue:
            player, module, command, args = self.queue.pop(0)
            self.trigger("OnClientCommand", module, command, player, args)
            n += 1
        return n


class Net:
    """A multiplayer server and its clients."""

    def __init__(self):
        self.server, self.clients = None, []
        self.to_server, self.to_clients, self.moddata = [], [], []
        self.drop_commands = False                        # test the mod data path alone

    def add(self, side):
        if side.role == "server":
            self.server = side
        elif side.role == "client":
            self.clients.append(side)

    def pump(self, reorder=None, between=None):
        """Deliver everything queued: client commands to the server (its own player object for the
        sender), then the server's commands (to every client, or the one addressed: sendServerCommand(player,
        ...)) and part mod data to every client. Returns the count.

        reorder: the real net's delivery order instead of the send order. Server commands are RELIABLE but
        UNORDERED in 42.21 (PacketTypes.ClientCommand, reliability 2), the part mod data rides VehicleUpdate
        (RELIABLE_ORDERED): a callable taking the queued server -> client packets (Net.take's labelled list)
        and returning them in the order to deliver (Net.legal_orders lists every order the net allows).
        between(packet): called after each server -> client packet (a client's poll between packets)."""
        n = 0
        while self.to_server or self.to_clients or self.moddata:
            while self.to_server:
                name, module, command, args = self.to_server.pop(0)
                player = self.server.eval("PLAYERS")[name] if name else None
                self.server.trigger("OnClientCommand", module, command, player, self.server.table(args))
                n += 1
            packets = self.take()
            if reorder is not None:
                packets = list(reorder(packets))
            n += self.deliver(packets, between)
        return n

    def take(self):
        """Remove and return the queued server -> client packets in send order, each labelled:
        ("cmd", (module, command, args, to)) or ("md", (vehicle_id, part_id, moddata)). Commands queued
        before mod data in the same pump go first, as pump has always delivered them."""
        out = [("cmd", x) for x in self.to_clients] + [("md", x) for x in self.moddata]
        self.to_clients.clear()
        self.moddata.clear()
        return out

    def deliver(self, packets, between=None):
        """Deliver labelled server -> client packets (Net.take) in the given order; returns the count."""
        n = 0
        for kind, p in packets:
            if kind == "cmd":
                module, command, args = p[0], p[1], p[2]
                to = p[3] if len(p) > 3 else None
                if not self.drop_commands:
                    for c in self.clients:
                        if to is None or c.player == to:
                            c.trigger("OnServerCommand", module, command, c.table(args))
            else:
                vid, pid, md = p
                for c in self.clients:
                    v = c.eval("VEHICLES")[vid]
                    if v is not None and v.parts[pid] is not None:
                        v.parts[pid].md = c.table(md)                # the packet replaces the part's mod data
            n += 1
            if between is not None:
                between((kind, p))
        return n

    @staticmethod
    def legal_orders(packets):
        """Every delivery order of labelled packets (Net.take) the 42.21 net allows: the mod data packets
        (VehicleUpdate, RELIABLE_ORDERED, one channel) keep their relative order, the commands (ClientCommand,
        RELIABLE, unordered) go anywhere. Yields lists; duplicates (identical packets swapped) are skipped."""
        import itertools
        n = len(packets)
        md_idx = [i for i, (k, _) in enumerate(packets) if k == "md"]
        seen = set()
        for perm in itertools.permutations(range(n)):
            pos = [perm.index(i) for i in md_idx]
            if pos != sorted(pos):
                continue
            key = tuple(repr(packets[i]) for i in perm)
            if key in seen:
                continue
            seen.add(key)
            yield [packets[i] for i in perm]

    def sync_item(self, vehicle_id, part_id):
        """The server's transmitPartItem: every client's part gets a fresh item of the same type
        (or none) and, like VehiclePart.setInventoryItem, shows every one of its models."""
        sv = self.server.eval("VEHICLES")[vehicle_id]
        item = sv.parts[part_id].item
        for c in self.clients:
            v = c.eval("VEHICLES")[vehicle_id]
            if v is not None:
                new = c.eval("newItem")(item.type) if item is not None else None
                v.parts[part_id].setInventoryItem(v.parts[part_id], new)
