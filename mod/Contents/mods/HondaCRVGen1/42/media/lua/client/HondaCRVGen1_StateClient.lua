--[[
Honda CR-V (RD1): the drawing half of HondaCRVGen1.State (shared/HondaCRVGen1_State.lua).

  * OnServerCommand "changed": the server's announcement of a State.set, applied to the client's copy
    of the host part's mod data at once and passed to the listeners (how "sync");
  * a poll every State.POLL ticks over the cars State.refresh started tracking: a value that changed
    without its command (the mod data packet alone) fires "sync", and a part whose installed item
    changed calls its State.watchPart functions, since the engine has just shown every model of that
    part again (VehiclePart.setInventoryItem -> setAllModelsVisible) and no Lua hook runs on a client
    for an install the server completed.
Runs wherever the car is drawn: single player and multiplayer clients.
]]

if isServer() then return end

require "HondaCRVGen1_State"

local State = HondaCRVGen1.State

function State.OnServerCommand(module, command, args)
    if module ~= State.MODULE then return end
    if command == "changed" then
        State.applyRemote(args)
    end
end

local ticks = 0
function State.OnTickClient()
    ticks = ticks + 1
    if ticks % State.POLL ~= 0 then return end
    State.poll()
end

Events.OnServerCommand.Add(State.OnServerCommand)
Events.OnTick.Add(State.OnTickClient)
