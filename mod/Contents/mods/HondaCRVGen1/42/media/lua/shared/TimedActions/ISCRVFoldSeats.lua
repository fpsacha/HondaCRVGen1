require "TimedActions/ISBaseTimedAction"
require "HondaCRVGen1_Shared"

-- Fold the CR-V's rear seats flat into a bed (on = true) or put them back.
--
-- Multiplayer (function feature, 2026-10-13): B42 runs perform() on the acting client and complete()
-- on the authoritative side (the server, or the local game in single player). The fold used to change
-- the state in perform(), where transmitPartModData does nothing, so on a server the bed was
-- client-local and never saved. The change now happens in complete() through HondaCRVGen1.State
-- (saved in the seat part's mod data, pushed to every client). NetTimedAction rebuilds the action on
-- the server from new()'s parameter names: character, vehicle and on are stored under those names.
ISCRVFoldSeats = ISBaseTimedAction:derive("ISCRVFoldSeats")

-- ok, why: can the seats go to `on` now (folding: rear seats fitted, empty, unoccupied; putting
-- them back: the folded load floor empty)
function ISCRVFoldSeats.check(vehicle, on)
    local S = HondaCRVGen1.Shared
    if not vehicle or vehicle:isRemovedFromWorld() or not S.isCRV(vehicle) then return false end
    if S.isBed(vehicle) == on then return false end
    if on then return S.canFold(vehicle) end
    return S.canUnfold(vehicle)
end

function ISCRVFoldSeats:isValid()
    if isClient() then
        -- a multiplayer client: the server decides (its complete() checks again). The state flips
        -- under this action when the server's answer arrives, which must not cancel it
        if not self.vehicle or self.vehicle:isRemovedFromWorld() then return false end
        if HondaCRVGen1.Shared.isBed(self.vehicle) == self.on then return true end
    end
    return (ISCRVFoldSeats.check(self.vehicle, self.on))
end

function ISCRVFoldSeats:waitToStart()
    self.character:faceThisObject(self.vehicle)
    return self.character:shouldBeTurning()
end

function ISCRVFoldSeats:update()
    self.character:faceThisObject(self.vehicle)
end

function ISCRVFoldSeats:start()
    self:setActionAnim("Loot")
    self.character:SetVariable("LootPosition", "Mid")
end

function ISCRVFoldSeats:stop()
    ISBaseTimedAction.stop(self)
end

-- the acting client: feedback only, no state
function ISCRVFoldSeats:perform()
    HaloTextHelper.addText(self.character, getText(self.on and "IGUI_CRV_SeatsFolded" or "IGUI_CRV_SeatsUp"))
    ISBaseTimedAction.perform(self)
end

-- the authoritative side: check again, then change the state (saved, synced, listeners fired)
function ISCRVFoldSeats:complete()
    if not ISCRVFoldSeats.check(self.vehicle, self.on) then return false end
    HondaCRVGen1.Shared.setBed(self.vehicle, self.on)
    return true
end

function ISCRVFoldSeats:getDuration()
    if self.character:isTimedActionInstant() then return 1 end
    return 150
end

function ISCRVFoldSeats:new(character, vehicle, on)
    local o = ISBaseTimedAction.new(self, character)
    o.character = character
    o.vehicle = vehicle
    o.on = on
    o.stopOnWalk = true
    o.stopOnRun = true
    o.maxTime = o:getDuration()
    return o
end
