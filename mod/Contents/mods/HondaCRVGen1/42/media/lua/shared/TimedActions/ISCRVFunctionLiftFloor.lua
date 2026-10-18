require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Function"

-- "Lift the cargo floor": the player kneels at the open tailgate, lifts the load floor (the
-- picnic-table panel on the real RD1) and finds the storage well under it. Once found, the
-- under-floor storage (part CRVFunctionUnderfloor) shows in the loot window whenever the gate is open.
--
-- Multiplayer: perform() runs on the acting client (feedback), complete() on the authoritative side,
-- which sets HondaCRVGen1.State key function_floorFound (saved in the part's mod data, synced to every
-- client). new()'s parameters are stored under their own names: NetTimedAction rebuilds the action on
-- the server from them.
ISCRVFunctionLiftFloor = ISBaseTimedAction:derive("ISCRVFunctionLiftFloor")

function ISCRVFunctionLiftFloor:isValid()
    if not self.vehicle or self.vehicle:isRemovedFromWorld() then return false end
    -- a multiplayer client: the server's answer (found) must not cancel the action; complete() checks again
    if isClient() and HondaCRVGen1.Function.isFloorFound(self.vehicle) then return true end
    return (HondaCRVGen1.Function.canLiftFloor(self.vehicle, self.character))
end

function ISCRVFunctionLiftFloor:waitToStart()
    self.character:faceThisObject(self.vehicle)
    return self.character:shouldBeTurning()
end

function ISCRVFunctionLiftFloor:update()
    self.character:faceThisObject(self.vehicle)
end

function ISCRVFunctionLiftFloor:start()
    self:setActionAnim("Loot")
    self.character:SetVariable("LootPosition", "Low")
end

function ISCRVFunctionLiftFloor:stop()
    ISBaseTimedAction.stop(self)
end

function ISCRVFunctionLiftFloor:perform()
    HaloTextHelper.addText(self.character, getText("IGUI_CRV_Function_FloorFound"))
    ISBaseTimedAction.perform(self)
end

function ISCRVFunctionLiftFloor:complete()
    if not HondaCRVGen1.Function.canLiftFloor(self.vehicle, self.character) then return false end
    HondaCRVGen1.Function.setFloorFound(self.vehicle)
    return true
end

function ISCRVFunctionLiftFloor:getDuration()
    if self.character:isTimedActionInstant() then return 1 end
    return 120
end

function ISCRVFunctionLiftFloor:new(character, vehicle)
    local o = ISBaseTimedAction.new(self, character)
    o.character = character
    o.vehicle = vehicle
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = o:getDuration()
    return o
end
