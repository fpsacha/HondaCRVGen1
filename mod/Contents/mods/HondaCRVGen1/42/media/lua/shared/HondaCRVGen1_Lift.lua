--[[
Honda CR-V (RD1): the lift conversion (scripts/features/lift.py, spec/feature-plugins.md).

Our own code. A 3 in. lift on all-terrain tyres is a second vehicle script (in PZ every car of one
script shares its body and wheel positions): Base.HondaCRVGen1LiftAlloy (the EX alloys) and
Base.HondaCRVGen1LiftSteel (black steel wheels), every part id the same as the stock car's. The
mechanic action ISCRVLiftConvert swaps a car for another of the three scripts:

    stock  -> alloy | steel     needs the kit (CRVGen1_LiftKit), consumed
    alloy | steel -> stock      gives the kit back
    alloy <-> steel             a wheel swap, no kit

Lift.convert runs where the game is authoritative (the action's complete(): single player or the
server). The game cannot change a live car's script for every client (BaseVehicle.scriptReloaded
re-creates the parts and sends nothing), so it spawns the new car where the old one stands and
moves everything over, in one call, before the vehicle manager first sends the new car:

  1. check again (Lift.canConvert: passengers, trailer, key, engine, the ground, tools, skill, kit,
     and nobody else at the car: another player's action on it would land on the removed car);
  2. take a snapshot of the old car: per part its item, condition, installer skill, item container
     (the object itself: its items and their fluids move with it), content amount (fuel, tyre
     pressure), mod data (every HondaCRVGen1.State value lives there), door and window state; the
     car's key id, skin, colour, rust, mechanical id, engine quality / loudness / power, hotwired,
     alarm, world transform (exact position and rotation), blood and vehicle mod data;
  3. detach the items and containers from the old car and remove it (permanentlyRemove);
  4. addVehicleDebug the target script on the same square (it adds the car only where the engine's
     own spawn gate passes: the square exists, outside or in a vehicle zone, no other car in the way;
     step 1 checked the first two before anything was touched). addToWorld then runs trySpawnKey on
     the never-entered car, which can put a fresh key in its ignition: it is taken out at once;
  5. restore everything onto the new car (the create hooks' random parts and loot are overwritten;
     each part gets its old container BEFORE its item, so VehiclePart.doInventoryItemStats writes
     the item's capacity into the container that stays), put the car back exactly where the old one
     stood (addVehicleDebug places it on the square's corner), re-run every part's init hook
     (accessory watchers, rack cargo), transmit what can be transmitted.

If the new car does not reach the world (a car parked in the way), the old script is spawned back
with the same snapshot; if even that fails, every item and container content is dropped on the
square, so nothing is ever lost.

What runs where: Lift.canConvert anywhere (the menu greys options with it, the action's isValid and
complete re-check it); Lift.convert only where the game is authoritative, which also tells the
acting player the outcome (Lift.report: a halo in single player, a server command in multiplayer).
]]

require "HondaCRVGen1_State"

HondaCRVGen1 = HondaCRVGen1 or {}
local Lift = HondaCRVGen1.Lift or {}
HondaCRVGen1.Lift = Lift

Lift.SCRIPTS = { stock = "Base.HondaCRVGen1", alloy = "Base.HondaCRVGen1LiftAlloy", steel = "Base.HondaCRVGen1LiftSteel" }
Lift.KIT = "Base.CRVGen1_LiftKit"
Lift.SKILL = 5                      -- Mechanics level to fit or remove the kit
Lift.SKILL_SWAP = 3                 -- to swap the wheels on a lifted car
Lift.TIME = 3000                    -- ticks (about 2.5 in-game hours at x1): springs, spacers, shocks, four wheels
Lift.TIME_SWAP = 1000
Lift.XP = 25                        -- Mechanics XP on completion (a wheel swap: a third)
-- XP once per car, per kind of work (fit, remove, swap) and per player, for one in-game day: vanilla's
-- own memory for install XP (IsoPlayer.addMechanicsItem / updateMechanicsItems, 42.21 bytecode: a key
-- pays once, then is forgotten 86400000 ms of game time later). Kept in the car's mod data, which the
-- conversion carries over, so the alloy <-> steel swap cannot be repeated for XP.
Lift.XP_MEMORY_MS = 86400000
Lift.REACH = 4                      -- tiles from the car's centre (the action pathfinds to the side)
Lift.COMMAND = "HondaCRVGen1Lift"   -- server -> client: the outcome of the player's conversion
-- tools: a wrench, a lug wrench and a jack (the vanilla tyre install uses the last two)
Lift.TOOLS = {
    { tag = "base:wrench", text = "Tooltip_CRV_Lift_NeedWrench" },
    { tag = "base:lugwrench", text = "Tooltip_CRV_Lift_NeedLugWrench" },
    { type = "Base.Jack", text = "Tooltip_CRV_Lift_NeedJack" },
}
Lift.BLOOD = { "Front", "Rear", "Left", "Right" }

for kind, name in pairs(Lift.SCRIPTS) do
    HondaCRVGen1.State.registerVehicle(name)
end

-- "stock", "alloy", "steel" or nil (not a CR-V)
function Lift.kindOf(vehicle)
    if not vehicle then return nil end
    local name = vehicle:getScriptName()
    for kind, s in pairs(Lift.SCRIPTS) do
        if s == name then return kind end
    end
    return nil
end

-- the menu text key for a conversion
function Lift.optionText(from, to)
    if from == "stock" then return to == "alloy" and "ContextMenu_CRV_Lift_Alloy" or "ContextMenu_CRV_Lift_Steel" end
    if to == "stock" then return "ContextMenu_CRV_Lift_Remove" end
    return to == "steel" and "ContextMenu_CRV_Lift_ToSteel" or "ContextMenu_CRV_Lift_ToAlloy"
end

function Lift.needsKit(from, to) return from == "stock" and to ~= "stock" end
function Lift.givesKit(from, to) return from ~= "stock" and to == "stock" end
function Lift.isSwap(from, to) return from ~= "stock" and to ~= "stock" end

function Lift.time(from, to)
    return Lift.isSwap(from, to) and Lift.TIME_SWAP or Lift.TIME
end

function Lift.skill(from, to)
    return Lift.isSwap(from, to) and Lift.SKILL_SWAP or Lift.SKILL
end

local function tagOf(name)
    if ItemTag and ItemTag.get and ResourceLocation and ResourceLocation.of then
        return ItemTag.get(ResourceLocation.of(name))
    end
    return name
end

-- the first item of the inventory (bags included) that serves as the tool, or nil
function Lift.findTool(inv, tool)
    if tool.type then return inv:getFirstTypeRecurse(tool.type) end
    return inv:getFirstTagRecurse(tagOf(tool.tag))
end

function Lift.findKit(character)
    return character:getInventory():getFirstTypeRecurse(Lift.KIT)
end

-- the engine's own spawn gate (IsoChunk.doSpawnedVehiclesInInvalidPosition): a square, outside or in
-- a vehicle zone. Checked before the old car is touched
function Lift.groundOk(vehicle)
    local sq = vehicle:getSquare()
    if not sq then return false end
    if sq:isOutside() then return true end
    if getVehicleZoneAt then
        local ok, zone = pcall(getVehicleZoneAt, sq:getX(), sq:getY(), sq:getZ())
        if ok and zone ~= nil then return true end
    end
    return false
end

-- ok, list of reason keys (translation keys; the first one is the main reason). Every side.
function Lift.canConvert(character, vehicle, to)
    local why = {}
    local from = Lift.kindOf(vehicle)
    if not from or not Lift.SCRIPTS[to] or from == to then return false, { "unknown" } end
    if vehicle:isRemovedFromWorld() then return false, { "removed" } end
    if vehicle.isBurnt and vehicle:isBurnt() then return false, { "Tooltip_CRV_Lift_Burnt" } end
    for seat = 0, vehicle:getMaxPassengers() - 1 do
        if vehicle:getCharacter(seat) then
            table.insert(why, "Tooltip_CRV_Lift_Passengers")
            break
        end
    end
    if vehicle:getVehicleTowing() or vehicle:getVehicleTowedBy() then table.insert(why, "Tooltip_CRV_Lift_Trailer") end
    if vehicle:isKeysInIgnition() or vehicle:isKeyIsOnDoor() then table.insert(why, "Tooltip_CRV_Lift_Key") end
    if vehicle:isEngineRunning() then table.insert(why, "Tooltip_CRV_Lift_Engine") end
    if not Lift.groundOk(vehicle) then table.insert(why, "Tooltip_CRV_Lift_Ground") end
    if character and Lift.othersNear(character, vehicle) then table.insert(why, "Tooltip_CRV_Lift_Busy") end
    if character then
        if character:getVehicle() then table.insert(why, "Tooltip_CRV_Lift_Passengers") end
        local cheat = character.isMechanicsCheat and character:isMechanicsCheat()
        if not cheat then
            local inv = character:getInventory()
            if Lift.needsKit(from, to) and not Lift.findKit(character) then table.insert(why, "Tooltip_CRV_Lift_NeedKit") end
            for _, tool in ipairs(Lift.TOOLS) do
                if not Lift.findTool(inv, tool) then table.insert(why, tool.text) end
            end
            if character:getPerkLevel(Perks.Mechanics) < Lift.skill(from, to) then
                table.insert(why, "Tooltip_CRV_Lift_NeedSkill")
            end
        end
    end
    return #why == 0, why
end

function Lift.near(character, vehicle)
    local dx, dy = character:getX() - vehicle:getX(), character:getY() - vehicle:getY()
    return dx * dx + dy * dy <= Lift.REACH * Lift.REACH
end

local function samePlayer(a, b)
    if rawequal(a, b) then return true end
    if (isClient() or isServer()) and a.getOnlineID and b.getOnlineID then
        local ok, x, y = pcall(function() return a:getOnlineID(), b:getOnlineID() end)
        if ok and x ~= nil and x == y and x ~= -1 then return true end
    end
    return false
end

-- another living player at the car (within REACH of its centre, on foot or in this car)? The whole car
-- is replaced by a new object, so a battery, tyre or siphon action another player has running on the
-- old one would land on the removed car (the server never re-checks a started action: NetTimedAction
-- isValid is false, ActionManager completes it on its timer). Vehicle actions need the player at the
-- car, so nobody near means nobody working on it. Online players (server and clients) and the
-- split-screen players of this machine
function Lift.othersNear(character, vehicle)
    local list = {}
    local online = getOnlinePlayers and getOnlinePlayers()
    if online then
        for i = 0, online:size() - 1 do list[#list + 1] = online:get(i) end
    end
    if getNumActivePlayers and getSpecificPlayer then
        for i = 0, getNumActivePlayers() - 1 do
            local p = getSpecificPlayer(i)
            if p then list[#list + 1] = p end
        end
    end
    for _, p in ipairs(list) do
        if p and not samePlayer(p, character) and not (p.isDead and p:isDead()) then
            local pv = p:getVehicle()
            if (pv == nil or pv == vehicle) and Lift.near(p, vehicle) then return true end
        end
    end
    return false
end

-- ---------------------------------------------------------------------------------------------
-- snapshot / restore (authoritative side)

local function try(fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok then print("HondaCRVGen1.Lift: " .. tostring(err)) end
    return ok, err
end

-- a plain copy of a mod data table (nested tables copied; Java objects kept as they are)
local function copyTable(t, depth)
    local out = {}
    if depth > 8 then return out end
    for k, v in pairs(t) do
        if type(v) == "table" then out[k] = copyTable(v, depth + 1) else out[k] = v end
    end
    return out
end

local function fill(dst, src)
    local keys = {}
    for k, _ in pairs(dst) do table.insert(keys, k) end
    for _, k in ipairs(keys) do dst[k] = nil end
    for k, v in pairs(src) do dst[k] = v end
end

function Lift.snapshot(vehicle)
    local s = { parts = {}, order = {} }
    s.script = vehicle:getScriptName()
    s.x, s.y, s.z = vehicle:getX(), vehicle:getY(), vehicle:getZ()
    s.ax, s.ay, s.az = vehicle:getAngleX(), vehicle:getAngleY(), vehicle:getAngleZ()
    -- the physics transform (origin and rotation, in the side's WorldSimulation frame, which both cars
    -- share): BaseVehicle.getWorldTransform copies jniTransform (zombie.core.physics.Transform is exposed)
    if Transform and Transform.new then
        local ok, xf = pcall(function() local t = Transform.new(); vehicle:getWorldTransform(t); return t end)
        if ok then s.xf = xf end
    end
    s.skin = vehicle:getSkinIndex()
    s.hue, s.sat, s.val = vehicle:getColorHue(), vehicle:getColorSaturation(), vehicle:getColorValue()
    s.rust = vehicle:getRust()
    s.keyId = vehicle:getKeyId()
    s.mechId = vehicle:getMechanicalID()
    s.quality, s.loudness, s.power = vehicle:getEngineQuality(), vehicle:getEngineLoudness(), vehicle:getEnginePower()
    local okF, force = pcall(function() return vehicle:getScript():getEngineForce() end)
    if okF then s.force = force end
    s.hotwired = vehicle:isHotwired()
    s.alarmed = vehicle:isAlarmed()
    s.entered = vehicle:isPreviouslyEntered()
    s.md = copyTable(vehicle:getModData(), 0)
    s.blood = {}
    for _, b in ipairs(Lift.BLOOD) do
        local ok, v = pcall(function() return vehicle:getBloodIntensity(b) end)
        if ok then s.blood[b] = v end
    end
    for i = 0, vehicle:getPartCount() - 1 do
        local part = vehicle:getPartByIndex(i)
        local p = { id = part:getId(), item = part:getInventoryItem(), cond = part:getCondition(),
                    cont = part:getItemContainer(), md = copyTable(part:getModData(), 0) }
        local okS, skill = pcall(function() return part:getMechanicSkillInstaller() end)
        p.skill = okS and skill or 0
        if part:isContainer() and not p.cont then p.amount = part:getContainerContentAmount() end
        local door = part:getDoor()
        if door then p.door = { locked = door:isLocked(), open = door:isOpen(), lockBroken = door:isLockBroken() } end
        local win = part:getWindow()
        if win then p.winOpen = win:isOpen() end
        s.parts[p.id] = p
        table.insert(s.order, p.id)
    end
    return s
end

-- take the items and containers off the old car (they are about to move to the new one)
function Lift.detach(vehicle, s)
    for _, id in ipairs(s.order) do
        local part = vehicle:getPartById(id)
        if part and s.parts[id].item then part:setInventoryItem(nil) end
    end
end

-- the engine power the target script gives this car: Vehicles.Create.Engine sets it to the script's
-- engineForce x a quality factor, so the old car's power is scaled by the scripts' ratio (the lifted
-- car's taller AT gearing). Without both forces the old power is kept
function Lift.power(v, s)
    local okF, force = pcall(function() return v:getScript():getEngineForce() end)
    if okF and force and s.force and s.force > 0 then
        return math.floor(s.power * force / s.force + 0.5)
    end
    return s.power
end

-- put the new car exactly where the old one stood: addVehicleDebug sets x / y to the square's integer
-- corner (42.21 bytecode) and its createPhysics seeds the body there, up to 1.4 tiles away.
-- setWorldTransform writes jniTransform (and teleports the Bullet body where there is one: not on a
-- dedicated server); x / y / z are what BaseVehicle.save and the full update send, on the same square
function Lift.place(v, s)
    if s.xf then
        if not try(function() v:setWorldTransform(s.xf) end) then v:setAngles(s.ax, s.ay, s.az) end
    else
        v:setAngles(s.ax, s.ay, s.az)
    end
    try(function()
        v:setX(s.x)
        v:setY(s.y)
        v:setZ(s.z)
    end)
end

function Lift.restore(v, s)
    for _, id in ipairs(s.order) do
        local p = s.parts[id]
        local part = v:getPartById(id)
        if part then
            -- the container first: setInventoryItem -> doInventoryItemStats writes the item's capacity
            -- (or the script's / 0 with no item) into the container the part holds at that moment
            if p.cont then part:setItemContainer(p.cont) end
            part:setInventoryItem(p.item, p.skill or 0)   -- nil where the old car had nothing fitted
            part:setCondition(p.cond)
            if p.amount then part:setContainerContentAmount(p.amount) end
            fill(part:getModData(), p.md)
            local door = part:getDoor()
            if door and p.door then
                try(function() door:setLockBroken(p.door.lockBroken) end)
                door:setLocked(p.door.locked)
                door:setOpen(p.door.open)
            end
            local win = part:getWindow()
            if win and p.winOpen ~= nil then try(function() win:setOpen(p.winOpen) end) end
        end
    end
    v:setSkinIndex(s.skin)
    -- setSkinIndex only writes the field; the model was built (ModelManager.addVehicle) with the spawn's random
    -- skin and nothing in single player rebinds it (a multiplayer client's VehicleProperties.parse does):
    -- updateSkin re-loads the texture, as vanilla ISVehicleColor does after its own setSkinIndex (42.21)
    try(function() v:updateSkin() end)
    v:setKeyId(s.keyId)
    v:setMechanicalID(s.mechId)
    v:setColorHSV(s.hue, s.sat, s.val)
    v:setRust(s.rust)
    v:setEngineFeature(s.quality, s.loudness, Lift.power(v, s))
    v:setHotwired(s.hotwired)
    try(function() v:setAlarmed(s.alarmed) end)
    try(function() v:setPreviouslyEntered(s.entered) end)
    for b, val in pairs(s.blood) do try(function() v:setBloodIntensity(b, val) end) end
    fill(v:getModData(), s.md)
    Lift.place(v, s)
end

-- addToWorld runs trySpawnKey on the fresh, never-entered car (42.21 bytecode): with an unlocked door
-- it can put a NEW key in the ignition (addKeyToWorld: keysInIgnition, ignitionSwitch.addItem), and
-- tryStartEngine only asks isKeysInIgnition(), which is "ignitionSwitch not empty" and never compares
-- key ids. Take it out before the car is restored and first sent. True when the ignition is empty
function Lift.clearSpawnKey(v)
    local ok, inIgnition = pcall(function() return v:isKeysInIgnition() end)
    if not ok or not inIgnition then return true end
    try(function()
        local key = v:getCurrentKey()
        local c = key and key:getContainer()
        if c then c:DoRemoveItem(key) end
    end)
    local ok2, still = pcall(function() return v:isKeysInIgnition() end)
    return ok2 and not still
end

-- addToWorld's trySpawnKey can also leave the fresh car's key elsewhere (42.21 bytecode, BaseVehicle.addKeyToWorld):
-- in its glove box (addKeyToGloveBox), in a container of an object within 10 tiles, in a zombie's inventory there
-- (addKeyToSquare -> checkSquareForVehicleKeySpot) or on the ground within 10 tiles (putKeyToWorld). The restore
-- gives the car the old key id, so that key would open nothing: remove every key carrying the new car's own id
-- (`keyId`, read right after the spawn) from the car's containers and the squares around it. `keep`: a key id never
-- touched (the old car's: its real keys stay wherever they are). Returns the number of keys removed
Lift.KEY_RADIUS = 10

local function isKeyOf(item, keyId)
    if not item or not item.getKeyId then return false end
    local ok, id = pcall(function() return item:getKeyId() end)
    return ok and id == keyId
end

-- the keys with that id directly in container c (removed, and the removal sent where the game is networked)
local function removeKeysFrom(c, keyId)
    if not c or not c.getItems then return 0 end
    local items = c:getItems()
    if not items then return 0 end
    local found = {}
    for i = 0, items:size() - 1 do
        local it = items:get(i)
        if isKeyOf(it, keyId) then found[#found + 1] = it end
    end
    for _, it in ipairs(found) do
        c:DoRemoveItem(it)
        if isServer() and sendRemoveItemFromContainer then try(sendRemoveItemFromContainer, c, it) end
    end
    return #found
end

local function list(javaList)
    local out = {}
    if javaList then
        for i = 0, javaList:size() - 1 do out[#out + 1] = javaList:get(i) end
    end
    return out
end

function Lift.removeSpawnKeys(v, keyId, keep)
    if keyId == nil or keyId == keep then return 0 end
    local n = 0
    for i = 0, v:getPartCount() - 1 do
        local part = v:getPartByIndex(i)
        n = n + removeKeysFrom(part:getItemContainer(), keyId)
    end
    if not getSquare then return n end
    local cx, cy, z = math.floor(v:getX()), math.floor(v:getY()), math.floor(v:getZ())
    local R = Lift.KEY_RADIUS
    for x = cx - R, cx + R do
        for y = cy - R, cy + R do
            local sq = getSquare(x, y, z)
            if sq then
                if sq.getWorldObjects then                   -- on the ground (IsoWorldInventoryObject)
                    for _, wo in ipairs(list(sq:getWorldObjects())) do
                        local ok, item = pcall(function() return wo:getItem() end)
                        if ok and isKeyOf(item, keyId) then
                            try(function() sq:transmitRemoveItemFromSquare(wo) end)
                            n = n + 1
                        end
                    end
                end
                if sq.getObjects then                        -- in a container of an object (a crate, a counter)
                    for _, o in ipairs(list(sq:getObjects())) do
                        if o.getContainerCount then
                            for k = 0, o:getContainerCount() - 1 do n = n + removeKeysFrom(o:getContainerByIndex(k), keyId) end
                        end
                    end
                end
                if sq.getMovingObjects then                  -- in a zombie's inventory
                    for _, o in ipairs(list(sq:getMovingObjects())) do
                        if instanceof and instanceof(o, "IsoZombie") then n = n + removeKeysFrom(o:getInventory(), keyId) end
                    end
                end
            end
        end
    end
    return n
end

-- every part's init hook again (the engine ran them for the create hooks' parts, before the restore)
function Lift.reinit(v)
    for i = 0, v:getPartCount() - 1 do
        local part = v:getPartByIndex(i)
        local fn = part:getLuaFunction("init")
        if fn and VehicleUtils and VehicleUtils.callLua then try(VehicleUtils.callLua, fn, v, part) end
    end
end

-- tell the clients what is not in a vehicle's first full update if it was already sent (harmless when not)
function Lift.transmit(v)
    for i = 0, v:getPartCount() - 1 do
        local part = v:getPartByIndex(i)
        v:transmitPartItem(part)
        v:transmitPartCondition(part)
        v:transmitPartModData(part)
        if part:getDoor() then v:transmitPartDoor(part) end
        if part:getWindow() then v:transmitPartWindow(part) end
    end
    v:transmitEngine()
    v:transmitRust()
    v:transmitColorHSV()
    v:transmitSkinIndex()
end

-- did addVehicleDebug add the car? Only its success path calls addToWorld -> createPhysics, which
-- builds the CarController and puts the car in the id map (42.21 bytecode). The cell's vehicle list is
-- NOT a test: createPhysics only queues the car in IsoCell.addVehicles, merged on the cell's next update
function Lift.inWorld(v)
    if not v then return false end
    if v:getController() ~= nil then return true end
    if getVehicleById then
        local ok, found = pcall(getVehicleById, v:getId())
        if ok and found ~= nil and found == v then return true end
    end
    return false
end

-- nothing could be spawned: every item, container content and the kit-able parts go on the ground
function Lift.dropAll(sq, s)
    for _, id in ipairs(s.order) do
        local p = s.parts[id]
        if p.cont then
            local items = p.cont:getItems()
            for i = items:size() - 1, 0, -1 do
                local it = items:get(i)
                p.cont:DoRemoveItem(it)
                sq:AddWorldInventoryItem(it, 0.5, 0.5, 0)
            end
        end
        if p.item then sq:AddWorldInventoryItem(p.item, 0.5, 0.5, 0) end
    end
end

-- the skin is set after the spawn (setSkinIndex, restore transmits it): a Lua number for the boxed
-- Integer parameter is one conversion we do not need to rely on
local function spawn(script, s, sq)
    for attempt = 1, 3 do
        local v = addVehicleDebug(script, IsoDirections.N, nil, sq)
        if not (v and Lift.inWorld(v)) then return nil, v end
        -- the fresh car's own key id, before the restore gives it the old one: its spawn key fits nothing after
        local okK, keyId = pcall(function() return v:getKeyId() end)
        if okK then try(Lift.removeSpawnKeys, v, keyId, s.keyId) end
        if Lift.clearSpawnKey(v) then return v end
        -- the key would not come out (never seen): try a fresh car, keep the last one
        if attempt == 3 then
            print("HondaCRVGen1.Lift: the new car's spawn key stayed in the ignition")
            return v
        end
        v:permanentlyRemove()
    end
end

-- tell the acting player how it went: a halo in single player, a server command to that player's
-- client in multiplayer (client/HondaCRVGen1_LiftMenu.lua shows it). The action's perform() runs on the
-- client before the server's complete(), so it cannot know the outcome itself. The mod's other networked
-- actions (ISCRVFoldSeats, ISCRVAwning, ISCRVFunctionLiftFloor) report through here too. No key: nothing to say
function Lift.report(character, ok, key)
    if not key then return end
    if isServer() then
        if sendServerCommand and character then
            local id = character.getOnlineID and character:getOnlineID() or nil
            sendServerCommand(character, Lift.COMMAND, "result", { ok = ok, key = key, id = id })
        end
    elseif not isClient() then
        Lift.halo(character, ok, key)
    end
end

function Lift.halo(character, ok, key)
    if not (HaloTextHelper and character and key) then return end
    -- vanilla's two-argument forms (ISCraftingUI, ISVehicleMechanics): the colour is the helper's own
    -- choice; a failure uses the bad-text helper
    if ok then
        HaloTextHelper.addText(character, getText(key))
    else
        HaloTextHelper.addBadText(character, getText(key))
    end
end

function Lift.doneText(from, to)
    if Lift.givesKit(from, to) then return "IGUI_CRV_Lift_Lowered" end
    if Lift.isSwap(from, to) then return "IGUI_CRV_Lift_Rewheeled" end
    return "IGUI_CRV_Lift_Lifted"
end

function Lift.work(from, to)
    if Lift.isSwap(from, to) then return "swap" end
    return Lift.needsKit(from, to) and "fit" or "remove"
end

-- Mechanics XP for a conversion that happened: once per car, kind of work and player per in-game day
-- (Lift.XP_MEMORY_MS). Returns the XP given
function Lift.giveXp(character, v, from, to)
    local md = v:getModData()
    local memory = type(md.crvLiftXP) == "table" and md.crvLiftXP or {}
    md.crvLiftXP = memory
    local now = 0
    if getGameTime then
        local ok, t = pcall(function() return getGameTime():getCalender():getTimeInMillis() end)
        if ok and t then now = t end
    end
    local old = {}
    for k, t in pairs(memory) do
        if type(t) ~= "number" or now - t > Lift.XP_MEMORY_MS or t > now then table.insert(old, k) end
    end
    for _, k in ipairs(old) do memory[k] = nil end
    local who = (character.getUsername and character:getUsername()) or "player"
    local key = tostring(who) .. "|" .. Lift.work(from, to)
    if memory[key] then return 0 end
    memory[key] = now
    local n = Lift.isSwap(from, to) and math.floor(Lift.XP / 3) or Lift.XP
    addXp(character, Perks.Mechanics, n)
    return n
end

-- the conversion itself: authoritative side only. Returns the new car, or nil and a reason
function Lift.convert(character, vehicle, to)
    if isClient() then return nil, "client" end
    local from = Lift.kindOf(vehicle)
    local ok, why = Lift.canConvert(character, vehicle, to)
    if not ok then return nil, why[1] end
    -- the player still at the car (the action's isValid checks it on the acting client only: the server never
    -- runs isValid for a client's action)
    if character and not Lift.near(character, vehicle) then return nil, "far" end
    local kit
    if Lift.needsKit(from, to) and not (character.isMechanicsCheat and character:isMechanicsCheat()) then
        kit = Lift.findKit(character)
        if not kit then return nil, "Tooltip_CRV_Lift_NeedKit" end
    end
    return Lift.swapCar(character, vehicle, from, to, kit)
end

function Lift.swapCar(character, vehicle, from, to, kit)
    local sq = vehicle:getSquare()
    local s = Lift.snapshot(vehicle)
    Lift.detach(vehicle, s)
    vehicle:permanentlyRemove()
    Lift.converting = true                      -- (for other features' create hooks: the car is not new)
    local v = spawn(Lift.SCRIPTS[to], s, sq)
    local restored = to
    if not v then
        print("HondaCRVGen1.Lift: " .. Lift.SCRIPTS[to] .. " could not be added at " .. s.x .. "," .. s.y .. "; putting the car back")
        v = spawn(s.script, s, sq)
        restored = from
    end
    Lift.converting = nil
    if not v then
        print("HondaCRVGen1.Lift: the car could not be put back either; its parts and contents are on the ground")
        Lift.dropAll(sq, s)
        return nil, "IGUI_CRV_Lift_Failed"
    end
    Lift.restore(v, s)
    Lift.reinit(v)
    Lift.transmit(v)
    if restored ~= to then return nil, "IGUI_CRV_Lift_Failed" end
    local inv = character:getInventory()
    if kit then
        local c = kit:getContainer() or inv
        c:DoRemoveItem(kit)
        sendRemoveItemFromContainer(c, kit)
    elseif Lift.givesKit(from, to) then
        Lift.giveKit(character)
    end
    Lift.giveXp(character, v, from, to)
    return v
end

-- the removed kit to the player: into the inventory when it has room, else on the ground at the player's feet, as
-- vanilla's ISUninstallVehiclePart:complete does with a part ("so player don't go over inventory capacity": 42.21,
-- hasRoomFor -> AddItem + sendAddItemToContainer, else AddWorldInventoryItem at ISTransferAction.GetDropItemOffset).
-- Returns the item and where it went ("inventory" / "ground")
function Lift.giveKit(character)
    local inv = character:getInventory()
    local item = instanceItem and instanceItem(Lift.KIT) or nil
    if not item then                                   -- (no instanceItem: the old way)
        item = inv:AddItem(Lift.KIT)
        if item then sendAddItemToContainer(inv, item) end
        return item, "inventory"
    end
    if inv:hasRoomFor(character, item) then
        inv:AddItem(item)
        sendAddItemToContainer(inv, item)
        return item, "inventory"
    end
    local sq = character:getCurrentSquare() or (getSquare and getSquare(character:getX(), character:getY(), character:getZ()))
    if not sq then                                     -- nowhere to put it down (never seen): the inventory after all
        inv:AddItem(item)
        sendAddItemToContainer(inv, item)
        return item, "inventory"
    end
    local dx, dy, dz = 0.5, 0.5, 0
    if ISTransferAction and ISTransferAction.GetDropItemOffset then
        local ok, x, y, z = pcall(ISTransferAction.GetDropItemOffset, character, sq, item)
        if ok and x then dx, dy, dz = x, y, z end
    end
    sq:AddWorldInventoryItem(item, dx, dy, dz)
    if not isServer() and ISInventoryPage then ISInventoryPage.renderDirty = true end
    return item, "ground"
end
