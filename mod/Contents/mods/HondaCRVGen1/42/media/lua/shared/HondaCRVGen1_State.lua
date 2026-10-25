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
                                     tick). Writes the mod data, transmits it, tells the clients near
                                     the car at once (server command "changed", numbered: State.announce),
                                     fires the listeners. Returns ok, why
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
    State.prunable(cache)            a drawing-side cache (vehicle id -> { vehicle =, ... }) the poll empties of
                                     cars that left the world (State.gone); returns the cache
    State.near(character, vehicle)   in the car or within REACH: a timed action's complete() re-checks it

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
State.hostKeys = State.hostKeys or {} -- host part id -> { key, ... } (the poll reads each host part's mod data once)
State.listeners = State.listeners or {}
State.partWatchers = State.partWatchers or {}   -- partId -> { fn, ... }
State.tracked = State.tracked or {}  -- vehicle id -> { vehicle =, values = { key = value }, items = { partId = item },
                                     --   session =, seqs = { key = last applied announcement seq } }
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
    spec.name = State.PREFIX .. key                    -- the mod data key, made once
    State.keys[key] = spec
    local list = State.hostKeys[spec.part]
    if not list then
        list = {}
        State.hostKeys[spec.part] = list
    end
    local listed = false
    for _, k in ipairs(list) do
        if k == key then listed = true end
    end
    if not listed then list[#list + 1] = key end
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
    local v = part:getModData()[spec.name or (State.PREFIX .. key)]
    if v == nil then return spec.default end
    return v
end

-- the value of key in md, its host part's mod data table (already in hand: one getModData for several keys)
function State.getFrom(md, key)
    local spec = State.keys[key]
    if not spec then return nil end
    local v = md and md[spec.name or (State.PREFIX .. key)]
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

-- ---------------------------------------------------------------------------------------------
-- the server's "changed" announcements (H-MP-1, H-MP-I3, 2026-10-24)
--
-- Order. sendServerCommand rides PacketTypes.ClientCommand, RELIABLE but UNORDERED in 42.21 (reliability 2), while
-- the part mod data rides VehicleUpdate (RELIABLE_ORDERED): a command lost once and resent can land after a newer
-- one, and applying it would undo the newer value on that client for good (the mod data packet that carried the
-- newer value had already landed). Every announcement carries seq, one counter of this server run rising with each
-- announcement (so rising per car and key), and session, this server run's id; a client keeps the last seq it applied
-- per key in the car's tracking entry (State.tracked[id].seqs) and drops an older or equal one. A new car object
-- (streamed back in) starts a fresh entry; a server restart has a new session, which clears the record.
--
-- Reach. The game sends a car's updates only to a connection the car is relevant to (VehicleManager.sendVehicles ->
-- UdpConnection.isRelevantTo, and GameServer.sendServerCommandToRelevant, which Lua cannot call): within
-- relevantRange chunks of the player on both axes, relevantRange = clamp(the client's chunk grid width, 12, 20) / 2
-- + 2 (GameServer.receivePlayerConnect), so at most 12 chunks = 96 tiles. A player farther away has no copy of the
-- car to change; one who streams it in later gets the state with the car (its mod data in the full update). So the
-- command goes, per player (sendServerCommand(player, ...)), to the online players within STREAM tiles on both axes:
-- 96 plus a 32-tile margin.
State.STREAM = 128
State.seq = State.seq or 0
-- this server run's id: its start time in ms (two runs never share one), or a random number without the clock
State.session = State.session or ((type(getTimestampMs) == "function" and tonumber(getTimestampMs())) or ZombRand(1000000000))

-- is player p (an online IsoPlayer) within STREAM tiles of the car on both axes
function State.inStream(p, vehicle)
    local dx, dy = p:getX() - vehicle:getX(), p:getY() - vehicle:getY()
    local r = State.STREAM
    return dx <= r and dx >= -r and dy <= r and dy >= -r
end

-- the server tells the clients that can see the car (authoritative side, MP server only: State.set calls it)
function State.announce(vehicle, key, value)
    State.seq = State.seq + 1
    local args = { vehicle = vehicle:getId(), key = key, value = value, seq = State.seq, session = State.session }
    local list = type(getOnlinePlayers) == "function" and getOnlinePlayers() or nil
    if not list then
        sendServerCommand(State.MODULE, "changed", args)            -- no player list: every client, as before
        return
    end
    for i = 0, list:size() - 1 do
        local p = list:get(i)
        if p and State.inStream(p, vehicle) then sendServerCommand(p, State.MODULE, "changed", args) end
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
    if isServer() then State.announce(vehicle, key, value) end
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
    if player and not State.near(player, vehicle) then return false, "too far" end
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
    local e = State.track(vehicle)                      -- (before the write: a fresh entry holds the value until now)
    -- an announcement older than one already applied (resent late on the unordered channel): dropped
    local seq = tonumber(args.seq)
    if seq then
        if e.session ~= args.session then             -- the first one from this server run: no record yet
            e.session = args.session
            e.seqs = {}
        end
        e.seqs = e.seqs or {}
        local last = e.seqs[args.key]
        if last and seq <= last then return false, "stale" end
        e.seqs[args.key] = seq
    end
    local value = args.value
    if value == nil then value = spec.default end      -- an absent value is the default
    part:getModData()[State.PREFIX .. args.key] = stored(spec, value)   -- right before the mod data packet lands
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
        State.track(vehicle).parts = nil                -- a part init: look the part objects up again (State.partOf)
    end
    for k, _ in pairs(State.keys) do
        if key == nil or k == key then
            local v = State.get(vehicle, k)
            if not isServer() then State.tracked[vehicle:getId()].values[k] = v end
            State.fire(vehicle, k, v, nil, "init")
        end
    end
end

-- is the car stored under `id` gone from this side (removed or unloaded: BaseVehicle.removeFromWorld sets
-- removedFromWorld; a streamed-out car's id may come back as another object)
function State.gone(vehicle, id)
    return vehicle == nil or vehicle:isRemovedFromWorld() or vehicle:getId() ~= id
end

-- per-car caches of the drawing side (vehicle id -> { vehicle = BaseVehicle, ... }: what a feature last showed)
-- that the poll empties of cars that left the world, as it does State.tracked (H-LUA-3: they held every CR-V a
-- client ever drew). State.prunable(t) registers t once and returns it
State.caches = State.caches or {}
function State.prunable(t)
    for _, c in ipairs(State.caches) do
        if c == t then return t end
    end
    State.caches[#State.caches + 1] = t
    return t
end

-- drop the entries of cars that left the world from a cache (id -> { vehicle = }); returns how many went
function State.prune(t)
    local n = 0
    for id, e in pairs(t) do
        if type(e) ~= "table" or State.gone(e.vehicle, id) then
            t[id] = nil
            n = n + 1
        end
    end
    return n
end

-- the acting character is at the car (in it, or within REACH tiles of its centre): the authoritative side's
-- check in a timed action's complete() (the server never runs isValid for a client's action)
function State.near(character, vehicle)
    if not character or not vehicle then return false end
    if character:getVehicle() == vehicle then return true end
    local dx, dy = character:getX() - vehicle:getX(), character:getY() - vehicle:getY()
    return dx * dx + dy * dy <= State.REACH * State.REACH
end

-- ---------------------------------------------------------------------------------------------
-- far cars (perf 2026-10-24). The throttled loops (the client poll, the engine bay, the authoritative side's
-- container and protection loops) look at a car no player is near less often: every pass while a player is within
-- the loop's radius, every slow-th pass otherwise. Nothing that matters happens at a car nobody is near (items go in
-- and out, hoods open, zombies thump only where a player is) and nobody there sees it; a player walking or driving
-- up is noticed within slow passes, long before they reach the car.

local spots, spotsAt, spotsBuf = nil, nil, {}
-- the players this side simulates, as a flat { x1, y1, x2, y2, ... }: every online player on a server, the local
-- players elsewhere; nil when this side cannot list them (then every car counts as near: the loops run as before).
-- stamp: the calling loop's tick count; the list is gathered once per stamp (once per pass, not per car)
function State.playerSpots(stamp)
    if stamp ~= nil and stamp == spotsAt then return spots end
    spotsAt = stamp
    local out = spotsBuf                               -- one table, refilled (valid until the next stamp)
    for i = #out, 1, -1 do out[i] = nil end
    if isServer() then
        if type(getOnlinePlayers) ~= "function" then spots = nil; return nil end
        local list = getOnlinePlayers()
        for i = 0, (list and list:size() or 0) - 1 do
            local p = list:get(i)
            if p then out[#out + 1] = p:getX(); out[#out + 1] = p:getY() end
        end
    else
        if type(getNumActivePlayers) ~= "function" or type(getSpecificPlayer) ~= "function" then spots = nil; return nil end
        for i = 0, getNumActivePlayers() - 1 do
            local p = getSpecificPlayer(i)
            if p then out[#out + 1] = p:getX(); out[#out + 1] = p:getY() end
        end
    end
    spots = out
    return out
end

-- is a player within r tiles of the car (true when the players cannot be listed); stamp: see State.playerSpots
function State.anyNear(vehicle, r, stamp)
    local s = State.playerSpots(stamp)
    if s == nil then return true end
    if #s == 0 then return false end
    local x, y = vehicle:getX(), vehicle:getY()
    local r2 = r * r
    for i = 1, #s, 2 do
        local dx, dy = s[i] - x, s[i + 1] - y
        if dx * dx + dy * dy <= r2 then return true end
    end
    return false
end

-- should a throttled loop look at the car of entry e (its own table: e.near, e.dueIn are kept there) this pass:
-- nearness (a player within r) is checked every slow-th pass; a near car is due on every pass, a far one on the
-- pass that found it far. stamp: the loop's tick count (the player list is gathered once per pass)
function State.due(e, vehicle, r, slow, stamp)
    local n = e.dueIn
    if n and n > 0 then
        e.dueIn = n - 1
        return e.near
    end
    e.near = State.anyNear(vehicle, r, stamp)
    e.dueIn = (slow or 1) - 1
    return true
end

State.POLL_NEAR = 50                 -- tiles: the client poll looks at a car farther from every local player
State.POLL_SLOW = 4                  -- every 4th poll (2 s)
State.PRUNE_EVERY = 4                -- polls between prunes of the registered caches (memory only: 2 s)

-- a tracked car's part object by id, looked up once: a VehiclePart lives as long as its BaseVehicle (42.21
-- VehicleParts.setScript keeps each part by id when the script is set again); State.refresh, which every part
-- init calls, drops the cache. false: the car has no such part
local function partOf(e, vehicle, partId)
    local parts = e.parts
    if not parts then
        parts = {}
        e.parts = parts
    end
    local p = parts[partId]
    if p == nil then
        p = vehicle:getPartById(partId) or false
        parts[partId] = p
    end
    return p or nil
end
State.partOf = partOf

-- one pass over the tracked cars (client half: OnTick every POLL ticks): values that changed under
-- the client (the mod data packet without its command), parts whose item changed (models reset);
-- then the registered caches lose the cars that left the world (every PRUNE_EVERY-th pass).
-- perf 2026-10-24: each host part's mod data is read once for all its keys, the part objects are kept per car
-- (State.partOf), and a car no local player is near is looked at every POLL_SLOW-th pass (State.due)
local polls = 0
function State.poll()
    polls = polls + 1
    if polls % State.PRUNE_EVERY == 1 or State.PRUNE_EVERY <= 1 then
        for _, t in ipairs(State.caches) do State.prune(t) end
    end
    for id, e in pairs(State.tracked) do
        local v = e.vehicle
        if State.gone(v, id) then
            State.tracked[id] = nil
        elseif State.due(e, v, State.POLL_NEAR, State.POLL_SLOW, polls) then
            for partId, keys in pairs(State.hostKeys) do
                local part = partOf(e, v, partId)
                local md = part and part:getModData() or nil
                for _, key in ipairs(keys) do
                    local spec = State.keys[key]
                    local now = md and md[spec.name]
                    if now == nil then now = spec.default end
                    local was = e.values[key]
                    if now ~= was then
                        e.values[key] = now
                        State.fire(v, key, now, was, "sync")
                    end
                end
            end
            for partId, fns in pairs(State.partWatchers) do
                local part = partOf(e, v, partId)
                local item = part and part:getInventoryItem() or false
                if e.items[partId] ~= item then
                    e.items[partId] = item
                    for _, fn in ipairs(fns) do call(fn, v, part) end
                end
            end
        end
    end
end

