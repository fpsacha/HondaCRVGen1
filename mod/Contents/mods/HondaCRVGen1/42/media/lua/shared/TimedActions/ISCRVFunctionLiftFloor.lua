require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Function"
require "HondaCRVGen1_Lift"                -- Lift.report: the outcome to the acting player

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

-- the acting client: no state, and no outcome text: the authoritative side may still refuse (complete())
function ISCRVFunctionLiftFloor:perform()
    ISBaseTimedAction.perform(self)
end

-- the authoritative side: check again (the player still at the car: the server never runs isValid for a
-- client's action), then set the state and tell the player how it went (HondaCRVGen1.Lift.report: a halo in
-- single player, the server's answer to that client in multiplayer)
function ISCRVFunctionLiftFloor:complete()
    local report = HondaCRVGen1.Lift.report
    if not HondaCRVGen1.State.near(self.character, self.vehicle) then
        report(self.character, false, nil)
        return false
    end
    local ok, why = HondaCRVGen1.Function.canLiftFloor(self.vehicle, self.character)
    if not ok then
        report(self.character, false, why)
        return false
    end
    HondaCRVGen1.Function.setFloorFound(self.vehicle)
    report(self.character, true, "IGUI_CRV_Function_FloorFound")
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
