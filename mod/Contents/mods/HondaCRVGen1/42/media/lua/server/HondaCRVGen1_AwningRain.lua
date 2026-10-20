--[[
Honda CR-V (RD1), awning feature: the rain stays off whoever stands under a rolled-out awning. Our own code.

How the game wets a character (42.21 bytecode, scratch awning_research): IsoGameCharacter.updateInternal ->
BodyDamage.Update -> BodyDamage.UpdateWetness, which counts a character as outside when its square is in no
room and has no roof (IsoGridSquare.isInARoom / haveRoof; a car seat with a roof and a tent bed count as
inside) and, while ClimateManager.isRaining(), passes the rain intensity to ClothingWetness.updateWetness:
the outer clothing soaks up rain x 0.015 x GameTime multiplier a tick, then the body parts under it, and the
WETNESS stat follows the body parts. Indoors (or without rain) everything dries by (0.1 + max(0, (T - 5) / 10))
x 0.01 x multiplier a tick. An umbrella (item property ProtectFromRainWhenEquipped, checked only in the hands)
does not stop the soaking: it caps each body part's wetness (head 5 %, torso 20-25 %, arms 25-35 %). A Lua
mod cannot make a square roofed (haveRoof is filled from real floor tiles above) nor a character count as
holding an umbrella, so the awning works on the result instead:

  for every player standing under a rolled-out awning (HondaCRVGen1.Awning.shelterOf: same floor, not in a
  car, inside the canopy's footprint) while it rains, each tick:
    * its wetness levels are remembered when it steps under (the WETNESS stat, every body part, every worn
      clothing item), and every value the rain pushed above its remembered level is put back;
    * the remembered levels go down at the game's own indoor drying rate, so a wet character dries under
      the awning as under a roof.
  Out from under it, or when the rain stops, the game's own rules take over again.

Multiplayer: the server owns wetness. BodyDamage.Update returns at once on a multiplayer client (it never
runs UpdateWetness there, not even for the client's own player), the server pushes clothing wetness
(ClothingWetnessSync, every 3 s) and the stats (PlayerStatsPacket, every 1 s) to the owning client, and a
client cannot push stats back without the CanModifyBodyStats capability. So this runs where the game is
authoritative, for every player: the dedicated server (getOnlinePlayers) and single player (the local
players). Media/lua/server also loads on multiplayer clients, which return at once. After putting values
back on a server it sends the body damage once a second (sendDamage, as the vanilla ISDryMyself does); the
engine's own syncs carry the stat and the clothing.

Limits: the error is at most one tick of rain before it is put back; the rain still falls on the character
on screen and its sound plays (the square is still outside); snow does not wet in PZ anyway; wind-driven rain
is not modelled (the canopy covers its footprint only); a character half out from under the edge counts by
its position (one point).
]]

if isClient() then return end

require "HondaCRVGen1_Awning"

local Awning = HondaCRVGen1.Awning
local Rain = Awning.Rain or {}
Awning.Rain = Rain

Rain.SYNC_MS = 1000               -- server: sendDamage at most this often per sheltered player
Rain.held = {}                    -- player key -> { player =, stat =, parts = { [i] = level }, clothes = { [item] = level }, sent = ms }

local function key(p)
    if p.getOnlineID and isServer() then return "o" .. tostring(p:getOnlineID()) end
    return "p" .. tostring(p:getPlayerNum())
end

function Rain.players()
    local out = {}
    if isServer() then
        local list = getOnlinePlayers()
        for i = 0, (list and list:size() or 0) - 1 do out[#out + 1] = list:get(i) end
    else
        for i = 0, getNumActivePlayers() - 1 do
            local p = getSpecificPlayer(i)
            if p then out[#out + 1] = p end
        end
    end
    return out
end

-- every worn clothing item of p (Clothing has the wetness)
local function clothes(p)
    local out = {}
    local worn = p:getWornItems()
    for i = 0, (worn and worn:size() or 0) - 1 do
        local item = worn:getItemByIndex(i)
        if item and item:IsClothing() then out[#out + 1] = item end
    end
    return out
end

function Rain.snapshot(p)
    local h = { player = p, stat = p:getStats():get(CharacterStat.WETNESS), parts = {}, clothes = {}, sent = 0 }
    local parts = p:getBodyDamage():getBodyParts()
    for i = 0, parts:size() - 1 do h.parts[i] = parts:get(i):getWetness() end
    for _, item in ipairs(clothes(p)) do h.clothes[item] = item:getWetness() end
    return h
end

-- the game's indoor drying for one tick (BodyDamage.UpdateWetness / ClothingWetness: 0.01 a tick at the rate);
-- the rate follows the air temperature AT the character (ClimateManager.getAirTemperatureForCharacter, what
-- UpdateWetness reads: it counts nearby heat sources and the wind), the climate's own as a fallback
function Rain.dryStep(p)
    local cm = ClimateManager.getInstance()
    local t = nil
    if p and cm.getAirTemperatureForCharacter then
        local ok, v = pcall(cm.getAirTemperatureForCharacter, cm, p)
        if ok and type(v) == "number" then t = v end
    end
    if t == nil then t = cm:getTemperature() end
    local rate = 0.1 + math.max(0, ((t or 5) - 5) / 10)
    return rate * 0.01 * getGameTime():getMultiplier()
end

-- put back what the rain added since the last tick; returns whether anything changed
function Rain.hold(p, h, dry)
    local changed = false
    local stats = p:getStats()
    h.stat = math.max(0, math.min(h.stat, stats:get(CharacterStat.WETNESS)) - dry)
    if stats:get(CharacterStat.WETNESS) > h.stat then
        stats:set(CharacterStat.WETNESS, h.stat)
        changed = true
    end
    local parts = p:getBodyDamage():getBodyParts()
    for i = 0, parts:size() - 1 do
        local bp = parts:get(i)
        local now = bp:getWetness()
        local lvl = math.max(0, math.min(h.parts[i] or now, now) - dry)
        h.parts[i] = lvl
        if now > lvl then
            bp:setWetness(lvl)
            changed = true
        end
    end
    local seen = {}
    for _, item in ipairs(clothes(p)) do
        local now = item:getWetness()
        local lvl = math.max(0, math.min(h.clothes[item] or now, now) - dry)
        seen[item] = lvl
        if now > lvl then
            item:setWetness(lvl)
            changed = true
        end
    end
    h.clothes = seen                                  -- clothes taken off under it are forgotten
    return changed
end

-- the game's Kahlua has no global 'next': an empty-table test with pairs
local function empty(t)
    for _ in pairs(t) do return false end
    return true
end

function Rain.OnTick()
    if empty(Awning.out) then
        if not empty(Rain.held) then Rain.held = {} end
        return
    end
    local cm = ClimateManager.getInstance()
    if not cm or not cm:isRaining() then
        if not empty(Rain.held) then Rain.held = {} end
        return
    end
    local now = getTimeInMillis()
    local keep = {}
    for _, p in ipairs(Rain.players()) do
        if not p:isDead() and Awning.shelterOf(p) then
            local k = key(p)
            local h = Rain.held[k]
            if not h or h.player ~= p then
                h = Rain.snapshot(p)
            elseif Rain.hold(p, h, Rain.dryStep(p)) and isServer() and now - h.sent >= Rain.SYNC_MS then
                h.sent = now
                sendDamage(p)
            end
            keep[k] = h
        end
    end
    Rain.held = keep
end

Events.OnTick.Add(Rain.OnTick)
