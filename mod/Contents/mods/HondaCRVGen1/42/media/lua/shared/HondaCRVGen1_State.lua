--[[
Honda CR-V (RD1): per-vehicle state for every feature (rack cargo, decals, folded seats, armour...).

Our own code. One value per key per car, stored in the mod data of a part the key names (its host
part), changed only where the game is authoritative (single player, or the server in multiplayer).
The game saves part mod data with the car and sends it to clients (BaseVehicle.transmitPartModData:
part and vehicle updateFlags bit 16, read by VehicleUpdatePacket's VehiclePartModData; a client that
streams a car in gets it with the full vehicle, VehicleFullUpdatePacket -> BaseVehicle.load), so a
value set here survives a reload and reaches every player. spec/feature-plugins.md is the contract.

    State.define(key, spec)          declare a key once, in shared code (every side loads it)
    State.get(vehicle, key)          read it on any side: the host part's mod data, or spec.default
    State.set(vehicle, key, value)   change it, AUTHORITATIVE SIDE ONLY (single player or the server:
                                     a timed action's complete(), an OnClientCommand handler, a server
                                     tick). Writes the mod data, transmits it, tells every client at
                                     once (server command), fires the listeners. Returns ok, why
    State.request(player, vehicle, key, value)
                                     ask for a change from client code (a menu): a client command the
                                     server half validates (spec.request, reach, the value) before
                                     State.set. Works in single player too (the game routes client
                                     commands through its local server a tick later)
    State.onChange(key, fn)          fn(vehicle, key, value, old, how); key "*" hears every key.
                                     how = "set" (the authoritative side changed it), "sync" (a client
                                     learned it from the server or its poll), "init" (State.refresh)
    State.refresh(vehicle[, key])    fire the listeners with the current values (how "init") and start
                                     tracking the car on a client: call it from a part's init hook so
                                     visuals follow a car that was just created, loaded or streamed in
    State.watchPart(partId, fn)      client side: fn(vehicle, part) once the part's installed item
                                     changes on a tracked car (the engine reset that part's models:
                                     VehiclePart.setInventoryItem -> setAllModelsVisible)
    State.sawPart(vehicle, part)     the drawing side just applied that part's visuals for its current
                                     item: the poll will not call its watchers for it
    State.registerVehicle(name)      another CR-V vehicle script (the lifted car) counts as a CR-V
    State.isCRV(vehicle)

spec = {
    part    = "CRVRoofRack",         -- host part id (required); the value lives in its mod data
    default = 0,                     -- value while nothing is stored (nil allowed)
    kind    = "number",              -- "number" | "string" | "boolean" (optional type check)
    values  = { 0, 1, 2, 3 },        -- optional: the only legal values
    min = 0, max = 3, integer = true,-- optional number checks
    request = false,                 -- may clients ask for it? false/nil: server-only (derived state);
                                     -- true: any player within REACH; or a function
                                     -- fn(vehicle, player, value, old) -> ok, why for a custom rule
}

Mod data key: State.PREFIX .. key ("crv_" .. key) in the host part's mod data; a value equal to the
default is stored as nil. Values are scalars (number / string / boolean): they ride client and server
commands, which only carry what TableNetworkUtils.canSave accepts.
Single player: sendServerCommand does nothing there (LuaManager.GlobalObject: GameServer.server only),
so State.set fires the listeners itself; the client half's poll keeps a client right in multiplayer
even without the command.
]]

HondaCRVGen1 = HondaCRVGen1 or {}
local State = HondaCRVGen1.State or {}
HondaCRVGen1.State = State

State.MODULE = "HondaCRVGen1"        -- client / server command module
State.PREFIX = "crv_"                -- mod data key = PREFIX .. key
State.REACH = 8                      -- tiles: a requesting player must be this close (or inside the car)
State.POLL = 30                      -- ticks between a client's checks of its tracked cars

State.keys = State.keys or {}        -- key -> spec
State.listeners = State.listeners or {}
State.partWatchers = State.partWatchers or {}   -- partId -> { fn, ... }
State.tracked = State.tracked or {}  -- vehicle id -> { vehicle =, values = { key = value }, items = { partId = item } }
State.VEHICLES = State.VEHICLES or { ["Base.HondaCRVGen1"] = true }

local function warn(msg)
    print("HondaCRVGen1.State: " .. msg)
end

function State.registerVehicle(scriptName)
    State.VEHICLES[scriptName] = true
end

function State.isCRV(vehicle)
    return vehicle ~= nil and State.VEHICLES[vehicle:getScriptName()] == true
end

function State.define(key, spec)
    if type(key) ~= "string" or key == "" or key == "*" then
        error("HondaCRVGen1.State.define: bad key " .. tostring(key))
    end
    if type(spec) ~= "table" or type(spec.part) ~= "string" then
        error("HondaCRVGen1.State.define(" .. key .. "): spec.part (the host part id) is required")
    end
    local old = State.keys[key]
    if old and old.part ~= spec.part then
        error("HondaCRVGen1.State.define(" .. key .. "): already defined on part " .. old.part)
    end
    State.keys[key] = spec
    return spec
end

-- ok, why: is value legal for spec (nil = back to the default)
function State.check(spec, value)
    if value == nil then return true end
    local t = type(value)
    if t ~= "number" and t ~= "string" and t ~= "boolean" then
        return false, "values are numbers, strings or booleans"
    end
    if spec.kind and t ~= spec.kind then
        return false, "want a " .. spec.kind .. ", got a " .. t
    end
    if spec.values then
        local found = false
        for _, v in ipairs(spec.values) do
            if v == value then found = true end
        end
        if not found then return false, "not one of the allowed values: " .. tostring(value) end
    end
    if t == "number" then
        if spec.min and value < spec.min then return false, "below " .. tostring(spec.min) end
        if spec.max and value > spec.max then return false, "above " .. tostring(spec.max) end
        if spec.integer and math.floor(value) ~= value then return false, "not a whole number" end
    end
    return true
end

function State.hostPart(vehicle, key)
    local spec = State.keys[key]
    if not spec or not vehicle then return nil, spec end
    return vehicle:getPartById(spec.part), spec
end

-- what is stored (nil while at the default)
local function stored(spec, value)
    if value == spec.default then return nil end
    return value
end

function State.get(vehicle, key)
    local part, spec = State.hostPart(vehicle, key)
    if not spec then
        warn("get of undefined key " .. tostring(key))
        return nil
    end
    if not part then return spec.default end
    local v = part:getModData()[State.PREFIX .. key]
    if v == nil then return spec.default end
    return v
end

function State.onChange(key, fn)
    local list = State.listeners[key]
    if not list then
        list = {}
        State.listeners[key] = list
    end
    list[#list + 1] = fn
end

function State.watchPart(partId, fn)
    local list = State.partWatchers[partId]
    if not list then
        list = {}
        State.partWatchers[partId] = list
    end
    list[#list + 1] = fn
end

local function call(fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then warn("listener error: " .. tostring(err)) end
end

function State.fire(vehicle, key, value, old, how)
    local list = State.listeners[key]
    if list then
        for _, fn in ipairs(list) do call(fn, vehicle, key, value, old, how) end
    end
    list = State.listeners["*"]
    if list then
        for _, fn in ipairs(list) do call(fn, vehicle, key, value, old, how) end
    end
end

-- the tracking entry of a car (created on first use); a new BaseVehicle under the same id (the car
-- was unloaded and streamed back in) starts a fresh entry
function State.track(vehicle)
    local id = vehicle:getId()
    local e = State.tracked[id]
    if not e or e.vehicle ~= vehicle then
        e = { vehicle = vehicle, values = {}, items = {} }
        for key, _ in pairs(State.keys) do
            e.values[key] = State.get(vehicle, key)
        end
        for partId, _ in pairs(State.partWatchers) do
            local part = vehicle:getPartById(partId)
            e.items[partId] = part and part:getInventoryItem() or false
        end
        State.tracked[id] = e
    end
    return e
end

-- drawing side: the part's visuals were just applied for its current item (no watchPart call for it)
function State.sawPart(vehicle, part)
    if isServer() or not vehicle or not part then return end
    State.track(vehicle).items[part:getId()] = part:getInventoryItem() or false
end

local function remember(vehicle, key, value)
    if not isServer() then
        local e = State.track(vehicle)
        e.values[key] = value
    end
end

function State.set(vehicle, key, value)
    if isClient() then
        warn("set(" .. tostring(key) .. ") on a multiplayer client: use State.request")
        return false, "client"
    end
    local part, spec = State.hostPart(vehicle, key)
    if not spec then return false, "undefined key " .. tostring(key) end
    if not part then return false, "no part " .. spec.part end
    local ok, why = State.check(spec, value)
    if not ok then
        warn("set(" .. key .. "): " .. tostring(why))
        return false, why
    end
    if value == nil then value = spec.default end      -- nil = back to the default
    local md = part:getModData()
    local name = State.PREFIX .. key
    local old = md[name]
    if old == nil then old = spec.default end
    if old == value then return true, "unchanged" end
    md[name] = stored(spec, value)
    vehicle:transmitPartModData(part)                 -- a no-op outside a server
    if isServer() then
        sendServerCommand(State.MODULE, "changed", { vehicle = vehicle:getId(), key = key, value = value })
    end
    remember(vehicle, key, value)
    State.fire(vehicle, key, value, old, "set")
    return true
end

function State.request(player, vehicle, key, value)
    local spec = State.keys[key]
    if not spec then return false, "undefined key " .. tostring(key) end
    if not spec.request then return false, "server-only key " .. key end
    local ok, why = State.check(spec, value)
    if not ok then return false, why end
    sendClientCommand(player, State.MODULE, "set", { vehicle = vehicle:getId(), key = key, value = value })
    return true
end

-- the authoritative side's answer to a client's "set" command (server half: OnClientCommand)
function State.handleRequest(player, args)
    if type(args) ~= "table" then return false, "no args" end
    local spec = State.keys[args.key]
    if not spec then return false, "undefined key " .. tostring(args.key) end
    if not spec.request then return false, "server-only key " .. tostring(args.key) end
    local vehicle = args.vehicle and getVehicleById(args.vehicle)
    if not vehicle or not State.isCRV(vehicle) then return false, "no such CR-V " .. tostring(args.vehicle) end
    if player and player:getVehicle() ~= vehicle then
        local dx, dy = player:getX() - vehicle:getX(), player:getY() - vehicle:getY()
        if dx * dx + dy * dy > State.REACH * State.REACH then return false, "too far" end
    end
    local ok, why = State.check(spec, args.value)
    if not ok then return false, why end
    if type(spec.request) == "function" then
        ok, why = spec.request(vehicle, player, args.value, State.get(vehicle, args.key))
        if not ok then return false, why or "refused" end
    end
    return State.set(vehicle, args.key, args.value)
end

-- a client's copy of a change the server announced (client half: OnServerCommand)
function State.applyRemote(args)
    if type(args) ~= "table" then return false end
    local vehicle = args.vehicle and getVehicleById(args.vehicle)
    if not vehicle then return false end                 -- not streamed in here: its init reads the mod data later
    local part, spec = State.hostPart(vehicle, args.key)
    if not spec or not part then return false end
    if not State.check(spec, args.value) then return false end
    local value = args.value
    if value == nil then value = spec.default end      -- an absent value is the default
    part:getModData()[State.PREFIX .. args.key] = stored(spec, value)   -- right before the mod data packet lands
    local e = State.track(vehicle)
    local old = e.values[args.key]
    e.values[args.key] = State.get(vehicle, args.key)
    if old ~= e.values[args.key] then
        State.fire(vehicle, args.key, e.values[args.key], old, "sync")
    end
    return true
end

function State.refresh(vehicle, key)
    if not vehicle then return end
    if not isServer() then
        State.track(vehicle)
    end
    for k, _ in pairs(State.keys) do
        if key == nil or k == key then
            local v = State.get(vehicle, k)
            if not isServer() then State.tracked[vehicle:getId()].values[k] = v end
            State.fire(vehicle, k, v, nil, "init")
        end
    end
end

-- one pass over the tracked cars (client half: OnTick every POLL ticks): values that changed under
-- the client (the mod data packet without its command), parts whose item changed (models reset)
function State.poll()
    for id, e in pairs(State.tracked) do
        local v = e.vehicle
        if v == nil or v:isRemovedFromWorld() or v:getId() ~= id then
            State.tracked[id] = nil
        else
            for key, _ in pairs(State.keys) do
                local now = State.get(v, key)
                local was = e.values[key]
                if now ~= was then
                    e.values[key] = now
                    State.fire(v, key, now, was, "sync")
                end
            end
            for partId, fns in pairs(State.partWatchers) do
                local part = v:getPartById(partId)
                local item = part and part:getInventoryItem() or false
                if e.items[partId] ~= item then
                    e.items[partId] = item
                    for _, fn in ipairs(fns) do call(fn, v, part) end
                end
            end
        end
    end
end
