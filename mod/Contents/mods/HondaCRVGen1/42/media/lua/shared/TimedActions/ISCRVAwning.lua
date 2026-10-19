require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Awning"

-- Roll the CR-V's side awning out (on = true) or up (awning feature, scripts/features/awning.py).
--
-- B42 runs perform() on the acting client and complete() on the authoritative side (the server, or the local
-- game in single player): the state changes in complete() through HondaCRVGen1.State (saved in the part's mod
-- data, pushed to every client, whose listeners show or hide the canopy). NetTimedAction rebuilds the action on
-- the server from new()'s parameter names: character, vehicle and on are stored under those names
-- (ISCRVFoldSeats is the same pattern). Reaching up to the bag: the vanilla Loot animation at LootPosition High
-- (ISWoodenWall), with the game's tent sounds (TentPutUp / TentTakeDown).
ISCRVAwning = ISBaseTimedAction:derive("ISCRVAwning")

function ISCRVAwning.check(vehicle, character, on)
    return HondaCRVGen1.Awning.canSet(vehicle, character, on)
end

function ISCRVAwning:isValid()
    if isClient() then
        -- a multiplayer client: the server decides (its complete() checks again); the state flips under this
        -- action when the server's answer arrives, which must not cancel it
        if not self.vehicle or self.vehicle:isRemovedFromWorld() then return false end
        if HondaCRVGen1.Awning.isDeployed(self.vehicle) == self.on then return true end
    end
    return (ISCRVAwning.check(self.vehicle, self.character, self.on))
end

function ISCRVAwning:waitToStart()
    self.character:faceThisObject(self.vehicle)
    return self.character:shouldBeTurning()
end

function ISCRVAwning:update()
    self.character:faceThisObject(self.vehicle)
end

function ISCRVAwning:start()
    self:setActionAnim("Loot")
    self.character:SetVariable("LootPosition", "High")
    self.sound = self.character:playSound(self.on and "TentPutUp" or "TentTakeDown")
end

function ISCRVAwning:stopSound()
    if self.sound and self.sound ~= 0 and self.character:getEmitter():isPlaying(self.sound) then
        self.character:stopOrTriggerSound(self.sound)
    end
end

function ISCRVAwning:stop()
    self:stopSound()
    ISBaseTimedAction.stop(self)
end

-- the acting client: feedback only, no state
function ISCRVAwning:perform()
    self:stopSound()
    HaloTextHelper.addText(self.character, getText(self.on and "IGUI_CRV_Awning_Deployed" or "IGUI_CRV_Awning_Stowed"))
    ISBaseTimedAction.perform(self)
end

-- the authoritative side: check again, then change the state (saved, synced, listeners fired)
function ISCRVAwning:complete()
    if not ISCRVAwning.check(self.vehicle, self.character, self.on) then return false end
    HondaCRVGen1.Awning.set(self.vehicle, self.on)
    return true
end

function ISCRVAwning:getDuration()
    if self.character:isTimedActionInstant() then return 1 end
    return self.on and 400 or 250
end

function ISCRVAwning:new(character, vehicle, on)
    local o = ISBaseTimedAction.new(self, character)
    o.character = character
    o.vehicle = vehicle
    o.on = on
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = o:getDuration()
    return o
end
