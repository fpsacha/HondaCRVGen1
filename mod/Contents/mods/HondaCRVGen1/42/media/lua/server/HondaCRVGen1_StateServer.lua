--[[
Honda CR-V (RD1): the authoritative half of HondaCRVGen1.State (shared/HondaCRVGen1_State.lua).

Answers the clients' "set" commands (State.request) after State.handleRequest has checked the key,
the car, the player's reach and the value. Runs in single player (the game's local server delivers
client commands a tick later, SinglePlayerServer.update -> OnClientCommand) and on a dedicated
server; media/lua/server also loads on multiplayer clients (GameLoadingState), which return here.
]]

if isClient() then return end

require "HondaCRVGen1_State"

local State = HondaCRVGen1.State

function State.OnClientCommand(module, command, player, args)
    if module ~= State.MODULE then return end
    if command == "set" then
        local ok, why = State.handleRequest(player, args)
        if not ok then
            print("HondaCRVGen1.State: refused " .. tostring(args and args.key) .. ": " .. tostring(why))
        end
    end
end

Events.OnClientCommand.Add(State.OnClientCommand)
