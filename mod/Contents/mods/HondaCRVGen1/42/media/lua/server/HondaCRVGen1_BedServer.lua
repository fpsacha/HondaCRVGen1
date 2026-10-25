--[[
Honda CR-V (RD1), function feature: the folded bed counts on a multiplayer server.

A sleeping player's stats run on the server (42.21 IsoGameCharacter.updateStats_WakeState: GameServer.server, or
the single-player local player; never a multiplayer client), and IsoPlayer.updateStats_Sleeping and
BodyDamage.UpdateDiscomfort read the player's bed type there. Vanilla sets the bed type only on the sleeper's own
side (ISWorldObjectContextMenu.onSleepWalkToComplete -> setBedType, client Lua; its "onVehicleSleep" command
carries the asleep flag alone), so on a server every sleeper keeps the server's "averageBed" and the CR-V's good
bed did nothing. The client (client/HondaCRVGen1_Menu.lua) sends "bedSleep" once asleep on a CR-V bed; the server
checks everything again (the sender sits in that CR-V, folded into a bed, the pillow rule:
HondaCRVGen1.Function.bedType) and sets the bed type, and puts the old one back once the player wakes, leaves the
car, the bed is cleared or the car moves (a bed in a parked car), so no other sleep inherits it. Single player needs none of this: the sleeper's own
setBedType is the one the stats read.
]]

if isClient() then return end

require "HondaCRVGen1_State"
require "HondaCRVGen1_Shared"
require "HondaCRVGen1_Function"

local F = HondaCRVGen1.Function
local S = HondaCRVGen1.Shared
local Bed = F.BedServer or {}
F.BedServer = Bed

Bed.COMMAND = "bedSleep"
Bed.CHECK = 30                 -- ticks between checks of the players whose bed type was set
Bed.GRACE = 20                 -- checks a player may take to fall asleep after the command (vanilla's command first)
Bed.sleepers = {}              -- player -> { vehicle =, old =, set =, seen =, checks = }

-- the answer to a client's "bedSleep": ok, why (or the bed type set)
function Bed.handle(player, args)
    if not player then return false, "no player" end
    local vehicle = player:getVehicle()
    if not vehicle or not S.isCRV(vehicle) then return false, "not in a CR-V" end
    if type(args) == "table" and args.vehicle ~= nil and args.vehicle ~= vehicle:getId() then
        return false, "not the car the player sits in"
    end
    local bedType = F.bedType(player, vehicle)
    if not bedType then return false, "not a bed" end
    local e = Bed.sleepers[player]
    if not e then
        e = { old = player:getBedType() }
        Bed.sleepers[player] = e
    end
    e.vehicle, e.set, e.seen, e.checks = vehicle, bedType, false, 0
    player:setBedType(bedType)
    return true, bedType
end

-- put the old bed type back once the sleep on the CR-V bed is over
function Bed.check()
    for player, e in pairs(Bed.sleepers) do
        e.checks = e.checks + 1
        local asleep = player:isAsleep() == true
        if asleep then e.seen = true end
        -- over once the player wakes or leaves, or the car is no made-up bed in a parked car any more (I-PLAY-3:
        -- driven or towed away, the bed folded away, the bench taken out: F.bedType says nil)
        local over = player:getVehicle() ~= e.vehicle or not F.bedType(player, e.vehicle)
            or (e.seen and not asleep) or (not e.seen and e.checks > Bed.GRACE)
        if over then
            if player:getBedType() == e.set then player:setBedType(e.old or "averageBed") end
            Bed.sleepers[player] = nil
        end
    end
end

function Bed.OnClientCommand(module, command, player, args)
    if module ~= HondaCRVGen1.State.MODULE or command ~= Bed.COMMAND then return end
    local ok, why = Bed.handle(player, args)
    if not ok then print("HondaCRVGen1.Function: bed refused: " .. tostring(why)) end
end

local ticks = 0
function Bed.OnTick()
    ticks = ticks + 1
    if ticks % Bed.CHECK ~= 0 then return end
    Bed.check()
end

Events.OnClientCommand.Add(Bed.OnClientCommand)
Events.OnTick.Add(Bed.OnTick)
